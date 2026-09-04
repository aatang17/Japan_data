# -*- coding: utf-8 -*-
u"""Market nicknames resolve to the right filer, and only to that filer.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_aliases
"""
import json
import unittest

from app import aliases, equity_api


class Initials(unittest.TestCase):
    def test_bank_names_give_their_market_abbreviation(self):
        self.assertEqual("MUFG", aliases.initials("Mitsubishi UFJ Financial Group, Inc."))
        self.assertEqual("SMFG", aliases.initials("Sumitomo Mitsui Financial Group, Inc."))

    def test_legal_forms_and_connectives_are_not_letters(self):
        self.assertEqual("NEH", aliases.initials("NIPPON EXPRESS HOLDINGS, INC."))
        # "Company" is a legal form, which is exactly why JR East needs curation.
        self.assertEqual("EJR", aliases.initials("East Japan Railway Company"))

    def test_too_short_or_too_long_is_not_an_acronym(self):
        self.assertEqual("", aliases.initials("Nintendo Co., Ltd."))
        self.assertEqual("", aliases.initials("A B C D E F G H"))
        self.assertEqual("", aliases.initials(None))


class Folding(unittest.TestCase):
    u"""How a name is typed vs how EDINET filed it."""

    def test_spacing_and_legal_form_fall_away(self):
        for written in (u"株式会社\u3000りそなホールディングス",
                        u"株式会社りそなホールディングス",
                        u"りそなホールディングス"):
            self.assertEqual(u"りそなホールディングス", aliases.fold(written))

    def test_width_and_half_width_kana_meet_in_the_middle(self):
        self.assertEqual("NTT", aliases.fold(u"ＮＴＴ株式会社"))
        self.assertEqual(u"ジャフコ", aliases.fold(u"ｼﾞｬﾌｺ"))

    def test_a_long_vowel_is_part_of_the_word_not_punctuation(self):
        self.assertEqual(u"コーヒー", aliases.fold(u"コーヒー"))


class Normalisation(unittest.TestCase):
    def test_case_width_and_punctuation_fold_away(self):
        self.assertEqual("MUFG", aliases.normalize("mufg"))
        self.assertEqual("MUFG", aliases.normalize(u"ＭＵＦＧ"))
        self.assertEqual("JREAST", aliases.normalize("JR-East "))
        self.assertEqual("7I", aliases.normalize("7&i"))


class Curation(unittest.TestCase):
    def setUp(self):
        with open(str(aliases.CURATION_PATH), encoding="utf-8") as fh:
            self.doc = json.load(fh)

    def test_every_row_states_a_code_and_a_reason(self):
        for row in self.doc["aliases"]:
            self.assertTrue(row.get("alias"), row)
            self.assertRegex(row.get("sec_code", ""), r"^[0-9A-Z]{4}$", row)
            self.assertTrue(row.get("why"), row)

    def test_no_alias_names_the_same_company_twice(self):
        seen = set()
        for row in self.doc["aliases"]:
            key = (aliases.normalize(row["alias"]), row["sec_code"])
            self.assertNotIn(key, seen, row)
            seen.add(key)

    @unittest.skipUnless(equity_api.DB_PATH.exists(), "equity database not built")
    def test_every_curated_code_is_a_company_we_hold(self):
        cur = equity_api._cur()
        for row in self.doc["aliases"]:
            hit = cur.execute("SELECT 1 FROM eq_entities WHERE sec_code = ? LIMIT 1",
                              [row["sec_code"]]).fetchone()
            self.assertIsNotNone(hit, "%s -> %s is not a known filer"
                                 % (row["alias"], row["sec_code"]))


@unittest.skipUnless(equity_api.DB_PATH.exists(), "equity database not built")
class AgainstTheDatabase(unittest.TestCase):
    def setUp(self):
        self.cur = equity_api._cur()

    def test_generated_initials_find_the_bank(self):
        self.assertEqual(["8306"], aliases.codes(self.cur, "MUFG"))
        self.assertEqual(["8316"], aliases.codes(self.cur, "smfg"))

    def test_curation_beats_colliding_initials(self):
        # Three filers' initials spell JT; the curated row is Japan Tobacco.
        self.assertEqual(["2914"], aliases.codes(self.cur, "JT"))

    def test_a_plain_word_is_not_an_alias(self):
        self.assertEqual([], aliases.codes(self.cur, "Mitsubishi"))
        self.assertEqual([], aliases.codes(self.cur, ""))

    def test_clause_binds_its_codes_as_parameters(self):
        sql, params = aliases.clause(self.cur, "c.sec_code", "TEPCO")
        self.assertEqual(" OR c.sec_code IN (?)", sql)
        self.assertEqual(["9501"], params)
        self.assertEqual(("", []), aliases.clause(self.cur, "c.sec_code", "no such name"))

    def test_a_full_legal_name_finds_its_filer(self):
        # EDINET files 株式会社　商船三井 and 株式会社　りそなホールディングス
        # with a full-width space inside the name; nobody types one.
        self.assertIn("9104", aliases.rescued(self.cur, u"株式会社商船三井"))
        self.assertIn("8308", aliases.rescued(self.cur, u"株式会社りそなホールディングス"))
        # 前株 typed for a 後株 filer: トヨタ自動車株式会社, typed the other way.
        self.assertIn("7203", aliases.rescued(self.cur, u"株式会社トヨタ自動車"))

    def test_nothing_is_rescued_when_the_plain_search_already_finds_it(self):
        self.assertEqual([], aliases.rescued(self.cur, u"りそな"))
        self.assertEqual([], aliases.rescued(self.cur, "Toyota"))
        self.assertEqual([], aliases.rescued(self.cur, u"トヨタ自動車株式会社"))

    def test_latin_words_are_not_welded_together(self):
        u"""ＴＯＹＯ　ＴＡＮＳＯ must not answer a search for Toyota, so a
        space between two latin words survives the fold and only the WHOLE
        de-spaced name matches a query typed without spaces."""
        self.assertEqual("TOYO TANSO COLTD", aliases.fold("TOYO TANSO CO.,LTD."))
        self.assertNotIn("5310", aliases.rescued(self.cur, "Toyota"))
        self.assertIn("5105", aliases.rescued(self.cur, "TOYOTIRE"))   # ＴＯＹＯ　ＴＩＲＥ

    def test_every_filed_name_is_findable_typed_without_its_spaces(self):
        u"""181 filers carry a space inside the filed name. Not one of them may
        be unreachable by its own name typed the way a person types it."""
        rows = self.cur.execute(
            u"""SELECT sec_code, name_ja FROM eq_entities
                WHERE sec_code IS NOT NULL AND name_ja IS NOT NULL
                  AND (name_ja LIKE '%\u3000%' OR name_ja LIKE '% %')""").fetchall()
        self.assertGreater(len(rows), 100, "the spacing trap should still exist")
        for sec_code, name_ja in rows:
            typed = name_ja.replace(u"\u3000", "").replace(" ", "")
            self.assertIn(sec_code, aliases.rescued(self.cur, typed), typed)

    def test_the_search_a_user_types_returns_the_company(self):
        from app import equity_api as eq
        for query, code in (("MUFG", "8306"), ("JAL", "9201"), ("Uniqlo", "9983"),
                            (u"株式会社商船三井", "9104"), (u"ｼﾞｬﾌｺ", "8595")):
            found = [c["sec_code"] for c in eq.companies(q=query)["companies"]]
            self.assertIn(code, found, query)


if __name__ == "__main__":
    unittest.main()
