# -*- coding: utf-8 -*-
u"""Reading an EDINET t1 package: the honbun document, its tables, its facts.

Every EDINET disclosure that is not a periodic report arrives the same way —
a zip holding an XBRL instance and an inline-XBRL `honbun` HTML document — and
every extractor that reads one needs the same four things: the honbun text, the
tagged facts, the section under a given heading, and Japanese numbers and dates
out of table cells. That shared machinery lives here so a tender-offer parser
and a capital-raise parser do not have to import each other.

Two traps are handled here once, because both cost real data when missed:

  * XBRL element prefixes carry hyphens (`jptoo-ton_cor:`), which `\\w` does not
    match, and an untagged fact is written SELF-CLOSING (`xsi:nil="true"/>`) —
    a lazy `(.*?)</` runs straight through it and files the NEXT element's
    value under the empty one.
  * Which disclosure items carry an inline-XBRL wrapper changes with the
    taxonomy year and the filer's software, but the Japanese heading does not.
    `section()` asks for the element names it knows and falls back to the
    heading.
"""
import io
import re
import zipfile
import datetime as dt

from facility_extract import grid_of, norm, strip_tags, to_num   # noqa: F401


class NoHonbun(Exception):
    u"""The package holds no honbun document."""


def honbun(blob):
    u"""The filing's body as HTML. Multi-part filings are concatenated."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        parts = [z.read(n) for n in z.namelist()
                 if "honbun" in n and n.endswith(".htm")]
        if not parts:
            raise NoHonbun("no honbun document in package")
        return b"".join(parts).decode("utf-8", "ignore")


def instance(blob):
    u"""The XBRL instance as text, or "" when the package carries none."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist()
                 if n.startswith("XBRL/PublicDoc/") and n.endswith(".xbrl")]
        return z.read(names[0]).decode("utf-8", "ignore") if names else ""


def taxonomy_prefix(blob):
    u"""e.g. `jptoo` or `jpcrp` — the form family, from the instance filename."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in z.namelist():
            if n.startswith("XBRL/PublicDoc/") and n.endswith(".xbrl"):
                return n.split("/")[-1].split("-")[0]
    return None


FACT_RE = re.compile(
    r"<(?:[A-Za-z0-9_.-]+:)?([A-Za-z0-9_]+)\s+[^>]*?contextRef=\"([^\"]+)\""
    r"[^>]*?(?<!/)>([^<]*)</")


def facts(xml):
    u"""{local element name: text} for every tagged, non-empty fact."""
    out = {}
    for name, _ctx, val in FACT_RE.findall(xml):
        v = strip_tags(val)
        if v:
            out[name] = v
    return out


def blocks(html):
    u"""{element local name: inner HTML} for every inline-XBRL text block."""
    out = {}
    for m in re.finditer(r"<ix:nonNumeric\s+[^>]*name=\"[\w-]+:([A-Za-z0-9_]+)\""
                         r"[^>]*>(.*?)</ix:nonNumeric>", html, re.S):
        out.setdefault(m.group(1), m.group(2))
    return out


def tables_in(html):
    return re.findall(r"<table[^>]*>.*?</table>", html or "", re.S | re.I)


HEADING_RE = re.compile(u"【[^】]{2,40}】")


def section(bl, html, names, marks):
    u"""HTML of one disclosure item: the tagged block if there is one, else the
    slice of the document that follows its heading.

    A section runs to the next bracketed heading, which is what stops one
    table swallowing the one after it. A heading immediately followed by
    another heading is a section header over a sub-heading, so the search
    continues past it rather than returning an empty slice.
    """
    for n in names:
        if bl.get(n):
            return bl[n]
    for mk in marks:
        i = html.find(mk)
        if i < 0:
            continue
        rest = html[i + len(mk):]
        nxt = HEADING_RE.search(rest)
        end = nxt.start() if nxt else min(len(rest), 40000)
        if end < 200 and nxt:
            more = HEADING_RE.search(rest, nxt.end())
            end = more.start() if more else min(len(rest), 40000)
        return rest[:end]
    return ""


def section_text(bl, html, names, marks):
    return norm(re.sub(r"<[^>]+>", " ", section(bl, html, names, marks)))


def block_text(bl, name):
    return norm(re.sub(r"<[^>]+>", " ", bl.get(name, "")))


# ------------------------------------------------------------------ numbers

FULLWIDTH_DATE = re.compile(u"(\\d{4})年\\s*(\\d{1,2})月\\s*(\\d{1,2})日")
# Filings mix the Western year with the imperial era in the same document:
# `(3)当該異動年月日 令和6年4月15日` sits under a 2024-dated cover page. An era
# date that is not converted is simply read as no date at all.
ERA_DATE = re.compile(u"(令和|平成|昭和)\\s*(\\d{1,2}|元)年\\s*(\\d{1,2})月\\s*(\\d{1,2})日")
ERA_BASE = {u"令和": 2018, u"平成": 1988, u"昭和": 1925}
# Filers type money by hand and some put a space inside the thousands
# separator: `1株につき金2, 900 円`. Matching only [0-9,] takes the 900 and
# reports a 2,900-yen price as a 900-yen one.
YEN_NUM = re.compile(u"([0-9][0-9,， ]*)\\s*円")


def jp_date(text):
    u"""`2026年８月27日（木曜日）` or `令和6年4月15日` -> a date. None if neither."""
    t = norm(text or "")
    m = FULLWIDTH_DATE.search(t)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = ERA_DATE.search(t)
    if not m:
        return None
    yr = 1 if m.group(2) == u"元" else int(m.group(2))
    try:
        return dt.date(ERA_BASE[m.group(1)] + yr, int(m.group(3)), int(m.group(4)))
    except (ValueError, KeyError):
        return None


def to_int(s):
    v = to_num(s)
    return None if v is None else int(round(v))


def to_float(s):
    return to_num(s)


def to_int_loose(s):
    u"""Like to_int, for a number a human typed with stray spaces in it."""
    return to_int(re.sub(u"[\\s　，]", "", norm(s or "")).replace(u"，", ","))
