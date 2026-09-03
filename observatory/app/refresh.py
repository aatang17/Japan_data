"""The daily data refresh, and the watch that notices when it stops.

Why the process ends itself
---------------------------
DuckDB takes one writer, and the API holds a long-lived read-only handle on
the same file, so the ingest cannot run while the server is serving. The
refresh is therefore a restart: start.sh runs the ingests, then serves, and
when the server exits it runs them again. This module is what makes the
server exit, once a day, on the clock.

The alternative — a second Railway service that restarts this one on a cron —
is what observatory/README.md recommended for a month. It was never created,
and in early September 2026 the site quietly served three-day-old yields
because nothing had restarted it since the 1st. An in-repo scheduler cannot
be forgotten, needs no API token, and works identically under Docker and on a
laptop. That is the whole argument for it.

Only when something will restart us
-----------------------------------
Exiting is safe only under a supervisor. start.sh exports
REFRESH_SUPERVISED=1; nothing else does, so a plain `uvicorn app.main:app`
during development is never killed by this code, whatever the clock says.
The health watch below runs everywhere, because it only reports.

Why UTC
-------
The schedule is UTC and the default is 09:00, which is 18:00 in Tokyo — after
the Ministry of Finance posts the day's yield curve. Japan has no daylight
saving, so a fixed UTC offset is exactly right all year, and the slim
container image needs no timezone database for it to be.
"""
import asyncio
import datetime
import json
import os
import signal
import time
import urllib.request

from starlette.concurrency import run_in_threadpool

from . import heartbeat

# The loop wakes every minute rather than sleeping until the target: a long
# sleep survives neither a suspended laptop nor a clock correction, and a
# minute of drift on a daily job is immaterial.
TICK_SECONDS = 60

# Never exit before this much uptime, whatever the clock says. A belt to the
# braces of _Clock's boot rule, so no combination of restart timing can turn
# into a restart loop.
MIN_UPTIME_SECONDS = 600

HEALTH_EVERY_SECONDS = 900
ALERT_REPEAT_SECONDS = 6 * 3600

DEFAULT_AT = "09:00"  # 18:00 Asia/Tokyo
_UTC = datetime.timezone.utc

_FALSE = ("0", "false", "no", "off", "")


def _utcnow():
    return datetime.datetime.now(_UTC)


def enabled():
    return os.environ.get("REFRESH_ENABLED", "1").strip().lower() not in _FALSE


def supervised():
    return os.environ.get("REFRESH_SUPERVISED", "").strip().lower() not in _FALSE


def scheduled_at():
    """(hour, minute) of the daily refresh, in UTC."""
    raw = (os.environ.get("REFRESH_AT") or DEFAULT_AT).strip()
    head, _, tail = raw.partition(":")
    try:
        hour, minute = int(head), int(tail or 0)
    except ValueError:
        hour, minute = -1, -1
    if not (0 <= hour < 24 and 0 <= minute < 60):
        print("refresh: REFRESH_AT=%r is not HH:MM; using %s UTC" % (raw, DEFAULT_AT))
        return int(DEFAULT_AT[:2]), int(DEFAULT_AT[3:])
    return hour, minute


class _Clock(object):
    """Fires once per day, the first time the tick lands past the target.

    The boot rule matters more than it looks: a container that starts *after*
    today's target has, by definition, just ingested, so today's slot is
    already served. Without that, every restart after the target time would
    schedule another one a minute later, forever.
    """

    def __init__(self, now):
        self.hour, self.minute = scheduled_at()
        self.last_fired = now.date() if self.target(now) <= now else None

    def target(self, now):
        return now.replace(hour=self.hour, minute=self.minute,
                           second=0, microsecond=0)

    def due(self, now):
        return self.last_fired != now.date() and now >= self.target(now)

    def fired(self, now):
        self.last_fired = now.date()


# --- what counts as a problem ------------------------------------------------

def problems(report):
    """(key, message) for everything wrong in a health report.

    Keyed so the alert throttle can hold one problem quiet while letting a
    new one through immediately.
    """
    found = []
    if report.get("refresh_overdue"):
        found.append(("refresh", "the ingest has not run for %s hours (limit %s) — "
                                 "the daily refresh has stopped"
                      % (report.get("hours_since_ingest"),
                         report.get("refresh_max_age_hours"))))
    for row in report.get("datasets", []):
        slug = row.get("dataset")
        if not row.get("published"):
            found.append((slug + ":unpublished",
                          "%s has no published release" % slug))
            continue
        if row.get("stale"):
            found.append((slug + ":stale",
                          "%s is stale: latest period %s, %s days old (limit %s)"
                          % (slug, row.get("latest_period"),
                             row.get("days_since_latest_period"),
                             row.get("stale_after_days"))))
        if row.get("unpublished_artifact"):
            found.append((slug + ":orphan",
                          "%s fetched a file that produced no release — a validation "
                          "failure nobody was told about" % slug))
    return found


# --- alerting ----------------------------------------------------------------

_last_alert = {}


def _webhook():
    return (os.environ.get("ALERT_WEBHOOK_URL") or "").strip()


def _post(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return getattr(response, "status", response.getcode())


def alert(found, now=None):
    """Push the problems that are not already in their quiet window.

    Returns the keys actually sent, so a caller (and the tests) can see what
    the throttle let through.
    """
    url = _webhook()
    stamp = time.time() if now is None else now
    # A fault that has cleared forgets its quiet window, so the same fault
    # recurring an hour later is reported again rather than swallowed.
    for key in list(_last_alert):
        if key not in [k for k, _ in found]:
            del _last_alert[key]
    # Membership, not a zero sentinel: "never alerted" has to pass the throttle
    # whatever the clock reads, and `stamp - 0` does not on a small clock.
    fresh = [(key, message) for key, message in found
             if key not in _last_alert
             or stamp - _last_alert[key] >= ALERT_REPEAT_SECONDS]
    if not fresh:
        return []
    if url:
        site = os.environ.get("SITE_BASE_URL", "").rstrip("/")
        text = "Japan Data Observatory — %d problem(s):\n%s" % (
            len(fresh), "\n".join("• " + message for _, message in fresh))
        if site:
            text += "\n%s/api/v1/catalog/health" % site
        try:
            _post(url, {"text": text})
        except Exception as exc:  # noqa: BLE001 — an alert must never crash the app
            print("refresh: alert webhook failed: %s" % exc)
            return []
    for key, _ in fresh:
        _last_alert[key] = stamp
    return [key for key, _ in fresh]


def watch():
    """One pass of the health watch. Synchronous; run it off the event loop."""
    from . import api  # local: api imports heartbeat, and this imports api

    found = problems(api.health())
    for _, message in found:
        # Same shape as the boot check in start.sh, so one log rule catches both.
        print("ATTENTION %s" % message)
    # Called even when nothing is wrong, so cleared faults release their
    # throttle entries.
    alert(found)
    return found


# --- the loop ----------------------------------------------------------------

async def run():
    """Tick until cancelled: refresh on the clock, watch health in between."""
    if not enabled():
        print("refresh: disabled by REFRESH_ENABLED")
        return
    started = time.time()
    clock = _Clock(_utcnow())
    armed = supervised()
    print("refresh: watching health every %dmin; daily refresh at %02d:%02d UTC %s"
          % (HEALTH_EVERY_SECONDS // 60, clock.hour, clock.minute,
             "armed" if armed else "not armed (no supervisor)"))
    next_watch = time.time() + 60

    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            now = _utcnow()
            if (armed and clock.due(now)
                    and time.time() - started >= MIN_UPTIME_SECONDS):
                clock.fired(now)
                print("REFRESH scheduled daily refresh (%02d:%02d UTC) — shutting down "
                      "so the supervisor can re-run the ingests" % (clock.hour, clock.minute))
                os.kill(os.getpid(), signal.SIGTERM)
                return
            if time.time() >= next_watch:
                next_watch = time.time() + HEALTH_EVERY_SECONDS
                await run_in_threadpool(watch)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives any one failure
            print("refresh: tick failed: %s" % exc)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "heartbeat":
        print("ingest heartbeat: %s" % heartbeat.write()["at"])
    else:
        print(json.dumps(heartbeat.status(), indent=2))
