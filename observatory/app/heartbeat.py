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

# The per-dataset journal: when the refresh last got to each dataset, and what
# happened. The cycle stamp above answers "is the machinery alive?"; it cannot
# answer "is it still reaching THIS dataset?", and the difference is not
# academic. Between 14 and 19 September 2026 the stamp was written on time
# every night — it is stamped after the macro loop and before the equity work
# — while every macro re-publish was being discarded and all eleven EDINET
# extractors sat frozen. The cycle looked healthy because it was running; it
# just was not landing anything.
#
# So each dataset records its own last contact, and a dataset the refresh has
# not touched for a day is a fault regardless of how fresh its data looks.
# That is deliberately a statement about the PIPELINE, not the source: CPI is
# monthly and fiscal data is annual, so "no new period today" is normal for
# almost everything here and makes a useless alarm.
JOURNAL_PATH = DATA_DIR / "refresh_journal.json"

# How old the stamp may get before the refresh counts as broken. The refresh
# runs daily, so anything past a day plus slack for a slow ingest is a real
# fault rather than a late run.
DEFAULT_MAX_AGE_HOURS = 26.0

# Same argument, per dataset. The refresh is daily, so a dataset untouched for
# more than a day and a bit has been skipped, not merely queued behind a slow
# neighbour.
DEFAULT_CHECK_MAX_AGE_HOURS = 26.0

_UTC = datetime.timezone.utc
_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _now():
    return datetime.datetime.now(_UTC).replace(microsecond=0)


def _hours_from_env(name, default):
    raw = os.environ.get(name)
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print("heartbeat: %s=%r is not a positive number; using %s"
              % (name, raw, default))
    return default


def max_age_hours():
    return _hours_from_env("REFRESH_MAX_AGE_HOURS", DEFAULT_MAX_AGE_HOURS)


def check_max_age_hours():
    return _hours_from_env("REFRESH_CHECK_MAX_AGE_HOURS",
                           DEFAULT_CHECK_MAX_AGE_HOURS)


def write(outcomes=None, now=None):
    """Stamp the end of an ingest cycle. Called by start.sh, never by the API.

    Written to a temporary name and renamed, so a reader never sees a
    half-written file and a crash mid-write cannot destroy the last good
    stamp.
    """
    payload = {"at": (now or _now()).strftime(_FORMAT), "outcomes": outcomes or {}}
    _write_json(PATH, payload)
    return payload


def read():
    """The last stamp, or None if the cycle has never completed here."""
    try:
        payload = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and payload.get("at") else None


def _write_json(path, payload):
    """Atomically, so a reader never sees half a file and a crash keeps the last."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def journal():
    """dataset -> {at, outcome, detail}, or {} before anything was recorded."""
    try:
        payload = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = payload.get("datasets") if isinstance(payload, dict) else None
    return entries if isinstance(entries, dict) else {}


def record(dataset, outcome, detail=None, now=None):
    """Note that the refresh reached `dataset`, and how it went.

    Written after every dataset rather than once at the end of the cycle, so a
    run that is cut short — by the daily restart, a deploy, or a crash — still
    says exactly how far it got. That is the whole point: the failure this
    exists to catch was a refresh that ran to completion every night and
    silently stopped landing anything.

    `outcome` is 'published', 'unchanged' or 'failed'. 'unchanged' counts as
    contact: the pipeline looked, and the source had nothing new.

    Never raises. Bookkeeping for the alarm must not be able to break the
    refresh it is watching.
    """
    try:
        entries = journal()
        entries[dataset] = {
            "at": (now or _now()).strftime(_FORMAT),
            "outcome": outcome,
            "detail": detail,
        }
        _write_json(JOURNAL_PATH, {"datasets": entries})
    except Exception as exc:                                 # noqa: BLE001
        print("heartbeat: could not record %s=%s: %r" % (dataset, outcome, exc),
              flush=True)


def check_status(dataset, now=None):
    """Journal entry for one dataset, shaped for health(), never None.

    `checked_overdue` is None — unknown, not healthy — for a dataset the
    journal has never heard of, which is every dataset until the first cycle
    after this shipped. A volume that predates the journal must not light up
    as forty-three faults on the first boot, and must not read as success
    either.
    """
    limit = check_max_age_hours()
    entry = journal().get(dataset)
    if not isinstance(entry, dict) or not entry.get("at"):
        return {"last_checked_at": None, "hours_since_checked": None,
                "last_check_outcome": None, "check_max_age_hours": limit,
                "checked_overdue": None}
    try:
        stamped = datetime.datetime.strptime(entry["at"], _FORMAT).replace(tzinfo=_UTC)
    except ValueError:
        return {"last_checked_at": entry.get("at"), "hours_since_checked": None,
                "last_check_outcome": entry.get("outcome"),
                "check_max_age_hours": limit, "checked_overdue": None}
    hours = ((now or _now()) - stamped).total_seconds() / 3600.0
    return {"last_checked_at": entry["at"],
            "hours_since_checked": round(hours, 2),
            "last_check_outcome": entry.get("outcome"),
            "last_check_detail": entry.get("detail"),
            "check_max_age_hours": limit,
            "checked_overdue": hours > limit}


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
