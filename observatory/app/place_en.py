# -*- coding: utf-8 -*-
u"""English municipality names, derived at serve time.

Two of our sources name places only in Japanese: the Basic Resident Register
by municipality (2,274 areas) and the Tourism Agency's accommodation survey
(210). Their adapters store the filed Japanese, which is right -- but it left
every one of those series with a Japanese label in the `name_en` column, which
is not.

Nothing here is transliterated by guess. Every name resolves to Japan Post's
published romanization (`gazetteer_en.csv`) or it resolves to nothing and the
caller keeps the Japanese. That is the same bar `facility_labels.location_en`
already holds itself to, and the reason `jta_accommodation.MUNICIPALITIES`
declined to romanize its own city names in the first place.

Three ways in, in order of preference:

  * **by code** -- `municipality_en("01101")`. The register's series codes carry
    the five-digit municipality code, so this is a lookup.
  * **derived, for an aggregate code** -- the register also reports prefecture
    totals (`01000`), designated-city totals (`01100`) and 郡 subtotals
    (`02300`), none of which Japan Post lists, because none of them is an
    address. Each is derived from its own members: the first member present in
    the block supplies the head of its name, so 01101 "Sapporo-shi Chuo-ku"
    gives 01100 "Sapporo-shi" and 02301 "Higashitsugaru-gun Hiranai-machi"
    gives 02300 "Higashitsugaru-gun". Derivation, not invention -- the English
    is still Japan Post's.
  * **by Japanese name** -- `municipality_en_by_name("01", u"函館市")`, for the
    accommodation survey, which prints a name and no code.

Eleven areas are in neither Japan Post's file nor derivable from it; they are
listed in `EXTRA` with the reason.

Applied at serve time, never written back: a label is not an observation, and
re-extracting 585,000 series to change a caption would be the wrong trade.
"""
import csv
import io
import os
import pathlib
import re

_GAZ = pathlib.Path(__file__).resolve().parent / "gazetteer_en.csv"

# Areas Japan Post's file cannot supply.
#
#   * The six Northern Territories villages have no postal service, so they are
#     in no zipcode file. The register still reports them (at a population of
#     zero), so they still need a label. Romanized from the Geographical Survey
#     Institute's own English usage for the islands.
#   * Toshima-mura and the 島しょ block header: Tokyo's island subprefecture is
#     a grouping, not an address, and 利島村 is absent from KEN_ALL_ROME.
#   * Hamamatsu's three post-2024 wards, which replaced the seven the gazetteer
#     already romanizes by hand.
EXTRA = {
    "01695": (u"Shikotan-gun Shikotan-mura", u"Hokkaido"),
    "01696": (u"Kunashiri-gun Tomari-mura", u"Hokkaido"),
    "01697": (u"Kunashiri-gun Ruyobetsu-mura", u"Hokkaido"),
    "01698": (u"Etorofu-gun Rubetsu-mura", u"Hokkaido"),
    "01699": (u"Shana-gun Shana-mura", u"Hokkaido"),
    "01700": (u"Shibetoro-gun Shibetoro-mura", u"Hokkaido"),
    "13360": (u"Island districts", u"Tokyo"),
    "13362": (u"Toshima-mura", u"Tokyo"),
    "22138": (u"Hamamatsu-shi Chuo-ku", u"Shizuoka"),
    "22139": (u"Hamamatsu-shi Hamana-ku", u"Shizuoka"),
    "22140": (u"Hamamatsu-shi Tenryu-ku", u"Shizuoka"),
}

# The whole country, which the register codes 00000 and the survey calls 全国.
NATIONAL = u"Japan"

_BY_CODE = None        # "01101" -> ("Sapporo-shi Chuo-ku", "Hokkaido")
_BY_JA = None          # ("01", u"札幌市中央区") -> "01101"
_BY_JA_BARE = None     # ("01", u"倶知安町") -> "01400", unique-in-prefecture only
_PREF_EN = None        # "01" -> "Hokkaido"
_DERIVED = {}          # memoized aggregate-code results

# A 郡 or a subprefecture is an administrative container, not part of the town's
# own name, and sources disagree about whether to print it. Stripping it is how
# 虻田郡倶知安町, 後志総合振興局倶知安町 and 倶知安町 are recognised as one town.
_QUALIFIER = re.compile(u"^.*?(?:郡|総合振興局|振興局|支庁)")

_HEAD = re.compile(r"^(.*?-(?:shi|gun))\s")
_CJK = re.compile(u"[぀-ヿ㐀-鿿＀-￯]")


def has_japanese(s):
    return bool(s) and bool(_CJK.search(s))


def _load():
    global _BY_CODE, _BY_JA, _BY_JA_BARE, _PREF_EN
    if _BY_CODE is not None:
        return
    by_code, by_ja, pref = {}, {}, {}
    bare = {}
    with io.open(str(_GAZ), encoding="utf-8") as f:
        for row in csv.reader(l for l in f if not l.startswith("#")):
            if not row or row[0] == "code":
                continue
            code, city_en, pref_en = row[0], row[1], row[2]
            city_ja = row[3] if len(row) > 3 else ""
            by_code[code] = (city_en, pref_en)
            pref.setdefault(code[:2], pref_en)
            if city_ja:
                by_ja[(code[:2], city_ja)] = code
                short = _QUALIFIER.sub(u"", city_ja)
                if short and short != city_ja:
                    bare.setdefault((code[:2], short), []).append(code)
    for code, (city_en, pref_en) in EXTRA.items():
        by_code.setdefault(code, (city_en, pref_en))
        pref.setdefault(code[:2], pref_en)
    # A bare name is only usable where it is unambiguous inside its prefecture.
    _BY_CODE, _BY_JA, _PREF_EN = by_code, by_ja, pref
    _BY_JA_BARE = dict((k, v[0]) for k, v in bare.items()
                       if len(v) == 1 and k not in by_ja)


def prefecture_en(code):
    u"""English prefecture name from a two- or five-digit code."""
    _load()
    return _PREF_EN.get((code or "")[:2])


def _derive(code):
    u"""An aggregate code -> the head of its members' names.

    A designated city's wards and a 郡's towns all carry the parent in their
    own romanized name, so the parent's English is a prefix of the child's:
    "Kawasaki-shi Kawasaki-ku" -> "Kawasaki-shi". The first member present in
    the block decides, which keeps neighbouring blocks (14130 Kawasaki and
    14150 Sagamihara) from bleeding into each other.
    """
    try:
        base = int(code)
    except (TypeError, ValueError):
        return None
    for span in (20, 30):
        for k in range(1, span):
            hit = _BY_CODE.get("%05d" % (base + k))
            if hit:
                m = _HEAD.match(hit[0])
                return (m.group(1), hit[1]) if m else None
    return None


def municipality_en(code):
    u"""Five-digit municipality code -> "Sapporo-shi, Hokkaido", or None.

    Handles the register's aggregate codes as well as real municipalities.
    """
    _load()
    code = (code or "").strip()
    if not code:
        return None
    if code == "00000":
        return NATIONAL
    hit = _BY_CODE.get(code)
    if hit is None and code.endswith("000"):
        pref = _PREF_EN.get(code[:2])
        return pref
    if hit is None:
        if code not in _DERIVED:
            _DERIVED[code] = _derive(code)
        hit = _DERIVED[code]
    if hit is None:
        return None
    return u"%s, %s" % (hit[0], hit[1])


def municipality_en_by_name(pref_code, name_ja):
    u"""("01", u"函館市") -> "Hakodate-shi, Hokkaido", or None.

    For a source that prints a municipality name and no code. Three passes, all
    of them exact matches against a published name -- never a fuzzy one:

      1. the name as printed;
      2. the name with a 郡 or 振興局/支庁 qualifier stripped, which the Tourism
         Agency adds and drops between editions (虻田郡倶知安町 and
         後志総合振興局倶知安町 are one town);
      3. a designated city named as a whole (札幌市), which Japan Post lists
         only ward by ward -- resolved through the same member-head derivation
         an aggregate code uses.
    """
    _load()
    pref_code = (pref_code or "")[:2]
    name_ja = (name_ja or "").strip()
    if not pref_code or not name_ja:
        return None

    code = _BY_JA.get((pref_code, name_ja))
    if code is None:
        bare = _QUALIFIER.sub(u"", name_ja) or name_ja
        code = (_BY_JA.get((pref_code, bare))
                or _BY_JA_BARE.get((pref_code, bare)))
    if code is not None:
        return municipality_en(code)

    # A designated city named whole: find its wards and take the common head.
    if name_ja.endswith(u"市"):
        heads = set()
        for (pref, city_ja), member in _BY_JA.items():
            if pref == pref_code and city_ja.startswith(name_ja):
                m = _HEAD.match(_BY_CODE[member][0])
                if m:
                    heads.add((m.group(1), _BY_CODE[member][1]))
        if len(heads) == 1:
            head, pref_en = heads.pop()
            return u"%s, %s" % (head, pref_en)
    return None


def relabel(name_en, place_en):
    u"""Swap the Japanese place at the head of a series label for its English.

    Both sources build a label as "<place>, <Prefecture> — <measure>" or
    "<place> — <measure>", with only the place left in Japanese. Only that
    leading segment is replaced; the measure, which is already English, is
    untouched. A label that does not have that shape, or a place that did not
    resolve, comes back exactly as it was.
    """
    if not name_en or not place_en:
        return name_en
    head, sep, rest = name_en.partition(u" — ")
    if not sep or not has_japanese(head):
        return name_en
    return place_en + sep + rest


def series_name_en(dataset, code, name_en):
    u"""The English label for one series of a place-keyed dataset.

    Returns `name_en` unchanged for every other dataset, for a label that is
    already English, and for a place with no published romanization.
    """
    if not has_japanese(name_en):
        return name_en
    if dataset == "population-jp-municipal":
        return relabel(name_en, municipality_en((code or "")[:5]))
    if dataset == "accommodation-jp" and (code or "").startswith("muni."):
        parts = code.split(".")
        if len(parts) > 1:
            return relabel(name_en, _accommodation_place(parts[1]))
    return name_en


def _accommodation_place(muni_code):
    u"""The survey's own area code ("01-01") -> English, via its Japanese name."""
    from app.adapters import jta_accommodation as jta
    pref = jta._MUNI_PREF.get(muni_code)
    city = jta._MUNI_CITY.get(muni_code)
    if not pref or not city:
        return None
    return municipality_en_by_name(pref, city)


def selftest():
    u"""Coverage report: `python -m app.place_en`."""
    import duckdb
    db = os.environ.get("OBSERVATORY_DB_PATH",
                        os.path.join(os.path.dirname(_GAZ.parent), "data",
                                     "observatory.duckdb"))
    con = duckdb.connect(db, read_only=True)
    bad = 0
    for dataset in ("population-jp-municipal", "accommodation-jp"):
        rows = con.execute(
            "SELECT code, name_en FROM series WHERE dataset=?", [dataset]).fetchall()
        left = [(c, n) for c, n in rows
                if has_japanese(series_name_en(dataset, c, n))]
        print("%-26s %7d series, %6d still Japanese" % (dataset, len(rows), len(left)))
        for c, n in left[:10]:
            print("      ", c, n)
        bad += len(left)
    con.close()
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if selftest() else 0)
