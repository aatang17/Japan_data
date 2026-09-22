# -*- coding: utf-8 -*-
"""Share-price history for a set of tickers — research use only, never served.

Why this is separate from everything else here: the only free source of
Japanese share-price history that answers a plain HTTP request is Yahoo
Finance's chart endpoint, and Yahoo's terms do not allow republishing what
it returns. So this writes to its own file (data/prices.duckdb), no API
reads it, no page shows it, and nothing in app/ imports it. It exists so a
research pull (a rate-sensitivity regression, a scatter of unrealised bond
losses against a year's share-price move) has prices to join to — on a
laptop, for the author's own use.

Stooq, the other free source, sits behind a JavaScript challenge (checked
2026-09-23). JPX sells its own index and price history; the TOPIX Banks
index is not captured here for that reason.

Usage
-----
  python price_capture.py --sec-codes 8331,7186,8354 --interval 1mo
  python price_capture.py --banks --interval 1wk        # every bank-industry filer with a code
"""
import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.request

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PRICES_DB_PATH", os.path.join(HERE, "..", "data", "prices.duckdb"))
EQUITY_DB = os.environ.get("EQUITY_DB_PATH", os.path.join(HERE, "..", "data", "equity.duckdb"))
SOURCE = "Yahoo Finance chart API (research use only; not licensed for redistribution)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS px_prices (
    sec_code VARCHAR, symbol VARCHAR, interval VARCHAR, date DATE,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, adj_close DOUBLE, volume BIGINT,
    fetched_at TIMESTAMP, source VARCHAR,
    PRIMARY KEY (sec_code, interval, date));
"""


def fetch(symbol, interval, rng="max"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s&events=div,splits"
           % (symbol, rng, interval))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        doc = json.loads(resp.read().decode("utf-8"))
    res = (doc.get("chart") or {}).get("result") or []
    if not res:
        raise ValueError("no result for %s: %s" % (symbol, (doc.get("chart") or {}).get("error")))
    r = res[0]
    ts = r.get("timestamp") or []
    q = (r.get("indicators") or {}).get("quote", [{}])[0]
    adj = ((r.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or [None] * len(ts)
    rows = []
    for i, t in enumerate(ts):
        d = _dt.datetime.utcfromtimestamp(t).date()
        rows.append((d, q.get("open", [None])[i], q.get("high", [None])[i], q.get("low", [None])[i],
                     q.get("close", [None])[i], adj[i], q.get("volume", [None])[i]))
    return rows


def bank_codes():
    con = duckdb.connect(EQUITY_DB, read_only=True)
    try:
        return [r[0][:4] for r in con.execute(
            "SELECT DISTINCT sec_code FROM eq_entities WHERE industry = '銀行業' "
            "AND sec_code IS NOT NULL ORDER BY 1").fetchall()]
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec-codes", help="comma-separated four-digit codes")
    ap.add_argument("--banks", action="store_true", help="every bank-industry filer with a code")
    ap.add_argument("--interval", default="1mo", choices=("1d", "1wk", "1mo"))
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()
    codes = [c.strip() for c in (args.sec_codes or "").split(",") if c.strip()]
    if args.banks:
        codes += bank_codes()
    codes = sorted(set(codes))
    if not codes:
        raise SystemExit("nothing to fetch: pass --sec-codes or --banks")
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    con = duckdb.connect(args.db)
    con.execute(SCHEMA)
    now = _dt.datetime.utcnow().replace(microsecond=0)
    ok = 0
    for code in codes:
        symbol = code + ".T"
        try:
            rows = fetch(symbol, args.interval)
        except Exception as e:                                    # noqa: BLE001
            print("  %s: %s" % (symbol, str(e)[:100]))
            continue
        con.execute("DELETE FROM px_prices WHERE sec_code = ? AND interval = ?", [code, args.interval])
        con.executemany(
            "INSERT INTO px_prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(code, symbol, args.interval, d, o, h, lo, c, a, v, now, SOURCE)
             for d, o, h, lo, c, a, v in rows if c is not None])
        ok += 1
        print("  %s: %d rows, %s – %s" % (symbol, len(rows), rows[0][0] if rows else None,
                                          rows[-1][0] if rows else None))
        time.sleep(0.5)
    con.close()
    print("fetched %d of %d symbols into %s" % (ok, len(codes), args.db))


if __name__ == "__main__":
    main()
