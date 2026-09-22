# -*- coding: utf-8 -*-
"""Interest-rate risk in the banking book (IRRBB) — each bank's own Basel III figure.

What this collects
------------------
Since fiscal 2018 every Japanese bank has had to publish, once a year, the
Basel Committee's IRRBB1 table under the third pillar of the capital rules
(自己資本の充実の状況 → 金利リスク): the fall in the economic value of its
banking book (ΔEVE) and in its net interest income (ΔNII) under six
prescribed rate shocks — parallel up, parallel down, steepener, flattener,
short rate up, short rate down — the largest of the six, and Tier 1 capital,
against which the supervisor measures it (the "materiality" line is 15% for
an internationally active bank, 20% of core capital for a domestic one).

That table is NOT in the securities report on EDINET. It sits in each
bank's own disclosure magazine (ディスクロージャー誌, usually the 資料編) or
in a separate Pillar 3 PDF on its website, and there is no central feed of
it. This module finds it, bank by bank, and reads it off the PDF.

How it finds the table
----------------------
It starts from the disclosure-page URL the FSA records for every regional
bank, shinkin bank and credit co-operative in 中小・地域金融機関情報一覧
(ingested as `fsa-regional-fi`; the raw workbook is read from the archive),
walks at most two pages deep on that site following links that look like
disclosure material, downloads the PDFs that look most like the annual
disclosure or Pillar 3 document, converts each to text with pdftotext, and
keeps the first one whose text carries the IRRBB1 template. Link text is
only used to ORDER the candidates; a document is accepted only on what is
in it. Sites that build their link lists in JavaScript are handled by also
taking every `.pdf` URL that appears anywhere in the page source.

What is kept, and how it is checked
-----------------------------------
Every scenario row as printed — ΔEVE and ΔNII, current and prior year-end
where both are shown — plus the 最大値 row and Tier 1 capital, in yen (the
table's own unit is read from the text), with the source URL, the PDF's
SHA-256, the page the table is on and the as-of date printed beside it.
The page text is archived so the number can always be checked against what
the bank printed. Gates: the 最大値 row must equal the largest ΔEVE among
the six scenarios (rounding aside), Tier 1 must be positive, and the ratio
must be below one; a table that fails is stored as `partial` with the
reason. Nothing is recomputed to pass.

Basis: a bank holding company prints the table for the group (連結) and often
for the bank alone (単体); both are kept and labelled.

Usage
-----
  python irrbb_collect.py --codes 0134,0143 --dump          # two banks, show the parse
  python irrbb_collect.py --types regional-1,regional-2     # every regional bank
  python irrbb_collect.py --types shinkin --limit 20
Requires `pdftotext` (poppler) on PATH and network access to the banks' sites.
"""
import argparse
import datetime as _dt
import hashlib
import html as _html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
import ssl
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from extract import DB_PATH, record_run   # noqa: E402

PARSER_VERSION = "irrbb-1"
# Where each institution's table was found last time: fi_code -> PDF URL.
# A HINT, never a lock — the 2026 document becomes the 2027 one and the path
# changes with it, so a hint that no longer carries the table falls through to
# the crawl exactly as if it were absent. It earns its place twice over: a hint
# that still works turns ~100 site crawls into one download, and it reaches the
# banks whose sites build their document lists in JavaScript, which a container
# with no browser cannot crawl at all. Regenerate with --export-sources after a
# good run.
SOURCE_HINTS_PATH = os.path.join(HERE, "irrbb_sources.json")
EXTRACTOR = "bank-irrbb"
RAW_DIR = os.environ.get("IRRBB_RAW_DIR", os.path.join(HERE, "..", "data", "raw", "irrbb"))
PDF_CACHE = os.environ.get("IRRBB_PDF_CACHE")
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 PloverAnalytics/1.0")
MAX_PDF_BYTES = 80 * 1024 * 1024
MAX_PDFS_PER_BANK = int(os.environ.get("IRRBB_MAX_PDFS", "14"))
MAX_PAGES_PER_BANK = int(os.environ.get("IRRBB_MAX_PAGES", "10"))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS eq_bank_irrbb_sources (
    fi_code VARCHAR PRIMARY KEY, name_ja VARCHAR, fi_type VARCHAR,
    disclosure_url VARCHAR, status VARCHAR, detail VARCHAR,
    source_url VARCHAR, pdf_sha256 VARCHAR, page INTEGER, as_of DATE,
    unit_label VARCHAR, tables INTEGER, pdfs_tried INTEGER, pages_crawled INTEGER,
    collected_at TIMESTAMP, parser_version VARCHAR, archive_path VARCHAR);
CREATE TABLE IF NOT EXISTS eq_bank_irrbb (
    fi_code VARCHAR, name_ja VARCHAR, basis VARCHAR, as_of DATE, year_offset INTEGER,
    scenario VARCHAR, ord INTEGER, delta_eve_yen DOUBLE, delta_nii_yen DOUBLE,
    tier1_yen DOUBLE, unit_label VARCHAR, source_url VARCHAR, pdf_sha256 VARCHAR,
    page INTEGER, status VARCHAR, detail VARCHAR);
"""
SOURCES_COLS = 17
ROW_COLS = 16

SCENARIOS = [
    ("parallel_up", (u"上方パラレルシフト", u"上方パラレル")),
    ("parallel_down", (u"下方パラレルシフト", u"下方パラレル")),
    ("steepener", (u"スティープ化", u"スティープナー", u"スティープニング")),
    ("flattener", (u"フラット化", u"フラットナー", u"フラットニング")),
    ("short_up", (u"短期金利上昇",)),
    ("short_down", (u"短期金利低下",)),
    ("max", (u"最大値", u"最大幅")),
]
TIER1_RE = re.compile(u"(Tier\\s*1|ティア1|コア資本|自己資本の額|中核的自己資本)", re.I)
MARK_RE = re.compile(u"IRRBB|ΔEVE|△EVE|ΔＥＶＥ|上方パラレルシフト", re.I)
NUM_RE = re.compile(u"[△▲\\-−(]?\\s*\\d[\\d,]*(?:\\.\\d+)?\\)?|－|―|—|-(?=\\s|$)")
DATE_RE = re.compile(u"(20\\d{2})年\\s*(\\d{1,2})月\\s*(?:(\\d{1,2})日|末|期)")
FY_END_RE = re.compile(u"(20\\d{2})年度末")
UNIT_RE = re.compile(u"(百万円|億円|千円)")

# Link words that make a page or a PDF worth looking at, and how much.
PDF_SCORE = [
    (re.compile(u"IRRBB|金利リスク", re.I), 12),
    (re.compile(u"第[3３]の柱|pillar|自己資本の充実|充実の状況|開示事項|バーゼル|basel", re.I), 8),
    (re.compile(u"資料編|定量|開示", re.I), 5),
    (re.compile(u"ディスクロージャー|disclo|現況", re.I), 4),
    (re.compile(u"統合報告書|integrated", re.I), 1),
    (re.compile(u"中間|interim|半期|_t/|/09/|_09|09\\.pdf|mid_", re.I), -10),
    (re.compile(u"ミニ|株主通信|営業のご報告|mini|招集", re.I), -12),
]
YEAR_RE = re.compile(u"(20[12]\\d)")
THIS_YEAR = _dt.date.today().year


def year_score(hay):
    """Newest year named in the link, scored against this year: the annual
    disclosure for March is out by July, so the current calendar year is the
    one wanted from then on and last year's before that."""
    years = [int(y) for y in YEAR_RE.findall(hay)]
    if not years:
        return 0
    y = max(years)
    want = THIS_YEAR if _dt.date.today().month >= 7 else THIS_YEAR - 1
    if y >= want:
        return 4
    if y == want - 1:
        return -2
    return -10
PAGE_FOLLOW = re.compile(u"ディスクロージャー|disclo|バーゼル|basel|第[3３]の柱|pillar|資料編|"
                         u"充実|開示|report|レポート|library|ir/|investor|kabunushi|"
                         u"株主|財務|financial|現況|2026|2025", re.I)


# ---------------------------------------------------------------- fetching

_SSL = ssl.create_default_context()


def fetch(url, timeout=60, binary=False, max_bytes=MAX_PDF_BYTES):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Language": "ja,en;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
        data = resp.read(max_bytes + 1)
        final = resp.geturl()
    if len(data) > max_bytes:
        raise ValueError("response larger than %d bytes" % max_bytes)
    if binary:
        return data, final
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return data.decode(enc), final
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "ignore"), final


def links_of(page_html, base):
    """[(url, text)] for every anchor, plus every bare .pdf URL in the source."""
    out = []
    for m in re.finditer(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         page_html, re.S | re.I):
        href = _html.unescape(m.group(1)).strip()
        if href.startswith(("javascript:", "mailto:", "#", "tel:")):
            continue
        text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        out.append((urllib.parse.urljoin(base, href), text))
    for m in re.finditer(r'(https?:)?//[^\s"\'<>()]+?\.pdf(?:\?[^\s"\'<>()]*)?', page_html, re.I):
        u = m.group(0)
        if u.startswith("//"):
            u = "https:" + u
        out.append((u, ""))
    for m in re.finditer(r'["\'](/[^\s"\'<>()]+?\.pdf(?:\?[^\s"\'<>()]*)?)["\']', page_html, re.I):
        out.append((urllib.parse.urljoin(base, m.group(1)), ""))
    seen, uniq = set(), []
    for u, t in out:
        u = u.split("#")[0]
        key = (u, t)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((u, t))
    return uniq


def same_site(a, b):
    ha = urllib.parse.urlparse(a).netloc.lower().split(":")[0]
    hb = urllib.parse.urlparse(b).netloc.lower().split(":")[0]
    if ha == hb:
        return True
    ra = ".".join(ha.split(".")[-3:]) if ha.endswith(".co.jp") or ha.endswith(".or.jp") else ".".join(ha.split(".")[-2:])
    rb = ".".join(hb.split(".")[-3:]) if hb.endswith(".co.jp") or hb.endswith(".or.jp") else ".".join(hb.split(".")[-2:])
    return ra == rb


def score(text, url, table):
    s = 0
    hay = nfkc(text) + " " + url
    for rx, w in table:
        if rx.search(hay):
            s += w
    return s + year_score(hay)


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


CHROME = os.environ.get("IRRBB_CHROME") or next(
    (p for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser")
     if os.path.exists(p)), None)


def render(url):
    """The page as a browser sees it, for sites that build their document
    lists in JavaScript. Headless Chrome with its own profile directory, so
    nothing touches — or is ever killed alongside — a real browser window."""
    if not CHROME:
        raise RuntimeError("no Chrome binary for rendering")
    prof = tempfile.mkdtemp(prefix="irrbb-chrome-")
    try:
        out = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
             "--user-data-dir=" + prof, "--virtual-time-budget=6000",
             "--timeout=25000", "--dump-dom", url],
            capture_output=True, timeout=60)
        return out.stdout.decode("utf-8", "replace")
    finally:
        subprocess.run(["rm", "-rf", prof])


def crawl(start_url, log):
    """-> (pdf candidates sorted best first, pages crawled)."""
    queue = [(start_url, 0)]
    seen_pages = set()
    pdfs = {}
    pages = 0
    renders = 0
    roots = [start_url]
    while queue and pages < MAX_PAGES_PER_BANK:
        url, depth = queue.pop(0)
        if url in seen_pages:
            continue
        seen_pages.add(url)
        try:
            page, final = fetch(url, timeout=40, max_bytes=6 * 1024 * 1024)
        except Exception as e:                                    # noqa: BLE001
            log.append("page %s: %s" % (url, str(e)[:80]))
            # A site that refuses a script (403) or trips urllib's TLS usually
            # serves a browser; one render is worth the try on the start page.
            if depth == 0 and renders < 4:
                renders += 1
                try:
                    page, final = render(url), url
                except Exception as e2:                           # noqa: BLE001
                    log.append("render %s: %s" % (url, str(e2)[:60]))
                    continue
                if len(page) < 500:
                    continue
            else:
                continue
        pages += 1
        if depth == 0:
            roots = [start_url, final]
        # A page with no PDF and few links is usually one whose list is built
        # in JavaScript; render it once and take the DOM instead.
        if page.lower().count(".pdf") < 2 and renders < 4:
            renders += 1
            try:
                rendered = render(final)
                if rendered.lower().count(".pdf") > page.lower().count(".pdf"):
                    page = rendered
                    log.append("rendered %s" % final)
            except Exception as e:                                # noqa: BLE001
                log.append("render %s: %s" % (final, str(e)[:60]))
        follow = []
        for link, text in links_of(page, final):
            low = link.lower()
            path = urllib.parse.urlparse(low).path
            filelike = (".pdf" in low
                        or (not re.search(r"\.(html?|php|aspx?|jsp|cgi|xml|jpg|png|gif|css|js)$", path)
                            and re.search(u"PDF|KB|MB", nfkc(text))))
            if filelike:
                sc = score(text, link, PDF_SCORE)
                if link not in pdfs or pdfs[link][0] < sc:
                    pdfs[link] = (sc, text)
            elif depth < 2 and any(same_site(r, link) for r in roots) and PAGE_FOLLOW.search(nfkc(text) + " " + link):
                if link not in seen_pages and not low.endswith((".jpg", ".png", ".zip", ".xls", ".xlsx", ".doc", ".docx")) \
                        and score(text, link, PDF_SCORE) > -5:
                    follow.append((score(text, link, PDF_SCORE), link))
        follow.sort(reverse=True)
        for _sc, link in follow[:6]:
            queue.append((link, depth + 1))
    ranked = sorted(pdfs.items(), key=lambda kv: -kv[1][0])
    return [(u, sc, t) for u, (sc, t) in ranked], pages


# ------------------------------------------------------------- PDF to text

def pdf_text(blob, sha):
    """The PDF's text, page-separated by form feeds, via pdftotext -layout."""
    if PDF_CACHE:
        os.makedirs(PDF_CACHE, exist_ok=True)
        tpath = os.path.join(PDF_CACHE, sha + ".txt")
        if os.path.exists(tpath):
            with open(tpath, encoding="utf-8") as f:
                return f.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(blob)
        path = f.name
    try:
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
                             capture_output=True, timeout=300)
        text = out.stdout.decode("utf-8", "replace")
    finally:
        os.unlink(path)
    if PDF_CACHE:
        with open(tpath, "w", encoding="utf-8") as f:
            f.write(text)
    return text


# ------------------------------------------------------------- the table

def to_num(tok):
    t = nfkc(tok).replace(",", "").replace(" ", "")
    if t in (u"-", u"－", u"―", u"—", u"△", u"▲", ""):
        return None
    neg = False
    if t[0] in u"△▲-−":
        neg, t = True, t[1:]
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def numbers_in(line):
    """Numeric tokens in a table line, in order; '-' style blanks as None."""
    out = []
    for m in re.finditer(u"(?:(?<=\\s)|^)([△▲−\\-(]?\\s?\\d[\\d,]*(?:\\.\\d+)?\\)?|－|―|—|-)(?=\\s|$)", line):
        tok = m.group(1)
        if re.fullmatch(u"\\d{4}", tok.replace(",", "")) and re.search(u"年", line):
            continue
        out.append(to_num(tok))
    return out


def segments_after(line, label):
    """The numbers after each occurrence of `label` on the line, one list per
    occurrence — a line holding the label twice is two tables side by side."""
    idx = [m.start() for m in re.finditer(re.escape(label), line)]
    out = []
    for a, b in zip(idx, idx[1:] + [len(line)]):
        out.append(numbers_in(line[a + len(label):b]))
    return out


def month_end(y, mo):
    return _dt.date(y, mo, 31 if mo in (1, 3, 5, 7, 8, 10, 12) else (29 if mo == 2 and y % 4 == 0 else 28 if mo == 2 else 30))


def dates_in(text):
    """Every as-of date the text names: 2026年3月31日, 2026年3月末, 2026年3月期,
    and 2025年度末 (the fiscal year ending March 2026)."""
    out = [month_end(int(y), int(mo)) for y, mo, _d in DATE_RE.findall(text)
           if 1 <= int(mo) <= 12]
    out += [_dt.date(int(y) + 1, 3, 31) for y in FY_END_RE.findall(text)]
    return out


def best_as_of(dates):
    """The reporting date among the dates named: the newest March or
    September end if any (a disclosure is dated to a fiscal half), else the
    newest date at all (a publication month such as 2026年6月 is not it)."""
    if not dates:
        return None
    ends = [d for d in dates if d.month in (3, 9)]
    return max(ends) if ends else max(dates)


def find_tables(text):
    """Every IRRBB1 table in the text -> [dict(page, line, rows, tier1, unit, as_of, basis)]."""
    pages = text.split("\f")
    found = []
    for pno, page in enumerate(pages, start=1):
        if not MARK_RE.search(page) or u"上方パラレル" not in nfkc(page):
            continue
        lines = page.split("\n")
        n = nfkc(page)
        i = 0
        while i < len(lines):
            if u"上方パラレル" in nfkc(lines[i]):
                rows = {}        # key -> [numbers per column group]
                groups = 1
                j = i
                while j < len(lines) and j < i + 60:
                    ln = nfkc(lines[j])
                    for key, needles in SCENARIOS:
                        if key in rows:
                            continue
                        hit = [nd for nd in needles if nd in ln]
                        if hit:
                            # Numbers AFTER each label occurrence: the template
                            # numbers its rows (1 上方パラレルシフト …) and that
                            # digit is not data; two occurrences on one line are
                            # two tables printed side by side (連結 | 単体).
                            segs = segments_after(ln, hit[0])
                            rows[key] = segs
                            groups = max(groups, len(segs))
                            break
                    if len(rows) == len(SCENARIOS):
                        break
                    j += 1
                tier1 = None
                k = i          # from the table's first row: a two-column page
                while k < len(lines) and k < i + 90:   # interleaves it with prose
                    ln = nfkc(lines[k])
                    tm = TIER1_RE.search(ln)
                    if tm:
                        # current and prior only; anything after is the next row
                        segs = [[v for v in seg if v is not None][:2] for seg in segments_after(ln, tm.group(0))]
                        if any(segs):
                            tier1 = segs
                            break
                    k += 1
                above = "\n".join(lines[max(0, i - 40):i])
                below = "\n".join(lines[i:k + 1])
                unit = None
                um = UNIT_RE.findall(nfkc(above)) or UNIT_RE.findall(nfkc(below))
                if um:
                    unit = um[-1]
                as_of = None
                dates = dates_in(nfkc(above) + nfkc(below))
                if dates:
                    as_of = best_as_of(dates)
                basis = None
                ctx = nfkc(above)[-600:]
                if u"連結" in ctx and u"単体" not in ctx[-200:]:
                    basis = "consolidated"
                elif u"単体" in ctx:
                    basis = "non-consolidated"
                k = max(k, j)
                text_block = "\n".join(lines[max(0, i - 25):k + 2])
                header = "\n".join(lines[max(0, i - 8):i])
                if as_of is None:
                    dates = dates_in(n)
                    if dates:
                        as_of = best_as_of(dates)
                        as_of_from = "page"
                    else:
                        as_of_from = None
                else:
                    as_of_from = "table"
                for g in range(groups):
                    grows = dict((kk, (v[g] if g < len(v) else [])) for kk, v in rows.items())
                    gt = (tier1[g] if tier1 and g < len(tier1) else (tier1[0] if tier1 else None))
                    if groups > 1:
                        gb = ("consolidated", "non-consolidated")[min(g, 1)]
                    else:
                        gb = basis
                    found.append({"page": pno, "line": i, "rows": grows, "tier1": gt,
                                  "unit": unit, "as_of": as_of, "as_of_from": as_of_from,
                                  "basis": gb, "text": text_block, "header": header})
                i = k + 1
            else:
                i += 1
    return found


def interpret(table):
    """Scenario numbers -> (rows, reason, tier1 current, tier1 prior).

    The template prints ΔEVE (current, prior) then ΔNII (current, prior), and
    ΔNII only on the two parallel shocks — so a steepener row with two numbers
    is ΔEVE this year and last, not ΔEVE and ΔNII. The widest row fixes the
    layout: four (or three) columns means the two-year layout, and a shorter
    row fills from the left. A table whose widest row has only two numbers is
    read from its header: one that names ΔNII is (ΔEVE, ΔNII) for the year;
    one that names two year-ends is (current, prior) ΔEVE."""
    rows = []
    reason = None
    counts = [len(v) for k, v in table["rows"].items() if k != "max"]
    if not counts:
        return rows, "no_scenario_rows", None, None
    width = max(counts)
    header = nfkc(table.get("header") or "")
    two_is_nii = width == 2 and re.search(u"NII", header) and not re.search(u"前期|前年|年度末.*年度末", header)
    for key, _n in SCENARIOS:
        vals = table["rows"].get(key)
        if vals is None:
            if key != "max":
                reason = reason or "missing_%s" % key
            continue
        vals = list(vals) + [None] * (4 - len(vals))
        if width >= 3:
            eve_cur, eve_prior, nii_cur, nii_prior = vals[0], vals[1], vals[2], vals[3]
        elif width == 2 and two_is_nii:
            eve_cur, eve_prior, nii_cur, nii_prior = vals[0], None, vals[1], None
        elif width == 2:
            eve_cur, eve_prior, nii_cur, nii_prior = vals[0], vals[1], None, None
        else:
            eve_cur, eve_prior, nii_cur, nii_prior = vals[0], None, None, None
        rows.append((key, eve_cur, eve_prior, nii_cur, nii_prior))
    tier1 = table["tier1"] or []
    t1_cur = tier1[0] if tier1 else None
    t1_prior = tier1[1] if len(tier1) > 1 else None
    # gate: 最大値 equals the largest scenario ΔEVE
    eves = [r[1] for r in rows if r[0] != "max" and r[1] is not None]
    mx = [r[1] for r in rows if r[0] == "max"]
    if eves and mx and mx[0] is not None and abs(max(eves) - mx[0]) > 1.0:
        reason = reason or "max_mismatch:%s_vs_%s" % (max(eves), mx[0])
    if t1_cur is None:
        reason = reason or "no_tier1"
    elif t1_cur <= 0:
        reason = reason or "tier1_not_positive"
    elif mx and mx[0] is not None and mx[0] > t1_cur:
        reason = reason or "delta_eve_exceeds_tier1"
    return rows, reason, t1_cur, t1_prior


# ----------------------------------------------------------------- registry

def registry(db_path_macro):
    """{code: entity} from the newest archived FSA workbook pair."""
    sys.path.insert(0, os.path.join(HERE, ".."))
    from app.adapters import fsa_fi_list   # noqa: E402
    con = duckdb.connect(db_path_macro, read_only=True)
    try:
        row = con.execute(
            "SELECT a.path FROM source_artifacts a JOIN releases r ON r.artifact_id = a.artifact_id "
            "WHERE a.source_id = 'fsa:chusho-shihyou' AND r.status = 'published' "
            "ORDER BY a.retrieved_at DESC LIMIT 1").fetchone()
    finally:
        con.close()
    if not row:
        raise SystemExit("no published fsa-regional-fi release; ingest it first")
    with open(row[0], "rb") as f:
        raw = f.read()
    fsa_fi_list.parse(raw)
    return fsa_fi_list.parse.entities


# --------------------------------------------------------------------- main

def load_hints():
    try:
        with open(SOURCE_HINTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def read_pdf(url, log):
    """Download one PDF and look for the IRRBB table in it.

    -> {"url", "sha", "tables", "text"} or None. Every failure is a log line,
    never an exception: a bank whose server is down is a gap, not a crash."""
    try:
        blob, final = fetch(url, timeout=180, binary=True)
    except Exception as e:                                        # noqa: BLE001
        log.append("pdf %s: %s" % (url, str(e)[:80]))
        return None
    if blob[:4] != b"%PDF":
        log.append("pdf %s: not a PDF" % url)
        return None
    sha = hashlib.sha256(blob).hexdigest()
    try:
        txt = pdf_text(blob, sha)
    except Exception as e:                                        # noqa: BLE001
        log.append("pdftotext %s: %s" % (url, str(e)[:80]))
        return None
    tables = [t for t in find_tables(txt)
              if any(v is not None for vals in t["rows"].values() for v in vals)]
    if not tables:
        return None
    return {"url": final, "sha": sha, "tables": tables, "text": txt}


def date_tables(hit):
    """Stamp each table with an as-of, and say where that date came from."""
    txt, final = hit["text"], hit["url"]
    head_dates = dates_in(nfkc("\f".join(txt.split("\f")[:3])))
    url_years = [int(y) for y in YEAR_RE.findall(final)]
    doc_date = best_as_of(head_dates) if head_dates else None
    url_year = max(url_years) if url_years else None
    if doc_date and doc_date.month not in (3, 9):
        doc_date = None
    if doc_date and url_year and doc_date.year < url_year - 1:
        doc_date = None
    for t in hit["tables"]:
        if t["as_of"] is None and doc_date:
            t["as_of"], t["as_of_from"] = doc_date, "document"
        elif t["as_of"] is None and url_year:
            t["as_of"], t["as_of_from"] = _dt.date(url_year, 3, 31), "url"
    hit["as_of"] = max((t["as_of"] for t in hit["tables"] if t["as_of"]), default=None)
    return hit


def collect_one(ent, dump=False, hints=None):
    code, name, url = ent["code"], ent["name_ja"], ent["disclosure_url"]
    log = []
    result = {"code": code, "name": name, "type": ent["type"], "url": url,
              "status": "no_source", "detail": None, "tables": [], "pdfs_tried": 0,
              "pages": 0, "source_url": None, "sha": None, "text": None}
    if not url.startswith("http"):
        result["detail"] = "no disclosure URL on the FSA list"
        return result
    hint = (hints or {}).get(code, {}).get("url")
    if hint:
        got = read_pdf(hint, log)
        if got is not None:
            got = date_tables(got)
            got["score"] = 0
            result.update({"status": "found", "source_url": got["url"], "sha": got["sha"],
                           "tables": got["tables"], "text": got["text"],
                           "from_hint": True, "pdfs_tried": 1})
            if dump:
                print("== %s %s: hint hit %s" % (code, name, got["url"]))
            return result
        log.append("hint did not carry the table: %s" % hint)

    try:
        candidates, pages = crawl(url, log)
    except Exception as e:                                        # noqa: BLE001
        result["detail"] = "crawl failed: %s" % str(e)[:120]
        return result
    result["pages"] = pages
    hits = []
    if dump:
        print("== %s %s: %d pages, %d PDF candidates" % (code, name, pages, len(candidates)))
        for u, sc, t in candidates[:MAX_PDFS_PER_BANK]:
            print("     %3d %s | %s" % (sc, u, t[:50]))
        for l in log[:6]:
            print("     log:", l)
    tried = 0
    for pdf_url, sc, text in candidates[:MAX_PDFS_PER_BANK]:
        if sc < 0:
            break
        tried += 1
        try:
            blob, final = fetch(pdf_url, timeout=180, binary=True)
        except Exception as e:                                    # noqa: BLE001
            log.append("pdf %s: %s" % (pdf_url, str(e)[:80]))
            continue
        if blob[:4] != b"%PDF":
            log.append("pdf %s: not a PDF" % pdf_url)
            continue
        sha = hashlib.sha256(blob).hexdigest()
        try:
            txt = pdf_text(blob, sha)
        except Exception as e:                                    # noqa: BLE001
            log.append("pdftotext %s: %s" % (pdf_url, str(e)[:80]))
            continue
        tables = [t for t in find_tables(txt)
                  if any(v is not None for vals in t["rows"].values() for v in vals)]
        if not tables:
            continue
        # A table that names no date takes the newest date on the document's
        # first pages, else the year in the URL; both are recorded as such.
        head_dates = dates_in(nfkc("\f".join(txt.split("\f")[:3])))
        url_years = [int(y) for y in YEAR_RE.findall(final)]
        doc_date = best_as_of(head_dates) if head_dates else None
        url_year = max(url_years) if url_years else None
        # Only a fiscal half-year end counts as a reporting date; a June or
        # July date on the cover is when the book was printed.
        if doc_date and doc_date.month not in (3, 9):
            doc_date = None
        # A document date more than a year older than the year in the URL is
        # a print date or a footnote, not the reporting date; the URL wins
        # and the row is marked as inferred.
        if doc_date and url_year and doc_date.year < url_year - 1:
            doc_date = None
        for t in tables:
            if t["as_of"] is None and doc_date:
                t["as_of"], t["as_of_from"] = doc_date, "document"
            elif t["as_of"] is None and url_year:
                t["as_of"], t["as_of_from"] = _dt.date(url_year, 3, 31), "url"
        hits.append({"url": final, "sha": sha, "tables": tables, "text": txt,
                     "as_of": max((t["as_of"] for t in tables if t["as_of"]), default=None),
                     "score": sc})
        if len(hits) >= 3:
            break
    result["pdfs_tried"] = tried
    if hits:
        # newest as-of wins; a hit with no readable date only wins when no
        # dated hit exists
        hits.sort(key=lambda h: (h["as_of"] or _dt.date(1900, 1, 1), h["score"]), reverse=True)
        best = hits[0]
        result.update({"status": "found", "source_url": best["url"], "sha": best["sha"],
                       "tables": best["tables"], "text": best["text"],
                       "others": [(h["url"], h["as_of"]) for h in hits[1:]]})
    if result["status"] != "found":
        result["detail"] = ("no IRRBB table in %d PDFs from %d pages; %s"
                            % (tried, pages, "; ".join(log[:3])))[:400]
    if dump:
        print("== %s %s -> %s %s" % (code, name, result["status"], result["source_url"]))
        for t in result["tables"]:
            print("   page %s basis=%s unit=%s as_of=%s tier1=%s" % (t["page"], t["basis"], t["unit"], t["as_of"], t["tier1"]))
            for k, v in t["rows"].items():
                print("     %-14s %s" % (k, v))
        if result["status"] != "found":
            print("   ", result["detail"])
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default="regional-1,regional-2",
                    help="comma-separated: regional-1, regional-2, shinkin, shinkumi")
    ap.add_argument("--codes", help="comma-separated institution codes")
    ap.add_argument("--limit", type=int,
                    default=int(os.environ.get("IRRBB_MAX_PER_RUN", "0")) or None,
                    help="institutions per run. Already-clean ones are skipped "
                         "before any network call, so the work is the ones still "
                         "missing; a bound keeps one run to minutes and lets the "
                         "rest arrive on later runs. IRRBB_MAX_PER_RUN sets it.")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--db", default=DB_PATH, help="equity DuckDB to write")
    ap.add_argument("--macro-db", default=os.path.join(HERE, "..", "data", "observatory.duckdb"),
                    help="the macro DuckDB holding the fsa-regional-fi artifact")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--redo", action="store_true", help="re-collect institutions already stored")
    ap.add_argument("--no-hints", action="store_true",
                    help="ignore irrbb_sources.json and crawl every site")
    ap.add_argument("--export-sources", action="store_true",
                    help="write irrbb_sources.json from what is already stored, "
                         "then exit. Run it after a good collection so the next "
                         "run — and the container, which has no browser — goes "
                         "straight to each PDF.")
    ap.add_argument("--no-compact", action="store_true")
    # Accepted for uniformity with the other extractors (refresh_equity.py
    # passes them to every script); this one reads bank websites, not the archive.
    ap.add_argument("--source", default="s3")
    ap.add_argument("--new-only", action="store_true")
    ap.add_argument("--catch-up", type=int, default=0)
    args = ap.parse_args()

    if args.export_sources:
        con = duckdb.connect(args.db, read_only=True)
        rows = con.execute(
            "SELECT fi_code, name_ja, source_url, as_of FROM eq_bank_irrbb_sources "
            "WHERE status IN ('clean','partial') AND source_url IS NOT NULL "
            "ORDER BY fi_code").fetchall()
        con.close()
        out = dict((r[0], {"name": r[1], "url": r[2],
                           "as_of": r[3].isoformat() if r[3] else None}) for r in rows)
        with open(SOURCE_HINTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        print("wrote %s (%d institutions)" % (SOURCE_HINTS_PATH, len(out)))
        return

    hints = {} if args.no_hints else load_hints()
    if hints:
        print("source hints: %d institutions" % len(hints))
    ents = registry(args.macro_db)
    types = {t.strip() for t in args.types.split(",") if t.strip()}
    todo = [e for e in ents.values() if e["type"] in types]
    if args.codes:
        want = {c.strip() for c in args.codes.split(",")}
        todo = [e for e in ents.values() if e["code"] in want]
    todo.sort(key=lambda e: e["code"])

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)
    if not args.redo and not args.codes:
        have = {r[0] for r in con.execute(
            "SELECT fi_code FROM eq_bank_irrbb_sources WHERE status = 'clean' "
            "AND parser_version = ?", [PARSER_VERSION]).fetchall()}
        todo = [e for e in todo if e["code"] not in have]
    if args.limit:
        todo = todo[:args.limit]
    print("institutions to collect: %d" % len(todo))
    os.makedirs(RAW_DIR, exist_ok=True)

    stats = defaultdict(int)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(collect_one, e, args.dump, hints) for e in todo]
        for fut in as_completed(futures):
            r = fut.result()
            code = r["code"]
            now = _dt.datetime.utcnow().replace(microsecond=0)
            con.execute("DELETE FROM eq_bank_irrbb_sources WHERE fi_code = ?", [code])
            con.execute("DELETE FROM eq_bank_irrbb WHERE fi_code = ?", [code])
            if r["status"] != "found":
                stats["no_source"] += 1
                con.execute("INSERT INTO eq_bank_irrbb_sources VALUES (%s)" % ",".join(["?"] * SOURCES_COLS),
                            [code, r["name"], r["type"], r["url"], "no_source", r["detail"],
                             None, None, None, None, None, 0, r["pdfs_tried"], r["pages"],
                             now, PARSER_VERSION, None])
                continue
            # newest as-of first; within it, consolidated before non-consolidated
            tables = sorted(r["tables"], key=lambda t: (t["as_of"] or _dt.date(1900, 1, 1),
                                                         t["basis"] == "consolidated"), reverse=True)
            latest = tables[0]
            keep = [t for t in tables if t["as_of"] == latest["as_of"]]
            statuses, details = [], []
            archive = os.path.join(RAW_DIR, "%s-%s-%s.txt" % (code, (latest["as_of"] or _dt.date(1900, 1, 1)).isoformat(), r["sha"][:12]))
            with open(archive, "w", encoding="utf-8") as f:
                f.write("# %s %s\n# source: %s\n# sha256: %s\n# collected: %sZ\n\n" % (code, r["name"], r["source_url"], r["sha"], now.isoformat()))
                for t in keep:
                    f.write("# page %s basis=%s\n%s\n\n" % (t["page"], t["basis"], t["text"]))
            seen_basis = set()
            for t in keep:
                rows, reason, t1_cur, t1_prior = interpret(t)
                basis = t["basis"] or ("consolidated" if "consolidated" not in seen_basis else "non-consolidated")
                if basis in seen_basis:
                    continue
                seen_basis.add(basis)
                mult = {u"百万円": 1e6, u"億円": 1e8, u"千円": 1e3}.get(t["unit"])
                if mult is None:
                    reason = reason or "no_unit"
                    mult = 1e6
                if t.get("as_of_from") == "url":
                    reason = reason or "as_of_from_url"
                elif t.get("as_of_from") == "document":
                    details.append("%s:as_of_from_document" % basis)
                st = "partial" if reason else "clean"
                statuses.append(st)
                if reason:
                    details.append("%s:%s" % (basis, reason))
                for i, (key, eve_cur, eve_prior, nii_cur, nii_prior) in enumerate(rows):
                    for off, eve, nii, t1 in ((0, eve_cur, nii_cur, t1_cur), (-1, eve_prior, nii_prior, t1_prior)):
                        if eve is None and nii is None:
                            continue
                        con.execute("INSERT INTO eq_bank_irrbb VALUES (%s)" % ",".join(["?"] * ROW_COLS),
                                    [code, r["name"], basis, t["as_of"], off, key, i,
                                     None if eve is None else eve * mult,
                                     None if nii is None else nii * mult,
                                     None if t1 is None else t1 * mult,
                                     t["unit"], r["source_url"], r["sha"], t["page"], st, reason])
            status = "clean" if statuses and all(s == "clean" for s in statuses) else "partial"
            stats[status] += 1
            con.execute("INSERT INTO eq_bank_irrbb_sources VALUES (%s)" % ",".join(["?"] * SOURCES_COLS),
                        [code, r["name"], r["type"], r["url"], status, "; ".join(details) or None,
                         r["source_url"], r["sha"], latest["page"], latest["as_of"], latest["unit"],
                         len(keep), r["pdfs_tried"], r["pages"], now, PARSER_VERSION, archive])
            print("  %s %-14s %s %s p%s %s %s" % (code, r["name"][:14], status, latest["as_of"], latest["page"], r["source_url"], ("; ".join(details) or "")[:120]))
            sys.stdout.flush()
    print("\nstatus counts:")
    for k in sorted(stats, key=lambda x: -stats[x]):
        print("  %-12s %d" % (k, stats[k]))
    n = con.execute("SELECT count(*) FROM eq_bank_irrbb_sources").fetchone()[0]
    con.close()
    if todo:
        record_run(args.db, EXTRACTOR, _dt.date.today(), n, PARSER_VERSION)


if __name__ == "__main__":
    main()
