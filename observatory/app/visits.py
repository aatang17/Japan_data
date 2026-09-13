"""Server-side visit counting: traffic as the server itself sees it.

Script-tag analytics (Plausible, Google Analytics) are blocked by default on
the bank and fund networks this product is aimed at, so they undercount
exactly the readers that matter. Counting inside the app sees every request,
blocker or not, and needs no third party and no cookie banner.

A visitor is HMAC(daily salt, address + user agent), truncated: stable for one
UTC day so a session counts once, unlinkable across days, and not reversible
to an address. No cookies, and no address is ever stored. The salt lives
beside the log on the volume, so a restart does not split a day's visitors in
two.

Writes take the same shape as the admin audit trail (see admin_api.py):
append-only JSONL under data/, no DuckDB write path anywhere (CLAUDE.md,
Ingest Guardrails 5), and no failure able to reach a response. Events are
buffered and flushed in batches, so a kill loses at most the live buffer —
immaterial for a visit counter.

The counts are an estimate and the admin page says so: one office behind one
address on one browser version reads as a single visitor, while one person on
a laptop and a phone reads as two.
"""
import binascii
import datetime
import hashlib
import hmac
import json
import os
import time
from threading import Lock

from . import db, geoip

ANALYTICS_DIR = db.DATA_DIR / "analytics"
SALT_PATH = ANALYTICS_DIR / "salt"

VISITOR_CHARS = 12
MAX_PATH_CHARS = 200

# Batch size and age at which the buffer is written out.
FLUSH_EVERY = 25
FLUSH_SECONDS = 60

# Ceiling on how much log a single summary will parse, so the admin page cannot
# be made slow by a year of accumulated traffic.
MAX_LINES = 500000

# Static files are requests, not visits: one page pulls a dozen and they would
# swamp every count on the page.
ASSET_SUFFIXES = (".css", ".js", ".map", ".png", ".jpg", ".jpeg", ".gif",
                  ".svg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".txt",
                  ".xml", ".csv", ".pdf")

# Substrings of a user agent that mean "not a person". An absent agent counts
# too: real browsers always send one, so a blank belongs to the platform's
# healthcheck or a script.
BOT_MARKERS = ("bot", "crawler", "spider", "crawl", "slurp", "curl", "wget",
               "python-requests", "httpx", "go-http-client", "java/",
               "okhttp", "headless", "phantom", "monitor", "uptime",
               "pingdom", "healthcheck", "health-check", "kube-probe",
               "railway", "preview", "scraper", "fetcher", "archiver",
               "facebookexternalhit", "embedly", "feedfetcher")

_SALT = []
_BUFFER = []
_LOCK = Lock()
_LAST_FLUSH = [time.monotonic()]


def _salt():
    """The HMAC key, generated once and kept on the volume."""
    if _SALT:
        return _SALT[0]
    value = b""
    try:
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        if SALT_PATH.exists():
            with open(str(SALT_PATH), "rb") as f:
                value = f.read().strip()
        if not value:
            value = binascii.hexlify(os.urandom(32))
            with open(str(SALT_PATH), "wb") as f:
                f.write(value + b"\n")
    except OSError as exc:
        # An unwritable volume must never stop the server. A per-boot key
        # still counts today's visitors; it just cannot survive a restart.
        print("VISIT SALT UNAVAILABLE (%s): using a per-boot key" % exc)
        if not value:
            value = binascii.hexlify(os.urandom(32))
    _SALT.append(value)
    return value


def _visitor(ip, user_agent, day):
    mac = hmac.new(_salt(), ("%s|%s|%s" % (day, ip, user_agent)).encode("utf-8"),
                   hashlib.sha256)
    return mac.hexdigest()[:VISITOR_CHARS]


def _header(headers, name):
    for key, value in headers:
        if key == name:
            return value.decode("latin-1")
    return ""


def _client_ip(scope, forwarded):
    """The reader's address, which behind Railway's proxy is the first hop of
    X-Forwarded-For. Used only as HMAC input, never stored or trusted."""
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _referrer_host(referer, host):
    """Only the sending host is kept: enough to tell Substack from a search
    engine, without recording the page someone came from. The port is stripped
    from both sides before comparing, or every click inside a host:port
    deployment reads as an external referral."""
    if not referer:
        return None
    rest = referer.split("://", 1)[-1]
    sender = rest.split("/", 1)[0].split("@")[-1].split(":")[0].lower()
    if not sender or sender == (host or "").split(":")[0].lower():
        return None
    return sender[:MAX_PATH_CHARS] or None


def _is_bot(user_agent):
    if not user_agent.strip():
        return True
    agent = user_agent.lower()
    for marker in BOT_MARKERS:
        if marker in agent:
            return True
    return False


def _kind(path):
    """What was asked for. None means "do not count at all"."""
    if path.startswith("/admin"):
        return None  # the console watching itself is not traffic
    if path.startswith("/api/v1") or path.startswith("/api/openapi"):
        return "api"
    if path.startswith("/mcp"):
        return "mcp"
    lowered = path.lower()
    for suffix in ASSET_SUFFIXES:
        if lowered.endswith(suffix):
            return None
    return "page"


def _month_path(when):
    return ANALYTICS_DIR / ("visits-%s.jsonl" % when.strftime("%Y-%m"))


def _flush_locked():
    """Write the buffer out, grouped by the month each event belongs to.
    Never raises: an unwritable log must not take the site down."""
    if not _BUFFER:
        return
    batch, _BUFFER[:] = list(_BUFFER), []
    _LAST_FLUSH[0] = time.monotonic()
    by_month = {}
    for event in batch:
        by_month.setdefault(event["at"][:7], []).append(event)
    try:
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        for month, events in by_month.items():
            path = ANALYTICS_DIR / ("visits-%s.jsonl" % month)
            with open(str(path), "a", encoding="utf-8") as f:
                for event in events:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as exc:
        print("VISIT LOG WRITE FAILED (%s): %d event(s) dropped" % (exc, len(batch)))


def flush():
    with _LOCK:
        _flush_locked()


def _record(event):
    with _LOCK:
        _BUFFER.append(event)
        due = (len(_BUFFER) >= FLUSH_EVERY
               or time.monotonic() - _LAST_FLUSH[0] >= FLUSH_SECONDS)
        if due:
            _flush_locked()


def observe(scope, status):
    """Note one finished request. Called from the middleware's finally block,
    so every exit path is counted and none can raise into the response."""
    if scope.get("obs_synthetic"):
        return  # the cache warm-up driving the app at boot, not a reader
    method = scope.get("method")
    if method not in ("GET", "POST"):
        return
    path = (scope.get("path") or "/")[:MAX_PATH_CHARS]
    kind = _kind(path)
    if kind is None:
        return
    if kind == "page" and method == "POST":
        return  # a form post is not a page read

    headers = [(k.lower(), v) for k, v in scope.get("headers") or ()]
    user_agent = _header(headers, b"user-agent")
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    day = now.strftime("%Y-%m-%d")
    ip = _client_ip(scope, _header(headers, b"x-forwarded-for"))
    # Derived here, while the address is still in hand, and stored in place of
    # it — the address itself goes no further than this function.
    geoip.prepare()
    country, network = geoip.lookup(ip)
    _record({
        "at": now.isoformat(timespec="seconds") + "Z",
        "visitor": _visitor(ip, user_agent, day),
        "path": path,
        "kind": kind,
        "status": status,
        "ref": _referrer_host(_header(headers, b"referer"),
                              _header(headers, b"host")),
        "country": country,
        "network": network,
        "bot": _is_bot(user_agent),
    })


class VisitCounter(object):
    """ASGI middleware. Install it OUTSIDE the response cache: a cache hit
    never reaches the routers, and a reader served from memory is still a
    reader."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        seen = {"status": 0}

        async def watched(message):
            if message["type"] == "http.response.start":
                seen["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, watched)
        finally:
            try:
                observe(scope, seen["status"])
            except Exception as exc:  # noqa: BLE001 — counting is never fatal
                print("VISIT COUNT FAILED (%s)" % exc)


# --- reading back ------------------------------------------------------------

def _log_files():
    if not ANALYTICS_DIR.exists():
        return []
    return sorted(ANALYTICS_DIR.glob("visits-*.jsonl"))


def counting_since():
    """The day counting actually began, read from the oldest log file.

    Distinct from the first event inside a window, which for any window
    starting after that day is just the window's own start — reporting that as
    "counting since" would claim the counter is younger than it is.
    """
    files = _log_files()
    if not files:
        return None
    try:
        with open(str(files[0]), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    return json.loads(line)["at"][:10]
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        return None
    return None


def _months_in_window(start, end):
    months, cursor = set(), start
    while cursor <= end:
        months.add(cursor.strftime("%Y-%m"))
        cursor += datetime.timedelta(days=1)
    months.add(end.strftime("%Y-%m"))
    return months


def summary(days=30, top=15):
    """Traffic over the last `days` UTC days, aggregated for the admin page.

    Humans and automated traffic are separated rather than merged: the
    headline counts are people, and the bot total is reported beside them so
    a crawl is never mistaken for readership.
    """
    flush()  # so the page shows the requests that just arrived
    days = max(1, min(int(days), 365))
    today = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).date()
    start = today - datetime.timedelta(days=days - 1)
    wanted = _months_in_window(start, today)

    daily = {}
    pages, refs, countries, networks = {}, {}, {}, {}
    located, unlocated = 0, 0
    visitors, bot_hits, api_calls, mcp_calls = set(), 0, 0, 0
    first_event, last_event = None, None
    lines_read, unreadable = 0, 0

    for path in _log_files():
        month = path.name[len("visits-"):-len(".jsonl")]
        if month not in wanted:
            continue
        try:
            handle = open(str(path), encoding="utf-8")
        except OSError:
            continue
        with handle as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lines_read += 1
                if lines_read > MAX_LINES:
                    break
                try:
                    event = json.loads(line)
                    at = event["at"]
                    day = at[:10]
                except (ValueError, KeyError, TypeError):
                    unreadable += 1
                    continue
                if day < start.isoformat():
                    continue
                if first_event is None or at < first_event:
                    first_event = at
                if last_event is None or at > last_event:
                    last_event = at

                bucket = daily.setdefault(
                    day, {"visitors": set(), "pageviews": 0, "api": 0, "bots": 0})
                if event.get("bot"):
                    bot_hits += 1
                    bucket["bots"] += 1
                    continue

                kind = event.get("kind")
                visitor = event.get("visitor")
                if visitor:
                    bucket["visitors"].add(visitor)
                    visitors.add(visitor)
                if kind == "api":
                    api_calls += 1
                    bucket["api"] += 1
                elif kind == "mcp":
                    mcp_calls += 1
                    bucket["api"] += 1
                elif kind == "page" and (event.get("status") or 0) < 400:
                    bucket["pageviews"] += 1
                    page = pages.setdefault(
                        event.get("path") or "/", {"views": 0, "visitors": set()})
                    page["views"] += 1
                    if visitor:
                        page["visitors"].add(visitor)
                sender = event.get("ref")
                if sender:
                    ref = refs.setdefault(sender, {"views": 0, "visitors": set()})
                    ref["views"] += 1
                    if visitor:
                        ref["visitors"].add(visitor)

                # Location covers page reads AND API calls: an institution
                # pulling the API is the readership worth knowing about, and a
                # page-only cut would hide it.
                place = event.get("country")
                operator = event.get("network")
                if place or operator:
                    located += 1
                else:
                    unlocated += 1
                for source, key in ((countries, place), (networks, operator)):
                    if not key:
                        continue
                    row = source.setdefault(key, {"views": 0, "visitors": set()})
                    row["views"] += 1
                    if visitor:
                        row["visitors"].add(visitor)

    # A day before counting began is UNKNOWN, not zero: padding the window
    # back to its requested length with zeros would draw weeks of invented
    # quiet. A day after it with no traffic is a true zero.
    began = counting_since() or (first_event[:10] if first_event else None)
    series = []
    cursor = start
    while cursor <= today:
        key = cursor.isoformat()
        bucket = daily.get(key)
        if began is None or key < began:
            series.append({"date": key, "visitors": None, "pageviews": None,
                           "api_calls": None, "bot_hits": None})
        else:
            series.append({
                "date": key,
                "visitors": len(bucket["visitors"]) if bucket else 0,
                "pageviews": bucket["pageviews"] if bucket else 0,
                "api_calls": bucket["api"] if bucket else 0,
                "bot_hits": bucket["bots"] if bucket else 0,
            })
        cursor += datetime.timedelta(days=1)

    def ranked(source):
        rows = [{"key": k, "views": v["views"], "visitors": len(v["visitors"])}
                for k, v in source.items()]
        rows.sort(key=lambda r: (-r["views"], r["key"]))
        return rows[:max(1, min(int(top), 100))]

    files = _log_files()
    return {
        "window_days": days,
        "from": start.isoformat(),
        "to": today.isoformat(),
        "counting_since": began,
        "pageviews": sum(d["pageviews"] or 0 for d in series),
        "visitors": len(visitors),
        "api_calls": api_calls,
        "mcp_calls": mcp_calls,
        "bot_hits": bot_hits,
        "daily": series,
        "top_pages": ranked(pages),
        "top_referrers": ranked(refs),
        "top_countries": ranked(countries),
        "top_networks": ranked(networks),
        # What share of counted traffic could be placed at all. Without it an
        # empty location table reads as "nobody came" rather than "the tables
        # were not loaded".
        "located_hits": located,
        "unlocated_hits": unlocated,
        "geoip": geoip.status(),
        "first_event": first_event,
        "last_event": last_event,
        "log_files": len(files),
        "log_bytes": sum(p.stat().st_size for p in files if p.exists()),
        "lines_read": lines_read,
        "unreadable_lines": unreadable,
        "truncated": lines_read > MAX_LINES,
    }
