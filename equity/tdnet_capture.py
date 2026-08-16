# -*- coding: utf-8 -*-
"""M2b — TDnet daily capture (the fast tape's archive).

TDnet (適時開示情報閲覧サービス) is the TSE's timely-disclosure wire: earnings
releases (決算短信) with XBRL, management forecast revisions, buyback and
dividend resolutions, deal announcements. Public retention is ~31 days —
there is no backfill beyond that, ever. This job banks each day's disclosures
before they vanish: the daily list pages (raw HTML + parsed JSON) and every
document (PDF, plus the XBRL zip where offered).

No API exists; this parses the public list pages. If TSE redesigns them the
parser needs a small repair — the daily-run summary makes that loud, not
silent. Capture != parse: nothing is interpreted here.

Usage:
    python tdnet_capture.py                 # trailing 7 days through today
    python tdnet_capture.py --days 31       # rescue the full retention window

Same discipline as capture.py (EDINET): idempotent via manifest, fail-safe,
atomic writes, SHA-256 per file, polite throttle, local or S3 storage
(EDINET_S3_* env; objects under the tdnet/ prefix). Python 3.9; stdlib only
in local mode, boto3 (lazy) in S3 mode.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import heartbeat

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("TDNET_ARCHIVE_ROOT", os.path.join(HERE, "data", "raw", "tdnet"))
S3_PREFIX = "tdnet"
BASE = "https://www.release.tdnet.info/inbs/"
LIST_URL = BASE + "I_list_{page:03d}_{ymd}.html"

THROTTLE_SECONDS = 0.5
RETRIES = 3
TIMEOUT = 60
MAX_PAGES = 40                     # hard stop; heaviest observed days are ~10


def fetch(url, attempts=RETRIES):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "observatory-capture/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError("404: not found")   # expected end-of-list; no retry
            last = e
            time.sleep(2 ** i)
        except Exception as e:
            last = e
            time.sleep(2 ** i)
    raise RuntimeError("fetch failed after %d attempts: %s" % (attempts, last))


# ---- list page parsing -----------------------------------------------------
TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
TIME = re.compile(r">(\d{1,2}:\d{2})<")
CODE = re.compile(r">(\d{4,5})<")
PDF = re.compile(r'href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.S)
ZIP = re.compile(r'href="([^"]+\.zip)"')
TAGS = re.compile(r"<[^>]+>")


def parse_list(html):
    rows = []
    for tr in TR.findall(html):
        pdf = PDF.search(tr)
        if not pdf:
            continue
        t = TIME.search(tr)
        c = CODE.search(tr)
        z = ZIP.search(tr)
        title = TAGS.sub("", pdf.group(2))
        title = re.sub(r"\s+", " ", title).strip()
        rows.append({
            "time": t.group(1) if t else None,
            "sec_code": c.group(1) if c else None,
            "title": title,
            "pdf": pdf.group(1).rsplit("/", 1)[-1],
            "xbrl": z.group(1).rsplit("/", 1)[-1] if z else None,
        })
    return rows


# ---- storage (tdnet/ prefix; mirrors capture.py's two backends) ------------
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
                    done.add(rec["file"])
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

    def acquire_lock(self):
        lock = os.path.join(ROOT, ".lock")
        if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 6 * 3600:
            sys.exit("another tdnet capture appears to be running")
        open(lock, "w").write(str(os.getpid()))

    def release_lock(self):
        try:
            os.remove(os.path.join(ROOT, ".lock"))
        except OSError:
            pass


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
                    done.add(name[:-5])
            if not resp.get("IsTruncated"):
                return done
            token = resp.get("NextContinuationToken")

    def put(self, rel_key, blob):
        self.c.put_object(Bucket=self.bucket, Key=S3_PREFIX + "/" + rel_key, Body=blob)

    def record(self, rec):
        if rec.get("status") != "ok":
            return
        self.c.put_object(Bucket=self.bucket,
                          Key="%s/meta/%s.json" % (S3_PREFIX, rec["file"]),
                          Body=json.dumps(rec, ensure_ascii=False).encode("utf-8"))

    def acquire_lock(self):
        pass

    def release_lock(self):
        pass


def make_store():
    return S3Store() if os.environ.get("EDINET_S3_BUCKET") else LocalStore()


# ---- capture ---------------------------------------------------------------
def capture_day(date, store, archived, stats):
    day = date.isoformat()
    ymd = date.strftime("%Y%m%d")
    all_rows, page = [], 1
    while page <= MAX_PAGES:
        try:
            html = fetch(LIST_URL.format(page=page, ymd=ymd)).decode("utf-8", "replace")
        except Exception as e:
            # past the last page TDnet 404s — that is the normal end-of-list
            # signal on multi-page days; only a failing FIRST page is an error
            if "404" in str(e) and page > 1:
                break
            stats["list_fail"] += 1
            print("  %s list p%03d failed: %s" % (day, page, e))
            return
        rows = parse_list(html)
        if not rows:
            break
        store.put("lists/raw/%s_p%03d.html" % (day, page), html.encode("utf-8"))
        all_rows += rows
        page += 1
        time.sleep(THROTTLE_SECONDS)
    if not all_rows:
        return                                   # weekend / holiday
    store.put("lists/%s.json" % day,
              json.dumps(all_rows, ensure_ascii=False).encode("utf-8"))

    for r in all_rows:
        targets = [(r["pdf"], b"%PDF")]
        if r["xbrl"]:
            targets.append((r["xbrl"], b"PK"))
        for fname, magic in targets:
            if fname in archived:
                stats["skipped"] += 1
                continue
            time.sleep(THROTTLE_SECONDS)
            try:
                blob = fetch(BASE + fname)
                if not blob.startswith(magic):
                    raise RuntimeError("bad magic (%d bytes)" % len(blob))
                store.put("docs/%s/%s" % (day, fname), blob)
                store.record({"date": day, "file": fname,
                              "sec_code": r["sec_code"], "title": r["title"][:120],
                              "sha256": hashlib.sha256(blob).hexdigest(),
                              "bytes": len(blob), "status": "ok",
                              "captured_at": dt.datetime.now(dt.timezone.utc).isoformat()})
                archived.add(fname)
                stats["ok"] += 1
            except Exception as e:
                store.record({"date": day, "file": fname, "status": "fail",
                              "error": str(e)[:200],
                              "captured_at": dt.datetime.now(dt.timezone.utc).isoformat()})
                stats["fail"] += 1
                print("  %s %s FAILED: %s" % (day, fname, e))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--start")
    p.add_argument("--end")
    args = p.parse_args()
    today = dt.date.today()
    if args.start:
        start = dt.date.fromisoformat(args.start)
        end = dt.date.fromisoformat(args.end) if args.end else today
    else:
        start, end = today - dt.timedelta(days=args.days - 1), today

    store = make_store()
    store.acquire_lock()
    try:
        archived = store.archived()
        print("store: %s | already archived: %d files" % (type(store).__name__, len(archived)))
        stats = {"ok": 0, "fail": 0, "skipped": 0, "list_fail": 0}
        d = start
        while d <= end:
            capture_day(d, store, archived, stats)   # TDnet lists exist for
            d += dt.timedelta(days=1)                # weekends too (empty)
        summary = ("tdnet %s..%s  archived:%d  skipped:%d  failed:%d  list-failures:%d"
                   % (start, end, stats["ok"], stats["skipped"], stats["fail"], stats["list_fail"]))
        print(summary)
        heartbeat.ping(summary, failed=stats["list_fail"] > 0)
    finally:
        store.release_lock()


if __name__ == "__main__":
    main()
