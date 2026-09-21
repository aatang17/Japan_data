# -*- coding: utf-8 -*-
"""What a crawler without JavaScript receives: links, figures, a table, a description.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_prerender
"""
import pathlib
import re
import unittest

from fastapi.testclient import TestClient

from app import prerender
from app.main import app
from tests import _data

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

    @unittest.skipUnless(_data.MACRO, _data.NO_MACRO)
    def test_a_dataset_page_serves_its_headline_figures(self):
        block = re.search(r'(?is)<details class="calc readable".*?</details>', self.cpi)
        self.assertIsNotNone(block, "no figures served for a dataset page")
        self.assertIn("Latest reading", block.group(0))
        self.assertRegex(block.group(0), r"\d+\.\d")

    @unittest.skipUnless(_data.MACRO, _data.NO_MACRO)
    def test_a_dataset_page_serves_a_table_of_latest_values(self):
        # Crawlers that strip <noscript> — several of the ones behind AI
        # assistants — must still get the numbers: a real <table>, in the
        # page, with the period, the level and the unit.
        block = re.search(r'(?is)<details class="calc readable".*?</details>', self.cpi)
        self.assertIn("<table", block.group(0))
        self.assertIn("Headline CPI (index)", block.group(0))
        self.assertGreater(block.group(0).count("<tr>"), 6)
        self.assertNotIn("<noscript>", self.cpi)

    def test_the_figures_sit_where_no_script_repaints(self):
        # The block is written after the page's last section, inside <main>,
        # where no page script assigns innerHTML: it can neither flash nor
        # move the layout when the data lands.
        main = re.search(r"(?is)<main\b.*?</main>", self.cpi).group(0)
        self.assertIn('<details class="calc readable"', main)
        self.assertLess(main.rfind("<section"), main.find('class="calc readable"'))

    @unittest.skipUnless(_data.MACRO, _data.NO_MACRO)
    def test_the_same_figures_are_served_as_markdown(self):
        got = self.client.get("/cpi.md")
        self.assertEqual(got.status_code, 200)
        self.assertTrue(got.headers["content-type"].startswith("text/markdown"))
        self.assertIn("# ", got.text)
        self.assertIn("Latest reading", got.text)
        self.assertIn("| Period |", got.text)
        self.assertIn('type="text/markdown" href="/cpi.md"', self.cpi)
        self.assertEqual(self.client.get("/no-such-page.md").status_code, 404)
        self.assertEqual(self.client.get("/admin.md").status_code, 404)

    @unittest.skipUnless(_data.MACRO, _data.NO_MACRO)
    def test_the_landing_page_counts_are_served_not_dashes(self):
        home = self.client.get("/").text
        self.assertRegex(home, r'id="n-datasets">\d')
        self.assertRegex(home, r'id="n-sources">\d')
        self.assertIn('"@type":"Organization"', home)

    @unittest.skipUnless(_data.EQUITY, _data.NO_EQUITY)
    def test_a_company_page_serves_its_own_tables(self):
        page = self.client.get("/company.html?code=7203").text
        block = re.search(r'(?is)<details class="calc readable".*?</details>', page)
        self.assertIsNotNone(block)
        self.assertIn("Five-year summary", block.group(0))
        self.assertIn("Cross-shareholdings", block.group(0))
        md = self.client.get("/company.md?code=7203").text
        self.assertIn("| Fiscal year end |", md)

    @unittest.skipUnless(_data.EQUITY, _data.NO_EQUITY)
    def test_a_filings_page_serves_its_summary(self):
        page = self.client.get("/holdings.html").text
        block = re.search(r'(?is)<details class="calc readable".*?</details>', page)
        self.assertIsNotNone(block, "no figures served for a filings page")
        self.assertIn("filers disclosing", block.group(0))

    def test_rates_keep_a_decimal_and_large_numbers_get_separators(self):
        self.assertEqual(prerender._format(2.0, "%"), "2.0%")
        # A true minus: the sentence is on the page now, not in <noscript>.
        self.assertEqual(prerender._format(-0.35, "pp"), "\u22120.3pp")
        self.assertEqual(prerender._format(5193819.0, "¥100mn"),
                         "5,193,819 ¥100mn")

    def test_every_served_page_has_a_description(self):
        # Read the child sitemaps, not the /sitemap.xml index: the index
        # lists sitemaps, so a loop over it checks two XML files for a meta
        # tag, finds none missing and passes while every page goes
        # undescribed. One company page stands in for the four thousand that
        # share its template.
        urls = re.findall(r"<loc>([^<]+)</loc>",
                          self.client.get("/sitemap-pages.xml").text)
        urls += re.findall(r"<loc>([^<]+)</loc>",
                           self.client.get("/sitemap-companies.xml").text)[:1]
        self.assertTrue(urls, "no pages listed to check")
        missing = []
        for url in urls:
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
