# -*- coding: utf-8 -*-
"""The research desk's data search, asked what its readers will ask.

The desk sits behind a sign-in, so ci/search_examples.py (which types into
every public search box in a real browser) cannot reach it. This runs the
same search the box calls, with the examples read out of the box's own
placeholder, so changing the hint changes the test.

2026-10-03: the box said "e.g. core CPI, 7203" and found nothing for
"core CPI", nor for "CPI".
"""
import pathlib
import re
import unittest

from app import research_api
from tests import _data

ROOT = pathlib.Path(__file__).resolve().parent.parent

# What a writer types first, beyond the box's own examples.
OBVIOUS = ["CPI", "GDP", "10-year", "Toyota", "7203"]


def placeholder_examples():
    text = (ROOT / "web" / "assets" / "desk-research.js").read_text(encoding="utf-8")
    m = re.search(r'id="dk-rs-dq" placeholder="([^"]*)"', text)
    assert m, "the desk's data search box has moved: update this test"
    after = re.split(r"\be\.g\.?\s*", m.group(1), flags=re.I)[-1]
    return [p.strip() for p in after.split(",") if p.strip()]


class DeskSearchExamples(unittest.TestCase):
    def setUp(self):
        self._writer = research_api._writer
        research_api._writer = lambda request: {"id": 0}

    def tearDown(self):
        research_api._writer = self._writer

    def test_the_box_shows_examples(self):
        self.assertTrue(placeholder_examples())

    @unittest.skipUnless(_data.MACRO and _data.EQUITY, _data.NO_MACRO)
    def test_every_example_and_obvious_query_finds_something(self):
        for q in placeholder_examples() + OBVIOUS:
            with self.subTest(q=q):
                r = research_api.data_search(None, q)
                self.assertTrue(r["series"] or r["companies"],
                                "the desk search finds nothing for %r" % q)

    @unittest.skipUnless(_data.MACRO, _data.NO_MACRO)
    def test_cpi_lists_the_headline_first(self):
        r = research_api.data_search(None, "CPI")
        self.assertEqual((r["series"][0]["dataset"], r["series"][0]["name"]), ("cpi-jp", "All items"))


if __name__ == "__main__":
    unittest.main()
