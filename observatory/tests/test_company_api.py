# -*- coding: utf-8 -*-
"""The composed company view: /api/v1/company/{code}.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_company_api
The equity checks skip without data/equity.duckdb.
"""
import json
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import company_api, equity_api, registry
from app.main import app

EQUITY = equity_api.DB_PATH.exists()
COMPANY_DATASETS = None


def setUpModule():
    global COMPANY_DATASETS
    registry.load()
    registry.bind(app)
    COMPANY_DATASETS = [i for i in registry.ids()
                        if "company" in registry.get(i)["capabilities"]]


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_route_beats_the_dataset_catch_all(self):
        """/api/v1/company/{code} must not be read as /api/v1/{dataset}/..."""
        r = self.client.get("/api/v1/company/7203")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["code"], "7203")

    def test_as_of_refuses_rather_than_returning_today(self):
        """Answering a point-in-time question with current filings would be
        silently wrong; refusing is not."""
        r = self.client.get("/api/v1/company/7203?as_of=2025-07-01")
        self.assertEqual(r.status_code, 400)
        self.assertIn("filed_date", r.json()["detail"])

    def test_bad_code_and_unknown_filters(self):
        self.assertEqual(self.client.get("/api/v1/company/ ").status_code, 400)
        self.assertEqual(
            self.client.get("/api/v1/company/7203?datasets=nope").status_code, 404)
        self.assertEqual(
            self.client.get("/api/v1/company/7203?sections=weather").status_code, 404)


@unittest.skipUnless(EQUITY, "equity database not present")
class ComposeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.doc = cls.client.get("/api/v1/company/7203").json()

    def test_every_company_dataset_is_accounted_for(self):
        """Present or missing-with-a-reason — never silently dropped."""
        cov = self.doc["coverage"]
        seen = set(cov["present"]) | set(m["dataset"] for m in cov["missing"]) \
            | set(e["dataset"] for e in cov["errors"])
        self.assertEqual(seen, set(COMPANY_DATASETS))
        self.assertEqual(cov["errors"], [])
        for m in cov["missing"]:
            self.assertTrue(m["reason"])

    def test_identity_comes_from_the_filings(self):
        self.assertEqual(self.doc["company"]["sec_code"], "7203")
        self.assertEqual(self.doc["company"]["name_en"], "TOYOTA MOTOR CORPORATION")

    def test_blocks_carry_their_own_provenance_and_formulas(self):
        for mid in self.doc["coverage"]["present"]:
            block = self.doc["datasets"][mid]
            self.assertTrue(block["provenance"]["credit"], mid)
            self.assertEqual(block["provenance"]["trust"], "official", mid)
            manifest = registry.get(mid)
            derived = [m["id"] for m in manifest["measures"] if m["trust"] == "derived"]
            self.assertEqual(sorted(block["calc"]), sorted(derived), mid)
            for mid2, formula in block["calc"].items():
                self.assertTrue(formula.strip(), (mid, mid2))

    def test_cites_and_api_links_are_filled_in(self):
        for mid in self.doc["coverage"]["present"]:
            block = self.doc["datasets"][mid]
            self.assertNotIn("{", block["cite"], mid)
            if block["api"]:
                self.assertNotIn("{", block["api"], mid)
                self.assertTrue(registry.resolves(app, block["api"].replace("7203", "{sec_code}"))
                                or "7203" in block["api"], mid)

    def test_sections_are_in_registry_order_and_hold_only_present_datasets(self):
        order = [s["id"] for s in self.doc["sections"]]
        self.assertEqual(order, [s for s in registry.SECTION_IDS if s in order])
        listed = [d for s in self.doc["sections"] for d in s["datasets"]]
        self.assertEqual(sorted(listed), sorted(self.doc["coverage"]["present"]))

    def test_compact_drops_tables_but_keeps_the_counts(self):
        compact = self.client.get("/api/v1/company/7203?compact=1").json()
        for mid in compact["coverage"]["present"]:
            block = compact["datasets"][mid]
            self.assertNotIn("tables", block)
            self.assertIn("table_counts", block)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(self.doc)))

    def test_row_limit_caps_tables_and_discloses_the_total(self):
        small = self.client.get("/api/v1/company/7203?limit=2").json()
        for mid, block in small["datasets"].items():
            for name, rows in block.get("tables", {}).items():
                self.assertLessEqual(len(rows), 2, (mid, name))
                if block["table_counts"][name] > 2:
                    self.assertEqual(block["truncated"][name]["total"],
                                     block["table_counts"][name])

    def test_filters(self):
        one = self.client.get("/api/v1/company/7203?datasets=boards-and-pay").json()
        self.assertEqual(list(one["datasets"]), ["boards-and-pay"])
        sec = self.client.get("/api/v1/company/7203?sections=ownership").json()
        for mid in sec["datasets"]:
            self.assertEqual(registry.get(mid)["section"], "ownership")

    def test_coverage_endpoint_is_the_matrix_alone(self):
        r = self.client.get("/api/v1/company/7203/coverage")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertNotIn("datasets", body)
        self.assertEqual(body["coverage"]["present"], self.doc["coverage"]["present"])

    def test_unknown_company_is_an_answer_not_an_error(self):
        r = self.client.get("/api/v1/company/0000")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["coverage"]["present"], [])
        self.assertEqual(body["coverage"]["errors"], [])
        self.assertEqual(len(body["coverage"]["missing"]), len(COMPANY_DATASETS))

    def test_one_failing_dataset_costs_the_others_nothing(self):
        """A block that raises becomes an errors entry, not a 500."""
        mid = "boards-and-pay"
        real = registry.bound
        registry.bound = (lambda m, a, _r=real:
                          (_ for _ in ()).throw(RuntimeError("boom"))
                          if (m == mid and a == "company") else _r(m, a))
        try:
            doc = company_api.compose("7203", compact=True)
        finally:
            registry.bound = real
        self.assertIn(mid, [e["dataset"] for e in doc["coverage"]["errors"]])
        self.assertNotIn(mid, doc["coverage"]["present"])
        self.assertTrue(doc["coverage"]["present"], "the other blocks still answered")

    def test_the_mcp_tool_and_the_endpoint_agree(self):
        """One implementation: the tool is the endpoint's compact form."""
        from app import tools_v2
        tool = json.loads(tools_v2.get_company("7203"))
        endpoint = self.client.get("/api/v1/company/7203?compact=1").json()
        self.assertEqual(tool["coverage"], endpoint["coverage"])
        self.assertEqual(tool["company"], endpoint["company"])
        self.assertEqual(sorted(tool["datasets"]), sorted(endpoint["datasets"]))
        self.assertTrue(tool["cite"].startswith("http"))


if __name__ == "__main__":
    unittest.main()
