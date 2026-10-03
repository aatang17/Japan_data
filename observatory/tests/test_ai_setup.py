# -*- coding: utf-8 -*-
"""Admin → AI Setup: skills, house style, connectors and Google Drive, and
what an AI run gets from them.

What is proved: the three seeded skills appear once and a deleted seed stays
deleted; writers edit skills and the house style, only the Team permission
changes connectors; a connector's key is sealed and never returned; a tool its
server marks destructive starts off and a switched-off tool cannot be called;
a run is shown the skills and the chosen skill's steps, can open a skill
itself, and calls connector tools under a prefixed name with the stored key;
a CLI run's tool server uses the credentials it was handed, not the keychain;
Google Drive tools appear only for a writer who connected it; the MCP client
reads event-stream replies and keeps a server's session.

Writing modes: the seeds come in the order of writing a note; a skill that
only answers (Brainstorm) runs without the draft-changing tools, makes no
"Before AI" copy and never reports a change; a run's offered next steps come
back as buttons naming a real skill, from the API loop and from a CLI run's
call log alike; clicking one starts a run that may write.
"""
import json
import os
import threading
import time

from app import connectors, research, research_ai, research_ai_mcp, skills, staff, staff_google
from app.assistant import gateway, mcp_client

from tests.test_research_ai import AIBase, Fake, call, say


class SetupBase(AIBase):
    def setUp(self):
        super(SetupBase, self).setUp()
        from app import ai_setup_api
        self.app.include_router(ai_setup_api.router)
        self._connect, self._call = mcp_client.connect, mcp_client.call_tool
        self._check = mcp_client.check_url
        mcp_client.check_url = lambda u: u
        self.remote = []

        def fake_connect(server, secret=None):
            self.remote.append(("connect", server["url"], secret))
            return {"name": "Notes"}, [
                {"name": "search_notes", "description": "Search notes.", "inputSchema": {"type": "object"},
                 "annotations": {"readOnlyHint": True}},
                {"name": "delete_note", "description": "Delete a note.", "inputSchema": {"type": "object"},
                 "annotations": {"destructiveHint": True}}]

        def fake_call(server, name, args, secret=None):
            self.remote.append(("call", name, args, secret))
            return json.dumps({"hits": ["BoJ minutes, 1 Oct"]}), False
        mcp_client.connect, mcp_client.call_tool = fake_connect, fake_call
        self.addCleanup(self._restore_client)
        team, self.tid = self.person("t@example.com", ["writing", "team"])
        self.team = team

    def _restore_client(self):
        mcp_client.connect, mcp_client.call_tool = self._connect, self._call
        mcp_client.check_url = self._check


class SkillTest(SetupBase):
    def test_seeds_once_and_deleted_seed_stays_deleted(self):
        got = self.w.get("/admin/api/ai/setup").json()["skills"]
        self.assertEqual([s["name"] for s in got],
                         ["Brainstorm", "Plan", "Draft", "Find Charts", "Edit", "Review", "Fact Check",
                          "Headlines", "Data Flash"])
        self.assertEqual([s["name"] for s in got if not s["writes"]],
                         ["Brainstorm", "Find Charts", "Review", "Headlines"])
        fc = skills.get("fact-check")
        self.assertEqual(self.w.delete("/admin/api/ai/skills/%d" % fc["id"]).status_code, 200)
        skills._seed_once()                                   # even if seeding runs again
        self.assertNotIn("Fact Check", [s["name"] for s in skills.list_skills()])
        # a seed nobody edited takes the newest wording; an edited one is left alone
        plan, edit = skills.get("plan"), skills.get("edit")
        staff.conn().execute("UPDATE team_skills SET instructions = 'old' WHERE id IN (?, ?)",
                             (plan["id"], edit["id"]))
        staff.conn().commit()
        self.w.put("/admin/api/ai/skills/%d" % edit["id"], json={"instructions": "Ours."})
        skills._refreshed.clear()
        self.assertIn("Plan — an outline", skills.get("plan")["instructions"])
        self.assertEqual(skills.get("edit")["instructions"], "Ours.")

    def test_writer_edits_skills_and_style(self):
        r = self.w.post("/admin/api/ai/skills", json={"name": "Yen Note", "description": "For yen moves.",
                                                      "instructions": "1. Pull the yen."})
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["id"]
        self.assertEqual(self.w.post("/admin/api/ai/skills", json={"name": "Yen Note", "description": "x",
                                                                   "instructions": "y"}).status_code, 400)
        self.assertEqual(self.w.post("/admin/api/ai/skills", json={"name": "No Steps",
                                                                   "description": "x"}).status_code, 400)
        self.assertTrue(r.json()["writes"])
        r = self.w.put("/admin/api/ai/skills/%d" % sid, json={"writes": False})
        self.assertFalse(r.json()["writes"])
        self.assertIn("Yen Note (answers only", skills.menu_text(skills.list_skills(True)))
        r = self.w.put("/admin/api/ai/skills/%d" % sid, json={"enabled": False})
        self.assertFalse(r.json()["enabled"])
        self.assertNotIn("Yen Note", [k["name"] for k in self.w.get("/admin/api/research/ai").json()["skills"]])
        r = self.w.put("/admin/api/ai/house-style", json={"text": "Two decimals for yields."})
        self.assertEqual(r.json()["house_style"], "Two decimals for yields.")
        r = self.w.put("/admin/api/ai/house-style", json={"text": ""})       # empty = the default
        self.assertEqual(r.json()["house_style"], skills.HOUSE_STYLE)


class ModeTest(SetupBase):
    def test_answer_only_run_and_next_steps(self):
        self.connect()
        before = research.get(self.aid)
        brainstorm, plan = skills.get("brainstorm"), skills.get("plan")
        fake = Fake([call("replace_draft", markdown="# Not allowed"),
                     call("offer_next_step", label="Plan This: Yen Pass-Through", skill="Plan",
                          instruction="Plan an article on yen pass-through to import prices."),
                     call("offer_next_step", label="Nowhere", skill="No Such Skill", instruction="x"),
                     say("1. **Yen pass-through** is faster than in 2015.\n2. **Bank margins** widen.")])
        gateway.complete = fake
        r = self.w.post("/admin/api/research/articles/%d/ai" % self.aid,
                        json={"instruction": "", "skill_id": brainstorm["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        j = self.wait(r.json()["id"])
        self.assertEqual(j["status"], "done", j)
        self.assertFalse(j["writes"])
        self.assertNotIn("replace_draft", fake.seen_tools)
        self.assertNotIn("set_details", fake.seen_tools)
        self.assertIn("offer_next_step", fake.seen_tools)
        self.assertFalse(j["changed"])
        self.assertIsNone(j["before_history_id"])
        self.assertEqual(research.get(self.aid)["revision"], before["revision"])
        self.assertNotIn("Before AI", [h["label"] for h in research.history(self.aid)])
        self.assertEqual(j["next"], [{"label": "Plan This: Yen Pass-Through", "skill": "Plan",
                                      "skill_id": plan["id"],
                                      "instruction": "Plan an article on yen pass-through to import prices."}])
        self.assertEqual([s["kind"] for s in j["steps"]], ["error", "tool", "error"])

        # the button: a Plan run, which may write
        o = j["next"][0]
        fake = Fake([call("replace_draft", markdown="# Yen Pass-Through\n\n## Plan\n\nQuestion."),
                     call("offer_next_step", label="Draft It", skill="Draft", instruction="Write it."),
                     say("Planned.")])
        gateway.complete = fake
        r = self.w.post("/admin/api/research/articles/%d/ai" % self.aid,
                        json={"instruction": o["instruction"], "skill_id": o["skill_id"]})
        j = self.wait(r.json()["id"])
        self.assertEqual(j["status"], "done", j)
        self.assertTrue(j["writes"])
        self.assertTrue(j["changed"])
        self.assertIsNotNone(j["before_history_id"])
        self.assertIn("replace_draft", fake.seen_tools)
        self.assertEqual([x["label"] for x in j["next"]], ["Draft It"])

    def test_cli_run_answer_only_and_offers_from_log(self):
        log = os.path.join(str(research.DATA_DIR), "calls.jsonl")
        ctx = research_ai_mcp.Context({"staff_id": self.wid, "article_id": self.aid, "client": "Codex",
                                       "log": log, "read_only": True})
        names = [t["name"] for t in ctx.tools]
        self.assertNotIn("replace_draft", names)
        self.assertIn("get_draft", names)
        text, err = ctx.call("append_to_draft", {"markdown": "x"})
        self.assertTrue(err)
        text, err = ctx.call("offer_next_step", {"label": "Review It", "skill": "Review",
                                                 "instruction": "Review the draft."})
        self.assertFalse(err, text)
        job = {"steps": [], "next": []}
        stop = threading.Event()
        stop.set()
        research_ai._follow(job, log, stop)
        self.assertEqual([(x["label"], x["skill"]) for x in job["next"]], [("Review It", "Review")])
        self.assertEqual(job["steps"][-1]["text"], "Offered a next step: Review It")


class ConnectorTest(SetupBase):
    def add(self, client=None):
        return (client or self.team).post("/admin/api/ai/connectors", json={
            "label": "Notes", "url": "https://notes.example.com/mcp", "auth_kind": "bearer",
            "key": "secret-key-12345678"})

    def test_team_only_key_sealed_destructive_off(self):
        self.assertEqual(self.add(self.w).status_code, 403)              # writing alone is not enough
        r = self.add()
        self.assertEqual(r.status_code, 200, r.text)
        c = r.json()
        self.assertNotIn("secret-key", json.dumps(c))
        self.assertEqual(c["key_last4"], "5678")
        self.assertIn(("connect", "https://notes.example.com/mcp", "secret-key-12345678"), self.remote)
        on = dict((t["name"], t["on"]) for t in c["tools"])
        self.assertEqual(on, {"search_notes": True, "delete_note": False})
        names = [t["name"] for t in connectors.run_tools()]
        self.assertEqual(names, ["x%d_search_notes" % c["id"]])
        text, err = connectors.call(c["id"], "delete_note", {})
        self.assertTrue(err)
        self.assertIn("switched off", text)
        # a writer sees connectors but cannot change one
        self.assertEqual(self.w.put("/admin/api/ai/connectors/%d/tools" % c["id"],
                                    json={"tool": "delete_note", "on": True}).status_code, 403)

    def test_run_uses_skill_and_connector(self):
        cid = self.add().json()["id"]
        self.connect()
        fake = Fake([{"text": "", "tool_calls": [{"id": "s1", "name": "read_skill",
                                                  "args": {"name": "Fact Check"}}]},
                     call("x%d_search_notes" % cid, query="BoJ"),
                     say("Checked.")])
        seen = []
        real_complete = fake.__call__

        def spy(provider, key, model, messages, tools=None, max_tokens=1500, base_url=None):
            seen.append(messages[0]["content"])
            return real_complete(provider, key, model, messages, tools, max_tokens, base_url)
        gateway.complete = spy
        skill = skills.get("data-flash")
        r = self.w.post("/admin/api/research/articles/%d/ai" % self.aid,
                        json={"instruction": "", "skill_id": skill["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        j = self.wait(r.json()["id"])
        self.assertEqual(j["status"], "done", j)
        self.assertEqual(j["skill"], "Data Flash")
        self.assertIn("read_skill", fake.seen_tools)
        self.assertIn("x%d_search_notes" % cid, fake.seen_tools)
        self.assertNotIn("drive_search", fake.seen_tools)               # Drive not connected
        self.assertIn("Follow its steps", seen[0])
        self.assertIn("No implications, no flash", seen[0])
        self.assertIn("Notes", seen[0])                                  # told what is connected
        self.assertEqual([s["text"] for s in j["steps"]],
                         ['Opened the skill "Fact Check"', "Used Notes: search notes"])
        self.assertIn(("call", "search_notes", {"query": "BoJ"}, "secret-key-12345678"), self.remote)

    def test_cli_tool_server_uses_handed_credentials(self):
        cid = self.add().json()["id"]
        log = os.path.join(str(research.DATA_DIR), "calls.jsonl")
        ctx = research_ai_mcp.Context({
            "staff_id": self.wid, "article_id": self.aid, "client": "Codex", "log": log,
            "creds": {"google_token": "ya29.handed", "connector_keys": {str(cid): "handed-key"}}})
        names = [t["name"] for t in ctx.tools]
        self.assertIn("drive_search", names)                             # the handed token stands in
        text, err = ctx.call("x%d_search_notes" % cid, {"query": "q"})
        self.assertFalse(err, text)
        self.assertEqual(self.remote[-1], ("call", "search_notes", {"query": "q"}, "handed-key"))
        staff_google._handed.discard(self.wid)
        staff_google._access.pop(self.wid, None)


class GoogleTest(SetupBase):
    def test_drive_tools_need_a_connection(self):
        os.environ["GOOGLE_OAUTH_CLIENT_ID"] = "cid"
        os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = "csecret"
        self.addCleanup(os.environ.pop, "GOOGLE_OAUTH_CLIENT_ID", None)
        self.addCleanup(os.environ.pop, "GOOGLE_OAUTH_CLIENT_SECRET", None)
        person = staff.get(self.wid)
        self.assertNotIn("drive_read", [t["name"] for t in research_ai.tool_list({"person": person})])
        self.assertEqual(self.admin.post("/admin/api/ai/google/start").status_code, 403)   # shared login
        url = self.w.post("/admin/api/ai/google/start").json()["url"]
        self.assertIn("drive.readonly", url)
        self.assertIn("%2Fadmin%2Fapi%2Fai%2Fgoogle%2Fcallback", url)
        state = url.split("state=")[1].split("&")[0]
        self.assertTrue(staff_google.check_state(state, self.wid))
        self.assertFalse(staff_google.check_state(state, self.tid))    # bound to the person

        from app.assistant import drive as gd
        real = gd._http
        sent = []

        def fake_http(method, url, headers=None, data=None, timeout=30):
            sent.append(url)
            if "oauth2" in url:
                return 200, json.dumps({"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                                        "scope": "openid email https://www.googleapis.com/auth/drive.readonly"}).encode(), ""
            if "/export" in url:
                return 200, b"Minutes text", "text/plain"
            if "/files/" in url:
                return 200, json.dumps({"id": "abc123abc123abc123abc1", "name": "BoJ notes",
                                        "mimeType": "application/vnd.google-apps.document"}).encode(), ""
            return 200, json.dumps({"files": [{"id": "abc123abc123abc123abc1", "name": "BoJ notes",
                                               "mimeType": "application/vnd.google-apps.document"}]}).encode(), ""
        gd._http = fake_http
        try:
            staff_google.finish(self.wid, "code", "http://testserver")
            self.assertIn("drive_read", [t["name"] for t in research_ai.tool_list({"person": person})])
            found = staff_google.search(self.wid, "BoJ")
            self.assertEqual(found[0]["type"], "Google Doc")
            doc = staff_google.read(self.wid, "https://docs.google.com/document/d/abc123abc123abc123abc1/edit")
            self.assertEqual(doc["text"], "Minutes text")
            self.assertNotIn("rt", json.dumps(staff_google.status_for(self.wid)))
            staff_google.set_team_enabled(False)
            self.assertNotIn("drive_read", [t["name"] for t in research_ai.tool_list({"person": person})])
        finally:
            gd._http = real
            staff_google.set_team_enabled(True)
            staff_google._access.pop(self.wid, None)


class ClientTest(SetupBase):
    def test_event_stream_and_session(self):
        text = ('event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
                'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"ok":1}}\n\n')
        self.assertEqual(mcp_client._from_stream(text, 7)["result"], {"ok": 1})
        with self.assertRaises(ValueError):
            mcp_client._from_stream("data: \n\n", 1)
        server = {"url": "https://s.example.com/mcp", "_session": "sess-1"}
        self.assertEqual(mcp_client._headers(server, None)["Mcp-Session-Id"], "sess-1")
        self.assertIn("text/event-stream", mcp_client._headers(server, None)["Accept"])


if __name__ == "__main__":
    import unittest
    unittest.main()
