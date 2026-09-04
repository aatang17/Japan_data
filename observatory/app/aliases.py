# -*- coding: utf-8 -*-
u"""The gap between the name a person types and the string EDINET filed.

Every equity search box matched a substring of three fields — the securities
code, the filed Japanese name, the filed English name — against the query
exactly as typed. That is how the filings read and it is not how anyone types.
Two different failures came out of it, and this module closes both. Everything
here is DERIVED and applied at serve time: nothing is stored, no extraction
changes, and no vintage is touched.

**1. Nobody types the filed name.** "MUFG" appears neither in
株式会社三菱ＵＦＪフィナンシャル・グループ nor in "Mitsubishi UFJ Financial
Group, Inc.", so the largest bank in Japan returned nothing. Two layers answer
that, both keyed on an EXACT nickname, never a substring:

  * **initials** — generated from the filed English name by taking the first
    letter of every word that is not a legal form: "Mitsubishi UFJ Financial
    Group, Inc." → MUFG, "Sumitomo Mitsui Financial Group, Inc." → SMFG. Free,
    self-maintaining, and blind to size — a small-cap component maker gets its
    acronym on the same terms as a megabank. Initials shared by more than
    MAX_SHARING filers are dropped rather than guessed at.

  * **curation** — ``app/curation/company_aliases.json``, for what initials
    cannot reach: JAL, TEPCO, JR East, Uniqlo, brands, operating subsidiaries
    that do not list, former names. Hand-typed, deliberately small, every row
    carrying the reason it is there, and a curated alias beats generated
    initials outright (JT is Japan Tobacco, not the three filers whose
    initials collide with it).

**2. Nobody types the filed name the way it was filed, either.** EDINET names
carry full-width latin (ＮＴＴ株式会社), full-width spaces inside the name
(株式会社　りそなホールディングス — 181 listed filers have one), and a
株式会社 that a searcher usually omits or puts on the other end. Typing the
company's own full legal name therefore returned nothing at all. `fold` folds
both sides of that comparison — NFKC, upper-case, legal form and punctuation
removed — and `rescued` returns the companies the folded name finds that the
raw substring search missed. This one matters most in the small-cap tail, where
there is no famous English name to fall back on.

Both layers only ever ADD codes to a search: the original substring match still
runs, unchanged, beside them. Nothing that used to be found can be reordered or
lost. Companies are identified by securities code only — names are resolved
from the filings at read time, exactly as everywhere else.
"""
import json
import pathlib
import re
import threading
import unicodedata

CURATION_PATH = pathlib.Path(__file__).resolve().parent / "curation" / "company_aliases.json"

# Legal forms and connecting words carry no signal in a set of initials: every
# second filer ends in "Co., Ltd." and reading that L into the acronym would
# put nobody's real abbreviation in the index.
LEGAL_WORDS = frozenset((
    "CO", "COMPANY", "CORP", "CORPORATION", "INC", "INCORPORATED", "LTD",
    "LIMITED", "KK", "PLC", "LLC", "SA", "NV", "AG", "THE", "AND", "OF",
))
MIN_KEY = 2          # "K" is not an alias; two characters is the floor
MAX_INITIALS = 6     # beyond six letters nobody is typing an acronym
MAX_SHARING = 4      # initials shared by more filers than this are noise
MAX_CODES = 8        # never let an alias flood a 25-row search result
MAX_RESCUED = 100    # a folded name that matches half the market is not a name

# Two locks, not one: building the index reads the curation file, and a single
# non-reentrant lock around both deadlocks the first search on a cold process.
_INDEX_LOCK = threading.Lock()
_CURATION_LOCK = threading.Lock()
_CACHE = {"version": None, "aliases": {}, "names": []}
_CURATED = {"mtime": None, "aliases": {}}

_KEEP = re.compile(r"[^0-9A-Z]+")

# Removed from both sides of a name comparison. NFKC runs first, so ㈱ has
# already become 株式会社 and （株） has become (株) by the time these apply.
_LEGAL_JA = re.compile(u"株式会社|合同会社|有限会社|合名会社|合資会社|\\(株\\)|\\(有\\)")
# Punctuation only. Kana, kanji, letters, digits and the katakana long vowel
# ー all survive: ー is part of コーヒー, not decoration.
_PUNCT = re.compile(u"['\"“”‘’.,;:!?()\\[\\]{}<>「」『』【】・･/\\\\&+*=_~|@#$%^-]+")
# Japanese is written without spaces, so a space touching a kana or kanji is
# EDINET's typography and comes out. A space between two latin words is part of
# the name and STAYS: gluing "TOYO TANSO" into one word would answer a search
# for Toyota with a graphite maker.
_CJK = u"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
_SPACE_BY_CJK = re.compile(u"(?<=[%s]) +| +(?=[%s])" % (_CJK, _CJK))


def normalize(text):
    u"""Fold a typed query or a curated alias to one comparable nickname key.

    NFKC first, so full-width ＭＵＦＧ and half-width MUFG are the same string —
    EDINET names are full of full-width latin, and so are Japanese keyboards.
    """
    folded = unicodedata.normalize("NFKC", text or "").upper()
    return _KEEP.sub("", folded)


def fold(text):
    u"""Fold a company name — Japanese or English — for comparison.

    株式会社　りそなホールディングス, 株式会社りそなホールディングス and
    りそなホールディングス all fold to the same string, which is the point:
    a searcher should not have to reproduce EDINET's spacing.
    """
    folded = unicodedata.normalize("NFKC", text or "").upper()
    # The legal form becomes a space, never nothing: deleting it outright would
    # weld the two halves of ジャフコ株式会社グループ-shaped names together.
    folded = _PUNCT.sub("", _LEGAL_JA.sub(" ", folded))
    return _SPACE_BY_CJK.sub("", re.sub(r"\s+", " ", folded).strip())


def initials(name_en):
    """The acronym a filed English name would be abbreviated to, or ''."""
    words = re.split(r"[^0-9A-Za-z]+", unicodedata.normalize("NFKC", name_en or ""))
    letters = "".join(w[0].upper() for w in words
                      if w and w[0].isalpha() and w.upper() not in LEGAL_WORDS)
    if MIN_KEY <= len(letters) <= MAX_INITIALS:
        return letters
    return ""


def curated():
    """{normalised alias: [sec_code]} from the curation file, reloaded on edit."""
    try:
        mtime = CURATION_PATH.stat().st_mtime_ns
    except OSError:
        return {}
    with _CURATION_LOCK:
        if _CURATED["mtime"] != mtime:
            out = {}
            try:
                with open(str(CURATION_PATH), encoding="utf-8") as fh:
                    doc = json.load(fh)
                for row in doc.get("aliases", []):
                    key = normalize(row.get("alias"))
                    code = (row.get("sec_code") or "").strip()
                    if len(key) >= MIN_KEY and code:
                        out.setdefault(key, [])
                        if code not in out[key]:
                            out[key].append(code)
            except (ValueError, OSError):
                # A malformed curation file must never take the search box
                # down with it: fall back to generated initials alone.
                out = {}
            _CURATED["mtime"] = mtime
            _CURATED["aliases"] = out
        return _CURATED["aliases"]


def _build(cur):
    """(nickname index, folded-name table) for every listed filer."""
    from .equity_api import NAME_CTES  # local: equity_api imports this module

    rows = cur.execute("WITH x AS (SELECT 1)" + NAME_CTES + """
        SELECT e.sec_code, e.name_ja, coalesce(n.name_en, s.name_en) AS name_en
        FROM eq_entities e
        LEFT JOIN en_ecode n ON n.edinet_code = e.edinet_code
        LEFT JOIN en_scode s ON s.sec_code = e.sec_code
        WHERE e.sec_code IS NOT NULL""").fetchall()
    index = {}
    names = []
    for sec_code, name_ja, name_en in rows:
        key = initials(name_en)
        if key:
            index.setdefault(key, []).append(sec_code)
        # Both forms of each name: the folded one to match on, and the raw one
        # to tell whether the dataset's own LIKE would have found it anyway.
        folded = fold(name_ja) + "\n" + fold(name_en)
        names.append((sec_code, folded, folded.replace(" ", ""),
                      (name_ja or "") + "\n" + (name_en or "").lower()))
    index = dict((k, sorted(v)) for k, v in index.items() if len(v) <= MAX_SHARING)
    index.update(curated())   # a hand-typed alias wins outright
    return index, names


def _tables(cur):
    """The index and the name table, rebuilt when the database is replaced."""
    from . import equity_api  # local: equity_api imports this module

    version = equity_api._version()
    with _INDEX_LOCK:
        if _CACHE["version"] != version:
            _CACHE["aliases"], _CACHE["names"] = _build(cur)
            _CACHE["version"] = version
        return _CACHE["aliases"], _CACHE["names"]


def codes(cur, q):
    """[sec_code] a typed query is a known nickname for — usually none."""
    key = normalize(q)
    if len(key) < MIN_KEY:
        return []
    try:
        return _tables(cur)[0].get(key, [])[:MAX_CODES]
    except Exception:  # noqa: BLE001 — search must degrade, never fail
        return []


def rescued(cur, q):
    u"""[sec_code] whose FOLDED name contains the query but whose filed name,
    matched raw, does not — i.e. exactly what the dataset's own LIKE missed.

    Computing the difference rather than the whole match set is what keeps this
    safe: the codes returned are only ever additions, so the cap can never
    displace a company the plain search already found.
    """
    needle = fold(q)
    if len(needle) < MIN_KEY:
        return []
    # A name typed with no spaces at all — TOYOTIRE for ＴＯＹＯ　ＴＩＲＥ — is
    # matched only against the WHOLE de-spaced name, never as a substring of
    # it. Exactness is what keeps "Toyota" from returning Toyo Tanso.
    flat = needle.replace(" ", "")
    raw = (q or "").strip()
    raw_lower = raw.lower()
    try:
        out = []
        for sec_code, folded, flattened, as_filed in _tables(cur)[1]:
            if (needle in folded or flat in flattened.split("\n")) \
                    and not (raw in as_filed or raw_lower in as_filed):
                out.append(sec_code)
                if len(out) >= MAX_RESCUED:
                    break
        return out
    except Exception:  # noqa: BLE001 — search must degrade, never fail
        return []


def clause(cur, column, q):
    u"""(SQL to OR into a search's WHERE, params) — ('', []) when nothing to add.

    The caller owns `column`; it is a literal in its own query, never user
    input. The codes are bound as parameters like every other value here.
    """
    matched = list(codes(cur, q))
    for sec_code in rescued(cur, q):
        if sec_code not in matched:
            matched.append(sec_code)
    if not matched:
        return "", []
    return " OR %s IN (%s)" % (column, ",".join("?" for _ in matched)), matched
