# -*- coding: utf-8 -*-
"""BOJ snapshot capture — the vintage archive for Bank of Japan statistics.

Unlike EDINET/TDnet, the BOJ API never deletes: full history is always
served. What is NOT recoverable later is what the data looked like BEFORE a
revision — money stock, Flow of Funds and Tankan revise heavily. This job
takes a dated, complete snapshot of every relevant database (metadata + every
series' full history) so revisions become an archive instead of an
overwrite. Run monthly: each run is one vintage.

Mechanics (verified empirically 2026-08-10):
  - any request is capped at <1,250 series -> we walk each DB's own metadata
    catalog and fetch series in batches via /getDataCode (same frequency per
    request), full history, JSON.
  - obligations: notify BOJ RSD on service release; display the BOJ credit
    line wherever this data is served. No redistribution restriction.

Storage: boj/{snapshot-date}/{db}/metadata.json + data_{freq}_b{NNN}.json,
same manifest/SHA-256 discipline, local (data/raw/boj/) or S3 (EDINET_S3_*).
Python 3.9; stdlib in local mode, boto3 lazy in S3 mode.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import heartbeat

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("BOJ_ARCHIVE_ROOT", os.path.join(HERE, "data", "raw", "boj"))
S3_PREFIX = "boj"
API = "https://www.stat-search.boj.or.jp/api/v1"

# every database in the API's catalog (manual pp.8-9), Flow of Funds included
DBS = ["IR01", "IR02", "IR03", "IR04",
       "FM01", "FM02", "FM03", "FM04", "FM05", "FM06", "FM07", "FM08", "FM09",
       "PS01", "PS02",
       "MD01", "MD02", "MD03", "MD04", "MD05", "MD06", "MD07", "MD08", "MD09",
       "MD10", "MD11", "MD12", "MD13", "MD14",
       "LA01", "LA02", "LA03", "LA04", "LA05",
       "BS01", "BS02", "FF", "OB01", "OB02", "CO",
       "PR01", "PR02", "PR03", "PR04",
       "PF01", "PF02", "BP01", "DER", "BIS", "OT"]

BATCH = 200                       # series per data request (cap is 1,250; URLs stay short)
THROTTLE_SECONDS = 0.8
RETRIES = 3
TIMEOUT = 180


def fetch(url, attempts=RETRIES):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "observatory-capture/1.0",
                "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                blob = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    blob = gzip.decompress(blob)
                return blob
        except Exception as e:
            last = e
            time.sleep(2 ** i)
    raise RuntimeError("fetch failed after %d attempts: %s" % (attempts, last))


# ---- storage (boj/ prefix; mirrors tdnet_capture.py) -----------------------
class LocalStore(object):
    def __init__(self):
        os.makedirs(ROOT, exist_ok=True)
        self._manifest = os.path.join(ROOT, "manifest.jsonl")

    def archived(self):
        done = set()
        if os.path.exists(self._manifest):
            for line in open(self._manifest, encoding="utf-8"):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("status") == "ok":
                    done.add(rec["key"])
        return done

    def put(self, rel_key, blob):
        path = os.path.join(ROOT, rel_key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)

    def record(self, rec):
        with open(self._manifest, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class S3Store(object):
    def __init__(self):
        import boto3
        self.bucket = os.environ["EDINET_S3_BUCKET"]
        self.c = boto3.client(
            "s3",
            endpoint_url=os.environ["EDINET_S3_ENDPOINT"],
            aws_access_key_id=os.environ["EDINET_S3_KEY_ID"],
            aws_secret_access_key=os.environ["EDINET_S3_SECRET"],
            region_name=os.environ.get("EDINET_S3_REGION", "auto"))

    def archived(self):
        done, token = set(), None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": S3_PREFIX + "/meta/"}
            if token:
                kw["ContinuationToken"] = token
            resp = self.c.list_objects_v2(**kw)
            for o in resp.get("Contents") or []:
                name = o["Key"].rsplit("/", 1)[-1]
                if name.endswith(".json"):
                    done.add(name[:-5].replace("__", "/"))
            if not resp.get("IsTruncated"):
                return done
            token = resp.get("NextContinuationToken")

    def put(self, rel_key, blob):
        self.c.put_object(Bucket=self.bucket, Key=S3_PREFIX + "/" + rel_key, Body=blob)

    def record(self, rec):
        if rec.get("status") != "ok":
            return
        self.c.put_object(
            Bucket=self.bucket,
            Key="%s/meta/%s.json" % (S3_PREFIX, rec["key"].replace("/", "__")),
            Body=json.dumps(rec, ensure_ascii=False).encode("utf-8"))


def make_store():
    return S3Store() if os.environ.get("EDINET_S3_BUCKET") else LocalStore()


# ---- snapshot --------------------------------------------------------------
def save(store, archived, stats, key, blob, extra=None):
    if key in archived:
        stats["skipped"] += 1
        return False
    store.put(key, blob)
    rec = {"key": key, "sha256": hashlib.sha256(blob).hexdigest(),
           "bytes": len(blob), "status": "ok",
           "captured_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if extra:
        rec.update(extra)
    store.record(rec)
    archived.add(key)
    stats["ok"] += 1
    return True


def snapshot_db(db, snap, store, archived, stats):
    meta_key = "%s/%s/metadata.json" % (snap, db)
    try:
        time.sleep(THROTTLE_SECONDS)
        meta_blob = fetch("%s/getMetadata?format=json&lang=en&db=%s" % (API, db))
        meta = json.loads(meta_blob)
        if meta.get("STATUS") != 200:
            raise RuntimeError("metadata status %s: %s" % (meta.get("STATUS"), meta.get("MESSAGE")))
    except Exception as e:
        stats["db_fail"] += 1
        print("  %s metadata FAILED: %s" % (db, e))
        return
    save(store, archived, stats, meta_key, meta_blob, {"db": db})

    # group by the EXACT frequency label: /getDataCode only requires that one
    # request not mix frequencies, and weekly variants (W1 vs W4…) count as
    # different frequencies — coarse grouping 400s (learned live on IR02)
    by_freq = {}
    for row in meta.get("RESULTSET") or []:
        code = row.get("SERIES_CODE")
        label = (row.get("FREQUENCY") or "").strip()
        if not code or not label:
            continue
        by_freq.setdefault(label, []).append(code)

    import re as _re
    n_series = sum(len(v) for v in by_freq.values())
    for f, codes in sorted(by_freq.items()):
        slug = _re.sub(r"[^A-Za-z0-9]+", "", f)[:16] or "X"
        for b in range(0, len(codes), BATCH):
            batch = codes[b:b + BATCH]
            key = "%s/%s/data_%s_b%03d.json" % (snap, db, slug, b // BATCH)
            if key in archived:
                stats["skipped"] += 1
                continue
            time.sleep(THROTTLE_SECONDS)
            try:
                # some series codes literally end in '%' (YoY-change series) —
                # they must be URL-encoded or the request 400s
                quoted = ",".join(urllib.parse.quote(c, safe="") for c in batch)
                blob = fetch("%s/getDataCode?format=json&lang=en&db=%s&code=%s"
                             % (API, db, quoted))
                payload = json.loads(blob)
                if payload.get("STATUS") != 200:
                    raise RuntimeError("status %s: %s"
                                       % (payload.get("STATUS"), payload.get("MESSAGE")))
                save(store, archived, stats, key, blob,
                     {"db": db, "freq": f, "series": len(batch)})
            except Exception as e:
                stats["fail"] += 1
                print("  %s %s b%03d FAILED: %s" % (db, f, b // BATCH, e))
    print("  %s: %d series across %s" % (db, n_series, "/".join(sorted(by_freq))))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", help="snapshot id (default: today, YYYY-MM-DD)")
    p.add_argument("--dbs", help="comma list to limit (default: all)")
    # accepted and ignored: the shared container CMD defaults to "--days 7"
    p.add_argument("--days", type=int, help=argparse.SUPPRESS)
    args = p.parse_args()
    snap = args.snapshot or dt.date.today().isoformat()
    dbs = args.dbs.split(",") if args.dbs else DBS

    store = make_store()
    archived = store.archived()
    print("store: %s | snapshot: %s | already archived: %d objects"
          % (type(store).__name__, snap, len(archived)))
    stats = {"ok": 0, "fail": 0, "skipped": 0, "db_fail": 0, "freq_unmapped": 0}
    for db in dbs:
        snapshot_db(db, snap, store, archived, stats)
    summary = ("boj snapshot %s  archived:%d  skipped:%d  failed:%d  db-failures:%d  unmapped-freq:%d"
               % (snap, stats["ok"], stats["skipped"], stats["fail"],
                  stats["db_fail"], stats["freq_unmapped"]))
    print(summary)
    # monthly cadence, so any gap is worth being told about: a missed batch is
    # missing series in a vintage that can never be re-taken for this date
    heartbeat.ping(summary, failed=(stats["fail"] > 0 or stats["db_fail"] > 0))


if __name__ == "__main__":
    main()
