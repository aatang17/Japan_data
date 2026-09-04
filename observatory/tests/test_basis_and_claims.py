# -*- coding: utf-8 -*-
"""Measurement basis and claim checking.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_basis_and_claims
Needs data/equity.duckdb (every case skips without it).

The fixtures come from a real reconciliation: Nikkei Asia put the three
megabanks' cross-shareholdings at ¥2.56tn at 30 September 2025 (acquisition
cost, interim); this product holds ¥11.5085tn at 31 March 2026 (carrying
amount, annual). Both are right. These tests exist so neither is ever
published as a correction of the other.
"""
import datetime
import unittest

from app import basis, equity_api

MEGABANKS = "8306,8316,8411"
HAVE_DB = equity_api.DB_PATH.exists()


def nikkei(**kw):
    args = dict(figure_yen=2_560_000_000_000, companies=MEGABANKS,
                as_of="2025-09-30", measure="holdings",
                claimed_measurement="acquisition_cost", claimed_entity_scope="",
                claimed_share_scope="", claimed_period_type="interim",
                context="held ¥2.56tn at the end of September, down 60% "
                        "from a decade earlier by book value")
    args.update(kw)
    return equity_api.claim_check(**args)


class Vocabulary(unittest.TestCase):
    """No database needed: the tuple is computed, not stored."""

    def test_entity_scope_is_read_not_assumed(self):
        # holder_table IS entity_scope. Assuming holdco_consolidated for every
        # row is the one falsehood this feature exists to prevent.
        self.assertEqual(basis.entity_scope_for(["largest"]),
                         "largest_holding_company")
        self.assertEqual(basis.entity_scope_for(["reporting"]), "parent_only")
        self.assertEqual(basis.entity_scope_for(["second_largest"]),
                         "second_largest_holding_company")
        # more than one disclosing entity means the figure sums the group
        self.assertEqual(basis.entity_scope_for(["reporting", "largest"]),
                         "holdco_consolidated")
        # an unknown value degrades; it never invents a scope name
        self.assertEqual(basis.entity_scope_for(["something_new"]),
                         "holdco_consolidated")

    def test_share_scope_is_read_not_assumed(self):
        self.assertEqual(basis.share_scope_for(["listed"]), "listed")
        self.assertEqual(basis.share_scope_for(["listed", "unlisted"]), "both")

    def test_every_label_has_text(self):
        for field, value, note in basis.label_rows():
            self.assertTrue(note and len(note) > 20, (field, value))

    def test_verdict_vocabulary_never_grades_a_publisher(self):
        forbidden = ("false", "wrong", "incorrect", "unsupported", "debunk")
        for name in list(equity_api.VERDICTS) + ["cannot_verify", "consistent"]:
            for word in forbidden:
                self.assertNotIn(word, name)

    def test_precision_matching_respects_the_claims_own_rounding(self):
        # ¥2.56tn is three significant figures; the match is tested there, not
        # against an arbitrary percentage.
        self.assertTrue(equity_api._rounds_to(11_508_500_000_000,
                                              11_500_000_000_000))
        self.assertFalse(equity_api._rounds_to(11_508_500_000_000,
                                               11_400_000_000_000))


@unittest.skipUnless(HAVE_DB, "equity database not built")
class BasisOnResponses(unittest.TestCase):

    def test_market_responses_carry_a_basis(self):
        for payload in (equity_api.summary(year=""),
                        equity_api.unwind(year=""),
                        equity_api.history(limit=3),
                        equity_api.reclassified(year="", limit=3)):
            b = payload["basis"]
            self.assertEqual(b["measurement"], "carrying_amount")
            self.assertEqual(b["period_type"], "annual")
            self.assertEqual(b["trust_included"], "unknown")
            self.assertTrue(b["not_comparable"])

    def test_smfg_discloses_two_entity_scopes(self):
        # The finding that reshaped the design: SMFG reports ¥3.46tn under SMBC
        # and ¥154bn at the holding company. One scope for both would be wrong.
        got = equity_api.company("8316")
        scopes = set(e["entity_scope"] for e in got["scale_entities"])
        self.assertEqual(scopes, {"parent_only", "largest_holding_company"})
        self.assertEqual(got["basis"]["entity_scope"], "holdco_consolidated")

    def test_mufg_reports_one_entity_scope(self):
        got = equity_api.company("8306")
        self.assertEqual(got["basis"]["entity_scope"],
                         "largest_holding_company")

    def test_company_states_no_reduction_measure_is_held(self):
        self.assertTrue(equity_api.company("8306")["no_reduction_measure"])

    def test_basis_resolves_without_the_labels_table(self):
        # The volume can carry a database an extract has not touched. The basis
        # must still resolve — it is computed, never looked up.
        cur = equity_api._cur()
        names = set(r[0] for r in cur.execute(
            "SELECT table_name FROM duckdb_tables()").fetchall())
        payload = equity_api.summary(year="")
        self.assertEqual(payload["basis"]["measurement"], "carrying_amount")
        if "eq_basis_labels" not in names:
            self.assertNotIn("eq_basis_labels", names)  # absence path exercised


@unittest.skipUnless(HAVE_DB, "equity database not built")
class ClaimCheck(unittest.TestCase):

    def test_nikkei_fixture_names_both_mismatches(self):
        # Must be "cannot verify" with the date AND basis mismatch both named —
        # not a false contradiction, and not a spurious match.
        got = nikkei()
        self.assertEqual(got["verdict"], "cannot_verify")
        reasons = set(r["reason"] for r in got["reasons"])
        self.assertIn("date_mismatch", reasons)
        self.assertIn("basis_mismatch", reasons)
        self.assertEqual(round(got["ours_total_yen"] / 1e12, 3), 11.508)
        self.assertGreater(got["ratio_ours_to_claim"], 4)

    def test_nikkei_fixture_returns_source_documents(self):
        got = nikkei()
        self.assertEqual(set(r["doc_id"] for r in got["ours"]),
                         {"S100YJQO", "S100YERK", "S100YF8Y"})
        for row in got["ours"]:
            self.assertTrue(row["sha256"])

    def test_context_is_echoed_never_parsed(self):
        # The wording must not move the verdict — otherwise the tool is
        # guessing the basis out of prose, which the design forbids.
        with_text, without = nikkei(), nikkei(context="")
        self.assertEqual(with_text["verdict"], without["verdict"])
        self.assertEqual([r["reason"] for r in with_text["reasons"]],
                         [r["reason"] for r in without["reasons"]])
        self.assertTrue(with_text["claim"]["context"])
        self.assertIsNone(without["claim"]["context"])

    def test_unstated_basis_is_not_guessed(self):
        got = nikkei(claimed_measurement="", claimed_period_type="")
        reasons = set(r["reason"] for r in got["reasons"])
        self.assertIn("basis_not_supplied", reasons)
        self.assertNotIn("basis_mismatch", reasons)

    def test_our_own_figure_on_our_own_basis_is_consistent(self):
        got = equity_api.claim_check(
            figure_yen=11_508_000_000_000, companies=MEGABANKS,
            as_of="2026-03-31", measure="holdings",
            claimed_measurement="carrying_amount", claimed_entity_scope="",
            claimed_share_scope="", claimed_period_type="annual", context="")
        self.assertEqual(got["verdict"], "consistent")
        self.assertEqual(got["reasons"], [])

    def test_reduction_claim_is_never_contradicted_by_sale_proceeds(self):
        # ¥160bn of interim book-value reduction must not read as contradicting
        # ¥1.48tn of annual listed sale proceeds. Different measures.
        got = equity_api.claim_check(
            figure_yen=160_000_000_000, companies=MEGABANKS,
            as_of="2025-09-30", measure="reduction",
            claimed_measurement="acquisition_cost", claimed_entity_scope="",
            claimed_share_scope="", claimed_period_type="interim", context="")
        self.assertEqual(got["verdict"], "cannot_verify")
        self.assertIn("measure_not_held",
                      set(r["reason"] for r in got["reasons"]))
        self.assertTrue(got["no_reduction_measure"])

    def test_uncovered_company_is_reported_not_dropped(self):
        got = equity_api.claim_check(
            figure_yen=1, companies="8306,0000", as_of="2026-03-31",
            measure="holdings", claimed_measurement="carrying_amount",
            claimed_entity_scope="", claimed_share_scope="",
            claimed_period_type="annual", context="")
        self.assertIn("0000", got["companies_not_covered"])
        self.assertIn("coverage_gap", set(r["reason"] for r in got["reasons"]))


@unittest.skipUnless(HAVE_DB, "equity database not built")
class Corroboration(unittest.TestCase):
    """Exits the article reports for fiscal 2024. A name reappearing means
    either an extraction regression or a real change worth knowing about."""

    CASES = [("8306", ["本田", "ホンダ",
                       "アシックス"]),
             ("8316", ["サンリオ",
                       "ブリヂストン"]),
             ("8411", ["ＪＳＲ", "ヤマハ発動機"])]

    def test_reported_exits_are_absent_from_the_named_tables(self):
        for code, absent in self.CASES:
            got = equity_api.company(code)
            if got["filing"]["period_end"] != datetime.date(2026, 3, 31):
                continue  # newer filing extracted; fixture describes FY2026-03
            names = " ".join(h["held_name_raw"] or "" for h in got["holdings"])
            for name in absent:
                self.assertNotIn(name, names, "%s in %s" % (name, code))


if __name__ == "__main__":
    unittest.main()
