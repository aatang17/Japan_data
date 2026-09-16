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
