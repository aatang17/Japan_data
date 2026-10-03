# -*- coding: utf-8 -*-
"""Send to Plover: pages a writer sends from their own browser.

What is proved: a sent page is stored as text and only its sender can list,
read or delete it; someone signed out cannot send one; the same article sent
again (tracking parameters and all) replaces the earlier copy; a page with no
text, or an address that is not a web address, is refused with a sentence the
writer can act on; text past the cap is cut, not refused; each person keeps
their newest pages only; the AI tab's read_page reads the writer's copy
instead of fetching the page, and only that writer's.
"""
import json

from app import research_ai, research_clips, research_web
from tests.test_research import Base, GOOD

FT = {
    "url": "https://www.ft.com/content/0b1c-yen",
    "title": "The yen and the BoJ",
    "site": "Financial Times",
    "published": "2026-10-02T05:00:00Z",
    "author": "A Reporter",
    "blocks": [{"kind": "h", "text": "The decision"},
               {"kind": "p", "text": "The Bank of Japan held its policy rate."},
               {"kind": "quote", "text": "We will act if needed."},
               {"kind": "nav", "text": "dropped: not a kind we keep"}],
}


class ClipTests(Base):
    def setUp(self):
        Base.setUp(self)
        self.app.include_router(research_clips.router)
        r = self.w.post("/admin/api/team", json={"email": "o@example.com", "name": "Otto Other",
                                                 "permissions": ["writing"]})
        tok = r.json()["setup_url"].split("#setup=")[1]
        from fastapi.testclient import TestClient
        self.o = TestClient(self.app)
        self.o.post("/admin/api/setup", json={"token": tok, "password": GOOD})
        self.other_id = r.json()["person"]["id"]

    def send(self, client=None, **over):
        body = dict(FT)
        body.update(over)
        return (client or self.w).post("/admin/api/research/clips", json=body)

    def test_send_list_read_delete_are_private(self):
        r = self.send()
        self.assertEqual(r.status_code, 200, r.text)
        clip = r.json()
        self.assertEqual([b["kind"] for b in clip["blocks"]], ["h", "p", "quote"])
        self.assertTrue(clip["sent"])
        self.assertEqual(clip["chars"], sum(len(b["text"]) for b in clip["blocks"]))

        mine = self.w.get("/admin/api/research/clips").json()["clips"]
        self.assertEqual([c["title"] for c in mine], ["The yen and the BoJ"])
        self.assertNotIn("blocks", mine[0])
        self.assertEqual(self.o.get("/admin/api/research/clips").json()["clips"], [])
        self.assertEqual(self.o.get("/admin/api/research/clips/%d" % clip["id"]).status_code, 404)
        self.assertEqual(self.o.delete("/admin/api/research/clips/%d" % clip["id"]).status_code, 404)
        self.assertEqual(self.w.get("/admin/api/research/clips/%d" % clip["id"]).json()["title"],
                         "The yen and the BoJ")

        self.assertEqual(self.w.delete("/admin/api/research/clips/%d" % clip["id"]).status_code, 200)
        self.assertEqual(self.w.get("/admin/api/research/clips").json()["clips"], [])

    def test_signed_out_cannot_send(self):
        self.assertEqual(self.send(self.anon).status_code, 401)

    def test_same_article_replaces_earlier_copy(self):
        self.send()
        self.send(url="https://www.ft.com/content/0b1c-yen?accessToken=x#comments",
                  title="The yen and the BoJ (updated)")
        mine = self.w.get("/admin/api/research/clips").json()["clips"]
        self.assertEqual([c["title"] for c in mine], ["The yen and the BoJ (updated)"])

    def test_refusals_are_worded(self):
        r = self.send(blocks=[{"kind": "p", "text": "   "}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("No article text came through", r.json()["detail"])
        r = self.send(url="javascript:alert(1)")
        self.assertEqual(r.status_code, 400)
        self.assertIn("address did not come through", r.json()["detail"])

    def test_long_text_is_cut_and_old_pages_drop_off(self):
        para = "x" * 19000
        r = self.send(blocks=[{"kind": "p", "text": para + str(i)} for i in range(10)])
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(r.json()["chars"], research_clips.TEXT_MAX)
        keep = research_clips.KEEP
        research_clips.KEEP = 3
        self.addCleanup(setattr, research_clips, "KEEP", keep)
        for i in range(5):
            self.send(url="https://www.wsj.com/articles/a-%d" % i, title="WSJ %d" % i)
        titles = [c["title"] for c in self.w.get("/admin/api/research/clips").json()["clips"]]
        self.assertEqual(titles, ["WSJ 4", "WSJ 3", "WSJ 2"])

    def test_ai_read_page_uses_the_writers_copy(self):
        self.send()
        fetched = []
        real = research_web.read
        research_web.read = lambda url: fetched.append(url) or {
            "url": url, "title": "Teaser", "site": "ft.com", "published": "", "author": "",
            "blocks": [{"kind": "p", "text": "Subscribe to read."}], "pdf": False}
        self.addCleanup(setattr, research_web, "read", real)

        from app import staff
        me = {"person": staff.get(self.writer_id), "client": "Claude", "article_id": 1}
        text, err = research_ai.call_tool(me, "read_page", {"url": "https://www.ft.com/content/0b1c-yen?ftcamp=x"})
        self.assertFalse(err)
        page = json.loads(text)
        self.assertIn("held its policy rate", page["text"])
        self.assertTrue(page["sent_from_browser"])
        self.assertEqual(fetched, [])

        text, err = research_ai.call_tool(me, "list_sent_pages", {})
        self.assertEqual([p["title"] for p in json.loads(text)["pages"]], ["The yen and the BoJ"])

        other = {"person": staff.get(self.other_id), "client": "Claude", "article_id": 1}
        text, err = research_ai.call_tool(other, "read_page", {"url": FT["url"]})
        self.assertEqual(json.loads(text)["title"], "Teaser")
        self.assertEqual(fetched, [FT["url"]])
