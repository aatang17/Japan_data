# -*- coding: utf-8 -*-
"""Derived English labels for facility rows — location and use category.

Two derivations, both flagged as derived wherever they render:

- **location_en** — the geocoded municipality's official Hepburn romanization,
  from Japan Post's romanized address data (``gazetteer_en.csv``, keyed on the
  same municipality code the geocoder assigns). A row that geocoded to no
  municipality gets no English location; nothing is transliterated by guess.
- **use** — a coarse category (production, office, rental real estate, …)
  classified from the filer's own text: the site name, the 設備の内容
  (contents-of-equipment) column, and the segment column, in that order of
  weight. Keyword rules, first match wins; a row whose text matches no rule
  stays unclassified and renders — like any other missing value. The point of
  the category is the core/non-core cut: rental real estate,
  dormitories/company housing, welfare facilities and idle land are the
  classic non-core holdings, so those three categories carry
  ``NONCORE = True``.

The category is deliberately coarse. It never overrides what the filer wrote —
segment and contents are always returned as filed next to it.
"""
import csv
import io
import pathlib
import re

_GAZ_EN = pathlib.Path(__file__).resolve().parent / "gazetteer_en.csv"

_LOCATION_EN = None


def location_en(muni_code):
    """English municipality label ("Yokohama-shi Tsurumi-ku, Kanagawa")."""
    global _LOCATION_EN
    if _LOCATION_EN is None:
        m = {}
        with io.open(str(_GAZ_EN), encoding="utf-8") as f:
            for row in csv.reader(l for l in f if not l.startswith("#")):
                if row and row[0] != "code":
                    m[row[0]] = "%s, %s" % (row[1], row[2])
        _LOCATION_EN = m
    return _LOCATION_EN.get(muni_code)


# Ordered: first match wins. The specific beat the generic — 本社工場 is a
# plant, 遊休 beats everything (idle land is the flag the screen exists for).
_RULES = [
    ("idle",       u"遊休"),
    ("rental",     u"賃貸|テナント|分譲|投資用|不動産"),
    ("housing",    u"寮|社宅|従業員住宅|厚生|保養|福利"),
    ("hotel",      u"ホテル|ゴルフ|リゾート|遊園地|スキー場|温泉|温浴|スポーツ|スイミング|フィットネス"),
    ("rnd",        u"研究|技術センター|開発センター|テクニカルセンター|実験"),
    ("energy",     u"発電|変電|送電|ＬＮＧ|LNG|ガス製造|供給設備|供給管|本支管|導管|"
                   u"太陽光|風力|ソーラー|蓄電|地域冷暖房|地冷|製油所|油田"),
    ("transport",  u"鉄道|軌道|線路|駅|車両|港湾|埠頭|空港|航空機|船|タンカー"),
    ("production", u"工場|製作所|製造|生産|製鉄|製錬|精錬|鉱山|プラント|工区"),
    ("logistics",  u"物流|倉庫|配送|流通センター|ターミナル|デポ|油槽所"),
    ("retail",     u"店舗|百貨店|ショールーム|直営店|販売|営業店"),
    ("office",     u"本社|本店|支店|支社|営業所|事務所|オフィス|統括|本部|営業設備|業務施設|業務設備"),
]
_RULES = [(code, re.compile(pat)) for code, pat in _RULES]

# Fallback when the row's own text says nothing: the filer's segment name.
_SEGMENT_RULES = [
    ("rental",    re.compile(u"不動産")),
    ("logistics", re.compile(u"物流|運輸|倉庫")),
    ("transport", re.compile(u"鉄道|輸送|航空|海運")),
    ("hotel",     re.compile(u"ホテル|レジャー")),
    ("housing",   re.compile(u"寮")),
]

NONCORE = ("rental", "housing", "idle")

# Ditto marks: the filer wrote "same as the row above". Classification (and
# only classification) resolves them; the filed cell is returned untouched.
_DITTO = re.compile(u"^(〃|々|同\\s*上)$")


def is_ditto(s):
    return bool(s) and bool(_DITTO.match(s.strip()))


def classify_rows(rows, name_key="name", location_key="location",
                  contents_key="contents", segment_key="segment",
                  table_key="table_no"):
    """Classify rows in filing order, carrying values through ditto marks.

    Returns the list of category codes, aligned with ``rows``. Carry never
    crosses a table boundary.
    """
    out = []
    last = {}
    for x in rows:
        t = (x.get("doc_id"), x.get(table_key))
        cts, seg = x.get(contents_key), x.get(segment_key)
        if is_ditto(cts):
            cts = last.get((t, "c"))
        elif cts:
            last[(t, "c")] = cts
        if is_ditto(seg):
            seg = last.get((t, "s"))
        elif seg:
            last[(t, "s")] = seg
        out.append(classify(site_name(x.get(name_key), x.get(location_key)),
                            cts, seg))
    return out


# Some filings merge the site name into the location column — 本社
# (京都府長岡京市). Classification wants the name part only; the address part
# would false-match tokens like 駅 or 港 that belong to place names.
_LOC_SPLIT = re.compile(u"^(.*?)\\s*[（(]([^（()）]+)[）)]\\s*$")


def site_name(name, location):
    if name:
        return name
    m = _LOC_SPLIT.match(location or u"")
    return m.group(1) if m and m.group(1) else None


def classify(name, contents, segment):
    """Coarse use category for one facility row, or None if nothing matches."""
    text = u" ".join(x for x in (name, contents) if x)
    for code, rx in _RULES:
        if rx.search(text):
            return code
    for code, rx in _SEGMENT_RULES:
        if segment and rx.search(segment):
            return code
    return None
