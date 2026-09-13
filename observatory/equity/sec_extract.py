# -*- coding: utf-8 -*-
"""US financial statements from SEC filings — the queryable shelf.

Why this reads the SEC's data sets and not the filings themselves
-----------------------------------------------------------------
Every 10-K, 10-Q, 20-F and 40-F on EDGAR carries an XBRL instance, and the
SEC's own Division of Economic and Risk Analysis already extracts every one
of them into four flat tables, republished each quarter as the *Financial
Statement Data Sets*: `sub` (one row per filing), `num` (every numeric fact:
tag, date, span, unit, value), `pre` (which facts sit on which primary
statement, in the filer's own order with the filer's own label) and `tag`
(the taxonomy: standard label, definition, instant-or-duration, debit-or-
credit). That is the SEC's parse of the SEC's filings, complete since
2009 Q1, and us_capture.py already banks every quarterly zip on our shelf
(us/{date}/sec/fsds_YYYYqQ.zip). Parsing the 10MB submission text files
ourselves would only reproduce those tables less reliably, so this
extractor loads them instead — DuckDB reads a 600MB quarter straight from
the tab files in seconds — and keeps them in exactly the shape the EDINET
financials already have: filings, long facts, statement lines, elements.

Tables (data/sec.duckdb — its own file, not equity.duckdb, because a quarter
is ~35MB compressed and the equity file ships inside the image as a seed):
    sec_quarters   one row per data-set vintage loaded: the zip's SHA-256,
                   when it was captured and loaded, counts, status
    sec_filings    every `sub` row: cik, name, form, period, fiscal year and
                   quarter, filed and accepted dates, the amendment flag —
                   plus this extractor's balance-sheet verdict
    sec_facts      every `num` row for the periodic reports (10-K, 10-Q,
                   20-F, 40-F and their amendments): tag, taxonomy version,
                   period end, span in quarters, unit, dimensional segments,
                   co-registrant, value, footnote. Nothing recomputed,
                   nothing rescaled; a value the SEC did not carry is absent.
    sec_lines      every `pre` row for those reports: statement (BS, IS, CF,
                   CI, EQ, UN), report and line order, the filer's label,
                   parenthetical and negating flags
    sec_tags       the taxonomy rows, merged across quarters
    sec_segments   the dimensional qualifiers (`EquityComponents=CommonStock;`)
                   once each; a fact with none is the consolidated, whole-
                   entity figure

Gate
----
The identity every balance sheet has to satisfy — assets equal liabilities
plus equity — checked per filing on its own period end, from the facts as
loaded (Assets against LiabilitiesAndStockholdersEquity, or Liabilities plus
StockholdersEquity). A filing that tags the totals and misses by more than
one basis point of assets is `partial` with the gap; one that tags no totals
(a holding company reporting a single line, a fund) is `partial` with that
reason, so a cross-section never silently includes a company whose numbers
were never checked. A filing whose form is outside the periodic set keeps
its `sub` row and no facts, status `skipped`.

Vintages
--------
The unit of ingest is one quarterly zip. It is loaded once, recorded with its
SHA-256, and reloaded only when the SEC republishes it with different bytes
(they do, occasionally, to fix a filing) or when this parser's version
changes. Loading is all-or-nothing per quarter: the new rows are staged and
validated first, and the old rows are replaced inside one transaction, so a
bad file leaves the previous load live and says why in sec_quarters.

Usage (from observatory/equity/):
    ../.venv/bin/python sec_extract.py                       # newest 4 quarters on the shelf
    ../.venv/bin/python sec_extract.py --quarters 2026q1,2026q2
    ../.venv/bin/python sec_extract.py --all                 # every quarter since 2009
    ../.venv/bin/python sec_extract.py --deepen 2            # two more older quarters
    ../.venv/bin/python sec_extract.py --source s3 --last 4  # nightly, against the bucket

Python 3.9; stdlib + duckdb, boto3 (lazy) in S3 mode.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SEC_DB_PATH",
                         os.path.join(HERE, "..", "data", "sec.duckdb"))
LOCAL_ROOT = os.environ.get("US_ARCHIVE_ROOT",
                            os.path.join(HERE, "..", "..", "equity", "data", "raw", "us"))
S3_PREFIX = "us"
POINTER_PREFIX = "latest/sec__fsds_"

PARSER_VERSION = "sec-1"
EXTRACTOR = "sec-financials"
DEFAULT_LAST = int(os.environ.get("SEC_QUARTERS", "4"))

# The periodic reports whose facts and statement lines are kept. Everything
# else in the data set (8-K earnings exhibits, S-1s, 11-K plan reports) keeps
# its filing row only.
CORE_FORMS = ("10-K", "10-K/A", "10-KT", "10-KT/A", "10-Q", "10-Q/A", "10-QT",
              "10-QT/A", "20-F", "20-F/A", "40-F", "40-F/A")

# The columns each member must carry, in the SEC's order. A file that has
# lost or renamed one is refused, not guessed at.
MEMBERS = {
    "sub": ["adsh", "cik", "name", "sic", "countryba", "stprba", "cityba", "zipba",
            "bas1", "bas2", "baph", "countryma", "stprma", "cityma", "zipma", "mas1",
            "mas2", "countryinc", "stprinc", "ein", "former", "changed", "afs", "wksi",
            "fye", "form", "period", "fy", "fp", "filed", "accepted", "prevrpt",
            "detail", "instance", "nciks", "aciks"],
    "num": ["adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg",
            "value", "footnote"],
    "pre": ["adsh", "report", "line", "stmt", "inpth", "rfile", "tag", "version",
            "plabel", "negating"],
    "tag": ["tag", "version", "custom", "abstract", "datatype", "iord", "crdr",
            "tlabel", "doc"],
}

# Balance-sheet identity: (assets, [liabilities-and-equity]) or
# (assets, [liabilities, equity]). Tried in order.
BS_IDENTITIES = [
    ("Assets", ["LiabilitiesAndStockholdersEquity"]),
    ("Assets", ["Liabilities",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
    ("Assets", ["Liabilities", "StockholdersEquity"]),
]
BS_TOLERANCE = 1e-4
BS_TAGS = sorted({t for a, rhs in BS_IDENTITIES for t in [a] + rhs})

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sec_quarters (
    quarter VARCHAR PRIMARY KEY, key VARCHAR, sha256 VARCHAR, content_hash VARCHAR,
    captured_at TIMESTAMP, loaded_at TIMESTAMP, parser_version VARCHAR,
    filings INTEGER, facts BIGINT, lines BIGINT, rejected_rows INTEGER,
    status VARCHAR, detail VARCHAR);
CREATE TABLE IF NOT EXISTS sec_filings (
    adsh VARCHAR PRIMARY KEY, quarter VARCHAR, cik BIGINT, name VARCHAR,
    sic INTEGER, country_ba VARCHAR, state_ba VARCHAR, city_ba VARCHAR,
    country_inc VARCHAR, state_inc VARCHAR, ein VARCHAR, former_name VARCHAR,
    name_changed DATE, filer_status VARCHAR, wksi BOOLEAN, fye VARCHAR,
    form VARCHAR, period DATE, fy INTEGER, fp VARCHAR, filed DATE,
    accepted TIMESTAMP, prevrpt BOOLEAN, detail BOOLEAN, instance VARCHAR,
    nciks INTEGER, aciks VARCHAR,
    status VARCHAR, note VARCHAR, bs_check VARCHAR, total_assets DOUBLE,
    facts INTEGER);
CREATE TABLE IF NOT EXISTS sec_facts (
    adsh VARCHAR, quarter VARCHAR, tag VARCHAR, version VARCHAR, ddate DATE,
    qtrs INTEGER, uom VARCHAR, segment_id INTEGER, coreg VARCHAR, value DOUBLE,
    footnote VARCHAR);
CREATE SEQUENCE IF NOT EXISTS sec_segment_seq;
CREATE TABLE IF NOT EXISTS sec_segments (
    segment_id INTEGER PRIMARY KEY, segments VARCHAR);
CREATE TABLE IF NOT EXISTS sec_lines (
    adsh VARCHAR, quarter VARCHAR, report INTEGER, line INTEGER, stmt VARCHAR,
    inpth BOOLEAN, rfile VARCHAR, tag VARCHAR, version VARCHAR, plabel VARCHAR,
    negating BOOLEAN);
CREATE TABLE IF NOT EXISTS sec_tags (
    tag VARCHAR, version VARCHAR, custom BOOLEAN, abstract BOOLEAN,
    datatype VARCHAR, iord VARCHAR, crdr VARCHAR, tlabel VARCHAR, doc VARCHAR,
    PRIMARY KEY (tag, version));
"""
# No secondary indexes: the fact and line tables are written in accession
# order, so DuckDB's per-row-group min/max prunes an adsh lookup to a block or
# two on its own (about 1ms on two quarters), while ART indexes on the same
# rows doubled the file. The dimensional `segments` strings — 40% of the
# facts, and by far the widest column — live once each in sec_segments.

QUARTER_RE = re.compile(r"fsds_(\d{4})q([1-4])\.zip")


def quarter_key(q):
    """'2026q2' -> (2026, 2), for sorting."""
    return int(q[:4]), int(q[5])


def quarter_of(filename):
    m = QUARTER_RE.search(filename)
    return "%sq%s" % (m.group(1), m.group(2)) if m else None


# ---- sources ---------------------------------------------------------------
class LocalSource(object):
    """The laptop copy of the us/ shelf (us_capture.py's LocalStore layout)."""

    name = "local"

    def __init__(self, root=LOCAL_ROOT):
        self.root = os.path.abspath(root)

    def pointers(self):
        out = {}
        for p in glob.glob(os.path.join(self.root, POINTER_PREFIX + "*.json")):
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
            q = quarter_of(rec.get("file", ""))
            if q and rec.get("status", "ok") == "ok":
                out[q] = rec
        return out

    def fetch(self, rec, dest):
        key = rec["key"]
        rel = key[len(S3_PREFIX) + 1:] if key.startswith(S3_PREFIX + "/") else key
        shutil.copyfile(os.path.join(self.root, rel), dest)


class S3Source(object):
    """The bucket the capture job writes to — same variables as capture.py."""

    name = "s3"

    def __init__(self):
        import boto3
        from botocore.config import Config
        self.bucket = os.environ["EDINET_S3_BUCKET"]
        self.c = boto3.client(
            "s3",
            endpoint_url=os.environ["EDINET_S3_ENDPOINT"],
            aws_access_key_id=os.environ["EDINET_S3_KEY_ID"],
            aws_secret_access_key=os.environ["EDINET_S3_SECRET"],
            region_name=os.environ.get("EDINET_S3_REGION", "auto"),
            config=Config(retries={"max_attempts": 5, "mode": "standard"}))

    def pointers(self):
        out = {}
        token = None
        prefix = S3_PREFIX + "/" + POINTER_PREFIX
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self.c.list_objects_v2(**kw)
            for o in r.get("Contents", []):
                body = self.c.get_object(Bucket=self.bucket, Key=o["Key"])["Body"].read()
                rec = json.loads(body)
                q = quarter_of(rec.get("file", ""))
                if q and rec.get("status", "ok") == "ok":
                    out[q] = rec
            if not r.get("IsTruncated"):
                return out
            token = r.get("NextContinuationToken")

    def fetch(self, rec, dest):
        self.c.download_file(self.bucket, rec["key"], dest)


# ---- one quarter -----------------------------------------------------------
class QuarterError(Exception):
    pass


def unpack(zip_path, workdir):
    """Extract the four members; refuse a zip missing any of them."""
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for m in MEMBERS:
            if m + ".txt" not in names:
                raise QuarterError("zip has no %s.txt (members: %s)"
                                   % (m, ", ".join(sorted(names))))
        for m in MEMBERS:
            z.extract(m + ".txt", workdir)
    return {m: os.path.join(workdir, m + ".txt") for m in MEMBERS}


def check_header(path, expected):
    with open(path, encoding="utf-8", errors="replace") as f:
        cols = f.readline().rstrip("\r\n").split("\t")
    missing = [c for c in expected if c not in cols]
    if missing:
        raise QuarterError("%s is missing columns %s" % (os.path.basename(path), missing))


def stage(con, paths):
    """Read the four tab files into typed temp tables; return the reject count.

    The files are tab-delimited and the SEC quotes the odd field that carries
    a tab or newline (a segment label naming an investee, say), so the reader
    honours double quotes. A row it still cannot parse is skipped and
    counted, never guessed at: the count is recorded on the quarter and a
    quarter with any is `partial`.
    """
    for m, path in paths.items():
        check_header(path, MEMBERS[m])
        con.execute(
            "CREATE OR REPLACE TEMP TABLE raw_%s AS SELECT * FROM read_csv(?, "
            "delim='\t', header=true, quote='\"', escape='\"', all_varchar=true, "
            "encoding='utf-8', null_padding=true, ignore_errors=true, "
            "store_rejects=true)" % m, [path])
    try:
        rejected = con.execute("SELECT count(*) FROM reject_errors").fetchone()[0]
    except duckdb.Error:                     # nothing was rejected, so no table
        rejected = 0

    con.execute("""
        CREATE OR REPLACE TEMP TABLE st_sub AS
        SELECT adsh, TRY_CAST(cik AS BIGINT) AS cik, name, TRY_CAST(sic AS INTEGER) AS sic,
               NULLIF(countryba,'') AS country_ba, NULLIF(stprba,'') AS state_ba,
               NULLIF(cityba,'') AS city_ba, NULLIF(countryinc,'') AS country_inc,
               NULLIF(stprinc,'') AS state_inc, NULLIF(ein,'') AS ein,
               NULLIF(former,'') AS former_name,
               TRY_CAST(try_strptime(NULLIF(changed,''), '%Y%m%d') AS DATE) AS name_changed,
               NULLIF(afs,'') AS filer_status, TRY_CAST(wksi AS INTEGER) = 1 AS wksi,
               NULLIF(fye,'') AS fye, form,
               TRY_CAST(try_strptime(NULLIF(period,''), '%Y%m%d') AS DATE) AS period,
               TRY_CAST(fy AS INTEGER) AS fy, NULLIF(fp,'') AS fp,
               TRY_CAST(try_strptime(NULLIF(filed,''), '%Y%m%d') AS DATE) AS filed,
               TRY_CAST(accepted AS TIMESTAMP) AS accepted,
               TRY_CAST(prevrpt AS INTEGER) = 1 AS prevrpt,
               TRY_CAST(detail AS INTEGER) = 1 AS detail,
               NULLIF(instance,'') AS instance, TRY_CAST(nciks AS INTEGER) AS nciks,
               NULLIF(aciks,'') AS aciks
        FROM raw_sub WHERE adsh IS NOT NULL AND adsh <> ''""")
    con.execute("""
        CREATE OR REPLACE TEMP TABLE st_num AS
        SELECT n.adsh, n.tag, n.version,
               TRY_CAST(try_strptime(NULLIF(n.ddate,''), '%%Y%%m%%d') AS DATE) AS ddate,
               TRY_CAST(n.qtrs AS INTEGER) AS qtrs, NULLIF(n.uom,'') AS uom,
               NULLIF(n.segments,'') AS segments, NULLIF(n.coreg,'') AS coreg,
               TRY_CAST(n.value AS DOUBLE) AS value, NULLIF(n.footnote,'') AS footnote,
               (n.value IS NULL OR n.value = '') AS nil
        FROM raw_num n JOIN st_sub s USING (adsh)
        WHERE s.form IN (%s) AND n.tag IS NOT NULL""" % ",".join("?" * len(CORE_FORMS)),
        list(CORE_FORMS))
    con.execute("""
        CREATE OR REPLACE TEMP TABLE st_pre AS
        SELECT p.adsh, TRY_CAST(p.report AS INTEGER) AS report,
               TRY_CAST(p.line AS INTEGER) AS line, NULLIF(p.stmt,'') AS stmt,
               TRY_CAST(p.inpth AS INTEGER) = 1 AS inpth, NULLIF(p.rfile,'') AS rfile,
               p.tag, p.version, NULLIF(p.plabel,'') AS plabel,
               TRY_CAST(p.negating AS INTEGER) = 1 AS negating
        FROM raw_pre p JOIN st_sub s USING (adsh)
        WHERE s.form IN (%s) AND p.tag IS NOT NULL""" % ",".join("?" * len(CORE_FORMS)),
        list(CORE_FORMS))
    con.execute("""
        CREATE OR REPLACE TEMP TABLE st_tag AS
        SELECT tag, version, TRY_CAST(custom AS INTEGER) = 1 AS custom,
               TRY_CAST(abstract AS INTEGER) = 1 AS abstract, NULLIF(datatype,'') AS datatype,
               NULLIF(iord,'') AS iord, NULLIF(crdr,'') AS crdr, NULLIF(tlabel,'') AS tlabel,
               NULLIF(doc,'') AS doc
        FROM raw_tag WHERE tag IS NOT NULL AND version IS NOT NULL""")
    return rejected


def validate_staged(con):
    """The checks a quarter must pass before it can replace the one it
    supersedes. Structural only — the per-filing balance check is a verdict
    on each filing, not a reason to refuse the file."""
    n_sub = con.execute("SELECT count(*) FROM st_sub").fetchone()[0]
    if n_sub == 0:
        raise QuarterError("sub.txt has no filings")
    dup = con.execute("SELECT count(*) - count(DISTINCT adsh) FROM st_sub").fetchone()[0]
    if dup:
        raise QuarterError("sub.txt repeats %d accession numbers" % dup)
    bad_dates = con.execute(
        "SELECT count(*) FROM st_sub WHERE filed IS NULL OR period IS NULL").fetchone()[0]
    if bad_dates > n_sub * 0.05:
        raise QuarterError("%d of %d filings have an unreadable filed/period date"
                           % (bad_dates, n_sub))
    n_num = con.execute("SELECT count(*) FROM st_num").fetchone()[0]
    n_core = con.execute("SELECT count(*) FROM st_sub WHERE form IN (%s)"
                         % ",".join("?" * len(CORE_FORMS)), list(CORE_FORMS)).fetchone()[0]
    if n_core and n_num == 0:
        raise QuarterError("num.txt carries no facts for %d periodic reports" % n_core)
    # A nil fact (the filer tagged a dash) has no value and is dropped as
    # missing — about 5% of rows in a normal quarter. What must be rare is a
    # value that is there and cannot be read.
    bad_vals = con.execute(
        "SELECT count(*) FROM st_num WHERE (value IS NULL AND NOT nil) OR ddate IS NULL"
    ).fetchone()[0]
    if n_num and bad_vals > n_num * 0.001:
        raise QuarterError("%d of %d facts have an unreadable value or date"
                           % (bad_vals, n_num))


def balance_verdicts(con):
    """Stage sec_filings' verdict columns: {adsh: (status, note, bs_check,
    total_assets, facts)} for every staged filing."""
    con.execute("""
        CREATE OR REPLACE TEMP TABLE st_bs AS
        SELECT n.adsh, n.tag, any_value(n.value) AS value
        FROM st_num n JOIN st_sub s USING (adsh)
        WHERE n.ddate = s.period AND n.qtrs = 0 AND n.segments IS NULL
          AND n.coreg IS NULL AND n.value IS NOT NULL AND n.tag IN (%s)
        GROUP BY n.adsh, n.tag""" % ",".join("?" * len(BS_TAGS)), list(BS_TAGS))
    totals = {}
    for adsh, tag, value in con.execute("SELECT adsh, tag, value FROM st_bs").fetchall():
        totals.setdefault(adsh, {})[tag] = value
    counts = dict(con.execute("SELECT adsh, count(*) FROM st_num GROUP BY adsh").fetchall())
    core = set(CORE_FORMS)
    out = {}
    for adsh, form in con.execute("SELECT adsh, form FROM st_sub").fetchall():
        if form not in core:
            out[adsh] = ("skipped", "form outside the periodic set; filing row only",
                         None, None, 0)
            continue
        t = totals.get(adsh, {})
        assets = t.get("Assets")
        verdict = None
        for a_tag, rhs in BS_IDENTITIES:
            if a_tag in t and all(r in t for r in rhs):
                gap = abs(t[a_tag] - sum(t[r] for r in rhs))
                if gap <= BS_TOLERANCE * abs(t[a_tag]):
                    verdict = "ok"
                else:
                    verdict = "off by %.0f" % gap
                break
        problems = []
        n = counts.get(adsh, 0)
        if n == 0:
            problems.append("no numeric facts")
        if verdict is None:
            problems.append("no balance-sheet totals tagged at the period end")
        elif verdict != "ok":
            problems.append("balance sheet %s" % verdict)
        status = "partial" if problems else "clean"
        out[adsh] = (status, "; ".join(problems) or None, verdict, assets, n)
    return out


def load_quarter(con, quarter, rec, src, workdir):
    """Stage, validate and publish one quarter. Raises QuarterError (or
    anything the reader raises) with the previous load untouched."""
    zip_path = os.path.join(workdir, "fsds.zip")
    t0 = time.time()
    src.fetch(rec, zip_path)
    paths = unpack(zip_path, workdir)
    rejected = stage(con, paths)
    validate_staged(con)
    verdicts = balance_verdicts(con)
    con.execute("CREATE OR REPLACE TEMP TABLE st_verdict (adsh VARCHAR, status VARCHAR, "
                "note VARCHAR, bs_check VARCHAR, total_assets DOUBLE, facts INTEGER)")
    con.executemany("INSERT INTO st_verdict VALUES (?,?,?,?,?,?)",
                    [(k,) + v for k, v in verdicts.items()])

    con.execute("BEGIN TRANSACTION")
    try:
        for t in ("sec_filings", "sec_facts", "sec_lines"):
            con.execute("DELETE FROM %s WHERE quarter = ?" % t, [quarter])
        # A filing re-published in a later quarter's set (it happens when the
        # SEC re-runs a quarter) replaces its earlier row wholesale.
        con.execute("DELETE FROM sec_filings WHERE adsh IN (SELECT adsh FROM st_sub)")
        con.execute("DELETE FROM sec_facts WHERE adsh IN (SELECT adsh FROM st_sub)")
        con.execute("DELETE FROM sec_lines WHERE adsh IN (SELECT adsh FROM st_sub)")
        con.execute("""
            INSERT INTO sec_filings
            SELECT s.adsh, ? AS quarter, s.cik, s.name, s.sic, s.country_ba, s.state_ba,
                   s.city_ba, s.country_inc, s.state_inc, s.ein, s.former_name,
                   s.name_changed, s.filer_status, s.wksi, s.fye, s.form, s.period, s.fy,
                   s.fp, s.filed, s.accepted, s.prevrpt, s.detail, s.instance, s.nciks,
                   s.aciks, v.status, v.note, v.bs_check, v.total_assets, v.facts
            FROM st_sub s JOIN st_verdict v USING (adsh)""", [quarter])
        con.execute("""
            INSERT INTO sec_segments
            SELECT nextval('sec_segment_seq'), d.segments
            FROM (SELECT DISTINCT segments FROM st_num WHERE segments IS NOT NULL) d
            WHERE NOT EXISTS (SELECT 1 FROM sec_segments g WHERE g.segments = d.segments)""")
        con.execute("""
            INSERT INTO sec_facts
            SELECT n.adsh, ?, n.tag, n.version, n.ddate, n.qtrs, n.uom, g.segment_id,
                   n.coreg, n.value, n.footnote
            FROM st_num n LEFT JOIN sec_segments g ON g.segments = n.segments
            WHERE NOT n.nil AND n.value IS NOT NULL AND n.ddate IS NOT NULL
            ORDER BY n.adsh, n.tag, n.ddate""", [quarter])
        con.execute("""
            INSERT INTO sec_lines
            SELECT adsh, ?, report, line, stmt, inpth, rfile, tag, version, plabel, negating
            FROM st_pre ORDER BY adsh, report, line""", [quarter])
        con.execute("""
            INSERT INTO sec_tags
            SELECT t.* FROM st_tag t
            WHERE NOT EXISTS (SELECT 1 FROM sec_tags k
                              WHERE k.tag = t.tag AND k.version = t.version)""")
        n_f = con.execute("SELECT count(*) FROM st_sub").fetchone()[0]
        n_n = con.execute("SELECT count(*) FROM sec_facts WHERE quarter = ?", [quarter]).fetchone()[0]
        n_p = con.execute("SELECT count(*) FROM st_pre").fetchone()[0]
        status = "partial" if rejected else "ok"
        detail = ("%d rows the reader could not parse were skipped" % rejected
                  if rejected else None)
        con.execute("""
            INSERT OR REPLACE INTO sec_quarters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [quarter, rec.get("key"), rec.get("sha256"), rec.get("content_hash"),
             _ts(rec.get("captured_at")), dt.datetime.now(), PARSER_VERSION,
             n_f, n_n, n_p, rejected, status, detail])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    verdict_counts = {}
    for v in verdicts.values():
        verdict_counts[v[0]] = verdict_counts.get(v[0], 0) + 1
    print("  %s: %d filings (%s), %d facts, %d lines, %d rejected rows, %.0fs"
          % (quarter, n_f,
             ", ".join("%s %d" % (k, verdict_counts[k]) for k in sorted(verdict_counts)),
             n_n, n_p, rejected, time.time() - t0))
    sys.stdout.flush()
    for t in ("raw_sub", "raw_num", "raw_pre", "raw_tag", "st_sub", "st_num",
              "st_pre", "st_tag", "st_bs", "st_verdict"):
        con.execute("DROP TABLE IF EXISTS %s" % t)


def _ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def record_failure(con, quarter, rec, err):
    """Say why a quarter did not load, without touching its standing rows or
    the SHA of the load that is still live (so the next run retries)."""
    row = con.execute("SELECT sha256 FROM sec_quarters WHERE quarter = ?", [quarter]).fetchone()
    if row:
        con.execute("UPDATE sec_quarters SET status = 'failed', detail = ? WHERE quarter = ?",
                    [err[:400], quarter])
    else:
        con.execute("INSERT INTO sec_quarters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [quarter, rec.get("key"), None, None, _ts(rec.get("captured_at")),
                     dt.datetime.now(), PARSER_VERSION, None, None, None, None,
                     "failed", err[:400]])


# ---- selection -------------------------------------------------------------
def choose(avail, loaded, last, deepen, explicit, everything):
    """Which quarters to (re)load.

    `avail` quarter -> pointer record from the shelf; `loaded` quarter ->
    (sha256, parser_version, status) from the database. A loaded quarter is
    redone only when the shelf's bytes or this parser changed, or its last
    load failed. New quarters come newest-first, `last` of them; `deepen`
    adds that many older ones below the loaded floor.
    """
    order = sorted(avail, key=quarter_key, reverse=True)
    if explicit:
        return [q for q in order if q in explicit]
    changed = [q for q in order if q in loaded and (
        loaded[q][0] != avail[q].get("sha256") or loaded[q][1] != PARSER_VERSION
        or loaded[q][2] == "failed")]
    fresh = [q for q in order if q not in loaded]
    if everything:
        return changed + fresh
    good = [q for q in loaded if loaded[q][2] != "failed"]
    floor = min(good, key=quarter_key) if good else None
    newest = [q for q in order[:last] if q not in loaded]
    older = [q for q in fresh if floor and quarter_key(q) < quarter_key(floor)][:deepen]
    seen, out = set(), []
    for q in changed + newest + older:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("local", "s3"), default="local")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--last", type=int, default=DEFAULT_LAST,
                    help="ensure the newest N quarters on the shelf are loaded (default %d)"
                         % DEFAULT_LAST)
    ap.add_argument("--deepen", type=int, default=0,
                    help="also load N older quarters below the loaded floor")
    ap.add_argument("--all", action="store_true", help="every quarter on the shelf")
    ap.add_argument("--quarters", help="comma-separated, e.g. 2026q1,2026q2")
    ap.add_argument("--workers", type=int, default=0, help="accepted for symmetry; unused")
    ap.add_argument("--new-only", action="store_true", help="accepted for symmetry; the "
                    "default already loads only changed and missing quarters")
    ap.add_argument("--no-compact", action="store_true", help="accepted for symmetry")
    args = ap.parse_args()

    src = S3Source() if args.source == "s3" else LocalSource()
    avail = src.pointers()
    if not avail:
        print("no fsds quarters on the %s shelf; nothing to do" % src.name)
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)
    loaded = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "SELECT quarter, sha256, parser_version, status FROM sec_quarters").fetchall()}
    explicit = {q.strip().lower() for q in (args.quarters or "").split(",") if q.strip()}
    targets = choose(avail, loaded, args.last, args.deepen, explicit, args.all)
    print("shelf: %d quarters (%s..%s); loaded: %d; to load: %s"
          % (len(avail), min(avail, key=quarter_key), max(avail, key=quarter_key),
             len(loaded), ", ".join(targets) or "nothing"))
    sys.stdout.flush()

    failed = []
    for q in targets:
        workdir = tempfile.mkdtemp(prefix="fsds-%s-" % q)
        try:
            load_quarter(con, q, avail[q], src, workdir)
        except Exception as e:                                    # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, str(e)[:300])
            print("  %s FAILED: %s — previous load stays live" % (q, err))
            failed.append(q)
            try:
                record_failure(con, q, avail[q], err)
            except Exception as e2:                               # noqa: BLE001
                print("  (could not record the failure: %s)" % e2)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    con.close()
    if failed:
        print("ATTENTION sec quarters failed: %s" % ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
