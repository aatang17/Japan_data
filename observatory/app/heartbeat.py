"""When the ingest cycle last ran — the signal that the refresh is alive.

The staleness thresholds each adapter declares are deliberately generous: 90
days for monthly CPI, 75 for the BOJ balance sheet, 7 for the daily yield
curve. They answer "is this data too old to publish?", which is the right
question for the data and the wrong one for the machinery. A refresh that
stops running is invisible inside them for days, and for the monthly sets for
months.

That is not hypothetical. Nothing restarted the service between 1 and 3
September 2026; the yield curve fell three days behind and every dataset
still reported `ok`, because three days is well inside the seven the adapter
allows. The gap was found by hand, not by the health endpoint.

So the machinery gets its own, much tighter signal, independent of any
dataset: the boot script stamps this file at the end of every ingest cycle,
and `api.health()` reports how long ago that was. A stamp older than one
refresh interval means the refresh itself has stopped, whatever the data
happens to look like.

Deliberately a plain file on the data volume rather than a DuckDB row. It is
written by the boot script while nothing is serving, and read by the API,
which must never write to the database.
"""
import datetime
import json
import os

from .db import DATA_DIR

PATH = DATA_DIR / "ingest_heartbeat.json"

# How old the stamp may get before the refresh counts as broken. The refresh
# runs daily, so anything past a day plus slack for a slow ingest is a real
# fault rather than a late run.
DEFAULT_MAX_AGE_HOURS = 26.0

_UTC = datetime.timezone.utc
_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _now():
    return datetime.datetime.now(_UTC).replace(microsecond=0)


def max_age_hours():
    raw = os.environ.get("REFRESH_MAX_AGE_HOURS")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            print("heartbeat: REFRESH_MAX_AGE_HOURS=%r is not a number; using %s"
                  % (raw, DEFAULT_MAX_AGE_HOURS))
    return DEFAULT_MAX_AGE_HOURS


def write(outcomes=None, now=None):
    """Stamp the end of an ingest cycle. Called by start.sh, never by the API.

    Written to a temporary name and renamed, so a reader never sees a
    half-written file and a crash mid-write cannot destroy the last good
    stamp.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"at": (now or _now()).strftime(_FORMAT), "outcomes": outcomes or {}}
    tmp = PATH.with_name(PATH.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(PATH)
    return payload


def read():
    """The last stamp, or None if the cycle has never completed here."""
    try:
        payload = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and payload.get("at") else None


def status(now=None):
    """How the refresh machinery is doing, in the shape health() reports.

    `overdue` is None — unknown, not healthy — when there is no stamp at all.
    A volume that predates this file, or a first boot, must not read as a
    fault; it also must not read as success.
    """
    limit = max_age_hours()
    payload = read()
    if payload is None:
        return {"last_ingest_at": None, "hours_since_ingest": None,
                "refresh_max_age_hours": limit, "refresh_overdue": None}
    try:
        stamped = datetime.datetime.strptime(payload["at"], _FORMAT).replace(tzinfo=_UTC)
    except ValueError:
        return {"last_ingest_at": payload.get("at"), "hours_since_ingest": None,
                "refresh_max_age_hours": limit, "refresh_overdue": None}
    hours = ((now or _now()) - stamped).total_seconds() / 3600.0
    return {"last_ingest_at": payload["at"],
            "hours_since_ingest": round(hours, 2),
            "refresh_max_age_hours": limit,
            "refresh_overdue": hours > limit}
