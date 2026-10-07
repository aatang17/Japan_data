# -*- coding: utf-8 -*-
"""Send to Plover: pages a writer sends from their own browser.

What is proved: a sent page is stored as text and only its sender can list,
read or delete it; someone signed out cannot send one; the same article sent
again (tracking parameters and all) replaces the earlier copy; a page with no
text, or an address that is not a web address, is refused with a sentence the
writer can act on; text past the cap is cut, not refused; each person keeps
their newest pages only; the AI tab's read_page reads the writer's copy
instead of fetching the page, and only that writer's.

Pasting: a whole-page copy keeps the article and drops the menus, headline
lists and newsletter box around it; a short paste is kept whole as a
passage; plain text works when the clipboard had no HTML; the paste is kept
against the address the writer read, so read_page finds it; an empty paste
or a missing address is refused with a sentence the writer can act on.
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


ARTICLE = ["The Bank of Japan held its policy rate at 0.75 per cent on Friday, as officials weighed "
           "the yen's slide against signs that wage growth is spreading to smaller companies.",
           "Governor Ueda said the board would raise rates again if the outlook held, but gave no "
           "date, and markets pushed back their bets on a December move after the decision.",
           "The yen weakened past 160 per dollar after the announcement, its lowest level since "
           "July, before recovering some ground in late trading in Tokyo and London."]

PAGE = ("<meta charset='utf-8'><header><a href='/'>FT</a><a href='/markets'>Markets</a></header>"
        "<ul><li><a href='/a'>Home</a></li><li><a href='/b'>World</a></li></ul>"
        "<p>Accessibility help Skip to content</p>"
        "<h1>BoJ holds rates as yen slides</h1>"
        + "".join("<p>%s</p>" % t for t in ARTICLE[:2])
        + "<h2>Markets react</h2><p>%s</p>" % ARTICLE[2]
        + "<p>Copyright The Financial Times Limited 2026</p>"
        + "".join("<h3><a href='/c%d'>Recommended headline number %d about something else</a></h3>" % (i, i)
                  for i in range(8))
        + "<p>Sign up to our newsletter for the best of the FT every morning, with news, analysis "
          "and opinion from our reporters around the world, free.</p>"
        + "<p>Short</p>" * 7
        + "<p>Promoted content: a long paragraph from an advertiser that is not part of the article "
          "at all but is long enough to look like one on its own.</p>")


class PasteReaderTests(Base):
    def test_whole_page_keeps_the_article(self):
        r = research_web.read_pasted(PAGE, "")
        texts = [b["text"] for b in r["blocks"]]
        self.assertEqual(texts, [ARTICLE[0], ARTICLE[1], "Markets react", ARTICLE[2]])
        self.assertEqual(r["title"], "BoJ holds rates as yen slides")
        self.assertFalse(r["selection"])

    def test_a_short_paste_is_a_passage_kept_whole(self):
        r = research_web.read_pasted("<p>%s</p><p>Ueda, 2 October</p>" % ARTICLE[0], "")
        self.assertEqual([b["text"] for b in r["blocks"]], [ARTICLE[0], "Ueda, 2 October"])
        self.assertTrue(r["selection"])

    def test_plain_text_when_there_is_no_html(self):
        long_read = ARTICLE + ["Paragraph %d. %s" % (i, ARTICLE[i % 3]) for i in range(20)]
        text = "\n".join(["Home", "World", "Markets", "Skip to content"] + long_read +
                          ["Copyright 2026", "Terms", "Privacy", "Cookies", "Help", "Contact", "Careers"])
        r = research_web.read_pasted("", text)
        self.assertEqual([b["text"] for b in r["blocks"]], long_read)
        self.assertFalse(r["selection"])
        # A short passage pasted as plain text is kept whole.
        r = research_web.read_pasted("", ARTICLE[0] + "\nUeda, 2 October")
        self.assertEqual(len(r["blocks"]), 2)
        self.assertTrue(r["selection"])

    def test_japanese_paragraphs_count_as_article_text(self):
        jp = ["ニトリホールディングス（HD）は不要家具を再資源化する取り組みを始める。2028年に埼玉県で国内最大規模の"
              "リサイクル施設を稼働する。小売り大手のニトリが循環経済に向けた取り組みに踏み出す。",
              "約25億円を投じて処理施設を開設し28年度上半期に稼働させる。土地面積は1万5000平方メートルで、"
              "再資源化の施設2棟と事務所兼研究施設の1棟で構成する。",
              "回収した家具は分解して木材や金属、布などに分け、原材料として再利用する。新たな製品の生産に生かし、"
              "廃棄される家具の量を減らす計画で、他社からの受け入れも検討する。"]
        html = "<p><a href='/x'>日経の記事利用サービスについて</a></p>" + "".join("<p>%s</p>" % t for t in jp)
        r = research_web.read_pasted(html + "<p>新着</p>" * 8, "")
        self.assertEqual([b["text"] for b in r["blocks"]], jp)
        self.assertFalse(r["selection"])


class PasteTests(ClipTests):
    def paste(self, client=None, **over):
        body = {"url": "https://www.ft.com/content/0b1c-yen?ftcamp=x", "title": "", "site": "www.ft.com",
                "html": PAGE, "text": ""}
        body.update(over)
        return (client or self.w).post("/admin/api/research/clips/paste", json=body)

    def test_paste_is_kept_against_the_address(self):
        r = self.paste()
        self.assertEqual(r.status_code, 200, r.text)
        clip = r.json()
        self.assertEqual(clip["title"], "BoJ holds rates as yen slides")
        self.assertEqual(clip["blocks"][0]["text"], ARTICLE[0])
        self.assertEqual(research_clips.find(self.writer_id, "https://www.ft.com/content/0b1c-yen")["id"], clip["id"])
        self.assertIsNone(research_clips.find(self.other_id, "https://www.ft.com/content/0b1c-yen"))
        # The reader's own title wins over the heading found in the paste.
        self.assertEqual(self.paste(title="The yen and the BoJ").json()["title"], "The yen and the BoJ")
        self.assertEqual(len(self.w.get("/admin/api/research/clips").json()["clips"]), 1)

    def test_paste_refusals_are_worded(self):
        self.assertEqual(self.paste(self.anon).status_code, 401)
        r = self.paste(html="<nav><a href='/'>Home</a></nav>", text="  ")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Nothing readable was pasted", r.json()["detail"])
        r = self.paste(url="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Read the article's address above first", r.json()["detail"])
