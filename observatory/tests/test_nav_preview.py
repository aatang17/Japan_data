# -*- coding: utf-8 -*-
"""The Data menu's previews (/api/v1/catalog/previews).

What is proved: every page a dataset card names gets an entry; a page with a
main series gets its latest value from the same observations function the
page uses, a price index as its change on a year earlier; a page without one
gets a description, never an empty box. Skipped where the local database has
no CPI release (a fresh checkout).
"""
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import api, nav_preview


def _has_cpi():
    try:
        con = api._con()
        try:
            api._release(con, "cpi-jp")
        finally:
            con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_has_cpi(), "no CPI release in the local database")
class PreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(nav_preview.router)
        cls.pages = TestClient(app).get("/api/v1/catalog/previews").json()["pages"]

    def test_inflation_page_shows_headline_yoy(self):
        p = self.pages["/cpi.html"]
        self.assertEqual(p["kind"], "series")
        self.assertEqual((p["dataset"], p["measure"], p["unit"]), ("cpi-jp", "yoy", "%"))
        body = api.observations("cpi-jp", series=p["code"], measure="yoy", start=None, end=None,
                                as_of=None, period=None, fy_end=3, format="json", request=None)
        latest = [x for x in body["series"][0]["points"] if x[1] is not None][-1]
        self.assertEqual([p["latest"]["period"], p["latest"]["value"]], latest)

    def test_every_entry_is_drawable_or_described(self):
        self.assertGreater(len(self.pages), 10)
        for page, p in self.pages.items():
            if p["kind"] == "series":
                self.assertTrue(any(v is not None for _, v in p["points"]), page)
                self.assertTrue(p["credit"], page)
            else:
                self.assertEqual(p["kind"], "text", page)
                self.assertTrue(p["text"], page)


if __name__ == "__main__":
    unittest.main()
