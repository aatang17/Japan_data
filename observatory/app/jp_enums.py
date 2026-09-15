# -*- coding: utf-8 -*-
u"""Reading the small Japanese enumerations filers type by hand.

Three fields on these forms are, in principle, one of a handful of values. In
practice each is free text, and filers have written it every way a Japanese
keyboard allows:

    exchange (上場金融商品取引所)   574 spellings of about fifteen exchanges
    listing  (上場・店頭の別)         a dozen spellings of three states
    reciprocal (相互保有の有無)       661 spellings of yes, no and "see note"

The filed string is never replaced -- it is returned beside what is read from
it, the same contract `filer_labels` and `agm_labels` hold. What is added is a
reading, and only where the reading is unambiguous. Anything else comes back
None and renders as a gap.

Why it matters beyond tidiness: `reciprocal` drives a published count (how many
cross-shareholdings are held both ways), and the count was made with a
`LIKE '有%'` test that misread 265 rows -- the ones where a filer answered for
two years at once ("前事業年度：有 当事業年度：無") or bracketed the answer. The
reading here takes the CURRENT year from a two-year answer, which is what the
column means.
"""
import re
import unicodedata

__all__ = ["reciprocal", "exchange_en", "listing_en"]

_MISSING = (u"", u"-", u"－", u"−", u"―", u"ー", u"—", u"‐", u"･", u"・")

# Footnote scaffolding a filer hangs off the answer: （注）2, (注2), ※, 注1.
_NOTE = re.compile(u"[（(]?\\s*(?:注|※)\\s*[0-9０-９]*\\s*[.．]?\\s*[）)]?")
_CURRENT_YEAR = re.compile(u"当(?:事業年度|期)\\s*[:：]?")


def _fold(value):
    u"""Half-width, no spaces of any width, no footnote markers."""
    if not value:
        return u""
    s = unicodedata.normalize("NFKC", value).replace(u"　", u"")
    s = re.sub(r"\s+", u"", s)
    return _NOTE.sub(u"", s)


def reciprocal(value):
    u"""相互保有の有無 -> True (held both ways), False, or None if not stated.

    A filer who answers for both years ("前事業年度:有 当事業年度:無") is
    answering about the current one last; that is the year the row describes,
    so the text after 当事業年度 wins. A dash is a filer saying nothing, which
    is a gap and never a "no".
    """
    s = _fold(value)
    if not s or s in _MISSING:
        return None
    m = _CURRENT_YEAR.search(s)
    if m:
        s = s[m.end():]
    s = s.strip(u"()（）［］[]「」")
    if s.startswith(u"有"):
        return True
    if s.startswith(u"無"):
        return False
    # An answer buried mid-string ("注7無"), once the footnote marker is gone.
    if u"有" in s and u"無" not in s:
        return True
    if u"無" in s and u"有" not in s:
        return False
    return None


# Exchanges, longest key first so 東京証券取引所 is not read as 東京 twice.
_EXCHANGES = [
    (u"東京証券取引所", u"Tokyo"), (u"名古屋証券取引所", u"Nagoya"),
    (u"福岡証券取引所", u"Fukuoka"), (u"札幌証券取引所", u"Sapporo"),
    (u"大阪証券取引所", u"Osaka"), (u"東証", u"Tokyo"), (u"名証", u"Nagoya"),
    (u"福証", u"Fukuoka"), (u"札証", u"Sapporo"), (u"大証", u"Osaka"),
    (u"東京", u"Tokyo"), (u"名古屋", u"Nagoya"), (u"福岡", u"Fukuoka"),
    (u"札幌", u"Sapporo"), (u"大阪", u"Osaka"),
    # The professional markets are named in Latin on the form.
    (u"TOKYO", u"Tokyo"), (u"FUKUOKA", u"Fukuoka"), (u"NAGOYA", u"Nagoya"),
    (u"SAPPORO", u"Sapporo"),
]

# Market segments. Mothers, JASDAQ and the numbered sections are historical --
# the filings go back far enough to need them.
_SEGMENTS = [
    (u"プライム", u"Prime"), (u"スタンダード", u"Standard"),
    (u"グロース", u"Growth"), (u"マザーズ", u"Mothers"),
    (u"JASDAQ", u"JASDAQ"), (u"ジャスダック", u"JASDAQ"),
    (u"Q-Board", u"Q-Board"), (u"QBoard", u"Q-Board"),
    (u"セントレックス", u"Centrex"), (u"アンビシャス", u"Ambitious"),
    (u"ネクスト", u"NEXT"), (u"第一部", u"First Section"),
    (u"第二部", u"Second Section"), (u"1部", u"First Section"),
    (u"2部", u"Second Section"), (u"一部", u"First Section"),
    (u"二部", u"Second Section"), (u"PROMARKET", u"PRO Market"),
]

_LISTING = [
    (u"非上場", u"Unlisted"), (u"未上場", u"Unlisted"), (u"上場", u"Listed"),
    (u"店頭", u"Over-the-counter"), (u"登録", u"Registered"),
    (u"市場外", u"Off-exchange"),
]


def exchange_en(value):
    u"""上場金融商品取引所 -> "Tokyo (Prime)", or None if nothing is recognised.

    Reads the exchanges named and the market segment, in the order the filer
    wrote them, de-duplicated. A filer naming several exchanges gets all of
    them; the segment is stated at most once on these forms.
    """
    s = _fold(value)
    if not s or s in _MISSING:
        return None
    found, seen = [], set()
    # Matching is case-insensitive because the professional markets are written
    # TOKYO PRO Market, Tokyo PRO Market and TOKYO PRO MARKET in the same year.
    # Each match is blanked out so a longer name is not counted twice by a
    # shorter one inside it.
    rest = s.replace(u"株式会社", u"").upper()
    for ja, en in _EXCHANGES:
        key = ja.upper()
        idx = rest.find(key)
        while idx >= 0:
            if en not in seen:
                seen.add(en)
                found.append((idx, en))
            rest = rest[:idx] + u"\x00" * len(key) + rest[idx + len(key):]
            idx = rest.find(key)
    segment = None
    upper = s.upper()
    for ja, en in _SEGMENTS:
        if ja.upper() in upper:
            segment = en
            break
    if not found:
        return segment
    names = u", ".join(en for _, en in sorted(found))
    return u"%s (%s)" % (names, segment) if segment else names


def listing_en(value):
    u"""上場・店頭の別 -> "Listed", "Over-the-counter", "Unlisted", or None.

    Some filers put the market segment in this box instead, which still says
    the company is listed.
    """
    s = _fold(value)
    if not s or s in _MISSING:
        return None
    for ja, en in _LISTING:
        if ja in s:
            return en
    for ja, _en in _SEGMENTS:
        if ja.upper() in s.upper():
            return u"Listed"
    # Some filers name the exchange in this box instead of answering it, which
    # is still a statement that the shares are listed there.
    return u"Listed" if exchange_en(value) else None


def annotate_listing(rows):
    u"""Attach `exchange_en` and `listing_en` beside the filed strings."""
    for row in rows or ():
        if "exchange" in row:
            row["exchange_en"] = exchange_en(row.get("exchange"))
        if "listing" in row:
            row["listing_en"] = listing_en(row.get("listing"))
    return rows


def annotate_reciprocal(rows, key="reciprocal"):
    u"""Attach `reciprocal_held_both_ways` (True/False/None) beside the filed text."""
    for row in rows or ():
        if key in row:
            row["reciprocal_held_both_ways"] = reciprocal(row.get(key))
    return rows
