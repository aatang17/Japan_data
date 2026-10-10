# -*- coding: utf-8 -*-
"""Nightly copies of the data files off the server.

research_backup copies the research desk and the staff accounts. Nothing
copied the rest, and research_backup's own docstring says it "can be rebuilt
from its source" — which is not true of vintages. observatory.duckdb holds
every release we have kept; a release the source has since replaced cannot be
downloaded again, and vintage history is the moat (CLAUDE.md). So once a day,
from the refresher, this uploads to the object store the EDINET archive uses
(``EDINET_S3_*``), under ``plover-backups/data/``:

  daily/YYYY-MM-DD/<file>   observatory.duckdb, equity.duckdb, sec.duckdb and
                            workspace.db (reader accounts, Assistant state);
                            kept KEEP_DAILY days
  monthly/YYYY-MM/<file>    the first good night of each month, a copy made
                            in the store; kept KEEP_MONTHLY months
  raw/<file>                each archived source file, uploaded once — they
                            are immutable and named by their hash

The served DuckDB files are only ever replaced whole (os.replace, by
app/backfill.py), never written in place, so one open file read start to end
is a consistent copy even if a swap lands meanwhile. workspace.db is SQLite
and written by the server, so it is copied with SQLite's backup API first.
Every upload is checked against its size afterwards. The result goes to
data/data-backup-status.json and to Telegram, success and failure alike: a
backup nobody hears about is one nobody notices has stopped.
"""
import datetime
import hashlib
import json
import os
import sqlite3
import tempfile
import time

from . import db, research_backup

PREFIX = research_backup.PREFIX + "data/"
DUCKDB_FILES = ("observatory.duckdb", "equity.duckdb", "sec.duckdb")
KEEP_DAILY = 14
KEEP_MONTHLY = 12
STATUS_PATH = db.DATA_DIR / "data-backup-status.json"


def enabled():
    """OFFSITE_BACKUPS=0 turns this off, as it does research_backup's uploads:
    a rehearsal copy of production must never write over its backups."""
    return research_backup.offsite_enabled()


def expired_days(days, today, keep=KEEP_DAILY):
    """Daily folders (YYYY-MM-DD) older than the newest `keep` days."""
    cutoff = today - datetime.timedelta(days=keep - 1)
    out = []
    for d in days:
        try:
            if datetime.datetime.strptime(d, "%Y-%m-%d").date() < cutoff:
                out.append(d)
        except ValueError:
            continue
    return sorted(out)


def expired_months(months, today, keep=KEEP_MONTHLY):
    """Monthly folders (YYYY-MM) beyond the newest `keep` months."""
    valid = sorted(m for m in months if len(m) == 7 and m[4] == "-" and m.replace("-", "").isdigit())
    current = "%04d-%02d" % (today.year, today.month)
    valid = [m for m in valid if m <= current]
    return valid[:-keep] if len(valid) > keep else []


def _folders(client, bucket, prefix):
    out, token = set(), None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix, "Delimiter": "/"}
        if token:
            kw["ContinuationToken"] = token
        page = client.list_objects_v2(**kw)
        for p in page.get("CommonPrefixes", []):
            out.add(p["Prefix"][len(prefix):].rstrip("/"))
        if not page.get("IsTruncated"):
            return out
        token = page.get("NextContinuationToken")


def _keys(client, bucket, prefix):
    out, token = {}, None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        page = client.list_objects_v2(**kw)
        for obj in page.get("Contents", []):
            out[obj["Key"]] = obj["Size"]
        if not page.get("IsTruncated"):
            return out
        token = page.get("NextContinuationToken")


def _delete_prefix(client, bucket, prefix):
    for key in _keys(client, bucket, prefix):
        client.delete_object(Bucket=bucket, Key=key)


def _upload_open(client, bucket, path, key):
    """Upload one open file, hashing as it is read; check the stored size."""
    with open(str(path), "rb") as f:
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
        size = f.tell()
        f.seek(0)
        client.upload_fileobj(f, bucket, key, ExtraArgs={"Metadata": {"sha256": h.hexdigest()}})
    stored = client.head_object(Bucket=bucket, Key=key)["ContentLength"]
    if stored != size:
        raise IOError("%s: stored %d bytes of %d" % (key, stored, size))
    return {"bytes": size, "sha256": h.hexdigest()}


def run(now=None):
    """One backup. Returns the status it recorded; never raises."""
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    started = time.time()
    status = {"last_run": now.replace(microsecond=0).isoformat() + "Z", "ok": False,
              "files": {}, "raw_uploaded": 0, "pruned": [], "error": None}
    if not enabled():
        status["error"] = "off (OFFSITE_BACKUPS=0)"
        return status
    try:
        client, bucket = research_backup._s3()
        if client is None:
            raise RuntimeError("object store not configured (EDINET_S3_*)")
        day = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")
        daily = PREFIX + "daily/%s/" % day
        for name in DUCKDB_FILES:
            path = db.DATA_DIR / name
            if path.exists():
                status["files"][name] = _upload_open(client, bucket, path, daily + name)
        workspace = db.DATA_DIR / "workspace.db"
        if workspace.exists():
            with tempfile.TemporaryDirectory(dir=str(db.DATA_DIR)) as tmp:
                copy = os.path.join(tmp, "workspace.db")
                src, dst = sqlite3.connect(str(workspace)), sqlite3.connect(copy)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                status["files"]["workspace.db"] = _upload_open(client, bucket, copy, daily + "workspace.db")
        # the first good night of a month is that month's copy
        if month not in _folders(client, bucket, PREFIX + "monthly/"):
            for name in status["files"]:
                client.copy_object(Bucket=bucket, Key=PREFIX + "monthly/%s/%s" % (month, name),
                                   CopySource={"Bucket": bucket, "Key": daily + name})
            status["monthly"] = month
        raw_dir = db.DATA_DIR / "raw"
        if raw_dir.exists():
            have = _keys(client, bucket, PREFIX + "raw/")
            for f in sorted(raw_dir.iterdir()):
                key = PREFIX + "raw/" + f.name
                if f.is_file() and have.get(key) != f.stat().st_size:
                    _upload_open(client, bucket, f, key)
                    status["raw_uploaded"] += 1
        today = now.date()
        for d in expired_days(_folders(client, bucket, PREFIX + "daily/"), today):
            _delete_prefix(client, bucket, PREFIX + "daily/%s/" % d)
            status["pruned"].append("daily/" + d)
        for m in expired_months(_folders(client, bucket, PREFIX + "monthly/"), today):
            _delete_prefix(client, bucket, PREFIX + "monthly/%s/" % m)
            status["pruned"].append("monthly/" + m)
        status["ok"] = True
    except Exception as exc:  # noqa: BLE001 — a backup never takes anything down
        status["error"] = "%s: %s" % (type(exc).__name__, exc)
    status["seconds"] = round(time.time() - started, 1)
    try:
        tmp = STATUS_PATH.with_name(STATUS_PATH.name + ".tmp")
        tmp.write_text(json.dumps(status, indent=1))
        os.replace(str(tmp), str(STATUS_PATH))
    except OSError:
        pass
    _tell(status)
    return status


def _tell(status):
    from . import refresh
    if status["ok"]:
        size = sum(f["bytes"] for f in status["files"].values()) / 1e9
        text = ("Data backup done: %d files, %.1f GB, %d new source files, %.0f s."
                % (len(status["files"]), size, status["raw_uploaded"], status.get("seconds", 0)))
    else:
        text = "ATTENTION data backup failed: %s" % status["error"]
    print("data backup: " + text, flush=True)
    refresh._send_telegram(text)


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
