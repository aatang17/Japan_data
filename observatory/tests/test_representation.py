# -*- coding: utf-8 -*-
u"""Vote value: the seat table, the arithmetic, and the served payload.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_representation
The endpoint checks skip without a published population-jp release.
"""
import unittest

from fastapi.testclient import TestClient

from app import apportionment as ap
from app import apportionment_api
from app.main import app


def _has_population():
    try:
        apportionment_api.councillors(base=ap.DEFAULT_BASE, period=None)
        return True
    except Exception:                                             # noqa: BLE001
        return False


HAS = _has_population()


class SeatTableTest(unittest.TestCase):
    """The constant that no downstream arithmetic could correct."""

    def test_table_passes_its_own_check(self):
        self.assertEqual(ap.check_table(), [])

    def test_forty_five_districts_and_one_hundred_forty_eight_seats(self):
        self.assertEqual(len(ap.DISTRICTS), 45)
        self.assertEqual(sum(s for _d, _c, s in ap.DISTRICTS), ap.SEATS_TOTAL)
        self.assertEqual(ap.SEATS_TOTAL, 148)

    def test_every_prefecture_sits_in_exactly_one_district(self):
        seen = [c for _d, codes, _s in ap.DISTRICTS for c in codes]
        self.assertEqual(len(seen), 47)
        self.assertEqual(len(set(seen)), 47)

    def test_the_two_merged_pairs_are_the_only_merged_districts(self):
        merged = [d["id"] for d in ap.districts() if d["merged"]]
        self.assertEqual(sorted(merged), ["31-32", "36-39"])

    def test_every_complement_halves_into_a_whole_number(self):
        for d in ap.districts():
            self.assertEqual(d["seats"], d["seats_per_election"] * 2)


class ArithmeticTest(unittest.TestCase):
    """Two districts, made up, so the formulas are checkable by hand."""

    def _pop(self, per_pref):
        return dict((code, per_pref.get(code, 1000.0)) for code in ap.PREF_EN)

    def test_vote_weight_is_the_reciprocal_of_disparity(self):
        rows, summary = ap.build(self._pop({}))
        for r in rows:
            self.assertAlmostEqual(r["vote_weight"] * r["disparity"], 1.0)

    def test_the_best_served_district_scores_one(self):
        rows, summary = ap.build(self._pop({"18": 10.0}))
        best = [r for r in rows if r["id"] == "18"][0]
        self.assertAlmostEqual(best["vote_weight"], 1.0)
        self.assertAlmostEqual(summary["max_disparity"],
                               rows[0]["per_seat"] / best["per_seat"])

    def test_headline_disparity_is_worst_over_best(self):
        # Every district put at exactly 500,000 electors per seat, then Tokyo
        # doubled to 1,000,000 per seat. The disparity is then exactly 2 and
        # neither extreme can come from anywhere else.
        pop = {}
        for d in ap.districts():
            for code in d["prefectures"]:
                pop[code] = 500000.0 * d["seats"] / len(d["prefectures"])
        pop["13"] = 12 * 1000000.0
        rows, summary = ap.build(pop)
        tokyo = [r for r in rows if r["id"] == "13"][0]
        fukui = [r for r in rows if r["id"] == "18"][0]
        self.assertEqual(tokyo["per_seat"], 1000000.0)
        self.assertEqual(fukui["per_seat"], 500000.0)
        self.assertAlmostEqual(summary["max_disparity"], 2.0)
        self.assertAlmostEqual(tokyo["vote_weight"], 0.5)
        self.assertAlmostEqual(fukui["vote_weight"], 1.0)

    def test_a_merged_district_sums_both_prefectures(self):
        pop = dict((code, 1000.0) for code in ap.PREF_EN)
        pop["31"], pop["32"] = 300000.0, 500000.0
        rows, _s = ap.build(pop)
        merged = [r for r in rows if r["id"] == "31-32"][0]
        self.assertEqual(merged["electorate"], 800000.0)
        self.assertEqual(merged["per_seat"], 400000.0)

    def test_an_empty_district_keeps_its_zero_and_anchors_nothing(self):
        # Not reachable from the register, but the ratio must not divide by
        # it: a zero count is a real count, unlike a gap, and it can neither
        # be the best-served district nor produce an infinity.
        pop = dict((code, 1000.0) for code in ap.PREF_EN)
        pop["18"] = 0.0
        rows, summary = ap.build(pop)
        fukui = [r for r in rows if r["id"] == "18"][0]
        self.assertEqual(fukui["per_seat"], 0.0)
        self.assertIsNone(fukui["vote_weight"])
        self.assertIsNone(fukui["disparity"])
        self.assertNotEqual(summary["best_served"]["name_en"], "Fukui")
        self.assertTrue(summary["max_disparity"] > 0)

    def test_a_missing_prefecture_nulls_its_district_and_leaves_totals_alone(self):
        pop = dict((code, 1000.0) for code in ap.PREF_EN)
        del pop["32"]                      # half of Tottori & Shimane
        rows, summary = ap.build(pop)
        merged = [r for r in rows if r["id"] == "31-32"][0]
        self.assertIsNone(merged["electorate"])
        self.assertIsNone(merged["per_seat"])
        self.assertIsNone(merged["vote_weight"])
        self.assertEqual(summary["districts_complete"], 44)
        self.assertEqual(summary["seats"], ap.SEATS_TOTAL - 2)

    def test_shares_reconcile(self):
        rows, summary = ap.build(dict((c, 1000.0) for c in ap.PREF_EN))
        self.assertAlmostEqual(sum(r["seat_share_pct"] for r in rows), 100.0, 6)
        self.assertAlmostEqual(
            sum(r["electorate_share_pct"] for r in rows), 100.0, 6)
        self.assertAlmostEqual(
            sum(r["over_representation_pp"] for r in rows), 0.0, 6)


class AgeBandTest(unittest.TestCase):
    """The one estimated quantity on the surface."""

    def test_eighteen_plus_adds_two_fifths_of_the_fifteen_to_nineteen_band(self):
        values = {
            "13.jp.age_15_19_total": [500.0],
            "13.jp.age_20_24_total": [1000.0],
            "13.jp.age_65_69_total": [200.0],
            "13.jp.age_10_14_total": [400.0],
            "13.jp.population": [9999.0],
            "13.all.population": [11111.0],
        }
        out = apportionment_api._population_by_base(values, 0)
        self.assertEqual(out["adults20"]["13"], 1200.0)
        self.assertEqual(out["adults18"]["13"], 1200.0 + 0.4 * 500.0)
        self.assertEqual(out["japanese"]["13"], 9999.0)
        self.assertEqual(out["residents"]["13"], 11111.0)

    def test_the_total_row_is_never_added_to_the_bands(self):
        values = {
            "13.jp.age_total_total": [99999.0],
            "13.jp.age_20_24_total": [1000.0],
        }
        out = apportionment_api._population_by_base(values, 0)
        self.assertEqual(out["adults20"]["13"], 1000.0)

    def test_the_national_row_is_not_a_prefecture(self):
        values = {"00.jp.age_20_24_total": [5.0], "13.jp.age_20_24_total": [1.0]}
        out = apportionment_api._population_by_base(values, 0)
        self.assertEqual(list(out["adults20"]), ["13"])


@unittest.skipUnless(HAS, "no published population-jp release")
class EndpointTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_serves_forty_five_districts_and_the_full_chamber(self):
        r = self.client.get("/api/v1/representation/councillors")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["rows"]), 45)
        self.assertEqual(body["summary"]["seats"], 148)
        self.assertEqual(body["trust"], "derived")
        self.assertTrue(body["calc"])

    def test_rows_are_ranked_worst_served_first(self):
        body = self.client.get("/api/v1/representation/councillors").json()
        per_seat = [r["per_seat"] for r in body["rows"]]
        self.assertEqual(per_seat, sorted(per_seat, reverse=True))

    def test_fukui_is_the_best_served_district(self):
        # Not a coincidence to be discovered afresh each release: since the
        # 2016 mergers Fukui has had the smallest electorate per seat of the
        # 45, and it is the district every published disparity is quoted
        # against. If this ever fails, the finding changed — check it.
        body = self.client.get("/api/v1/representation/councillors").json()
        self.assertEqual(body["summary"]["best_served"]["name_en"], "Fukui")
        self.assertAlmostEqual(body["rows"][-1]["vote_weight"], 1.0)

    def test_the_estimated_base_does_not_carry_the_headline(self):
        # adults18 splits a published band; adults20 splits nothing. If the
        # two disagreed materially the surface would be leading with an
        # artefact of the interpolation.
        body = self.client.get("/api/v1/representation/councillors").json()
        by_base = dict((s["base"], s["max_disparity"]) for s in body["sensitivity"])
        self.assertLess(abs(by_base["adults18"] - by_base["adults20"]), 0.05)

    def test_every_base_is_servable(self):
        for key in ap.BASE_KEYS:
            r = self.client.get("/api/v1/representation/councillors?base=" + key)
            self.assertEqual(r.status_code, 200, key)
            self.assertEqual(r.json()["base"]["key"], key)

    def test_an_unknown_base_is_refused(self):
        r = self.client.get("/api/v1/representation/councillors?base=voters")
        self.assertEqual(r.status_code, 400)

    def test_an_unpublished_period_is_refused_rather_than_guessed(self):
        r = self.client.get("/api/v1/representation/councillors?period=1999-01-01")
        self.assertEqual(r.status_code, 404)

    def test_history_is_computed_on_complete_years_only(self):
        body = self.client.get("/api/v1/representation/councillors").json()
        points = body["history"]["points"]
        self.assertTrue(points)
        for p in points:
            self.assertGreater(p["max_disparity"], 1.0)
        periods = [p["period"] for p in points]
        self.assertEqual(periods, sorted(periods))

    def test_the_seat_table_travels_with_its_source(self):
        body = self.client.get("/api/v1/representation/councillors").json()
        table = body["seat_table"]
        self.assertEqual(table["seats"], 148)
        self.assertEqual(table["districts"], 45)
        self.assertTrue(table["law"])
        self.assertTrue(table["sources"])


if __name__ == "__main__":
    unittest.main()
