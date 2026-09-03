# -*- coding: utf-8 -*-
u"""M1 — 5%-rule extractor: 大量保有報告書・変更報告書 (EDINET types 350/360).

Who is buying whom, in the tape the market actually watches. Anyone crossing
5% of a listed company's voting shares must file within five business days,
and file again on every 1-point move — so this is the only public dataset in
Japan that names an accumulating holder BEFORE the annual report does.
Everything here is already in the archive (the daily capture has taken types
350 and 360 since 2021), so nothing new is downloaded.

Unlike every other extractor in this repo the source is the t1 INLINE-XBRL
package, not a type=5 CSV: EDINET publishes no CSV rendition for this form.
The facts are tagged all the same (jplvh_cor:*), spread across the header and
body documents of the package, which are read together.

Two tables:

    eq_lvh_filings   one row per report: issuer, group position, why it was
                     filed, and this dataset's gates
    eq_lvh_holders   one row per filer or joint holder named in it

WHAT MAKES THIS DATASET WORTH THE TROUBLE, and the traps under each:

  1. THE ISSUER IS IDENTIFIED BY SECURITIES CODE (SecurityCodeOfIssuer), so
     the target resolves without name matching — the reverse view ("who has
     filed 5% on this company") is exact, not fuzzy.
  2. EACH HOLDER CARRIES ITS OWN EDINET CODE, so a holder resolves to one
     entity across every filing it has ever made. Names never have to be
     matched for the holder side either.
  3. 重要提案行為 (ActOfMakingImportantProposalEtc) IS A FILED FIELD. It is
     what separates a campaign from an index position, and it is disclosed
     rather than inferred. The special form (第二号様式, jplvh020000) is the
     exemption for institutions that undertake NOT to make such proposals, and
     it does not carry the field at all — absence there is meaningful, and is
     recorded as such rather than as a missing value.
  4. A JOINT HOLDER WHO HAS LEFT THE GROUP IS STILL DESCRIBED IN THE FILING.
     Nomura's report on Nissui details three holders, and its group total of
     33,338,274 shares is the sum of TWO of them: Nomura International plc had
     just ceased to be a joint holder and appears with last-report figures
     only. Summing every holder in the document overstates the position, so a
     holder counts toward the group only where the filing gives it a CURRENT
     figure (`in_group_total`).
  5. A CHANGE REPORT OFTEN RESTATES THE ORIGINAL OBLIGATION DATE. 提出義務発生日
     on a 変更報告書 is frequently the date the holder first crossed 5%, years
     earlier, not the date of the change being reported: 14% of change reports
     in the archive state a date more than 40 days before filing, and the
     oldest reaches back to 1990. requirement_date is as filed, and the gap
     between it and the filing date is NOT a measure of lateness.
  6. FILERS MIS-TAG THE FREE-TEXT FIELDS. A funding amount routinely arrives
     with a whole table's text wrapped inside the tag, and the one number in
     that text may be a different line of the form (Nomura's borrowings tag
     contains its total funding). A numeric fact is therefore taken ONLY when
     the tagged text is itself a number; anything else is missing, and counted
     in `messy_facts`. A plausible-looking number in the wrong column is worse
     than a gap.

Money is stated in 千円 on this form and stored in yen.

Gates (each recomputes a number the filing itself publishes):
    G1  holders' share counts sum to the filed group total          (exact)
    G2  holders' ratios sum to the filed group ratio      (rounding-aware)
    G3  the filed group ratio equals held / outstanding   (rounding-aware)
    G4  the ratio is between 0 and 100

One writer at a time: stop the local `uvicorn app.main:app` first.

Usage:
    python lvh_extract.py --limit 200                      # local smoke test
    python lvh_extract.py --all --source s3 --workers 16   # the whole archive

Python 3.9.
"""
import argparse
import glob
import hashlib
import html as html_mod
import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from extract import (LocalSource, S3Source, load_codelist, build_index, pick,
                     norm, core_name, base_name, is_foreign, compact,
                     DB_PATH, ARCHIVE, incremental_window, record_run,
                     seek_key)

PARSER_VERSION = "lvh-1"

L = "jplvh_cor:"
DEI = "jpdei_cor:"
GROUP_CTX = "FilingDateInstant"
# FilingDateInstant_jplvh010000-lvh_E03810-000FilerLargeVolumeHolder2Member
HOLDER_CTX = re.compile(r"FilerLargeVolumeHolder(\d+)Member$")

# Both ix element kinds are read: EDINET tags several numeric fields as
# nonNumeric and vice versa depending on the form generator, so the kind is not
# a reliable filter — the VALUE is checked instead (see clean_number).
#
# The scan CANNOT be a regular expression. Inline XBRL nests: a text-block fact
# wraps the tagged facts inside it, and a non-greedy regex closes the outer
# element on the inner element's end tag, then resumes past it — truncating the
# outer value and swallowing the inner facts whole. Measured on the archive
# that lost the holding ratio outright in 36% of filings. The parser below
# keeps a stack, which is what nesting requires.
IX_TAGS = ("ix:nonnumeric", "ix:nonfraction")
NUMERIC = re.compile(r"^-?[0-9,．.]+$")

# How filers write "none" in the 重要提案行為 box, verbatim from the archive.
NONE_STATED = (u"該当事項なし", u"該当事項無し", u"該当事項ありません",
               u"該当事項はありません", u"該当事項ございません",
               u"該当事項はございません", u"該当なし", u"該当無し",
               u"該当ありません", u"該当事項", u"ありません", u"ございません",
               u"なし", u"無し", u"無", u"-")
YEN_THOUSANDS = 1000

ERA = ((u"令和", 2018), (u"平成", 1988), (u"昭和", 1925))
DATE_RE = re.compile(u"(令和|平成|昭和)?\\s*([0-9０-９元]+)\\s*年\\s*([0-9０-９]+)\\s*月"
                     u"\\s*([0-9０-９]+)\\s*日")


class NoFacts(Exception):
    u"""A package with no inline-XBRL document — the amendment cover sheets
    ship a plain HTML rendering alongside the tagged one, and a handful of
    filings carry nothing else."""


def zen(s):
    u"""Full-width digits to ASCII. Filers use both, in the same document."""
    return (s or "").translate(dict(zip(range(0xFF10, 0xFF1A),
                                        range(ord("0"), ord("9") + 1))))


def jp_date(text):
    u"""'令和8年7月28日' or '2026年7月31日' -> '2026-07-28'. Both appear on
    this form, sometimes in the same filing."""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    era, y, mo, d = m.group(1), zen(m.group(2)), zen(m.group(3)), zen(m.group(4))
    y = 1 if y == u"元" else int(y)
    if era:
        y += dict(ERA)[era]
    if not (1900 <= y <= 2100):
        return None
    try:
        return "%04d-%02d-%02d" % (y, int(mo), int(d))
    except ValueError:
        return None


class Fact(object):
    u"""One tagged value, with the two attributes that change what it means.

    `scale` is the filing's own statement of the value's magnitude: money on
    this form is printed in 千円 and tagged scale="3", ratios are printed in
    percent and tagged scale="-2". So the printed text is what a reader sees,
    and text x 10**scale is the value in the declared unit. Money is stored in
    yen (scaled); a ratio is stored as the printed percent, because that is
    the figure the filing publishes and the one every other percentage on this
    platform is expressed in.
    """

    __slots__ = ("text", "scale", "sign")

    def __init__(self, text, scale, sign):
        self.text = text
        self.scale = scale
        self.sign = sign

    def number(self):
        u"""The printed number, or None when the tag holds anything else."""
        v = clean_number(self.text)
        if v is not None and self.sign == "-":
            v = -v
        return v

    def scaled(self):
        u"""The number in its declared unit — for money, yen."""
        v = self.number()
        if v is None:
            return None
        try:
            return v * (10.0 ** int(self.scale)) if self.scale not in (None, "") else None
        except ValueError:
            return None


def clean_number(text):
    u"""A number, or None when the tag holds anything else.

    Deliberately strict — see trap 5 in the module docstring. A tag wrapping a
    whole table is not a value, even when exactly one number can be fished out
    of it, because that number is routinely a different line of the form.
    """
    s = zen(html_mod.unescape(text or "")).strip().replace(u"，", ",")
    s = re.sub(r"\s+", "", s)
    if not s or not NUMERIC.match(s):
        return None
    s = s.replace(",", "").replace(u"．", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _days(iso):
    u"""ISO date -> a day number, for comparing two dates without a datetime."""
    y, m, d = [int(x) for x in iso.split("-")]
    return y * 372 + m * 31 + d


# A filer that states no English name sometimes writes a rule of dashes rather
# than leaving the field empty. That is "not stated", not a name, and it must
# never reach a page as a company's English name.
DASHES_ONLY = re.compile(u"^[-\u2010\u2011\u2012\u2013\u2014\u2015\u2500\uFF0D\s\u3000]+$")


def clean_english_name(value):
    t = clean_text(value)
    return None if (t is None or DASHES_ONLY.match(t)) else t


def clean_text(value):
    u"""Filed free text, whitespace collapsed, or None. Filers pad these fields
    with newlines and full-width spaces from the form's own layout."""
    t = re.sub(r"[\s\u3000]+", " ", (value or "")).strip()
    return t or None


def to_int(x):
    return int(round(x)) if x is not None else None


def yen_from_thousands(x):
    return int(round(x * YEN_THOUSANDS)) if x is not None else None


class IxScanner(HTMLParser):
    u"""Collects every ix fact in one document, nesting included.

    Text is pushed into every open frame, so a text block keeps the words of
    the facts inside it while those facts are still recorded in their own
    right — which is the point of the stack.
    """

    def __init__(self, facts):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.facts = facts
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag in IX_TAGS:
            a = dict(attrs)
            self.stack.append([a.get("name", ""), a.get("contextref", ""),
                               a.get("scale"), a.get("sign"), []])

    def handle_startendtag(self, tag, attrs):
        if tag in IX_TAGS:
            a = dict(attrs)
            self.facts[a.get("name", "")][a.get("contextref", "")].append(
                Fact("", a.get("scale"), a.get("sign")))

    def handle_data(self, data):
        for frame in self.stack:
            frame[4].append(data)

    def handle_endtag(self, tag):
        if tag in IX_TAGS and self.stack:
            name, ctx, scale, sign, parts = self.stack.pop()
            self.facts[name][ctx].append(
                Fact("".join(parts).strip(), scale, sign))


def parse_package(blob):
    u"""t1 zip -> ({element: {context: [Fact]}}, form code).

    Every inline document in the package is read and merged: this form spreads
    its facts across the header, the holder sections (one file per joint holder
    in some packages) and the body.
    """
    facts = defaultdict(lambda: defaultdict(list))
    form = None
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        docs = [n for n in z.namelist() if n.endswith("_ixbrl.htm")]
        if not docs:
            raise NoFacts(", ".join(sorted(
                os.path.basename(n) for n in z.namelist())[:4] or ["empty"]))
        for n in sorted(docs):
            if form is None:
                m = re.search(r"(jplvh\d+)", n)
                form = m.group(1) if m else None
            scanner = IxScanner(facts)
            scanner.feed(z.read(n).decode("utf-8", "replace"))
            scanner.close()
    return facts, form


def ctx_key(ctx):
    u"""Context id -> 'group' or a holder number. The filer's own extension
    namespace sits in the middle of the id and is ignored."""
    if ctx == GROUP_CTX:
        return 0
    m = HOLDER_CTX.search(ctx or "")
    return int(m.group(1)) if m else None


def fact(facts, element, ctx_no):
    u"""The first fact for an element in one context, or None.

    A filing states the same fact more than once — section 1 and the joint-
    holding breakdown carry the same numbers — and the first stated wins.

    Two namespaces are searched because the same element name lives in both:
    the cover page's EDINET code is jpdei_cor:EDINETCodeDEI while each
    holder's is jplvh_cor:EDINETCodeDEI. Searching only the form namespace
    left every filing without a filer code.
    """
    for prefix in (L, DEI):
        for ctx, vals in (facts.get(prefix + element) or {}).items():
            if ctx_key(ctx) == ctx_no and vals and vals[0].text:
                return vals[0]
    return None


def first(facts, element, ctx_no):
    u"""The first value of an element in one context, as text."""
    f = fact(facts, element, ctx_no)
    return f.text if f else ""


def holder_numbers(facts):
    nums = set()
    for element in ("Name", "IndividualOrCorporation", "EDINETCodeDEI",
                    "HoldingRatioOfShareCertificatesEtc"):
        for ctx in list(facts.get(L + element) or {}) + list(facts.get(DEI + element) or {}):
            k = ctx_key(ctx)
            if k:
                nums.add(k)
    return sorted(nums)


def stated_none(text):
    u"""Does the answer begin by saying "none"?

    Not an equality test: filers routinely leave the ix tag open over the rest
    of the section, so the value arrives as 該当事項なし followed by the next
    table. The answer is the first line either way, and anything that does not
    open with a none-phrase is treated as a stated act.
    """
    t = zen(text or "").strip()
    head = re.split(r"[\n\r。]", t, 1)[0]
    head = re.sub(r"[\s。．.、,]+", "", head)
    return (not head) or any(head.startswith(re.sub(r"[\s。．.]+", "", n))
                             for n in NONE_STATED)


REPORT_TYPES = ((u"訂正報告書", "amendment"), (u"変更報告書", "change"),
                (u"大量保有報告書", "initial"))
CHANGE_NO = re.compile(u"(?:No|NO|ＮＯ|Ｎｏ|№)?\\s*[.．]?\\s*([0-9０-９]+)")


# No Japanese share has ever traded near a million yen; a million yen per
# share is a ceiling nothing real can cross, not an estimate of anything.
MAX_YEN_PER_SHARE = 1000000


def implausible_funding(holders, group):
    u"""True when the stated acquisition cost cannot be a cost."""
    money, shares = 0, 0
    for h in holders:
        money += (h[17] or 0) + (h[18] or 0)
        shares += h[10] or 0
    money = money or ((group.get("own") or 0) + (group.get("borrow") or 0))
    shares = shares or (group.get("shares") or 0)
    if not money or not shares:
        return None
    return money / float(shares) > MAX_YEN_PER_SHARE


def report_type_of(title, doc_type):
    u"""(report_type, change_no). The cover-page title is the authority; the
    EDINET document type only says whether this is a correction of one."""
    t = zen(title or "")
    kind = next((k for mark, k in REPORT_TYPES if mark in t), None)
    if kind is None:
        kind = "amendment" if doc_type == "360" else "initial"
    no = None
    if kind == "change":
        m = CHANGE_NO.search(t.split(u"変更報告書", 1)[-1])
        if m:
            no = int(zen(m.group(1)))
    return kind, no


SCHEMA_SQL = """
        -- One row per 大量保有報告書 / 変更報告書 / 訂正報告書. The position is
        -- the GROUP's (filer plus joint holders) as the filing states it, not
        -- our sum; eq_lvh_holders carries the split.
        CREATE TABLE IF NOT EXISTS eq_lvh_filings (
            doc_id VARCHAR PRIMARY KEY, doc_type VARCHAR, form VARCHAR,
            report_type VARCHAR, change_no INTEGER, is_special_form BOOLEAN,
            filer_edinet_code VARCHAR, filer_name VARCHAR,
            issuer_name_raw VARCHAR, issuer_sec_code VARCHAR,
            issuer_edinet_code VARCHAR, issuer_match_status VARCHAR,
            listing VARCHAR, exchange VARCHAR,
            requirement_date DATE, filed_date DATE, cover_date DATE,
            holders_declared INTEGER, holders_rows INTEGER, holders_in_total INTEGER,
            shares_held BIGINT, shares_outstanding BIGINT,
            ratio_pct DOUBLE, prior_ratio_pct DOUBLE, ratio_change_pp DOUBLE,
            important_proposal BOOLEAN, proposal_asked BOOLEAN,
            filing_reason_ja VARCHAR,
            purpose_ja VARCHAR, own_funds_yen BIGINT, borrowings_yen BIGINT,
            funding_implausible BOOLEAN,
            sha256 VARCHAR, parser_version VARCHAR, status VARCHAR,
            detail VARCHAR, messy_facts INTEGER);
        -- One row per filer or joint holder named in the report. in_group_total
        -- is false for a holder the filing describes but excludes from the
        -- group position — typically one that has just left the group.
        CREATE TABLE IF NOT EXISTS eq_lvh_holders (
            doc_id VARCHAR, holder_no INTEGER, name_raw VARCHAR, name_en VARCHAR,
            address_raw VARCHAR, holder_type_ja VARCHAR, is_individual BOOLEAN,
            holder_edinet_code VARCHAR, holder_sec_code VARCHAR,
            match_status VARCHAR, shares_held BIGINT, ratio_pct DOUBLE,
            prior_ratio_pct DOUBLE, in_group_total BOOLEAN, purpose_ja VARCHAR,
            important_proposal_ja VARCHAR, important_proposal BOOLEAN,
            own_funds_yen BIGINT, borrowings_yen BIGINT, total_funding_yen BIGINT,
            -- A stable identity for a holder that has no EDINET code of its
            -- own (or whose code was the issuer's — see the guard in build()).
            -- Width, spacing and old character forms are folded exactly as the
            -- entity resolver folds them, so one holder is one row of a
            -- ranking however the filer spelled it.
            name_key VARCHAR,
            -- 事業内容 and 職業, exactly as filed. What kind of institution a
            -- holder is gets read from these at serve time; storing the filer's
            -- own words rather than our reading of them means a change to that
            -- reading never rewrites a stored row.
            business_ja VARCHAR, occupation_ja VARCHAR);
"""

FILING_COLUMNS = ("doc_id", "doc_type", "form", "report_type", "change_no",
                  "is_special_form", "filer_edinet_code", "filer_name",
                  "issuer_name_raw", "issuer_sec_code", "issuer_edinet_code",
                  "issuer_match_status", "listing", "exchange",
                  "requirement_date", "filed_date", "cover_date", "holders_declared",
                  "holders_rows", "holders_in_total", "shares_held",
                  "shares_outstanding", "ratio_pct", "prior_ratio_pct",
                  "ratio_change_pp", "important_proposal", "proposal_asked",
                  "filing_reason_ja",
                  "purpose_ja", "own_funds_yen", "borrowings_yen",
                  "funding_implausible", "sha256",
                  "parser_version", "status", "detail", "messy_facts")
FILING_INSERT = "INSERT INTO eq_lvh_filings (%s) VALUES (%s)" % (
    ", ".join(FILING_COLUMNS), ", ".join(["?"] * len(FILING_COLUMNS)))


def build(doc_id, doc_type, facts, form, submitted, resolve_issuer, resolve_holder):
    u"""Parsed facts -> (filing row dict, holder rows, gate problems)."""
    problems = []
    messy = 0

    def take(element, ctx_no, money=False):
        u"""A numeric fact as printed, or the sentinel "messy" when the tag
        holds something else (trap 5). Money is returned in yen, using the
        filing's own scale where it states one and the form's 千円 otherwise."""
        f = fact(facts, element, ctx_no)
        if f is None or not f.text:
            return None
        v = f.scaled() if money else f.number()
        if v is None and money:
            v = f.number()
            v = v * YEN_THOUSANDS if v is not None else None
        return "messy" if v is None else v

    special = form == "jplvh020000"
    title = first(facts, "DocumentTitleCoverPage", 0)
    report_type, change_no = report_type_of(title, doc_type)

    sec = re.sub(r"\D", "", first(facts, "SecurityCodeOfIssuer", 0))[:4] or None
    issuer_name = first(facts, "NameOfIssuer", 0).strip() or None
    imstat, iec = resolve_issuer(sec, issuer_name)
    issuer_code = iec

    holders, in_total = [], 0
    for no in holder_numbers(facts):
        name = first(facts, "Name", no).strip()
        if not name:
            name = first(facts, "FilerNameInJapaneseDEI", no).strip()
        if not name:
            continue
        vals = {}
        for key, element, money in (
                ("shares", "TotalNumberOfStocksEtcHeld", False),
                ("ratio", "HoldingRatioOfShareCertificatesEtc", False),
                ("prior", "HoldingRatioOfShareCertificatesEtcPerLastReport", False),
                ("own", "AmountOfOwnFund", True),
                ("borrow", "TotalAmountOfBorrowings", True),
                ("funding", "TotalAmountOfFundingForAcquisition", True)):
            v = take(element, no, money)
            if v == "messy":
                messy += 1
                v = None
            vals[key] = v
        # The answer lives in one of TWO elements. When the holder states an
        # act it is tagged 重要提案行為等; when it states none, most form
        # generators leave that element empty and put 該当事項なし in the
        # …NA twin. Reading only the first left 89% of holders as "not
        # stated" — an unknown where the filing gives a plain no, which
        # makes an activist filter useless.
        business_ja = clean_text(first(facts, "DescriptionOfBusiness", no))
        occupation_ja = clean_text(first(facts, "Occupation", no))
        proposal_ja = (first(facts, "ActOfMakingImportantProposalEtc", no).strip()
                       or first(facts, "ActOfMakingImportantProposalEtcNA", no).strip())
        kind_ja = first(facts, "IndividualOrCorporation", no).strip()
        ecode = (first(facts, "EDINETCodeDEI", no) or "").strip() or None
        # A holder that has no EDINET registration of its own is sometimes
        # given the ISSUER's code by the filer's own XBRL tool. Be Brave, an
        # activist vehicle, files on three companies and carries a different
        # target's code each time — so its stakes split three ways and each
        # one lands on the code of the company it is challenging. The code is
        # only an identity when it is not the issuer's.
        if ecode and issuer_code and ecode == issuer_code and norm(name) != norm(issuer_name or ""):
            problems.append("holder %d filed under the issuer's own EDINET code "
                            "(%s); identified by name instead" % (no, ecode))
            ecode = None
        mstat, ec, sc = resolve_holder(ecode, name)
        # A holder counts toward the group position only where the filing gives
        # it a CURRENT figure (trap 4).
        current = vals["ratio"] is not None or vals["shares"] is not None
        in_total += 1 if current else 0
        holders.append((doc_id, no, name, clean_english_name(first(facts, "FilerNameInEnglishDEI", no)),
                        first(facts, "ResidentialAddressOrAddressOfRegisteredHeadquarter", no).strip() or None,
                        kind_ja or None, (u"個人" in kind_ja) if kind_ja else None,
                        ec, sc, mstat, to_int(vals["shares"]), vals["ratio"],
                        vals["prior"], current, first(facts, "PurposeOfHolding", no).strip() or None,
                        proposal_ja or None,
                        (None if special or not proposal_ja else not stated_none(proposal_ja)),
                        to_int(vals["own"]), to_int(vals["borrow"]),
                        to_int(vals["funding"]), norm(name), business_ja,
                        occupation_ja))

    # ---- the group position ------------------------------------------------
    group = {}
    for key, element, money in (
            ("shares", "TotalNumberOfStocksEtcHeld", False),
            ("ratio", "HoldingRatioOfShareCertificatesEtc", False),
            ("prior", "HoldingRatioOfShareCertificatesEtcPerLastReport", False),
            ("outstanding", "TotalNumberOfOutstandingStocksEtc", False),
            ("own", "AmountOfOwnFund", True),
            ("borrow", "TotalAmountOfBorrowings", True)):
        v = take(element, 0, money)
        if v == "messy":
            messy += 1
            v = None
        group[key] = v
    # A single-holder filing states its position once, in the holder's own
    # context; there is no separate group line to read.
    singles = [h for h in holders if h[13]]
    if group["shares"] is None and len(singles) == 1:
        group["shares"] = singles[0][10]
    if group["ratio"] is None and len(singles) == 1:
        group["ratio"] = singles[0][11]
    if group["prior"] is None and len(singles) == 1:
        group["prior"] = singles[0][12]
    if group["outstanding"] is None:
        # Stated per holder context in single-filer reports. It is the issuer's
        # figure, so every context should carry the same number; where they
        # disagree the most-stated one is taken rather than the first seen.
        seen = defaultdict(int)
        for h in holders:
            v = take("TotalNumberOfOutstandingStocksEtc", h[1])
            if v not in (None, "messy"):
                seen[v] += 1
        if seen:
            group["outstanding"] = max(sorted(seen), key=lambda v: seen[v])

    # ---- gates -------------------------------------------------------------
    # Every gate here is ONE-SIDED, and each side is the form's own arithmetic
    # rather than a symmetric band chosen for convenience:
    #
    #   G1/G2  The group line is the holders' positions MINUS the form's own
    #          deduction for claims between joint holders (共同保有者間で引渡
    #          請求権等の権利が存在するものとして控除する株券等の数). So the
    #          holders can legitimately sum to more than the group total, and
    #          a group total the holders cannot cover is the defect.
    #   G3     The statutory ratio divides by 発行済株式等総数 PLUS the
    #          holder's own potential shares, and subtracts underwritten
    #          shares from the numerator — so the filed ratio is at or below
    #          held/outstanding by construction, and only a filed ratio ABOVE
    #          that identity is evidence of a wrong figure. Checking equality
    #          would have failed one filing in six on the statute, not on the
    #          data.
    share_rows = [h[10] for h in holders if h[13] and h[10] is not None]
    if len(share_rows) > 1 and group["shares"] is not None:
        if sum(share_rows) < group["shares"]:                               # G1
            problems.append("G1 holder shares sum to %d, short of the filed "
                            "group total %d" % (sum(share_rows), group["shares"]))
    ratio_rows = [h[11] for h in holders if h[13] and h[11] is not None]
    if len(ratio_rows) > 1 and group["ratio"] is not None:
        # Each holder's ratio is printed to two decimals.
        if sum(ratio_rows) < group["ratio"] - 0.005 * len(ratio_rows) - 1e-9:  # G2
            problems.append("G2 holder ratios sum to %.2f%%, short of the filed "
                            "%.2f%%" % (sum(ratio_rows), group["ratio"]))
    if group["ratio"] is not None and group["shares"] and group["outstanding"]:
        calc = 100.0 * group["shares"] / group["outstanding"]
        if group["ratio"] > calc + 0.01 + 1e-9:                             # G3
            problems.append("G3 filed ratio %.2f%% exceeds %d/%d = %.2f%%"
                            % (group["ratio"], group["shares"],
                               group["outstanding"], calc))
    if group["ratio"] is not None and not 0 <= group["ratio"] <= 100:        # G4
        problems.append("G4 holding ratio %.2f%% is outside 0-100" % group["ratio"])
    req = jp_date(first(facts, "DateWhenFilingRequirementAroseCoverPage", 0))
    if req and submitted and req > submitted:                                # G5
        # An obligation cannot arise after the report that discloses it. Both
        # dates stay exactly as filed; this says the filer typed one wrong
        # (Asahicho wrote 2027 for 2026).
        problems.append("G5 obligation date %s is after the submission date %s"
                        % (req, submitted))
    cover = jp_date(first(facts, "FilingDateCoverPage", 0))
    if cover and submitted and cover > submitted:                            # G6
        # A document cannot be dated after the day EDINET received it. The
        # test is one-sided on purpose: a cover page dated days or months
        # BEFORE submission is ordinary — the filer dates the document when it
        # is drawn up, and a correction restates the original report's date
        # (482 filings are more than 60 days apart on that account alone).
        # Only the impossible direction is a defect, and it caught one filing
        # in 3,893: a Trusco corrector dated a 2026 filing 2028.
        problems.append("G6 cover page dated %s, after EDINET received it on %s"
                        % (cover, submitted))

    proposals = [h[16] for h in holders if h[16] is not None]

    row = {
        "doc_id": doc_id, "doc_type": doc_type, "form": form,
        "report_type": report_type, "change_no": change_no,
        "is_special_form": special,
        "filer_edinet_code": (first(facts, "EDINETCodeDEI", 0) or "").strip() or None,
        "filer_name": (holders[0][2] if holders else None),
        "issuer_name_raw": issuer_name, "issuer_sec_code": sec,
        "issuer_edinet_code": iec, "issuer_match_status": imstat,
        "listing": first(facts, "ListedOrOTC", 0).strip() or None,
        "exchange": first(facts, "StockListing", 0).strip() or None,
        "requirement_date": jp_date(first(facts, "DateWhenFilingRequirementAroseCoverPage", 0)),
        # The cover page's own filing date is typed by the filer and is
        # sometimes years out (a correction filed in 2026 dated 2028). The
        # authoritative publication date is EDINET's own submitDateTime, set by
        # the system that received the document, and main() supplies it;
        # cover_date keeps what the filer wrote so the two can be compared.
        "cover_date": jp_date(first(facts, "FilingDateCoverPage", 0)),
        "holders_declared": to_int(clean_number(
            first(facts, "TotalNumberOfFilersAndJointHoldersCoverPage", 0))),
        "holders_rows": len(holders), "holders_in_total": in_total,
        "shares_held": to_int(group["shares"]),
        "shares_outstanding": to_int(group["outstanding"]),
        "ratio_pct": group["ratio"], "prior_ratio_pct": group["prior"],
        "ratio_change_pp": (round(group["ratio"] - group["prior"], 2)
                            if group["ratio"] is not None and group["prior"] is not None
                            else None),
        # True when ANY holder states an important-proposal act. The special
        # form does not carry the field, and NULL there says "not asked", not
        # "none" — the exemption itself is the undertaking.
        "important_proposal": (None if not proposals else any(proposals)),
        # Whether the form put the question at all. 第三号様式 (the change
        # report) and 第二号様式 (the special form) carry no 重要提案行為 field,
        # so a null there is "not asked" — measured, not assumed: 4,719 holder
        # rows on change reports have no such element anywhere in the package.
        # Without this a reader cannot tell a silent filer from a form that
        # never asked.
        "proposal_asked": bool(facts.get(L + "ActOfMakingImportantProposalEtc")
                               or facts.get(L + "ActOfMakingImportantProposalEtcNA")),
        "filing_reason_ja": (first(facts, "ReasonForFilingChangeReportCoverPage", 0).strip()
                             or None),
        "purpose_ja": (holders[0][14] if holders else None),
        "own_funds_yen": to_int(group["own"]),
        "borrowings_yen": to_int(group["borrow"]),
        # 取得資金 is printed in 千円 and a minority of filers type YEN into
        # that box while still tagging scale="3" — Kobe Bussan's ¥1,677,200,000
        # of own funds becomes ¥1.68tn for 1.4m shares, a thousand times any
        # price that has ever existed. The amounts stay exactly as filed; this
        # flag says where the implied cost per share is impossible, so a page
        # can decline to print a number rather than print a wrong one.
        "funding_implausible": implausible_funding(holders, group),
        "messy_facts": messy,
    }
    return row, holders, problems


# ---- filing discovery ------------------------------------------------------
LVH_TYPES = ("350", "360")


def local_t1_filings():
    out = {}
    with open(os.path.join(ARCHIVE, "manifest.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if (r.get("status") == "ok" and r.get("doc_type") in LVH_TYPES
                    and str(r.get("dl_type")) == "1"):
                out[r["doc_id"]] = r
    return out


def s3_t1_filings(src, start_after=None):
    out = {}
    for key in src._keys("docs/", start_after):
        parts = key.split("/")                    # docs/YYYY-MM-DD/DOCID_t1.zip
        if len(parts) != 3 or not parts[2].endswith("_t1.zip"):
            continue
        out[parts[2][:-len("_t1.zip")]] = {"date": parts[1]}
    return out


def read_t1(src, doc_id, date):
    if src.name == "local":
        with open(os.path.join(ARCHIVE, "docs", date, doc_id + "_t1.zip"), "rb") as f:
            return f.read()
    key = "docs/%s/%s_t1.zip" % (date, doc_id)
    return src.c.get_object(Bucket=src.bucket, Key=key)["Body"].read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("local", "s3"), default="local")
    ap.add_argument("--all", action="store_true",
                    help="kept for symmetry with the other extractors; this "
                         "form has no listed/unlisted filter to apply")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--docs", help="comma-separated docIDs — re-extract just these")
    ap.add_argument("--new-only", action="store_true",
                    help="extract only filings archived since the last "
                         "recorded run (plus a lookback); what the nightly "
                         "refresh uses. A DB with no recorded run is built "
                         "in full, so this is always safe to pass.")
    ap.add_argument("--no-compact", action="store_true")
    args = ap.parse_args()

    src = S3Source(args.workers) if args.source == "s3" else LocalSource()
    codelist = load_codelist()
    tiers = build_index(codelist)
    by_sec, by_code = {}, {}
    for d in codelist:
        code = d.get(u"ＥＤＩＮＥＴコード")
        if not code:
            continue
        by_code[code] = d
        sec = (d.get(u"証券コード") or "")[:4]
        if sec:
            by_sec.setdefault(sec, []).append(d)

    # Window first, so the bucket listing can seek to it.
    since, have = (incremental_window(args.db, "5pct-filings", "eq_lvh_filings")
                   if args.new_only else (None, set()))
    filings = (local_t1_filings() if src.name == "local"
               else s3_t1_filings(src, seek_key(since)))
    through = max((r["date"] for r in filings.values()), default=None)
    pending = dict(filings) if since is None else {
        d: r for d, r in filings.items() if r["date"] >= since and d not in have}
    if since is not None:
        print("incremental: %d of %d archived filings are new since %s"
              % (len(pending), len(filings), since))
    meta = src.list_metadata(
        days=None if since is None else {r["date"] for r in pending.values()})
    targets = []
    for doc_id, rec in sorted(pending.items()):
        m = meta.get(doc_id) or {}
        doc_type = m.get("docTypeCode") or rec.get("doc_type")
        if doc_type not in LVH_TYPES:
            continue
        targets.append((doc_id, rec, m, doc_type))
    if args.docs:
        want = {d.strip() for d in args.docs.split(",") if d.strip()}
        targets = [t for t in targets if t[0] in want]
    if args.limit:
        targets = targets[:args.limit]
    dates = sorted({rec["date"][:4] for _, rec, _, _ in targets})
    print("target filings: %d (source=%s) filed %s"
          % (len(targets), src.name, "/".join(dates)))

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)
    # A database written by an earlier parser has the table already, and
    # CREATE TABLE IF NOT EXISTS will not add a column to it. Add rather than
    # rebuild, so a re-extraction stays a re-extraction.
    have = {r[1] for r in con.execute("PRAGMA table_info('eq_lvh_filings')").fetchall()}
    for col, typ in (("proposal_asked", "BOOLEAN"),
                     ("funding_implausible", "BOOLEAN"),
                     ("cover_date", "DATE")):
        if col not in have:
            con.execute("ALTER TABLE eq_lvh_filings ADD COLUMN %s %s" % (col, typ))

    def resolve_issuer(sec, name):
        u"""The issuer's securities code is filed, so this is a lookup, not a
        match. The name is a fallback for the handful of filings that state an
        issuer with no code (unlisted OTC issuers)."""
        if sec:
            hits = by_sec.get(sec) or []
            listed = [d for d in hits if d.get(u"上場区分") == u"上場"]
            pool = listed or hits
            if len(set(d[u"ＥＤＩＮＥＴコード"] for d in pool)) == 1:
                return "matched", pool[0][u"ＥＤＩＮＥＴコード"]
            if pool:
                return "ambiguous", None
        if name:
            for tier, key in zip(tiers, (norm(name), core_name(name), base_name(name))):
                hit = pick(tier.get(key) or [], None, None)
                if hit:
                    return "matched_by_name", hit[0]
        return ("foreign" if name and is_foreign(name) else "unmatched"), None

    def resolve_holder(ecode, name):
        u"""The holder files under its own EDINET code, so the code is the
        match. Name matching is a fallback only."""
        if ecode and ecode in by_code:
            d = by_code[ecode]
            return "matched", ecode, (d.get(u"証券コード") or "")[:4] or None
        if ecode:
            return "code_not_in_registry", ecode, None
        for tier, key in zip(tiers, (norm(name), core_name(name), base_name(name))):
            hit = pick(tier.get(key) or [], None, None)
            if hit:
                return "matched_by_name", hit[0], hit[1] or None
        return ("foreign" if is_foreign(name or "") else "unmatched"), None, None

    def fetch_and_parse(t):
        doc_id, rec, m, doc_type = t
        sha = None
        try:
            blob = read_t1(src, doc_id, rec["date"])
            sha = hashlib.sha256(blob).hexdigest()
            return t, parse_package(blob), sha, None
        except NoFacts as e:
            return t, None, sha, ("no_inline_xbrl", str(e)[:160])
        except Exception as e:                                       # noqa: BLE001
            return t, None, sha, ("failed", "%s: %s" % (type(e).__name__, str(e)[:160]))

    stats = defaultdict(int)
    tot_holders = tot_proposal = 0
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(fetch_and_parse, t) for t in targets]
        for fut in as_completed(futures):
            (doc_id, rec, m, doc_type), parsed, sha, err = fut.result()
            done += 1
            if done % 2000 == 0:
                print("  %d/%d filings" % (done, len(targets)))
                sys.stdout.flush()
            con.execute("DELETE FROM eq_lvh_holders WHERE doc_id = ?", [doc_id])
            con.execute("DELETE FROM eq_lvh_filings WHERE doc_id = ?", [doc_id])
            if err:
                st, detail = err
                stats[st] += 1
                blank = dict((c, None) for c in FILING_COLUMNS)
                blank.update({"doc_id": doc_id, "doc_type": doc_type,
                              "filer_name": rec.get("filer") or m.get("filerName"),
                              "filed_date": rec["date"], "sha256": sha,
                              "parser_version": PARSER_VERSION,
                              "status": st, "detail": detail})
                con.execute(FILING_INSERT, [blank[c] for c in FILING_COLUMNS])
                continue
            facts, form = parsed
            submitted = (m.get("submitDateTime") or "")[:10] or rec["date"]
            row, holders, problems = build(doc_id, doc_type, facts, form, submitted,
                                           resolve_issuer, resolve_holder)
            if not holders or row["ratio_pct"] is None:
                status = "partial"
                problems.insert(0, "no holder rows" if not holders
                                else "no holding ratio stated")
            elif problems:
                status = "partial"
            else:
                status = "clean"
            stats[status] += 1
            row.update({"sha256": sha, "parser_version": PARSER_VERSION,
                        "status": status,
                        "detail": "; ".join(problems[:4]) or None})
            if not row.get("filer_name"):
                row["filer_name"] = rec.get("filer") or m.get("filerName")
            # EDINET's receipt date is the publication date, always.
            row["filed_date"] = submitted
            con.execute(FILING_INSERT, [row[c] for c in FILING_COLUMNS])
            if holders:
                con.executemany("INSERT INTO eq_lvh_holders VALUES (%s)"
                                % ",".join(["?"] * 23), holders)
                tot_holders += len(holders)
                tot_proposal += sum(1 for h in holders if h[16])
    con.close()
    record_run(args.db, "5pct-filings", through, len(filings), PARSER_VERSION)
    if not args.no_compact:
        compact(args.db)
    print("filings: %s" % dict(stats))
    print("holder rows: %d (%d stating an important-proposal act)"
          % (tot_holders, tot_proposal))
    print("wrote", os.path.normpath(args.db))


if __name__ == "__main__":
    main()
