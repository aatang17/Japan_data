# -*- coding: utf-8 -*-
"""robots.txt and sitemap.xml: what we hand a crawler matches what we serve.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_seo
"""
import pathlib
import unittest
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from app import seo
from app.main import app

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


class SitemapTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.body = cls.client.get("/sitemap.xml").text
        cls.locs = [e.text for e in ET.fromstring(cls.body).iter(NS + "loc")]

    def test_it_is_served_ahead_of_the_static_mount(self):
        # The mount answers "/" and everything under it. Registered after the
        # sitemap route it would shadow both files with a 404.
        for path, kind in (("/sitemap.xml", "application/xml"),
                           ("/robots.txt", "text/plain")):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(kind, r.headers["content-type"])

    def test_every_listed_url_is_a_page_we_actually_serve(self):
        # A sitemap entry that 404s is worse than no sitemap: it is the one
        # error Search Console reports against the whole site.
        self.assertTrue(self.locs)
        for loc in self.locs:
            path = loc[len(seo.SITE_BASE_URL):]
            self.assertEqual(self.client.get(path).status_code, 200, loc)

    def test_every_page_is_listed_unless_it_says_noindex(self):
        # The page list is the directory, so a page added to the site is in
        # the sitemap without anyone remembering a second list.
        listed = set(self.locs)
        for page in WEB.glob("*.html"):
            name = "" if page.name == "index.html" else page.name
            url = seo.SITE_BASE_URL + "/" + name
            head = page.open(encoding="utf-8", errors="replace").read(4096)
            if seo._NOINDEX.search(head):
                self.assertNotIn(url, listed, "%s says noindex" % page.name)
            else:
                self.assertIn(url, listed, page.name)

    def test_the_admin_console_is_never_advertised(self):
        self.assertNotIn("/admin", self.body)
        self.assertIn("Disallow: /admin.html", self.client.get("/robots.txt").text)

    def test_robots_leaves_the_api_crawlable(self):
        # Pages draw their numbers from /api after load. A crawler forbidden
        # the API renders empty charts and indexes those.
        self.assertNotIn("Disallow: /api", self.client.get("/robots.txt").text)

    def test_one_canonical_host(self):
        # Both files name the same host the cite links do, so the deploy
        # domain never competes with it for the same page.
        self.assertIn("Sitemap: " + seo.SITE_BASE_URL + "/sitemap.xml",
                      self.client.get("/robots.txt").text)
        for loc in self.locs:
            self.assertTrue(loc.startswith(seo.SITE_BASE_URL + "/"), loc)


if __name__ == "__main__":
    unittest.main()
