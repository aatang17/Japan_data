# -*- coding: utf-8 -*-
"""The visit counter: who a reader is, and what is counted as what.

Run from observatory/:  ./.venv/bin/python -m unittest tests.test_visits

These cover the parts that fail silently. A broken identity still serves every
page and still writes a log; the damage only shows up weeks later as a
readership figure that was never true.
"""
import datetime
import json
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

from app import visits
from app.main import app

_REAL_DIR = [None, None]


def setUpModule():
    """Write the test's own events to a temporary directory. The visit log on
    the data volume is a product record, not a scratch file."""
    _REAL_DIR[0] = visits.ANALYTICS_DIR
    _REAL_DIR[1] = tempfile.mkdtemp(prefix="visits-test-")
    visits.ANALYTICS_DIR = __import__("pathlib").Path(_REAL_DIR[1])
    visits.SALT_PATH = visits.ANALYTICS_DIR / "salt"


def tearDownModule():
    visits.flush()
    visits.ANALYTICS_DIR = _REAL_DIR[0]
    visits.SALT_PATH = visits.ANALYTICS_DIR / "salt"
    shutil.rmtree(_REAL_DIR[1], ignore_errors=True)


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


class IdentityTest(unittest.TestCase):
    """Which of the two identities a request carries, and when."""

    def headers(self, cookie=None):
        pairs = [(b"user-agent", UA.encode())]
        if cookie:
            pairs.append((b"cookie", cookie.encode()))
        return pairs

    def test_daily_identity_changes_with_the_day(self):
        one = visits.identify("203.0.113.7", UA, self.headers(), "2026-09-16")
        two = visits.identify("203.0.113.7", UA, self.headers(), "2026-09-17")
        self.assertNotEqual(one[0], two[0])
        self.assertIsNone(one[2])  # nobody has answered the banner

    def test_accepted_cookie_survives_the_day_boundary(self):
        jar = "%s=granted; %s=abc123.2026-09-01" % (visits.CONSENT_COOKIE,
                                                    visits.VISITOR_COOKIE)
        one = visits.identify("203.0.113.7", UA, self.headers(jar), "2026-09-16")
        two = visits.identify("198.51.100.9", UA, self.headers(jar), "2026-09-17")
        # Same reader, a day later and on a different address.
        self.assertEqual(one[0], two[0])
        self.assertEqual(one[1], "2026-09-01")
        self.assertEqual(one[2], "granted")

    def test_the_stored_id_is_never_written_down(self):
        jar = "%s=granted; %s=abc123.2026-09-01" % (visits.CONSENT_COOKIE,
                                                    visits.VISITOR_COOKIE)
        visitor = visits.identify("203.0.113.7", UA, self.headers(jar),
                                  "2026-09-16")[0]
        self.assertNotIn("abc123", visitor)
        self.assertEqual(len(visitor), visits.VISITOR_CHARS)

    def test_declining_falls_back_to_the_daily_identity(self):
        jar = "%s=denied" % visits.CONSENT_COOKIE
        declined = visits.identify("203.0.113.7", UA, self.headers(jar), "2026-09-16")
        anonymous = visits.identify("203.0.113.7", UA, self.headers(), "2026-09-16")
        self.assertEqual(declined[0], anonymous[0])
        self.assertEqual(declined[2], "denied")
        self.assertIsNone(declined[1])

    def test_a_mangled_cookie_is_not_a_consent(self):
        for value in ("", "..", "not/a/id.2026-09-01", "x" * 80 + ".2026-09-01"):
            jar = "%s=granted; %s=%s" % (visits.CONSENT_COOKIE,
                                         visits.VISITOR_COOKIE, value)
            got = visits.identify("203.0.113.7", UA, self.headers(jar), "2026-09-16")
            self.assertIsNone(got[1], value)


class BotFilterTest(unittest.TestCase):
    """What the user-agent filter catches. The named agents below were each
    counted as readers until they were added; a regression here inflates
    every figure on the traffic page at once."""

    def test_googles_own_fetchers_are_not_readers(self):
        for agent in (
            "Mozilla/5.0 (compatible; Google-InspectionTool/1.0;)",
            "GoogleOther",
            "Mozilla/5.0 (Linux; Android 4.4.2; Nexus 4 Build/KOT49H) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/81.0.4044.138 Mobile Safari/537.36 "
            "(compatible; Google-Read-Aloud; +https://support.google.com/webmasters/answer/1061943)",
            "Mozilla/5.0 (compatible; Google-Site-Verification/1.0)",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "HeadlessChrome/128.0.0.0 Safari/537.36 Chrome-Lighthouse",
        ):
            self.assertTrue(visits._is_bot(agent), agent)

    def test_assistants_fetching_on_a_users_behalf_are_not_readers(self):
        for agent in ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                      "ChatGPT-User/1.0; +https://openai.com/bot",
                      "Claude-User/1.0", "Perplexity-User/1.0",
                      "meta-externalagent/1.1"):
            self.assertTrue(visits._is_bot(agent), agent)

    def test_libraries_are_not_readers(self):
        for agent in ("Scrapy/2.11 (+https://scrapy.org)", "Python/3.12 aiohttp/3.9",
                      "node-fetch/1.0", "axios/1.6.0", "PostmanRuntime/7.36"):
            self.assertTrue(visits._is_bot(agent), agent)

    def test_a_browser_is_a_reader(self):
        self.assertFalse(visits._is_bot(UA))
        self.assertFalse(visits._is_bot(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"))


class HostingTest(unittest.TestCase):
    """Which networks are data centres. The names are DB-IP's."""

    def test_clouds_hosts_and_cdns_are_hosting(self):
        for name in ("Google LLC", "Amazon.com, Inc.", "DigitalOcean, LLC", "OVH SAS",
                     "Shenzhen Tencent Computer Systems Company Limited",
                     "Microsoft Corporation", "Hetzner Online GmbH", "M247 Europe SRL",
                     "HostRoyale Technologies Pvt Ltd", "Scaleway SAS",
                     "Cloudflare, Inc.", "The Constant Company, LLC"):
            self.assertTrue(visits.is_hosting(name), name)

    def test_consumer_and_corporate_networks_are_not(self):
        for name in ("NTT Communications Corporation", "KDDI CORPORATION",
                     "SoftBank Corp.", "Bell Canada", "Comcast Cable Communications, LLC",
                     "COLT Technology Services Group Limited", "Google Fiber Inc.",
                     "Apple Inc.", "China Unicom Shanghai network"):
            self.assertFalse(visits.is_hosting(name), name)

    def test_an_unplaced_address_is_not_hosting(self):
        self.assertFalse(visits.is_hosting(None))
        self.assertFalse(visits.is_hosting(""))


class AIAgentTest(unittest.TestCase):
    """Which AI product asked, and what it was doing. The vendors ship a
    user-initiated fetcher and a training crawler whose names share a prefix,
    so the order of the table is the thing that can break."""

    def test_the_user_fetcher_is_not_the_training_crawler(self):
        self.assertEqual(visits.ai_agent("ChatGPT-User/1.0"), ("ChatGPT", "asked"))
        self.assertEqual(
            visits.ai_agent("Mozilla/5.0 (compatible; GPTBot/1.2; "
                            "+https://openai.com/gptbot)"),
            ("OpenAI GPTBot", "training"))
        self.assertEqual(visits.ai_agent("Claude-User/1.0"), ("Claude", "asked"))
        self.assertEqual(visits.ai_agent("ClaudeBot/1.0 (+claudebot@anthropic.com)"),
                         ("Anthropic ClaudeBot", "training"))
        self.assertEqual(visits.ai_agent("Perplexity-User/1.0"), ("Perplexity", "asked"))
        self.assertEqual(visits.ai_agent("Mozilla/5.0 (compatible; PerplexityBot/1.0)"),
                         ("Perplexity", "search"))

    def test_every_named_assistant_is_also_filtered_out_of_readership(self):
        for marker, _label, _purpose in visits.AI_AGENTS:
            self.assertTrue(visits._is_bot(marker + "/1.0"), marker)

    def test_a_browser_is_not_an_assistant(self):
        self.assertEqual(visits.ai_agent(UA), (None, None))
        self.assertEqual(visits.ai_agent(""), (None, None))

    def test_an_answer_engine_is_recognised_as_a_referrer(self):
        for host in ("chatgpt.com", "claude.ai", "www.perplexity.ai",
                     "copilot.microsoft.com", "gemini.google.com"):
            self.assertTrue(visits.is_ai_referrer(host), host)
        for host in ("www.google.com", "asiaecon.substack.com", "", None):
            self.assertFalse(visits.is_ai_referrer(host), host)

    def test_an_assistant_is_reported_apart_from_the_crawlers(self):
        now = datetime.datetime.utcnow().replace(microsecond=0)
        at = now.isoformat() + "Z"
        visits._record({"at": at, "visitor": "ai-asked", "path": "/holdings.html",
                        "kind": "page", "status": 200, "ref": None, "internal": False,
                        "country": "US", "network": "OpenAI", "bot": True,
                        "agent": "ChatGPT", "agent_purpose": "asked"})
        visits._record({"at": at, "visitor": "ai-crawl", "path": "/cpi.html",
                        "kind": "page", "status": 200, "ref": None, "internal": False,
                        "country": "US", "network": "Amazon.com, Inc.", "bot": True,
                        "agent": "OpenAI GPTBot", "agent_purpose": "training"})
        # A reader who followed a citation out of an answer: a person, not a bot.
        visits._record({"at": at, "visitor": "ai-reader", "path": "/holdings.html",
                        "kind": "page", "status": 200, "ref": "chatgpt.com",
                        "internal": False, "country": "GB",
                        "network": "British Telecommunications", "bot": False})
        visits.flush()

        got = visits.summary(1)
        agents = dict((r["key"], r) for r in got["ai_agents"])
        self.assertEqual(agents["ChatGPT"]["purpose"], "asked")
        self.assertEqual(agents["ChatGPT"]["top_page"], "/holdings.html")
        self.assertEqual(agents["OpenAI GPTBot"]["purpose"], "training")
        # Counted as automation, never as readers.
        self.assertNotIn("ai-asked", [r["key"] for r in got["ai_agents"]])
        self.assertGreaterEqual(got["bot_hits"], 2)
        self.assertGreaterEqual(got["ai_referrals"]["views"], 1)
        row = [r for r in got["top_referrers"] if r["key"] == "chatgpt.com"][0]
        self.assertTrue(row["ai"])
        google = [r for r in got["top_referrers"] if r["key"] == "www.google.com"]
        self.assertTrue(all(not r["ai"] for r in google))


class PeopleTest(unittest.TestCase):
    """The strict figure: a reading time, a placed network, not a data centre.
    Written straight into the log, so the test is of the summary alone."""

    def test_only_a_scripted_visit_off_a_data_centre_is_a_person(self):
        now = datetime.datetime.utcnow().replace(microsecond=0)
        at = now.isoformat() + "Z"

        def page(visitor, network, ref="www.google.com"):
            return {"at": at, "visitor": visitor, "path": "/holdings.html",
                    "kind": "page", "status": 200, "ref": ref, "internal": False,
                    "country": "JP", "network": network, "bot": False}

        def dwell(visitor):
            return {"at": at, "visitor": visitor, "kind": "dwell",
                    "path": "/holdings.html", "seconds": 40, "bot": False,
                    "view": "v-" + visitor}

        events = [
            page("pp-person", "NTT Communications Corporation"), dwell("pp-person"),
            page("pp-cloud", "Google LLC"), dwell("pp-cloud"),        # ran the script, but a data centre
            page("pp-silent", "KDDI CORPORATION"),                     # a placed ISP, no script report
            page("pp-unplaced", None), dwell("pp-unplaced"),            # ran the script, not placed
        ]
        for event in events:
            visits._record(event)
        visits.flush()

        got = visits.summary(1)
        self.assertEqual(got["confirmed"]["people"], 1)
        self.assertGreaterEqual(got["confirmed"]["scripted"], 3)
        self.assertGreaterEqual(got["confirmed"]["hosting"], 1)
        google = [r for r in got["top_referrers"] if r["key"] == "www.google.com"][0]
        self.assertEqual(google["visitors"], 4)
        self.assertEqual(google["people"], 1)
        networks = dict((r["key"], r) for r in got["top_networks"])
        self.assertTrue(networks["Google LLC"]["hosting"])
        self.assertFalse(networks["NTT Communications Corporation"]["hosting"])
        self.assertEqual(networks["NTT Communications Corporation"]["people"], 1)
        self.assertEqual(networks["Google LLC"]["people"], 0)
        today = got["daily"][-1]
        self.assertEqual(today["people"], 1)


class CountedAsTest(unittest.TestCase):
    """What each path counts as. The beacon is the trap: counted as an API
    call it would turn one reader on one page into a stream of them."""

    def test_the_beacon_and_the_banner_are_not_traffic(self):
        self.assertIsNone(visits._kind("/api/v1/visit/ping"))
        self.assertIsNone(visits._kind("/api/v1/visit/consent"))

    def test_everything_else_still_counts(self):
        self.assertEqual(visits._kind("/cpi.html"), "page")
        self.assertEqual(visits._kind("/api/v1/cpi-jp/overview"), "api")
        self.assertEqual(visits._kind("/mcp"), "mcp")
        self.assertEqual(visits._kind("/assets/app.css"), "asset")
        self.assertIsNone(visits._kind("/admin.html"))


class SessionTest(unittest.TestCase):
    """Sessions cut out of one visitor's request times."""

    def test_half_an_hour_of_silence_ends_a_session(self):
        base = 1_700_000_000
        lengths, pages, single = visits._sessions(
            {"a": [base, base + 60, base + 120,          # a three-page read
                   base + 4000, base + 4030]})           # and one an hour later
        self.assertEqual(sorted(lengths), [30, 120])
        self.assertEqual(sorted(pages), [2, 3])
        self.assertEqual(single, 0)

    def test_a_single_page_visit_is_counted_not_averaged_in(self):
        lengths, pages, single = visits._sessions({"a": [1_700_000_000]})
        self.assertEqual(lengths, [0])
        self.assertEqual(single, 1)


class DwellTest(unittest.TestCase):
    """One reading reported three times is one reading."""

    def test_the_longest_report_wins_per_page_view(self):
        client = TestClient(app)
        for seconds in (12, 95, 40):
            got = client.post("/api/v1/visit/ping", headers={"user-agent": UA},
                              content=json.dumps({"path": "/cpi.html", "view": "v-test",
                                                  "seconds": seconds, "closed": True}))
            self.assertEqual(got.status_code, 204)
        visits.flush()
        rows = [e for e in _events() if e.get("view") == "v-test"]
        self.assertEqual([e["seconds"] for e in rows], [12, 95, 40])
        # All three are written; the summary is where they become one.
        folded = {}
        for row in rows:
            key = row["view"]
            folded[key] = max(folded.get(key, 0), row["seconds"])
        self.assertEqual(folded["v-test"], 95)

    def test_an_abandoned_tab_is_capped_not_dropped(self):
        client = TestClient(app)
        client.post("/api/v1/visit/ping", headers={"user-agent": UA},
                    content=json.dumps({"path": "/cpi.html", "view": "v-long",
                                        "seconds": 90000, "closed": True}))
        visits.flush()
        rows = [e for e in _events() if e.get("view") == "v-long"]
        self.assertTrue(rows)
        self.assertEqual(rows[-1]["seconds"], visits.MAX_DWELL_SECONDS)

    def test_a_crawler_reports_nothing(self):
        client = TestClient(app)
        client.post("/api/v1/visit/ping", headers={"user-agent": "Googlebot/2.1"},
                    content=json.dumps({"path": "/cpi.html", "view": "v-bot",
                                        "seconds": 30, "closed": True}))
        visits.flush()
        self.assertEqual([e for e in _events() if e.get("view") == "v-bot"], [])


class ConsentEndpointTest(unittest.TestCase):

    def test_accepting_issues_one_id_and_keeps_it(self):
        client = TestClient(app)
        first = client.post("/api/v1/visit/consent", json={"choice": "granted"})
        self.assertEqual(first.json()["consent"], "granted")
        issued = client.cookies.get(visits.VISITOR_COOKIE)
        self.assertTrue(issued)
        # Saying yes twice must not make somebody a new reader.
        client.post("/api/v1/visit/consent", json={"choice": "granted"})
        self.assertEqual(client.cookies.get(visits.VISITOR_COOKIE), issued)

    def test_declining_deletes_the_id_and_is_itself_stored(self):
        client = TestClient(app)
        client.post("/api/v1/visit/consent", json={"choice": "granted"})
        client.post("/api/v1/visit/consent", json={"choice": "denied"})
        self.assertEqual(client.cookies.get(visits.CONSENT_COOKIE), "denied")
        self.assertIsNone(client.cookies.get(visits.VISITOR_COOKIE))

    def test_anything_that_is_not_a_yes_is_a_no(self):
        client = TestClient(app)
        got = client.post("/api/v1/visit/consent", json={"choice": "maybe"})
        self.assertEqual(got.json()["consent"], "denied")


class ProxiedSchemeTest(unittest.TestCase):
    """Behind the platform's proxy the connection to this process is plain
    http, so a cookie marked Secure from `request.url.scheme` is never marked
    at all. Production showed exactly that."""

    def test_the_forwarded_scheme_decides(self):
        client = TestClient(app)
        got = client.post("/api/v1/visit/consent", json={"choice": "granted"},
                          headers={"x-forwarded-proto": "https"})
        cookies = got.headers.get_list("set-cookie")
        self.assertTrue(cookies)
        for cookie in cookies:
            self.assertIn("Secure", cookie, cookie)

    def test_plain_http_still_gets_a_usable_cookie(self):
        client = TestClient(app)
        got = client.post("/api/v1/visit/consent", json={"choice": "granted"})
        for cookie in got.headers.get_list("set-cookie"):
            self.assertNotIn("Secure", cookie, cookie)


def _events():
    """Every event in the current month's log."""
    path = visits._month_path(datetime.datetime.utcnow())
    if not path.exists():
        return []
    out = []
    with open(str(path), encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


if __name__ == "__main__":
    unittest.main()
