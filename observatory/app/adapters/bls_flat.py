"""The Bureau of Labor Statistics' bulk flat files, read the same way for
every BLS dataset.

The BLS publishes each survey as a directory of tab-separated text under
https://download.bls.gov/pub/time.series/<survey>/: metadata tables
(`cu.series`, `cu.item`, `cu.area`, ...) and data files of
`series_id  year  period  value  footnote_codes`. No key is needed, which is
why these files are used rather than the BLS API (keyed, 50 series a call).

Three things about the source shape the code here.

**The BLS refuses undeclared clients.** A request without a User-Agent that
names a contact is answered 403. The contact is read from BLS_USER_AGENT, or
from EDGAR_USER_AGENT (the SEC imposes the same rule and the capture jobs
already carry one). Neither set is a fetch failure, and the ingest publishes
nothing — the last good release stays live.

**Files are large and change monthly.** The CPI directory alone is ~90MB.
Each file is cached under `data/bls-cache/` with its ETag and re-requested
conditionally, so a night when the BLS has published nothing costs one 304
per file rather than the download. The cache is derived state: delete it and
the next run rebuilds it.

**Periods are not all months.** `M01`–`M12` are months; `M13` is the BLS's
own annual average, `S01`/`S02` half-years and `S03` the annual average of a
semiannual series. The platform's datasets are monthly, so only M01–M12 are
read; the others are recomputable from the months or belong to series these
datasets do not carry, and are skipped rather than squeezed onto a month.

Public domain (US Government work, 17 U.S.C. §105).
"""
import datetime
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile

BASE = "https://download.bls.gov/pub/time.series/"


class FetchError(Exception):
    pass


def user_agent():
    ua = (os.environ.get("BLS_USER_AGENT") or os.environ.get("EDGAR_USER_AGENT") or "").strip()
    if not ua:
        raise FetchError(
            'BLS_USER_AGENT (or EDGAR_USER_AGENT) is not set — the BLS answers '
            '403 to a client that does not name a contact ("Company contact@domain").')
    return ua


def _cache_dir():
    """Under the data directory, because on Railway that is the mounted
    volume; anywhere else the cache would evaporate on every deploy."""
    root = os.environ.get("OBSERVATORY_DATA_DIR")
    if not root:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(here, "..", "..", "data")
    return os.path.join(root, "bls-cache")


def _write_whole(path, data):
    tmp = path + ".part"
    with open(tmp, "wb") as f:     # written whole then renamed: a crash must
        f.write(data)              # never leave a half file to be reused
    os.replace(tmp, path)


def fetch_url(url, cache_name, accept_prefix=None):
    """One file, conditionally re-fetched against the cached copy.

    `accept_prefix` is a sanity check on the body: the BLS serves an HTML
    error page with status 200 in some failure modes, and caching that as a
    data file would poison every later run.
    """
    folder = _cache_dir()
    os.makedirs(folder, exist_ok=True)
    body_path = os.path.join(folder, cache_name)
    meta_path = body_path + ".meta.json"
    meta = {}
    if os.path.exists(body_path) and os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except ValueError:
            meta = {}
    headers = {"User-Agent": user_agent()}
    if meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]

    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read()
                etag = resp.headers.get("ETag")
                modified = resp.headers.get("Last-Modified")
            if accept_prefix is not None and not raw.lstrip()[:len(accept_prefix)] == accept_prefix:
                raise FetchError("%s: unexpected body %r" % (url, raw[:60]))
            _write_whole(body_path, raw)
            with open(meta_path, "w") as f:
                json.dump({"etag": etag, "last_modified": modified, "url": url}, f)
            return raw
        except urllib.error.HTTPError as e:
            if e.code == 304:
                with open(body_path, "rb") as f:
                    return f.read()
            last = e
            if e.code in (403, 404):
                break              # a refusal or a missing file does not heal in 30s
        except (urllib.error.URLError, OSError) as e:
            last = e
        time.sleep(5 * (attempt + 1))
    raise FetchError("%s: fetch failed (%s)" % (url, last))


def fetch_file(survey, name):
    """download.bls.gov/pub/time.series/<survey>/<name>, via the cache."""
    time.sleep(0.5)                # one request at a time, politely spaced
    return fetch_url(BASE + survey + "/" + name, name)


# --- the archived artifact ----------------------------------------------------

_ZIP_DATE = (2000, 1, 1, 0, 0, 0)


def bundle(files):
    """{name: bytes} -> one deterministic zip.

    Fixed member timestamps and sorted names make the bytes a function of the
    content alone, so the ingest runner's SHA-256 comparison skips a night on
    which the BLS changed nothing. Deflated because the text compresses about
    eightfold and the archive keeps every vintage.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name])
    return buf.getvalue()


def unbundle(raw_bytes):
    z = zipfile.ZipFile(io.BytesIO(raw_bytes))
    return dict((n, z.read(n)) for n in z.namelist())


# --- reading ------------------------------------------------------------------

def read_table(raw_bytes):
    """A BLS metadata or data file -> list of dicts keyed by its header.

    Fields are tab-separated and space-padded (`CUUR0000SA0      `); every
    field is stripped. Blank lines are dropped.
    """
    text = raw_bytes.decode("utf-8", "replace").replace("\r\n", "\n")
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split("\t")]
    out = []
    for line in lines[1:]:
        fields = [f.strip() for f in line.split("\t")]
        if len(fields) < len(header):
            fields += [""] * (len(header) - len(fields))
        out.append(dict(zip(header, fields)))
    return out


def month_of(year, period):
    """'2026', 'M08' -> date(2026, 8, 1); None for M13, S01–S03 (see above)."""
    if len(period) != 3 or period[0] != "M":
        return None
    m = int(period[1:])
    if not 1 <= m <= 12:
        return None
    return datetime.date(int(year), m, 1)


def read_values(raw_bytes, wanted, origin, value_error, into=None):
    """Data rows for the series in `wanted` -> {series_id: {date: float}}.

    A value the BLS prints as '-' (not available; October 2025 is '-' throughout, footnoted
    by the BLS "data unavailable due to the 2025 lapse in appropriations") is a gap,
    never zero; so is a printed 0.0 (see below). The
    same (series, month) arriving twice with two different values is refused:
    the split files overlap, and if they ever disagreed there would be no
    honest way to choose. Pass `into` to merge several files into one map.
    """
    out = {} if into is None else into
    for row in read_table(raw_bytes):
        sid = row.get("series_id")
        if sid not in wanted:
            continue
        period = month_of(row["year"], row["period"])
        if period is None:
            continue
        cell = row.get("value", "")
        if cell in ("", "-", "(NA)"):
            continue
        try:
            v = float(cell)
        except ValueError:
            raise value_error("%s %s %s: non-numeric %r" % (origin, sid, period, cell))
        if v == 0.0:
            # The BLS prints 0.0 for a month that was not priced: area CPI
            # series priced quarterly in 1935-40, a few metro average prices
            # in 1996. Every series these files are read for is an index, a
            # price or an earnings level, none of which can be zero, so a
            # zero is a gap — the trust contract's "missing is never zero",
            # read in the other direction.
            continue
        prev = out.setdefault(sid, {}).get(period)
        if prev is not None and prev != v:
            raise value_error("%s %s %s: two values %r and %r" % (origin, sid, period, prev, v))
        out[sid][period] = v
    return out
