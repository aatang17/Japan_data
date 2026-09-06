# -*- coding: utf-8 -*-
"""The MCP v2 surface: six generic tools, manifest resources, the toolset flag,
and parity with the v1 tools they replace.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_mcp_v2
Needs both databases under data/ (the equity checks skip without the file).
"""
import json
import os
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import equity_api, lvh_api, mcp, registry, tools, tools_v2
from app.main import app

EQUITY = equity_api.DB_PATH.exists()


def rpc(client, method, params=None, msg_id=1):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    r = client.post("/mcp", json=body)
    return r.status_code, r.json()


def call(client, name, **arguments):
    status, body = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert status == 200, body
    if "error" in body:
        return body["error"], True
    res = body["result"]
    return json.loads(res["content"][0]["text"]), res["isError"]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        registry.load()
        registry.bind(app)
        cls.client = TestClient(app)

    def setUp(self):
        os.environ["MCP_TOOLSET"] = "both"
        # The contract test alone makes more calls than the per-IP limit allows
        # in a minute; the limiter is not what is under test here.
        mcp._HITS.clear()

    def tearDown(self):
        os.environ.pop("MCP_TOOLSET", None)


class ProtocolTest(Base):
    def test_initialize_instructions_name_every_available_dataset(self):
        os.environ["MCP_TOOLSET"] = "v2"
        _, body = rpc(self.client, "initialize", {"protocolVersion": "2025-06-18"})
        text = body["result"]["instructions"]
        for mid in registry.ids():
            if registry.available(mid):
                self.assertIn(mid, text)
        self.assertIn("resources", body["result"]["capabilities"])
        self.assertIn("calc", text)

    def test_toolset_flag_controls_the_list(self):
        counts = {}
        for ts in ("v1", "v2", "both"):
            os.environ["MCP_TOOLSET"] = ts
            _, body = rpc(self.client, "tools/list")
            counts[ts] = [t["name"] for t in body["result"]["tools"]]
        self.assertEqual(len(counts["v2"]), 6)
        self.assertEqual(sorted(counts["v2"]), sorted(tools_v2.IMPLS))
        self.assertEqual(len(counts["both"]), len(counts["v1"]) + 6)
        self.assertNotIn("get_series", counts["v1"])

    def test_v1_tools_refused_under_v2_and_vice_versa(self):
        os.environ["MCP_TOOLSET"] = "v2"
        err, _ = call(self.client, "get_overview")
        self.assertEqual(err["code"], -32602)
        os.environ["MCP_TOOLSET"] = "v1"
        data, is_err = call(self.client, "list_datasets")  # a v1 name too — routes to v1
        self.assertFalse(is_err)
        self.assertIn("datasets", data)
        self.assertNotIn("tool", data)  # v1's shape, not the v2 envelope
        err, _ = call(self.client, "get_series", dataset="cpi-jp", series="0001")
        self.assertEqual(err["code"], -32602)

    def test_resources_list_and_read(self):
        _, body = rpc(self.client, "resources/list")
        uris = [r["uri"] for r in body["result"]["resources"]]
        self.assertEqual(len(uris), len(registry.ids()) + 2)
        for mid in registry.ids():
            self.assertIn("observatory://datasets/%s" % mid, uris)
        _, body = rpc(self.client, "resources/read", {"uri": "observatory://datasets/cpi-jp"})
        item = body["result"]["contents"][0]
        self.assertEqual(item["mimeType"], "application/json")
        self.assertEqual(json.loads(item["text"])["id"], "cpi-jp")
        _, body = rpc(self.client, "resources/read", {"uri": "observatory://sections"})
        self.assertIn("sections", json.loads(body["result"]["contents"][0]["text"]))
        _, body = rpc(self.client, "resources/read", {"uri": "observatory://nope"})
        self.assertEqual(body["error"]["code"], -32002)

    def test_descriptor_enums_are_the_live_ids(self):
        d = dict((t["name"], t) for t in tools_v2.descriptors())
        self.assertEqual(d["describe_dataset"]["inputSchema"]["properties"]["dataset"]["enum"],
                         registry.ids())
        for t in d.values():
            self.assertTrue(t["annotations"]["readOnlyHint"])


class ToolTest(Base):
    def test_list_datasets(self):
        data, err = call(self.client, "list_datasets")
        self.assertFalse(err)
        self.assertEqual(data["count"], len(registry.ids()))
        self.assertTrue(all("capabilities" in d for d in data["datasets"]))
        data, err = call(self.client, "list_datasets", section="prices")
        self.assertEqual([d["id"] for d in data["datasets"]], ["cpi-jp", "cpi-jp-items"])
        data, err = call(self.client, "list_datasets", section="weather")
        self.assertTrue(err)
        self.assertIn("prices", data["error"])

    def test_describe_dataset(self):
        data, err = call(self.client, "describe_dataset", dataset="cpi-jp")
        self.assertFalse(err)
        self.assertEqual(data["id"], "cpi-jp")
        self.assertTrue(data["tools"]["get_series"])
        self.assertIn("to", data["coverage"])
        data, err = call(self.client, "describe_dataset", dataset="nope")
        self.assertTrue(err)
        self.assertIn("cpi-jp", data["error"])

    def test_get_series_matches_v1(self):
        data, err = call(self.client, "get_series", dataset="cpi-jp", series="0001",
                         measure="yoy")
        self.assertFalse(err, data)
        for key in ("tool", "dataset", "data", "provenance", "calc", "vintage", "cite",
                    "coverage"):
            self.assertIn(key, data)
        self.assertEqual(data["data"]["trust"], "derived")
        self.assertIn("yoy", data["calc"])
        v1 = json.loads(tools.get_series_values("0001", measure="yoy", dataset="cpi-jp"))
        self.assertEqual(data["data"]["series"][0]["points"][-1],
                         v1["series"][0]["points"][-1])
        self.assertEqual(data["vintage"]["latest_period"], v1["as_of_release"])

    def test_get_series_as_of_and_refusals(self):
        data, err = call(self.client, "get_series", dataset="cpi-jp", series="0001",
                         measure="index", as_of="2026-08-20")
        self.assertFalse(err, data)
        self.assertEqual(data["vintage"]["as_of"], "2026-08-20")
        data, err = call(self.client, "get_series", dataset="cpi-jp", series="0001",
                         as_of="yesterday")
        self.assertTrue(err)
        data, err = call(self.client, "get_series", dataset="jgb-yields", series="10Y",
                         measure="yoy")
        self.assertTrue(err)  # daily dataset serves no monthly rates
        data, err = call(self.client, "get_series", dataset="cross-shareholdings",
                         series="x")
        self.assertTrue(err)
        self.assertIn("get_company", data["error"])

    def test_search_series(self):
        data, err = call(self.client, "search", query="electricity", dataset="cpi-jp")
        self.assertFalse(err)
        self.assertTrue(data["series"])
        self.assertEqual(data["series"][0]["dataset"], "cpi-jp")

    def test_screen_rejects_unknown_sort_with_the_valid_list(self):
        data, err = call(self.client, "screen", dataset="cpi-jp")
        self.assertTrue(err)
        self.assertIn("no screens", data["error"])


@unittest.skipUnless(EQUITY, "equity database not present")
class EquityToolTest(Base):
    def test_lvh_404_is_a_404_not_a_typeerror(self):
        with self.assertRaises(HTTPException) as ctx:
            lvh_api.company("0000", history=50)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("5%", ctx.exception.detail)

    def test_search_company_lists_datasets(self):
        data, err = call(self.client, "search", query="7974")
        self.assertFalse(err, data)
        hit = data["companies"][0]
        self.assertEqual(hit["sec_code"], "7974")
        self.assertIn("cross-shareholdings", hit["datasets"])
        self.assertGreater(len(hit["datasets"]), 3)

    def test_get_company_single_matches_v1(self):
        data, err = call(self.client, "get_company", code="7974",
                         dataset="cross-shareholdings")
        self.assertFalse(err, data)
        v1 = json.loads(tools.get_company_holdings("7974"))
        self.assertEqual(len(data["data"]["holdings"]), len(v1["holdings"]))
        self.assertEqual(data["cite"], v1["cite"])
        self.assertEqual(data["vintage"]["unit"], "filing")
        self.assertIn("pct_of_equity", data["calc"])

    def test_get_company_composed_and_missing_is_not_an_error(self):
        data, err = call(self.client, "get_company", code="7974")
        self.assertFalse(err, data)
        self.assertIn("cross-shareholdings", data["coverage"]["present"])
        self.assertIn("boards-and-pay", data["coverage"]["present"])
        self.assertEqual(data["coverage"]["errors"], [])
        self.assertEqual(data["company"]["sec_code"], "7974")
        self.assertIn("board_size", data["datasets"]["boards-and-pay"]["facts"])
        # Whatever is absent is reported with a reason, never dropped silently.
        for block in data["coverage"]["missing"]:
            self.assertTrue(block["reason"])
        seen = set(data["coverage"]["present"]) | set(
            b["dataset"] for b in data["coverage"]["missing"])
        self.assertEqual(seen, set(i for i in registry.ids()
                                   if "company" in registry.get(i)["capabilities"]))

    def test_get_company_no_data_single_dataset(self):
        """No rows is an answer with a reason, not a JSON-RPC error."""
        data, err = call(self.client, "get_company", code="0000",
                         dataset="cross-shareholdings")
        self.assertFalse(err, data)
        self.assertIsNone(data["data"])
        self.assertIn("missing", data)
        self.assertIn("cite", data)

    def test_get_company_unknown_code_everywhere(self):
        data, err = call(self.client, "get_company", code="0000")
        self.assertFalse(err, data)
        self.assertEqual(data["coverage"]["present"], [])
        self.assertEqual(data["coverage"]["errors"], [])

    def test_screen_matches_v1_and_validates_sort(self):
        data, err = call(self.client, "screen", dataset="boards-and-pay",
                         sort="oldest_boards", limit=5)
        self.assertFalse(err, data)
        v1 = json.loads(tools.get_governance_screen(metric="oldest_boards", limit=5))
        self.assertEqual(data["data"]["rows"][0]["sec_code"], v1["rows"][0]["sec_code"])
        data, err = call(self.client, "screen", dataset="boards-and-pay", sort="tallest")
        self.assertTrue(err)
        self.assertIn("oldest_boards", data["error"])

    def test_every_dataset_capability_answers_with_the_envelope(self):
        """The contract test: no capability of any dataset raises, 500s, or
        returns a JSON-RPC error — including for a company with no rows."""
        keys = ("tool", "dataset", "data", "provenance", "calc", "vintage", "cite")
        for mid in registry.ids():
            m = registry.get(mid)
            if not registry.available(mid):
                continue
            if "company" in m["capabilities"]:
                for code in ("7974", "0000"):
                    data, err = call(self.client, "get_company", code=code, dataset=mid)
                    self.assertFalse(err, (mid, code, data))
                    for k in keys:
                        self.assertIn(k, data, (mid, k))
            if m.get("screens"):
                for s in m["screens"]:
                    data, err = call(self.client, "screen", dataset=mid, sort=s["id"], limit=3)
                    self.assertFalse(err, (mid, s["id"], data))
                    self.assertIn("data", data)
            if m["shape"] == "series":
                hits, err = call(self.client, "search", query="", dataset=mid)
                self.assertTrue(err)  # empty query refused
                data, err = call(self.client, "describe_dataset", dataset=mid)
                self.assertFalse(err, (mid, data))


if __name__ == "__main__":
    unittest.main()
