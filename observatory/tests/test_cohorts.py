# -*- coding: utf-8 -*-
"""Cohorts: resolution, the restriction gate, the statistics, and the filter.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_cohorts
The database checks skip without data/equity.duckdb carrying a classification.
"""
import os
import unittest

from fastapi.testclient import TestClient

from app import cohorts, cohorts_api, equity_api
from app.main import app


def _has_classification():
    if not equity_api.DB_PATH.exists():
        return False
    try:
        return cohorts.available(equity_api._cur())
    except Exception:                                             # noqa: BLE001
        return False


HAS = _has_classification()


class StatisticsTest(unittest.TestCase):
    """The maths, with no database in sight."""

    def test_quantiles_interpolate_between_ranks(self):
        v = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(cohorts_api.quantile(v, 0.0), 1.0)
        self.assertEqual(cohorts_api.quantile(v, 0.5), 2.5)
        self.assertEqual(cohorts_api.quantile(v, 1.0), 4.0)
        self.assertAlmostEqual(cohorts_api.quantile(v, 0.25), 1.75)

    def test_one_value_is_its_own_every_quantile(self):
        self.assertEqual(cohorts_api.quantile([7.0], 0.25), 7.0)
        self.assertIsNone(cohorts_api.quantile([], 0.5))

    def test_missing_is_excluded_and_never_zero(self):
        """The distinction the whole page rests on: a company that does not
        disclose is not a company reporting nil."""
        d = cohorts_api.distribution([10.0, None, 20.0, None])
        self.assertEqual(d["count"], 2)
        self.assertEqual(d["min"], 10.0)
        self.assertEqual(d["median"], 15.0)
        self.assertEqual(d["mean"], 15.0)

    def test_empty_distribution_is_all_none_not_zero(self):
        d = cohorts_api.distribution([None, None])
        self.assertEqual(d["count"], 0)
        for key in ("min", "p25", "median", "p75", "max", "mean"):
            self.assertIsNone(d[key], key)

    def test_percentile_is_mid_rank_on_ties(self):
        v = [1.0, 2.0, 2.0, 3.0]
        self.assertEqual(cohorts_api.percentile_rank(v, 2.0), 50.0)
        self.assertEqual(cohorts_api.percentile_rank(v, 1.0), 12.5)
        self.assertIsNone(cohorts_api.percentile_rank(v, None))
        self.assertIsNone(cohorts_api.percentile_rank([], 1.0))


class SpecTest(unittest.TestCase):
    def test_parse_splits_kind_from_value(self):
        self.assertEqual(cohorts.parse("size:core30"), ("size", "core30"))
        self.assertEqual(cohorts.parse("topix"), ("topix", None))
        self.assertEqual(cohorts.parse(""), (None, None))

    def test_cohort_sql_is_bound_never_interpolated(self):
        sql, params = equity_api.cohort_sql({"7203", "6758"}, "g")
        self.assertIn("g.sec_code IN (?, ?)", sql)
        self.assertEqual(params, ["6758", "7203"])

    def test_no_cohort_means_no_filter_but_an_empty_one_matches_nothing(self):
        self.assertEqual(equity_api.cohort_sql(None, "g"), ("", []))
        sql, params = equity_api.cohort_sql(set(), "g")
        self.assertEqual((sql, params), (" AND FALSE", []))


@unittest.skipUnless(HAS, "no classification in data/equity.duckdb")
class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.cur = equity_api._cur()

    def test_the_scale_bands_resolve_and_roll_up(self):
        c30 = cohorts.resolve(self.cur, "size:core30")
        l70 = cohorts.resolve(self.cur, "size:large70")
        large = cohorts.resolve(self.cur, "size:large")
        self.assertEqual(len(large["members"]),
                         len(c30["members"]) + len(l70["members"]))
        self.assertTrue(set(c30["members"]) <= set(large["members"]))

    def test_topix_is_every_issue_carrying_a_scale_band(self):
        topix = set(cohorts.resolve(self.cur, "topix")["members"])
        bands = set()
        for key, _ in cohorts.SIZE_BANDS:
            bands |= set(cohorts.resolve(self.cur, "size:" + key)["members"])
        self.assertEqual(topix, bands)

    def test_a_basket_keeps_the_callers_order_and_drops_duplicates(self):
        c = cohorts.resolve(self.cur, "codes:7203,6758,7203")
        self.assertEqual(c["members"], ["7203", "6758"])
        self.assertEqual(c["spec"], "codes:7203,6758")

    def test_a_basket_refuses_things_that_are_not_security_codes(self):
        for bad in ("codes:", "codes:72031", "codes:abcd", "codes:72"):
            with self.assertRaises(cohorts.CohortError, msg=bad):
                cohorts.resolve(self.cur, bad)

    def test_unknown_specs_answer_rather_than_resolve_to_the_market(self):
        for bad in ("size:huge", "segment:mothers", "ind33:9999", "wat", ""):
            with self.assertRaises(cohorts.CohortError, msg=bad):
                cohorts.resolve(self.cur, bad)

    def test_a_date_before_the_first_vintage_resolves_to_nothing(self):
        """Never a silent fall-through to today's membership."""
        with self.assertRaises(cohorts.CohortError):
            cohorts.resolve(self.cur, "size:core30", "1990-01-01")

    def test_a_company_carries_the_cohorts_it_belongs_to(self):
        info = cohorts.classify(self.cur, "7203")
        specs = [c["spec"] for c in info["cohorts"]]
        self.assertIn("ind33:" + info["ind33_code"], specs)
        self.assertEqual(cohorts.natural(self.cur, "7203"),
                         "ind33:" + info["ind33_code"])


@unittest.skipUnless(HAS, "no classification in data/equity.duckdb")
class RestrictionTest(unittest.TestCase):
    """Index membership is the publisher's copyrighted work: off unless the
    deployment says otherwise, and enforced where the codes are resolved."""

    def setUp(self):
        self.cur = equity_api._cur()
        self.prev = os.environ.pop("INTERNAL_COHORTS", None)

    def tearDown(self):
        os.environ.pop("INTERNAL_COHORTS", None)
        if self.prev is not None:
            os.environ["INTERNAL_COHORTS"] = self.prev

    def test_refused_by_default(self):
        with self.assertRaises(cohorts.CohortError):
            cohorts.resolve(self.cur, "index:nk225")

    def test_absent_from_the_catalogue_and_from_a_company(self):
        keys = [g["key"] for g in cohorts.catalogue(self.cur)["groups"]]
        self.assertNotIn("index", keys)
        self.assertNotIn("in_nk225", cohorts.classify(self.cur, "7203"))

    def test_served_once_the_switch_is_set(self):
        os.environ["INTERNAL_COHORTS"] = "1"
        c = cohorts.resolve(self.cur, "index:nk225")
        self.assertEqual(len(c["members"]), 225)
        self.assertFalse(c["public"])


@unittest.skipUnless(HAS, "no classification in data/equity.duckdb")
class ApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_compare_ranks_within_the_cohort_and_reconciles(self):
        r = self.client.get("/api/v1/equity/cohorts/compare",
                            params={"cohort": "size:core30", "metric": "roe_pct",
                                    "highlight": "7203"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["members"], d["with_value"] + d["without_value"])
        self.assertEqual(len(d["values"]), d["with_value"])
        self.assertEqual(d["distribution"]["count"], d["with_value"])
        ranks = [row["rank"] for row in d["rows"]]
        self.assertEqual(ranks, sorted(ranks))
        h = d["highlight"]
        self.assertEqual(h["value"] - d["distribution"]["median"], h["vs_median"])

    def test_the_full_value_list_is_never_cut_by_the_row_limit(self):
        """A distribution built from a page of a table is a different
        distribution, and would be wrong without ever looking wrong."""
        r = self.client.get("/api/v1/equity/cohorts/compare",
                            params={"cohort": "segment:prime",
                                    "metric": "foreign_pct", "limit": 10})
        d = r.json()
        self.assertEqual(len(d["rows"]), 10)
        self.assertTrue(d["truncated"])
        self.assertEqual(len(d["values"]), d["with_value"])
        self.assertGreater(len(d["values"]), 10)

    def test_every_metric_answers_for_a_real_cohort(self):
        for key, label, _, _, _, _ in cohorts_api.METRICS:
            r = self.client.get("/api/v1/equity/cohorts/compare",
                                params={"cohort": "size:core30", "metric": key})
            self.assertEqual(r.status_code, 200, key)
            d = r.json()
            self.assertEqual(d["metric"]["label"], label)
            self.assertEqual(d["members"], d["with_value"] + d["without_value"])

    def test_a_calculated_measure_carries_its_formula(self):
        d = self.client.get("/api/v1/equity/cohorts/compare",
                            params={"cohort": "size:core30",
                                    "metric": "roe_pct"}).json()
        self.assertEqual(d["metric"]["trust"], "derived")
        self.assertTrue(d["metric"]["formula"])
        for key in ("quartiles", "percentile", "vs_median"):
            self.assertTrue(d["calc"][key], key)

    def test_a_bad_cohort_answers_400_not_the_whole_market(self):
        r = self.client.get("/api/v1/equity/cohorts/compare",
                            params={"cohort": "size:huge", "metric": "roe_pct"})
        self.assertEqual(r.status_code, 400)

    def test_screens_take_the_same_cohort(self):
        members = set(cohorts.resolve(equity_api._cur(), "size:core30")["members"])
        for path, rows_key in (
                ("/api/v1/equity/governance/screen", "rows"),
                ("/api/v1/equity/ownership/screen", "companies"),
                ("/api/v1/equity/financials/screener", "rows")):
            d = self.client.get(path, params={"cohort": "size:core30",
                                              "limit": 50}).json()
            self.assertEqual(d["cohort"]["spec"], "size:core30", path)
            self.assertTrue(d[rows_key], path)
            for row in d[rows_key]:
                self.assertIn(row["sec_code"], members, path)

    def test_a_screen_without_a_cohort_keeps_the_whole_market(self):
        d = self.client.get("/api/v1/equity/governance/screen",
                            params={"limit": 5}).json()
        self.assertIsNone(d["cohort"])


def _extractor():
    """equity/class_extract.py, loaded by path — it is a script beside the
    other extractors, not part of the app package."""
    import importlib.util
    import pathlib
    path = (pathlib.Path(__file__).resolve().parent.parent
            / "equity" / "class_extract.py")
    spec = importlib.util.spec_from_file_location("class_extract", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ExtractorTest(unittest.TestCase):
    """The gates and the immutability rule, with no network and no files."""

    @classmethod
    def setUpClass(cls):
        cls.m = _extractor()

    def _jpx_rows(self, n=3400, core30=31, large70=68):
        rows = []
        bands = ([("core30", u"TOPIX Core30")] * core30 +
                 [("large70", u"TOPIX Large70")] * large70 +
                 [("mid400", u"TOPIX Mid400")] * 393 +
                 [("small1", u"TOPIX Small 1")] * 484 +
                 [("small2", u"TOPIX Small 2")] * 660)
        for i in range(n):
            band = bands[i] if i < len(bands) else (None, None)
            rows.append({"sec_code": "%04d" % (1000 + i), "name_ja": u"社",
                         "segment_ja": u"プライム（内国株式）", "segment": "prime",
                         "domestic": True,
                         "ind33_code": "%04d" % (50 * (1 + i % 33)),
                         "ind33_name": u"業種", "ind17_code": str(1 + i % 17),
                         "ind17_name": u"区分",
                         "size_code": band[0], "size_name": band[1]})
        return rows

    def test_a_sound_file_passes_and_reports_its_bands(self):
        bands = self.m.check_jpx(self._jpx_rows())
        self.assertEqual(bands["core30"], 31)
        self.assertEqual(sum(bands.values()), 1636)

    def test_a_short_file_is_rejected_rather_than_published(self):
        with self.assertRaises(self.m.SourceError):
            self.m.check_jpx(self._jpx_rows(n=500))

    def test_an_unmapped_market_segment_is_rejected(self):
        rows = self._jpx_rows()
        rows[0]["segment_ja"], rows[0]["segment"] = u"新市場", None
        with self.assertRaises(self.m.SourceError):
            self.m.check_jpx(rows)

    def test_a_band_that_has_moved_far_off_its_nominal_size_is_rejected(self):
        with self.assertRaises(self.m.SourceError):
            self.m.check_jpx(self._jpx_rows(core30=12))

    def test_the_225_must_be_225_and_must_sum_to_100(self):
        good = [{"sec_code": "%04d" % (1000 + i), "name_ja": u"社",
                 "nk_industry": u"電機", "nk_sector": u"技術",
                 "weight_pct": 100.0 / 225} for i in range(225)]
        self.assertAlmostEqual(self.m.check_nikkei(good), 100.0, places=6)
        with self.assertRaises(self.m.SourceError):
            self.m.check_nikkei(good[:224])
        heavy = [dict(r) for r in good]
        heavy[0]["weight_pct"] = 10.0
        with self.assertRaises(self.m.SourceError):
            self.m.check_nikkei(heavy)
        blank = [dict(r) for r in good]
        blank[0]["weight_pct"] = None
        with self.assertRaises(self.m.SourceError):
            self.m.check_nikkei(blank)

    def test_a_stored_vintage_is_never_rewritten(self):
        """P0. The same bytes store once; different bytes at the same date land
        beside the first rather than over it."""
        import datetime
        import duckdb
        con = duckdb.connect(":memory:")
        con.execute(self.m.SCHEMA_SQL)
        day = datetime.date(2026, 8, 31)
        rows = [{"sec_code": "7203", "name_ja": u"ト", "segment_ja": u"プ",
                 "segment": "prime", "domestic": True, "ind33_code": "3700",
                 "ind33_name": u"輸", "ind17_code": "6", "ind17_name": u"自",
                 "size_code": "core30", "size_name": u"TOPIX Core30"}]
        args = ("jpx-listed", day, "a" * 64, rows, True, "u", "p",
                "eq_classification", self.m.JPX_COLUMNS)
        vid, n = self.m.store(con, *args)
        self.assertEqual(n, 1)
        self.assertEqual(self.m.store(con, *args)[1], 0)      # same bytes: no-op
        revised = ("jpx-listed", day, "b" * 64, rows, True, "u", "p",
                   "eq_classification", self.m.JPX_COLUMNS)
        vid2, n2 = self.m.store(con, *revised)
        self.assertEqual(n2, 1)
        self.assertNotEqual(vid, vid2)
        self.assertEqual(con.execute(
            "SELECT count(*) FROM eq_class_vintages").fetchone()[0], 2)
        self.assertEqual(con.execute(
            "SELECT count(*) FROM eq_classification").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
