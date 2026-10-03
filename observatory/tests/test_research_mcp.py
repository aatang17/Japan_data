# -*- coding: utf-8 -*-
"""Drafting over MCP, charts copied from Plover pages, and the research panel.

What is proved: a personal key reaches /mcp/research only while its person is
active and can write, and a revoked key stops at once; the drafting tools
create and edit drafts as "<email> via Claude" and none of them publishes;
an edit on a stale revision is refused; replacing a draft keeps the data of a
chart already copied from a page; the editable Markdown round-trips; a page
chart is stored only with a kind the chart code knows and an address on this
site, renders with its source and capture date, and blocks publication until
it has been copied; the page reader refuses private and unusual addresses.
"""
import json
import os
import pathlib
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import (admin_api, research, research_api, research_doc as rd, research_mcp,
                 research_pages as rp, research_web, staff)

GOOD = "correct horse battery"
CFG = {"series": [{"name": "Revenue", "slot": 1, "points": [["2024-03-31", 45.1], ["2025-03-31", 48.0]]}],
       "unit": "¥tn", "trust": "official", "sourceLine": "Source: EDINET annual reports."}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        staff.DB_PATH = root / "staff.db"
        research.DATA_DIR = root / "research"
        admin_api.ADMIN_DIR = root
        admin_api.AUDIT_PATH = root / "audit.jsonl"
        admin_api._LOGIN_HITS.clear()
        self._iters = staff.PBKDF2_ITERATIONS
        staff.PBKDF2_ITERATIONS = 1000
        staff._DUMMY_HASH = None
        self._pw = os.environ.get("ADMIN_PASSWORD")
        os.environ["ADMIN_PASSWORD"] = "shared-secret"
        self.addCleanup(self._restore)
        app = FastAPI()
        app.include_router(admin_api.router)
        app.include_router(research_api.router)
        app.include_router(rp.router)
        app.include_router(research_mcp.router)
        self.app = app
        admin = TestClient(app)
        admin.post("/admin/api/login", json={"password": "shared-secret"})
        self.admin = admin
        self.w, self.wid = self.person("w@example.com", ["writing"])
        self.key = self.w.post("/admin/api/me/keys", json={"label": "Claude Code"}).json()["token"]

    def _restore(self):
        staff.PBKDF2_ITERATIONS = self._iters
        staff._DUMMY_HASH = None
        if self._pw is None:
            os.environ.pop("ADMIN_PASSWORD", None)
        else:
            os.environ["ADMIN_PASSWORD"] = self._pw

    def person(self, email, perms):
        r = self.admin.post("/admin/api/team", json={"email": email, "name": email.split("@")[0],
                                                     "permissions": perms})
        c = TestClient(self.app)
        c.post("/admin/api/setup", json={"token": r.json()["setup_url"].split("#setup=")[1],
                                         "password": GOOD})
        return c, r.json()["person"]["id"]

    def mcp(self, method, params=None, key=None, ua="claude-code/2.0"):
        c = TestClient(self.app)
        return c.post("/mcp/research", json={"jsonrpc": "2.0", "id": 1, "method": method,
                                             "params": params or {}},
                      headers={"Authorization": "Bearer " + (key or self.key), "User-Agent": ua})

    def tool(self, name, **args):
        r = self.mcp("tools/call", {"name": name, "arguments": args})
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()["result"]
        return json.loads(res["content"][0]["text"]), res["isError"]


class KeysTest(Base):
    def test_key_gates(self):
        self.assertEqual(TestClient(self.app).post("/mcp/research", json={}).status_code, 401)
        self.assertEqual(self.mcp("tools/list", key="plvr_wrong").status_code, 401)
        r = self.mcp("initialize", {"protocolVersion": "2025-06-18"})
        self.assertIn("Drafts only", r.json()["result"]["instructions"])
        names = [t["name"] for t in self.mcp("tools/list").json()["result"]["tools"]]
        self.assertIn("create_draft", names)
        self.assertIn("search", names)                      # Plover data tools ride along
        for forbidden in ("publish", "publish_article", "withdraw", "delete_article"):
            self.assertNotIn(forbidden, names)
        # shared password cannot make a key; it is nobody
        self.assertEqual(self.admin.post("/admin/api/me/keys", json={}).status_code, 400)
        # revoke stops it
        kid = self.w.get("/admin/api/me/keys").json()["keys"][0]["id"]
        self.w.delete("/admin/api/me/keys/%d" % kid)
        self.assertEqual(self.mcp("tools/list").status_code, 401)

    def test_key_dies_with_permission_or_account(self):
        self.admin.put("/admin/api/team/%d" % self.wid, json={"permissions": ["operations"]})
        self.assertEqual(self.mcp("tools/list").status_code, 403)
        self.admin.put("/admin/api/team/%d" % self.wid, json={"permissions": ["writing"], "status": "disabled"})
        self.assertEqual(self.mcp("tools/list").status_code, 401)

    def test_keys_are_hashed(self):
        raw = open(str(staff.DB_PATH), "rb").read()
        self.assertNotIn(self.key.encode(), raw)


class DraftingTest(Base):
    MD = ("# Core inflation and the yen\n\n*A short note.*\n\n## Prices\n\nCore CPI rose[^1].\n\n"
          "![Core CPI](plover:cpi-jp?series=0161&measure=yoy&start=2020-01)\n\n"
          "![Toyota revenue](https://ploveranalytics.com/financials.html?c=7203#chart-1)\n\n"
          "## Outlook\n\nMore to come.\n\n[^1]: Statistics Bureau, August 2026.\n")

    def test_create_read_edit_never_publishes(self):
        out, err = self.tool("create_draft", markdown=self.MD, summary="Core CPI and the yen.")
        self.assertFalse(err, out)
        aid = out["article_id"]
        self.assertEqual(out["pending_charts"], [{"chart": 2, "url": "/financials.html?c=7203"}])
        a = research.get(aid)
        self.assertEqual(a["created_by"], "w@example.com via Claude")
        self.assertEqual(a["draft"]["authors"], [self.wid])
        self.assertEqual(a["status"], "draft")
        read, _ = self.tool("read_article", article_id=aid)
        self.assertIn("plover:cpi-jp?series=0161&measure=yoy&start=2020-01", read["markdown"])
        self.assertIn("/financials.html?c=7203#chart-1", read["markdown"])
        self.assertIn("[^1]: Statistics Bureau", read["markdown"])
        # check names what is missing, including the uncaptured chart
        chk, _ = self.tool("check_article", article_id=aid)
        self.assertTrue(any("waiting to be copied" in p for p in chk["problems"]))
        self.assertFalse(chk["ready"])
        # a person captures the page chart in the desk (simulated: a save with cfg)
        d = research.get(aid)["draft"]
        snap = [b for b in d["blocks"] if b["type"] == "snapshot"][0]
        snap.update({"kind": "line", "cfg": CFG, "page_title": "Financials", "source": "EDINET",
                     "captured_at": "2026-10-03"})
        rev = research.save(aid, d, research.get(aid)["revision"], "w@example.com")["revision"]
        # replacing the body keeps the captured data for the same line
        md2 = read["markdown"].replace("More to come.", "Rates may follow.")
        out2, err2 = self.tool("replace_draft", article_id=aid, base_revision=rev, markdown=md2)
        self.assertFalse(err2, out2)
        kept = [b for b in research.get(aid)["draft"]["blocks"] if b["type"] == "snapshot"][0]
        self.assertEqual(kept["cfg"], CFG)
        self.assertEqual(out2["pending_charts"], [])
        # a stale revision is refused, naming who saved
        stale, err3 = self.tool("append_to_draft", article_id=aid, base_revision=rev, markdown="More.")
        self.assertTrue(err3)
        self.assertIn("newer revision", stale["error"])
        # append after a named section
        cur = research.get(aid)["revision"]
        out4, err4 = self.tool("append_to_draft", article_id=aid, base_revision=cur,
                               markdown="An added paragraph.", after_heading="Prices")
        self.assertFalse(err4, out4)
        blocks = research.get(aid)["draft"]["blocks"]
        texts = [rd.inline_text(b.get("html", "")) or b.get("text", "") for b in blocks]
        self.assertLess(texts.index("An added paragraph."), texts.index("Outlook"))
        hist = research.history(aid)
        self.assertTrue(any((h["label"] or "").endswith("via Claude") for h in hist))
        self.assertIsNone(research.get(aid)["published_version"])
        audit = [json.loads(x) for x in open(str(admin_api.AUDIT_PATH))]
        self.assertTrue(any(e["action"] == "mcp_draft_created" and e["by"] == "w@example.com via Claude"
                            for e in audit))

    def test_codex_label_and_slug_rules(self):
        r = self.mcp("tools/call", {"name": "create_draft", "arguments": {"markdown": "# T\n\nBody."}},
                     ua="codex_cli_rs/0.40")
        aid = json.loads(r.json()["result"]["content"][0]["text"])["article_id"]
        self.assertEqual(research.get(aid)["created_by"], "w@example.com via Codex")
        out, err = self.tool("create_draft", markdown="Body with no title.")
        self.assertTrue(err)
        self.assertIn("# Title", out["error"])


class SnapshotTest(unittest.TestCase):
    def test_validation(self):
        d = rd.clean_draft({"blocks": [
            {"type": "snapshot", "url": "https://evil.com/x.html", "kind": "line", "cfg": CFG},
            {"type": "snapshot", "url": "/admin.html", "kind": "line", "cfg": CFG},
            {"type": "snapshot", "url": "/financials.html?c=7203", "kind": "pie", "cfg": CFG},
            {"type": "snapshot", "url": "/financials.html?c=7203", "kind": "line", "cfg": CFG,
             "title": "Revenue", "source": "EDINET", "captured_at": "2026-10-03", "chart": 2}]})
        b = d["blocks"]
        self.assertEqual((b[0]["url"], b[1]["url"]), ("", ""))
        self.assertIsNone(b[2]["cfg"])                         # unknown chart kind
        self.assertEqual(b[3]["cfg"], CFG)
        self.assertEqual(b[3]["chart"], 2)
        with self.assertRaises(rd.DocError):
            rd.clean_draft({"blocks": [{"type": "snapshot", "url": "/x.html", "kind": "line",
                                        "cfg": {"series": [{"points": [["x", 1]] * 200000}]}}]})

    def test_render_and_problems(self):
        d = rd.clean_draft({"title": "T", "summary": "S", "slug": "t", "blocks": [
            {"type": "p", "html": "Text."},
            {"type": "snapshot", "url": "/financials.html?c=7203", "kind": "line", "cfg": CFG,
             "title": "Revenue", "source": "EDINET <annual> reports", "captured_at": "2026-10-03",
             "calc": "Sum of segments."},
            {"type": "snapshot", "url": "/ownership.html?c=7203", "title": "Holders"}]})
        html = rd.render_body(d)
        self.assertIn('href="/financials.html?c=7203">View on Plover</a>', html)
        self.assertIn("EDINET &lt;annual&gt; reports · Captured 3 October 2026 · Values as published.", html)
        self.assertNotIn("Official Statistic", html)
        self.assertIn("Show calculation", html)
        self.assertIn("not been copied", html)
        probs = rd.publish_problems(d, ["A"])
        self.assertEqual([p for p in probs if "Chart" in p],
                         ["Chart 2 is waiting to be copied from /ownership.html?c=7203: open the "
                          "draft in the desk to capture it."])
        v = {"doc": d, "snapshots": {}, "slug": "t", "version": 1}
        data = rp._chart_data(v)
        sid = d["blocks"][1]["id"]
        self.assertEqual(data["charts"][sid]["kind"], "line")
        self.assertEqual(data["charts"][sid]["cfg"], CFG)


class WebGuardTest(unittest.TestCase):
    def test_refuses_private_and_odd_addresses(self):
        for u in ("http://127.0.0.1/", "http://localhost/", "http://169.254.169.254/latest/meta-data",
                  "http://10.1.2.3/", "http://[::1]/", "file:///etc/passwd", "ftp://x.com/",
                  "https://example.com:8443/", "javascript:alert(1)"):
            with self.assertRaises(research_web.WebError, msg=u):
                research_web._check_url(u)

    def test_reader_extracts_text(self):
        p = research_web._Reader()
        p.feed('<html><head><title>T</title><meta property="og:site_name" content="BoJ">'
               '<meta property="article:published_time" content="2026-09-30"></head><body>'
               '<nav><p>menu</p></nav><h1>Head</h1><p>One <b>two</b>.</p><script>x()</script>'
               '<ul><li>Item</li></ul><footer><p>foot</p></footer></body></html>')
        p.close()
        p._flush()
        self.assertEqual([b["text"] for b in p.blocks], ["Head", "One two.", "Item"])
        self.assertEqual(p.meta["og:site_name"], "BoJ")


if __name__ == "__main__":
    unittest.main()
