# -*- coding: utf-8 -*-
u"""Tender offers (公開買付け) — the takeover tape, parser `toi-1`.

WHAT THIS READS
---------------
Five EDINET document types, all of which the capture job already archives:

    240 公開買付届出書        the offer itself: price, period, size, funding
    250 訂正公開買付届出書    every amendment — price bumps and extensions
    290 意見表明報告書        the TARGET BOARD's opinion: support or oppose
    300 訂正意見表明報告書    amendments to that opinion
    270 公開買付報告書        the result: how many shares actually came in

Only the t1 (full XBRL) package is archived for these types — the capture job
takes the CSV package for periodic reports alone — so this reads t1, like
agm_extract.py and facility_extract.py do. That is the better input anyway:
the scalar facts are in the XBRL instance, and the honbun inline-XBRL document
keeps the real HTML tables that the flattened CSV destroys (see
edinet-t5-flattens-textblocks).

ONE ROW PER DOCUMENT, NEVER PER DEAL
------------------------------------
A tender offer is a sequence of filings, not a state. The offer is filed, the
board opines, the price is raised, the period is extended, the result is
published. Collapsing that into one mutable "deal" row would overwrite the
history that makes this dataset worth having — the same reason vintages are
immutable. So every document is its own immutable row and `pair_key` groups
them, `round_no` separating one offer from the next by the same buyer for
the same target. Reconstructing the final terms is a query (ORDER BY
filed_date), and the price history falls out of it for free.

WHAT IS TAGGED AND WHAT IS NOT — the trap under this dataset
------------------------------------------------------------
Only the voting-rights ownership table is tagged as discrete numeric facts
(a/d/g/j and the two ratios). Price, period, share counts and consideration
live INSIDE text blocks, as HTML tables. They are parsed out of those tables
here, cell by cell, never by regex over flattened prose — a flattened
`株券普通株式１株につき金795円新株予約権証券―` is one string in which the
price and the next row's dash have no separator at all.

Dates are Japanese-formatted with full-width digits and a weekday in
parentheses: `2026年８月27日（木曜日）`. NFKC normalisation plus a strict
pattern; anything that does not match is left NULL rather than guessed.

GATES (a failing gate makes the row `partial` with the reason, never dropped)
-----------------------------------------------------------------------------
  G1  shares_sought x price_yen == consideration_yen, to the yen. A true
      identity in the filing: the 795-yen Seed offer prints 15,497,386 shares
      and 12,320,421,870 yen, and the product is exactly that. Skipped where
      the offer also buys warrants or convertible bonds, whose consideration
      this table does not price.
  G2  the two filed ownership ratios are between 0 and 1.

The ratios themselves are NOT gated against the tagged voting-rights table,
because they cannot be: see gates() for why, and `ratio_after_recomputed` for
what our own arithmetic says beside them.

Usage (from observatory/equity/):
    ../.venv/bin/python toi_extract.py --limit 20            # smoke test
    ../.venv/bin/python toi_extract.py --docs S100YZ5A
    ../.venv/bin/python toi_extract.py --all --source s3 --new-only   # nightly
"""
import argparse
import datetime as dt
import hashlib
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from extract import (LocalSource, S3Source, compact, DB_PATH,
                     incremental_window, record_run,
                     select_pending, catch_up_start, CATCH_UP_DAYS,
                     recorded_floor,
                     sec_code_of)
from edinet_honbun import (honbun, instance, facts, blocks, tables_in, section,
                           section_text, taxonomy_prefix, grid_of, norm,
                           jp_date, to_int, to_float, to_int_loose, YEN_NUM,
                           NoHonbun)

PARSER_VERSION = "toi-1"
EXTRACTOR = "tender-offers"

TOI_TYPES = ("240", "250", "270", "290", "300")
# The offer and its amendment share a taxonomy prefix; the opinion has its own;
# the result report a third. The form tells you which shape to expect.
FORM_OF = {"240": "offer", "250": "offer-amendment", "270": "result",
           "290": "opinion", "300": "opinion-amendment"}


class NotTenderOffer(Exception):
    """The package holds no tender-offer document we recognise."""


def form_family(blob):
    u"""`jptoo` (someone bidding for another company) or `jptoi` (a company
    tendering for its OWN shares).

    They are different documents with different headings, and they are
    different events: a jptoi offer is a buyback executed as a tender, which
    belongs beside the 自己株券買付状況報告書 data, not beside a takeover. The
    taxonomy prefix on the instance filename is the authority; nothing else in
    the filing says it as plainly.
    """
    return taxonomy_prefix(blob)


def price_from(bl, html):
    u"""Ordinary-share offer price, from the 買付け等の価格 table.

    One row per security class; the 株券 row holds `普通株式１株につき　金795円`.
    A price quoted for warrants or convertible bonds is deliberately not
    stored here — those are different instruments, and mixing them into one
    `price_yen` column would make a cross-section meaningless.
    """
    h = section(bl, html, ("PriceOfPurchaseEtcTextBlock",),
                (u"【買付け等の価格】", u"【買付け等の価格等】"))
    if not h:
        return None, False
    other = False
    price = None
    for t in tables_in(h):
        cells, _ = grid_of(t)
        for row in cells:
            label = norm(row[0] if row else "")
            body = " ".join(norm(c) for c in row[1:])
            m = YEN_NUM.search(body)
            if label.startswith(u"株券") or u"株につき" in body:
                if price is None and m:
                    price = to_int_loose(m.group(1))
            elif m and (u"新株予約権" in label or u"社債" in label):
                other = True           # a multi-instrument offer: see gates()
    if price is None:
        m = re.search(u"(?:普通株式)?\\s*[1１]\\s*株につき\\s*金?\\s*([0-9][0-9,\uff0c ]*)\\s*円",
                      norm(re.sub(r"<[^>]+>", " ", h)))
        price = to_int_loose(m.group(1)) if m else None
    return price, other


def shares_from(bl, html):
    u"""(sought, minimum, maximum) from the 買付予定の株券等の数 table.

    `―` in the upper-limit column means there is no cap. That is a real fact,
    stored as NULL; storing it as 0 would read as "buying nothing".
    """
    h = section(bl, html,
                ("NumberOfShareCertificatesEtcIntendedToPurchaseTextBlock",),
                (u"【買付予定の株券等の数】", u"【買付予定の上場株券等の数】"))
    for t in tables_in(h):
        cells, _ = grid_of(t)
        if not cells:
            continue
        header = None
        for r, row in enumerate(cells[:3]):
            if u"買付予定数" in " ".join(norm(c) for c in row):
                header = (r, [norm(c) for c in row])
                break
        if header is None:
            continue
        hr, hcells = header
        col = {}
        for i, hh in enumerate(hcells):
            if u"下限" in hh:
                col["min"] = i
            elif u"上限" in hh:
                col["max"] = i
            elif u"買付予定数" in hh:
                col.setdefault("sought", i)
        if "sought" not in col:
            continue
        best = None
        for row in cells[hr + 1:]:
            label = norm(row[0] if row else "")
            v = to_int(row[col["sought"]]) if col["sought"] < len(row) else None
            if v is None:
                continue
            cand = (v,
                    to_int(row[col["min"]]) if col.get("min", 99) < len(row) else None,
                    to_int(row[col["max"]]) if col.get("max", 99) < len(row) else None)
            if label.startswith(u"合計"):
                return cand
            if best is None:
                best = cand
        if best:
            return best
    return (None, None, None)


def consideration_from(bl, html):
    u"""買付代金（円）(a) — the cash the offeror must find."""
    h = section(bl, html, ("FundEtcForPurchaseEtcTextBlock",),
                (u"【買付け等に要する資金等】", u"【買付け等に要する資金】",
                 u"【買付け等に要する資金に充当しうる預金又は借入金等】"))
    for t in tables_in(h):
        cells, _ = grid_of(t)
        for row in cells:
            for i, c in enumerate(row):
                if u"買付代金" in norm(c):
                    for cell in row[i + 1:]:
                        v = to_int(cell)
                        if v is not None:
                            return v
    m = re.search(u"買付代金\\s*[（(]?円[）)]?\\s*\\(?a\\)?\\s*([0-9][0-9,]{5,})",
                  norm(re.sub(r"<[^>]+>", " ", h)))
    return int(m.group(1).replace(",", "")) if m else None


PERIOD_RE = re.compile(u"(\\d{4}年\\s*\\d{1,2}月\\s*\\d{1,2}日)[^0-9]{0,20}?から"
                       u"\\s*(\\d{4}年\\s*\\d{1,2}月\\s*\\d{1,2}日)[^0-9]{0,20}?まで")


def period_from(bl, html):
    text = section_text(bl, html,
                        ("PeriodOfPurchaseEtcTextBlock", "TenderOfferPeriodTextBlock"),
                        (u"【買付け等の期間】", u"【公開買付期間】"))
    m = PERIOD_RE.search(text)
    if not m:
        text = section_text(bl, html, ("OverviewOfPurchaseEtcTextBlock",),
                            (u"【買付け等の概要】",))
        m = PERIOD_RE.search(text)
    if not m:
        return (None, None)
    return (jp_date(m.group(1)), jp_date(m.group(2)))


PURPOSES = [(u"非公開化", "going-private"),
            (u"完全子会社化", "wholly-owned"),
            (u"子会社化", "subsidiary"),
            (u"持分法適用関連会社", "equity-method"),
            (u"自己株式", "self-tender"),
            (u"支配株主", "control")]


def purpose_from(bl, html):
    u"""What the buyer says the offer is FOR, e.g. 非公開化 (going private).

    In the overview table it is one labelled row; in prose it is the sentence
    right after the words 公開買付けの目的. Both are read; neither is guessed at
    from the rest of the document.
    """
    label = None
    h = section(bl, html, ("OverviewOfPurchaseEtcTextBlock",), (u"【買付け等の概要】",))
    for t in tables_in(h):
        cells, _ = grid_of(t)
        for row in cells:
            if row and u"公開買付けの目的" in norm(row[0]):
                rest = [norm(c) for c in row[1:] if norm(c)]
                if rest:
                    label = rest[0][:40]
                    break
        if label:
            break
    if not label:
        text = section_text(bl, html,
                            ("OverviewOfPurchaseEtcTextBlock", "PurposesOfPurchaseEtcTextBlock"),
                            (u"【買付け等の概要】", u"【買付け等の目的】"))
        m = re.search(u"公開買付けの目的\\s*([^\\s]{2,14}?)\\s*(?:買付け等の期間|買付け等の価格|$)", text)
        if m:
            label = m.group(1)
    key = None
    hay = label or section_text(bl, html, ("PurposesOfPurchaseEtcTextBlock",),
                                (u"【買付け等の目的】",))[:600]
    for jp, en in PURPOSES:
        if jp in hay:
            key = en
            break
    return label, key


# The board's answer is the point of the whole document, and it is a sentence,
# not a tag. 賛同 / 反対 / 留保 are the three the rules contemplate; the second
# half — whether shareholders are told to TENDER — is a separate decision and a
# board can support an offer without recommending it.
STANCE = [(u"反対する旨", "oppose"), (u"反対の意見", "oppose"),
          (u"留保する", "neutral"), (u"意見を留保", "neutral"),
          (u"中立の立場", "neutral"),
          (u"賛同する旨", "support"), (u"賛同の意見", "support"),
          (u"賛同いたします", "support")]


def opinion_from(bl, html):
    u"""(stance, recommends_tender, resolved_date) from the board's opinion.

    Two separate decisions live in this section and they do not always agree:
    a board can support an offer and still decline to tell shareholders to
    tender into it (typically when the price is fair but a squeeze-out is not
    assured). They are stored separately for that reason.
    """
    text = section_text(
        bl, html,
        ("OpinionAndBasisAndReasonOfOpinionRegardingSaidTenderOfferTextBlock",
         "OpinionRegardingSaidTenderOfferAndBasisAndReasonsEtcTextBlock"),
        (u"【当該公開買付けに関する意見の内容、根拠及び理由】", u"【意見の内容】"))
    if not text:
        return (None, None, None)
    head = text[:4000]
    stance = None
    for jp, en in STANCE:
        if jp in head:
            stance = en
            break
    recommends = None
    if u"応募することを推奨" in head or u"応募することを勧め" in head:
        recommends = True
    elif (u"応募するか否かについては" in head or u"応募の判断は" in head
            or u"応募するか否かにつきましては" in head
            or u"応募については" in head):
        recommends = False
    resolved = None
    m = re.search(u"(\\d{4}年\\s*\\d{1,2}月\\s*\\d{1,2}日)\\s*(?:開催の)?取締役会", head)
    if m:
        resolved = jp_date(m.group(1))
    return (stance, recommends, resolved)


def result_from(bl, html):
    u"""(tendered, purchased, succeeded) from the result report.

    THE SAME FACT ARRIVES IN TWO ORIENTATIONS. An issuer's self-tender prints
    one row per figure — `応募数(株) | 83,403,785`. A third party's result
    prints one row per SECURITY CLASS with the figures as columns —
    `株券等の種類 | 株式に換算した応募数 | 株式に換算した買付数`. Reading only
    the first shape silently returns nothing for most takeovers, so the header
    is inspected first and the table read the way it is actually laid out.

    Success is a separate disclosure and the one that matters: an offer whose
    minimum is not met buys nothing at all, however many shares were tendered.
    """
    h = section(bl, html,
                ("NumberOfShareCertificatesEtcAcquiredByPurchaseEtcTextBlock",
                 "NumberOfListedShareCertificatesEtcAcquiredByPurchaseEtcTextBlock"),
                (u"【買付け等を行った株券等の数】", u"【買付け等を行った上場株券等の数】"))
    tendered = purchased = None
    for t in tables_in(h):
        cells, _ = grid_of(t)
        if not cells:
            continue
        head = [norm(c) for c in cells[0]]
        joined = " ".join(head)
        if u"応募" in joined and u"買付" in joined:
            ci = {}
            for k, cell in enumerate(head):
                if u"応募" in cell:
                    ci.setdefault("t", k)
                elif u"買付" in cell:
                    ci.setdefault("p", k)
            best = None
            for row in cells[1:]:
                label = norm(row[0] if row else "")
                tv = to_int(row[ci["t"]]) if ci.get("t") is not None and ci["t"] < len(row) else None
                pv = to_int(row[ci["p"]]) if ci.get("p") is not None and ci["p"] < len(row) else None
                if tv is None and pv is None:
                    continue
                if label.startswith(u"合計"):
                    best = (tv, pv)
                    break
                if best is None and label.startswith(u"株券"):
                    best = (tv, pv)
            if best:
                tendered, purchased = best
                break
        else:
            for row in cells:
                label = " ".join(norm(c) for c in row[:2])
                nums = [n for n in (to_int(c) for c in row) if n is not None]
                if not nums:
                    continue
                if tendered is None and u"応募" in label:
                    tendered = nums[-1]
                elif purchased is None and u"買付" in label:
                    purchased = nums[-1]
            if tendered is not None or purchased is not None:
                break
    ok = section_text(bl, html, ("SuccessOrFailureOfTenderOfferTextBlock",),
                      (u"【公開買付けの成否】",))
    # MOST RESULT REPORTS NEVER USE THE WORD 成立. They recite the minimum as a
    # condition and then state the outcome: "応募株券等の総数(11,482,008株)が
    # 買付予定数の下限(7,073,300株)以上となりましたので…買付け等を行います".
    # The conditional clause always contains the failure wording (満たない場合
    # は…行わない), so the failure markers are tested on the PAST tense only,
    # and tested first.
    succeeded = None
    if ok:
        if (u"不成立" in ok or u"成立しませんでした" in ok
                or u"満たなかった" in ok or u"買付け等を行いません" in ok):
            succeeded = False
        elif (u"以上となりました" in ok or u"買付け等を行います" in ok
                or u"成立" in ok):
            succeeded = True
    return (tendered, purchased, succeeded)


# ---------------------------------------------------------------- assembling

# THE DENOMINATOR IS NOT ALWAYS j, AND IT IS NOT TAGGED.
# The two filed ratios look like they divide by the target's total voting
# rights (j). Often they do not. Where odd-lot shares are also being bought,
# the filer says so in a footnote and divides by the voting rights of the
# WHOLE base share count instead: Seed's offer prints j = 302,411 but computes
# both ratios over 302,657. Checking the filed ratio against j therefore fails
# on a filing that is perfectly correct. The note is prose, so the real
# denominator is read from it and stored alongside the ratios; a reader can
# then see which number the percentage is a percentage OF, which is the whole
# point of the trust contract. This is the same trap as the AGM approval
# percentage: the denominator behind a filed percentage is the filer's, never
# ours to assume.
DENOM_RE = re.compile(u"議決権(?:の)?数\\s*[（(]?\\s*([0-9][0-9,]*)\\s*個\\s*[）)]?"
                      u"\\s*を分母")


def denominator_from(bl, html):
    text = section_text(
        bl, html,
        ("NotesHoldingRatioOfShareCertificatesEtcAfterPurchaseEtcTextBlock",
         "HoldingRatioOfShareCertificatesEtcAfterPurchaseEtcTextBlock"),
        (u"【買付け等を行った後における株券等所有割合】",))
    m = DENOM_RE.search(text)
    return int(m.group(1).replace(",", "")) if m else None


VOTE_FACTS = {
    "votes_sought": "NumberOfVotingRightsRepresentedByShareCertificatesEtcToBePurchasedA",
    "votes_offeror": "NumberNumberOfVotingRightsRepresentedByShareCertificatesEtcOwnedByTenderOfferorD",
    "votes_special": "NumberNumberOfVotingRightsRepresentedByShareCertificatesEtcOwnedBySpecialInterestPartiesG",
    "votes_total": "NumberNumberOfVotingRightsOwnedByAllShareholdersEtcOfSubjectCompanyJ",
}
RATIO_FACTS = {
    "ratio_sought": "RatioOfNumberOfVotingRightsRepresentedByShareCertificatesEtc"
                    "ToBePurchasedAmongNumberOfVotingRightsOwnedByAllShareholdersEtc"
                    "OfSubjectCompany",
    "ratio_after": "HoldingRatioOfShareCertificatesEtcAfterPurchaseEtc",
}


def _first(fx, *names):
    for n in names:
        v = fx.get(n)
        if v:
            return v
    return None


def parse(blob, doc_type):
    html = honbun(blob)
    family = form_family(blob)
    bl = blocks(html)
    fx = facts(instance(blob))
    if not bl and not fx:
        raise NotTenderOffer("no inline-XBRL content")

    # form_family keeps the full form code (jptoo020000, jptoi040000 …) because
    # the last digits distinguish an offer from a result; the first five say
    # who is buying, which is what self_tender means.
    row = {"form": FORM_OF.get(doc_type), "form_family": family,
           "self_tender": None if family is None else family.startswith("jptoi")}

    # --- identity -------------------------------------------------------
    row["offeror_name"] = _first(
        fx, "FullNameOrNameOfFilerOfNotificationCoverPage", "NameOfFilerCoverPage",
        "FullNameOrNameCoverPage")
    row["target_name"] = None
    tn = section_text(bl, html, ("NameOfSubjectCompanyTextBlock",),
                      (u"【対象者名】",))
    if tn:
        row["target_name"] = norm(re.sub(u"^[０-９0-9]*\\s*【?対象者名】?", "", tn)).strip()
    row["filed_date"] = jp_date(_first(fx, "FilingDateCoverPage") or "")
    row["amendment_of"] = _first(fx, "IdentificationOfDocumentSubjectToAmendmentDEI")
    if row["amendment_of"] in (u"－", "-", u"―"):
        row["amendment_of"] = None
    n = _first(fx, "NumberOfSubmissionDEI")
    row["submission_no"] = to_int(n) if n else None

    # An opinion report is filed BY the target, so the two names swap round.
    if doc_type in ("290", "300"):
        row["target_name"] = row["offeror_name"]
        off = section_text(
            bl, html,
            ("NameAndResidentialAddressOrLocationOfTenderOfferorTextBlock",
             "NameAndResidentialAddressOrLocationOfTenderOffererTextBlock"),
            (u"【公開買付者の氏名又は名称及び住所又は所在地】",))
        off = re.sub(u"^[０-９0-9]*\\s*【[^】]*】", "", off).strip()
        m = re.search(u"名称\\s*(.{2,120}?)\\s*(?:所在地|住所)", off)
        row["offeror_name"] = norm(m.group(1)) if m else None

    # --- terms ----------------------------------------------------------
    row["price_yen"], row["multi_instrument"] = price_from(bl, html)
    row["shares_sought"], row["shares_min"], row["shares_max"] = shares_from(bl, html)
    row["consideration_yen"] = consideration_from(bl, html)
    row["period_start"], row["period_end"] = period_from(bl, html)
    row["purpose_ja"], row["purpose"] = purpose_from(bl, html)
    row["settlement_start"] = jp_date(section_text(
        bl, html, ("DateOfCommencementOfSettlementTextBlock",), (u"【決済の開始日】",)))

    for k, el in VOTE_FACTS.items():
        row[k] = to_int(fx.get(el))
    for k, el in RATIO_FACTS.items():
        row[k] = to_float(fx.get(el))
    row["denominator_votes"] = denominator_from(bl, html)

    row["opinion_stance"], row["opinion_recommends_tender"], row["opinion_resolved_date"] = \
        opinion_from(bl, html)
    row["shares_tendered"], row["shares_purchased"], row["succeeded"] = \
        result_from(bl, html)
    return row


# --------------------------------------------------------------------- gates

def gates(row):
    u"""Return (problems, checked, passed). Never mutates a filed number.

    WHAT IS GATED AND WHAT IS ONLY MEASURED
    ---------------------------------------
    G1, the cash identity, is a true identity and is gated: shares x price is
    the consideration, to the yen. It is skipped for an offer that also buys
    warrants or convertible bonds, where the consideration covers instruments
    this table does not price.

    The two OWNERSHIP RATIOS are not gated, and deliberately so. They look
    recomputable from the tagged voting-rights table and they are not: the
    denominator is routinely NOT the tagged total (j) but a base share count
    disclosed in a footnote in prose, which differs per filer, and the
    numerator follows the filer's reading of who counts as a special related
    party. Measured over the archive, recomputing them from the tagged facts
    disagrees with the filed figure often enough that a gate would mark good
    filings bad. This is the same trap as the AGM approval percentage: the
    filed percentage is the official number and is stored exactly as filed;
    our arithmetic is kept beside it in `ratio_after_recomputed`, clearly
    derived, with `ratio_consistent` saying whether the two agree. Publishing
    our version as if it were the company's would breach the trust contract.

    What IS gated about them is impossibility: a share of a total cannot
    exceed 1 or fall below 0. That catches a misread cell without pretending
    we know the filer's denominator.
    """
    problems, checked, passed = [], 0, 0

    if (row.get("shares_sought") and row.get("price_yen")
            and row.get("consideration_yen") and not row.get("multi_instrument")):
        checked += 1
        want = row["shares_sought"] * row["price_yen"]
        if want == row["consideration_yen"]:
            passed += 1
        else:
            problems.append("G1 consideration %d != %d x %d"
                            % (row["consideration_yen"], row["shares_sought"],
                               row["price_yen"]))
    for key in ("ratio_sought", "ratio_after"):
        v = row.get(key)
        if v is None:
            continue
        checked += 1
        if 0.0 <= v <= 1.0:
            passed += 1
        else:
            problems.append("G2 %s out of range: %.4f" % (key, v))
    return problems, checked, passed


def recompute_ratio(row):
    u"""Our own reading of the post-offer ownership share, always labelled.

    Uses the footnote denominator when the filer disclosed one, else the
    tagged total. Rounded the way the filings round (third decimal of the
    percentage). Never overwrites the filed figure.
    """
    denom = row.get("denominator_votes") or row.get("votes_total")
    if not denom:
        return None, None
    held = (row.get("votes_sought") or 0) + (row.get("votes_offeror") or 0) \
        + (row.get("votes_special") or 0)
    calc = round(float(held) / denom, 4)
    filed = row.get("ratio_after")
    consistent = None if filed is None else abs(calc - filed) <= 0.00005
    return calc, consistent


# -------------------------------------------------------------------- schema

SCHEMA_SQL = u"""
CREATE TABLE IF NOT EXISTS eq_toi_filings (
    doc_id VARCHAR PRIMARY KEY,
    doc_type VARCHAR,
    form VARCHAR,
    form_family VARCHAR,
    self_tender BOOLEAN,
    pair_key VARCHAR,
    round_no INTEGER,
    amendment_of VARCHAR,
    submission_no INTEGER,
    offeror_edinet_code VARCHAR,
    offeror_name VARCHAR,
    target_edinet_code VARCHAR,
    target_sec_code VARCHAR,
    target_name VARCHAR,
    filed_date DATE,
    purpose VARCHAR,
    purpose_ja VARCHAR,
    price_yen BIGINT,
    period_start DATE,
    period_end DATE,
    settlement_start DATE,
    shares_sought BIGINT,
    shares_min BIGINT,
    shares_max BIGINT,
    consideration_yen BIGINT,
    votes_sought BIGINT,
    votes_offeror BIGINT,
    votes_special BIGINT,
    votes_total BIGINT,
    ratio_sought DOUBLE,
    ratio_after DOUBLE,
    denominator_votes BIGINT,
    ratio_after_recomputed DOUBLE,
    ratio_consistent BOOLEAN,
    opinion_stance VARCHAR,
    opinion_recommends_tender BOOLEAN,
    opinion_resolved_date DATE,
    shares_tendered BIGINT,
    shares_purchased BIGINT,
    succeeded BOOLEAN,
    multi_instrument BOOLEAN,
    sha256 VARCHAR,
    parser_version VARCHAR,
    status VARCHAR,
    detail VARCHAR,
    gate_checked INTEGER,
    gate_passed INTEGER);
"""

COLS = ["doc_id", "doc_type", "form", "form_family", "self_tender", "pair_key", "round_no", "amendment_of", "submission_no",
        "offeror_edinet_code", "offeror_name", "target_edinet_code",
        "target_sec_code", "target_name", "filed_date", "purpose", "purpose_ja",
        "price_yen", "period_start", "period_end", "settlement_start",
        "shares_sought", "shares_min", "shares_max", "consideration_yen",
        "votes_sought", "votes_offeror", "votes_special", "votes_total",
        "ratio_sought", "ratio_after", "denominator_votes",
        "ratio_after_recomputed", "ratio_consistent", "opinion_stance",
        "opinion_recommends_tender", "opinion_resolved_date", "shares_tendered",
        "shares_purchased", "succeeded", "multi_instrument", "sha256", "parser_version", "status", "detail",
        "gate_checked", "gate_passed"]


# ------------------------------------------------------------------- sources

def s3_t1(src, start_after=None):
    out = {}
    for key in src._keys("docs/", start_after):
        p = key.split("/")
        if len(p) == 3 and p[2].endswith("_t1.zip"):
            out[p[2][:-len("_t1.zip")]] = {"date": p[1]}
    return out


def local_t1():
    import json
    from extract import ARCHIVE
    out = {}
    path = os.path.join(ARCHIVE, "manifest.jsonl")
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if (r.get("status") == "ok" and r.get("doc_type") in TOI_TYPES
                    and str(r.get("dl_type")) == "1"):
                out[r["doc_id"]] = r
    return out


def read_t1(src, doc_id, date):
    if src.name == "local":
        from extract import ARCHIVE
        with open(os.path.join(ARCHIVE, "docs", date, doc_id + "_t1.zip"), "rb") as f:
            return f.read()
    return src.c.get_object(Bucket=src.bucket,
                            Key="docs/%s/%s_t1.zip" % (date, doc_id))["Body"].read()


def pair_key_of(row, meta):
    u"""The two sides of the offer, which is what actually joins the documents.

    Not a deal id. The obvious key — target plus offer period — cannot work:
    an opinion report almost never restates the period (7% of them do), so it
    would never join the offer it answers. The pair of EDINET codes always
    works, because the daily list names both sides of every document in this
    family whichever way round they sit: on an offer the filer is the bidder
    and the subject is the target; on an opinion report it is reversed.

    A pair can run more than one offer. Kamogawa Grand Hotel was bid for at
    120 yen in December 2021 and again at 290 yen by the same buyer five weeks
    later; both rounds share this key. `round_no`, numbered below once every
    document is in, is what separates them — and the two prices are a real
    price history, not a parse error.
    """
    return "%s/%s" % (row.get("target_edinet_code") or "?",
                      row.get("offeror_edinet_code") or "?")


ROUND_SQL = u"""
UPDATE eq_toi_filings AS f SET round_no = (
    SELECT count(*) FROM eq_toi_filings o
    WHERE o.pair_key = f.pair_key AND o.form = 'offer'
      AND o.filed_date <= f.filed_date)
WHERE f.filed_date IS NOT NULL;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("local", "s3"), default="local")
    ap.add_argument("--all", action="store_true", help="kept for symmetry")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--docs", help="comma-separated docIDs — re-extract just these")
    ap.add_argument("--new-only", action="store_true",
                    help="extract only filings archived since the last recorded "
                         "run (plus a lookback); what the nightly refresh uses.")
    ap.add_argument("--no-compact", action="store_true")
    ap.add_argument("--catch-up", type=int, default=CATCH_UP_DAYS, metavar="DAYS",
                    help="on a --new-only run, also read the DAYS deepest archive "
                         "days below this extractor's own floor.")
    args = ap.parse_args()

    src = S3Source(args.workers) if args.source == "s3" else LocalSource()
    since, have = (incremental_window(args.db, EXTRACTOR, "eq_toi_filings")
                   if args.new_only else (None, set()))
    filings = (local_t1() if src.name == "local"
               else s3_t1(src, catch_up_start(since, args.catch_up if args.new_only else 0)))
    through = max((r["date"] for r in filings.values()), default=None)
    pending, catch_up_floor = select_pending(
        filings, since, have, args.catch_up if args.new_only else 0,
        recorded_floor(args.db, EXTRACTOR))
    if since is not None:
        print("incremental: %d of %d archived documents are new since %s"
              % (len(pending), len(filings), since))
    meta = src.list_metadata(
        days=None if since is None else {r["date"] for r in pending.values()})

    targets = []
    for doc_id, rec in sorted(pending.items()):
        m = meta.get(doc_id) or {}
        doc_type = m.get("docTypeCode") or rec.get("doc_type")
        if doc_type not in TOI_TYPES:
            continue
        targets.append((doc_id, rec, m, doc_type))
    if args.docs:
        want = {d.strip() for d in args.docs.split(",") if d.strip()}
        targets = [t for t in targets if t[0] in want]
    if args.limit:
        targets = targets[:args.limit]
    print("target filings: %d (source=%s)" % (len(targets), src.name))

    con = duckdb.connect(args.db)
    con.execute(SCHEMA_SQL)

    def fetch_and_parse(t):
        doc_id, rec, m, doc_type = t
        try:
            blob = read_t1(src, doc_id, rec["date"])
        except Exception as e:                                    # noqa: BLE001
            return t, None, None, ("failed", "fetch: %s" % str(e)[:120])
        sha = hashlib.sha256(blob).hexdigest()
        try:
            return t, parse(blob, doc_type), sha, None
        except (NotTenderOffer, NoHonbun) as e:
            return t, None, sha, ("not_toi", str(e)[:120])
        except Exception as e:                                    # noqa: BLE001
            return t, None, sha, ("failed", "%s: %s" % (type(e).__name__, str(e)[:120]))

    stats = defaultdict(int)
    g_checked = g_passed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(fetch_and_parse, t) for t in targets]
        for fut in as_completed(futures):
            (doc_id, rec, m, doc_type), row, sha, err = fut.result()
            base = dict.fromkeys(COLS)
            base["doc_id"] = doc_id
            base["doc_type"] = doc_type
            base["form"] = FORM_OF.get(doc_type)
            base["sha256"] = sha
            base["parser_version"] = PARSER_VERSION
            # The list metadata is the authority on WHO: the filer's own code
            # and the code of the company the filing is about.
            filer_code = m.get("edinetCode")
            subject = m.get("subjectEdinetCode")
            if doc_type in ("290", "300"):
                base["target_edinet_code"] = filer_code
                base["offeror_edinet_code"] = subject
                base["target_sec_code"] = sec_code_of(m)
            else:
                base["offeror_edinet_code"] = filer_code
                base["target_edinet_code"] = subject
            if err:
                base["status"], base["detail"] = err
                stats[base["status"]] += 1
                base["gate_checked"] = base["gate_passed"] = 0
                base["pair_key"] = "%s/?" % (base["target_edinet_code"] or "?")
                con.execute("INSERT OR REPLACE INTO eq_toi_filings VALUES (%s)"
                            % ",".join(["?"] * len(COLS)), [base[c] for c in COLS])
                continue
            base.update({k: v for k, v in row.items() if k in COLS})
            if not base.get("filed_date"):
                d = m.get("submitDateTime") or rec.get("date")
                base["filed_date"] = dt.date.fromisoformat(str(d)[:10]) if d else None
            base["ratio_after_recomputed"], base["ratio_consistent"] = \
                recompute_ratio(base)
            problems, checked, passed = gates(base)
            g_checked += checked
            g_passed += passed
            base["gate_checked"] = checked
            base["gate_passed"] = passed
            base["status"] = "partial" if problems else "clean"
            base["detail"] = "; ".join(problems[:3]) or None
            base["pair_key"] = pair_key_of(base, m)
            stats[base["status"]] += 1
            stats["form:" + (base["form"] or "?")] += 1
            con.execute("INSERT OR REPLACE INTO eq_toi_filings VALUES (%s)"
                        % ",".join(["?"] * len(COLS)), [base[c] for c in COLS])
    # Round numbering needs every document of a pair in the table, so it is a
    # single pass at the end rather than a per-document guess.
    con.execute(ROUND_SQL)
    con.close()
    record_run(args.db, EXTRACTOR, through, len(filings), PARSER_VERSION,
               back_to=catch_up_floor)
    if not args.no_compact:
        compact(args.db)
    print("filings: %s" % dict(stats))
    if g_checked:
        print("gates: %d/%d = %.1f%%" % (g_passed, g_checked,
                                         100.0 * g_passed / g_checked))
    print("wrote", os.path.normpath(args.db))


if __name__ == "__main__":
    main()
