# -*- coding: utf-8 -*-
"""What a crawler without JavaScript receives: links, figures, a description.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_prerender
"""
import pathlib
import re
import unittest

from fastapi.testclient import TestClient

from app import prerender
from app.main import app

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
LINK = re.compile(r'(?is)<a\b[^>]*href=["\']([^"\'#]+\.html)')


class PrerenderTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.cpi = cls.client.get("/cpi.html").text

    def test_the_site_links_are_in_the_served_html(self):
        # Before this, a page served one internal link and the whole nav was
        # built by JavaScript: a crawler that does not render saw 32 isolated
        # pages and could infer nothing about which mattered.
        links = set(LINK.findall(self.cpi))
        self.assertGreater(len(links), 20, "nav links missing from served HTML")
        self.assertIn("boj.html", links)

    def test_the_links_sit_where_nav_js_overwrites_them(self):
        # Inside the header shell, whose innerHTML nav.js assigns on load. A
        # reader therefore sees the real bar and never these; serving links
        # the rendered page does not show would be cloaking.
        header = re.search(r'(?is)<header class="site-header"[^>]*>(.*?)</header>',
                           self.cpi)
        self.assertIsNotNone(header)
        self.assertIn("<a href=", header.group(1))

    def test_a_dataset_page_serves_its_headline_figures(self):
        block = re.search(r"(?is)<noscript>(.*?)</noscript>", self.cpi)
        self.assertIsNotNone(block, "no figures served for a dataset page")
        self.assertIn("Latest reading", block.group(1))
        self.assertRegex(block.group(1), r"\d+\.\d")

    def test_the_figures_cannot_flash_or_shift_the_layout(self):
        # <noscript> is never rendered by a browser that runs scripts, so the
        # sentence cannot appear while the page script waits on its fetch.
        self.assertNotIn("Latest reading",
                         re.sub(r"(?is)<noscript>.*?</noscript>", "", self.cpi))

    def test_rates_keep_a_decimal_and_large_numbers_get_separators(self):
        self.assertEqual(prerender._format(2.0, "%"), "2.0%")
        self.assertEqual(prerender._format(-0.35, "pp"), "-0.3pp")
        self.assertEqual(prerender._format(5193819.0, "¥100mn"),
                         "5,193,819 ¥100mn")

    def test_every_served_page_has_a_description(self):
        missing = []
        for url in re.findall(r"<loc>([^<]+)</loc>",
                              self.client.get("/sitemap.xml").text):
            path = url.split("ploveranalytics.com")[-1] or "/"
            body = self.client.get(path).text
            if not re.search(r'(?is)<meta[^>]+name=["\']description["\']', body):
                missing.append(path)
        self.assertEqual(missing, [], "pages served with no meta description")

    def test_a_description_is_never_added_twice(self):
        page = '<html><head><meta name="description" content="mine"></head><body></body></html>'
        self.assertEqual(prerender.inject(page, "cpi.html").count("name=\"description\""), 1)

    def test_injection_never_raises(self):
        # Best-effort by design: a page that renders beats an annotated one.
        for junk in ("", "<html>", "not html at all", "<main data-dataset='nope'>"):
            self.assertIsInstance(prerender.inject(junk, "cpi.html"), str)
        self.assertEqual(prerender.inject("<x>", "unknown-page.html"), "<x>")

    def test_a_revisit_is_still_a_cheap_304(self):
        first = self.client.get("/cpi.html")
        tag = first.headers.get("etag")
        self.assertTrue(tag)
        again = self.client.get("/cpi.html", headers={"If-None-Match": tag})
        self.assertEqual(again.status_code, 304)

    def test_described_pages_all_exist(self):
        for name in prerender.DESCRIPTIONS:
            self.assertTrue((WEB / name).exists(), "%s is described but absent" % name)


if __name__ == "__main__":
    unittest.main()
