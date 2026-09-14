# -*- coding: utf-8 -*-
u"""English rendering of a Japanese AGM resolution title (議案名).

This is NOT machine translation, and nothing here is guessed. A Japanese
resolution title is a formula — 第2号議案 取締役7名選任の件 — assembled from a
small, stable vocabulary that company law fixes. This module parses that
formula and re-renders it in English from a fixed table, exactly the way
INDUSTRY_EN in equity_api renders a TSE sector.

The contract that makes it safe to show:

  * A title is translated only if EVERY part of it is recognised. One unknown
    segment and `label_en` returns None, and the page shows the filed Japanese
    unchanged. A half-translated resolution would be worse than none.
  * The filed Japanese is never replaced in the data — it is returned beside
    the English, and it is what the CSV, the API and the citation carry.
  * No number is touched. Counts of directors are copied, never inferred.
"""
import re
import unicodedata

__all__ = ["label_en"]


def _norm(s):
    u"""Filed title -> a form the rules can match: ASCII width, no spaces."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace(u"　", " ")
    s = re.sub(r"\s+", "", s)
    s = s.replace(u"。", "").replace(u"，", u"、")
    return s


# --- officer nouns --------------------------------------------------------
# Longest first: 監査等委員である取締役 must win over 取締役.
OFFICERS = [
    (u"監査等委員である取締役以外の取締役", "director", "directors", "excluding audit-committee members"),
    (u"監査等委員でない取締役",             "director", "directors", "excluding audit-committee members"),
    (u"監査等委員である取締役",             "audit-committee director", "audit-committee directors", None),
    (u"監査等委員たる取締役",               "audit-committee director", "audit-committee directors", None),
    (u"監査等委員",                         "audit-committee director", "audit-committee directors", None),
    (u"社外取締役",                         "outside director", "outside directors", None),
    (u"代表取締役",                         "representative director", "representative directors", None),
    (u"取締役",                             "director", "directors", None),
    (u"監査役",                             "statutory auditor", "statutory auditors", None),
    (u"会計監査人",                         "accounting auditor", "the accounting auditor", None),
    (u"執行役",                             "executive officer", "executive officers", None),
    (u"役員",                               "officer", "officers", None),
]

# Parenthetical scope notes that ride on an officer noun.
QUALIFIERS = [
    (u"(監査等委員である取締役及び社外取締役を除く)", "excluding audit-committee and outside directors"),
    (u"(監査等委員である取締役並びに社外取締役を除く)", "excluding audit-committee and outside directors"),
    (u"(監査等委員である取締役を除く)", "excluding audit-committee members"),
    (u"(監査等委員であるものを除く)",   "excluding audit-committee members"),
    (u"(監査等委員である者を除く)",     "excluding audit-committee members"),
    (u"(監査等委員を除く)",             "excluding audit-committee members"),
    (u"(監査等委員)",                   "audit-committee members"),
    (u"(社外取締役を除く)",             "excluding outside directors"),
    (u"(社外取締役及び監査等委員である取締役を除く)", "excluding outside and audit-committee directors"),
    (u"(株主提案)", None),
    (u"(会社提案)", None),
]


def _officer(s):
    u"""'取締役(監査等委員である取締役を除く)' -> (singular, plural, note, rest)."""
    for ja, one, many, note in OFFICERS:
        if s.startswith(ja):
            rest = s[len(ja):]
            for q_ja, q_en in QUALIFIERS:
                if rest.startswith(q_ja):
                    if q_en:
                        note = q_en
                    rest = rest[len(q_ja):]
                    break
            return one, many, note, rest
    return None


def _people(s):
    u"""Officer phrase, optionally counted: '取締役7名' -> '7 directors'.

    Returns (english, rest) or None. The count is copied from the filing.
    """
    got = _officer(s)
    if not got:
        return None
    one, many, note, rest = got
    m = re.match(r"^(\d+)名", rest)
    n = None
    if m:
        n = int(m.group(1))
        rest = rest[m.end():]
    elif rest.startswith(u"名"):
        # '取締役 名選任の件' — the filing left the number out of the title.
        rest = rest[1:]
    if n is None:
        body = many
    elif n == 1:
        body = "1 " + one
    else:
        body = "%d %s" % (n, many)
    if note:
        body += " (%s)" % note
    return body, rest


CONNECTORS = (u"並びに", u"及び", u"および", u"・")
PREFIXES = ((u"退任", "retiring "), (u"補欠の", "substitute "),
            (u"補欠", "substitute "), (u"新任", "newly appointed "))


def _split_top(s, connectors=None):
    u"""Split '取締役(…を除く)及び監査役' on connectors OUTSIDE parentheses."""
    connectors = connectors or CONNECTORS
    parts, buf, depth, i = [], "", 0, 0
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        if depth == 0:
            for conn in connectors:
                if s.startswith(conn, i):
                    parts.append(buf)
                    buf = ""
                    i += len(conn)
                    break
            else:
                buf += c
                i += 1
            continue
        buf += c
        i += 1
    parts.append(buf)
    return [p for p in parts if p]


def _people_list(s):
    u"""'退任取締役及び退任監査役' -> 'retiring directors and retiring statutory auditors'.

    Every part must resolve to a known officer noun; one that does not makes
    the whole title untranslatable, which is the point.
    """
    out = []
    for part in _split_top(s):
        lead = ""
        for ja, en in PREFIXES:
            if part.startswith(ja):
                lead, part = en, part[len(ja):]
                break
        got = _people(part)
        if not got or got[1]:
            return None
        who = got[0]
        if lead:
            who = re.sub(r"^(\d+ )?", lambda m: (m.group(1) or "") + lead, who, count=1)
        out.append(who)
    if not out:
        return None
    if len(out) == 1:
        return out[0]
    return ", ".join(out[:-1]) + " and " + out[-1]


# --- whole-title rules ----------------------------------------------------
# Each entry: (compiled pattern, handler). Patterns are matched against the
# normalised title with its trailing 「の件」 already removed. A handler
# returns English, or None to decline (which falls back to the Japanese).

def _rule_appoint(m):
    who = _people_list(m.group("subject"))
    if not who:
        return None
    verb = {u"選任": "Election", u"解任": "Removal", u"選定": "Appointment",
            u"不再任": "Non-reappointment", u"増員": "Addition"}[m.group("verb")]
    return "%s of %s" % (verb, who)


def _rule_pay(m):
    who = _people_list(m.group("subject"))
    if not who:
        return None
    verb = {u"改定": "Revision of", u"改訂": "Revision of", u"一部改定": "Partial revision of",
            u"設定": "Setting of", u"決定": "Determination of",
            u"承認": "Approval of"}[m.group("verb")]
    kind = "remuneration limit" if m.group("scope") in (u"枠", u"限度額") else "remuneration"
    return "%s %s for %s" % (verb, kind, who)


def _rule_equity_pay(m):
    who = _people_list(m.group("subject"))
    if not who:
        return None
    return "Remuneration for the grant of restricted stock to %s" % who


def _rule_share_plan(m):
    who = _people_list(m.group("subject"))
    if not who:
        return None
    verb = {u"導入": "Introduction of", u"改定": "Revision of", u"一部改定": "Partial revision of",
            u"改訂": "Revision of", u"継続": "Continuation of", u"廃止": "Abolition of",
            u"承認": "Approval of", u"決定": "Determination of", u"設定": "Setting of"}[
        m.group("verb")]
    kind = m.group("kind")
    name = ("a performance-linked share remuneration plan"
            if u"業績連動" in kind else
            "a restricted-stock remuneration plan"
            if u"譲渡制限付" in kind else "a share remuneration plan")
    return "%s %s for %s" % (verb, name, who)


def _rule_options(m):
    who = _people_list(m.group("subject"))
    if not who:
        return None
    return "Grant of stock options to %s" % who


def _rule_retirement(m):
    who = _people_list(u"退任" + m.group("subject"))
    if not who:
        return None
    return "Retirement benefits for %s" % who


def _rule_merit(m):
    who = _people_list(u"退任" + m.group("subject"))
    if not who:
        return None
    return "Special merit payment to %s" % who


def _rule_bonus(m):
    who = _people_list(m.group("subject"))
    if not who:
        return None
    return "Payment of bonuses to %s" % who


# Fixed topics. Left side is the normalised title with 「の件」 removed; a few
# carry an optional 「承認」 or 「決議」 that means the same thing in English.
TOPICS = {
    u"剰余金処分": "Appropriation of surplus",
    u"剰余金の処分": "Appropriation of surplus",
    u"剰余金の処分及び配当": "Appropriation of surplus and dividend",
    u"剰余金配当": "Dividend from surplus",
    u"剰余金の配当": "Dividend from surplus",
    u"期末配当": "Year-end dividend",
    u"定款一部変更": "Partial amendment to the Articles of Incorporation",
    u"定款の一部変更": "Partial amendment to the Articles of Incorporation",
    u"定款変更": "Amendment to the Articles of Incorporation",
    u"定款の変更": "Amendment to the Articles of Incorporation",
    u"株式併合": "Share consolidation",
    u"株式の併合": "Share consolidation",
    u"株式分割": "Share split",
    u"自己株式取得": "Acquisition of treasury shares",
    u"自己株式の取得": "Acquisition of treasury shares",
    u"自己株式の消却": "Cancellation of treasury shares",
    u"資本金の額の減少": "Reduction of stated capital",
    u"資本準備金の額の減少": "Reduction of the capital reserve",
    u"資本金及び資本準備金の額の減少": "Reduction of stated capital and the capital reserve",
    u"資本金の額の減少並びに剰余金の処分": "Reduction of stated capital and appropriation of surplus",
    u"資本金及び資本準備金の額の減少並びに剰余金の処分":
        "Reduction of stated capital and the capital reserve, and appropriation of surplus",
    u"資本準備金の額の減少及び剰余金の処分":
        "Reduction of the capital reserve and appropriation of surplus",
    u"利益準備金の額の減少": "Reduction of the legal earnings reserve",
    u"吸収分割契約承認": "Approval of the absorption-type company split agreement",
    u"吸収合併契約承認": "Approval of the absorption-type merger agreement",
    u"新設分割計画承認": "Approval of the incorporation-type company split plan",
    u"株式交換契約承認": "Approval of the share exchange agreement",
    u"株式移転計画承認": "Approval of the share transfer plan",
    u"事業譲渡契約承認": "Approval of the business transfer agreement",
    u"会社の解散": "Dissolution of the company",
    u"商号変更": "Change of trade name",
    u"計算書類承認": "Approval of the financial statements",
    u"会計監査人選任": "Election of accounting auditor",
    u"会計監査人不再任": "Non-reappointment of the accounting auditor",
    u"補欠会計監査人選任": "Election of a substitute accounting auditor",
    u"譲渡制限付株式報酬制度に関する報酬額承認":
        "Approval of remuneration under the restricted-stock remuneration plan",
    u"株式報酬制度導入": "Introduction of a share-based remuneration plan",
    u"信託型株式報酬制度導入": "Introduction of a trust-type share remuneration plan",
    u"ストックオプションとしての新株予約権発行":
        "Issue of share options as stock options",
    u"ストックオプションとして新株予約権を発行する":
        "Issue of share options as stock options",
    u"資本金の額の減少(減資)": "Reduction of stated capital",
    u"資本金の額の減少及び剰余金処分": "Reduction of stated capital and appropriation of surplus",
}

# Takeover defences and other long-form topics, matched by their distinctive
# phrase rather than exactly, because the surrounding wording varies by filer.
# The takeover-defence family. Filers name the same instrument a dozen ways —
# 大規模買付行為への対応方針, 大量取得行為に関する対応策, 買収防衛策 — so this is
# matched as a family rather than enumerated, and only the plain forms
# translate: see _topic_en.
CONTAINS = [
    (re.compile(u"大規模買[付収]|大量買付|大量取得|買収防衛|買収への対応方針"),
     "Response policy to large-scale share purchases (takeover defence)"),
]

CONTINUATION = [(u"継続", "Continuation of "), (u"導入", "Introduction of "),
                (u"更新", "Renewal of "), (u"廃止", "Abolition of ")]

RULES = [
    (re.compile(u"^(?P<subject>.+?)(?:の)?(?P<verb>選任|解任|選定|不再任|増員)$"), _rule_appoint),
    (re.compile(u"^(?P<subject>.+?)(?:の|に対する)?報酬(?:等)?(?:の)?(?P<scope>額|枠|限度額)"
                u"(?:の)?(?P<verb>一部改定|改定|改訂|設定|決定|承認)$"), _rule_pay),
    (re.compile(u"^(?P<subject>.+?)に対する譲渡制限付株式の(?:付与|割当て|割当)のための"
                u"報酬(?:額)?(?:の)?(?:決定|設定|承認|改定)$"), _rule_equity_pay),
    (re.compile(u"^(?P<subject>.+?)に対する(?P<kind>[^、]*?(?:株式報酬|株式報酬型)(?:制度)?)"
                u"(?:の)?(?P<verb>一部改定|導入|改定|改訂|継続|廃止|承認|決定|設定)$"), _rule_share_plan),
    (re.compile(u"^(?P<subject>.+?)に対する(?:ストック・?オプション|新株予約権)"
                u"(?:としての新株予約権)?(?:の)?(?:付与|発行|割当て|割当)$"), _rule_options),
    (re.compile(u"^退任(?P<subject>.+?)に(?:対し|対する)?退職慰労金(?:の)?(?:贈呈|支給)$"),
     _rule_retirement),
    (re.compile(u"^退任(?P<subject>.+?)に(?:対し|対する)?特別功労金(?:の)?(?:贈呈|支給)$"),
     _rule_merit),
    (re.compile(u"^(?P<subject>.+?)(?:に対する)?(?:役員)?賞与(?:の)?(?:支給|支払)$"), _rule_bonus),
]

PREFIX = re.compile(u"^第(\\d+)号議案")
PREFIX_RANGE = re.compile(u"^第(\\d+)号(?:乃至|ないし|から)第(\\d+)号(?:まで(?:の)?)?議案")
TRAILER = re.compile(u"(の件|に関する件|の承認の件|の承認に関する件)$")
# A filer that splits one topic across two resolutions numbers them at the end
# — 定款一部変更の件(1) — and the extractor keeps footnote markers. Neither
# changes what the resolution is.
NUMBERING = re.compile(u"(?:\\((?:注)?\\d*\\)\\d*|\\(\\d+\\))\\s*$")


def _topic_en(body):
    u"""One resolution topic -> English, or None if it is not in the table."""
    if body in TOPICS:
        return TOPICS[body]
    for pat, handler in RULES:
        m = pat.match(body)
        if m:
            out = handler(m)
            if out:
                return out
    for conn in (u"並びに", u"及び"):
        parts = _split_top(body, (conn,))
        if len(parts) > 1:
            outs = [_topic_en(p) for p in parts]
            if all(outs):
                return outs[0] + "".join(", and " + o[0].lower() + o[1:]
                                         for o in outs[1:])
    for phrase, en in CONTAINS:
        if phrase.search(body):
            # Only the plain forms translate. A title that also amends the
            # policy while continuing it says more than "Continuation of", so
            # it is left in Japanese rather than rendered as half of itself.
            tail = body[body.rindex(")") + 1:] if ")" in body else ""
            if tail.startswith(u"の"):
                tail = tail[1:]
            if not tail:
                return en
            for ja, lead in CONTINUATION:
                if tail == ja:
                    return lead + en[0].lower() + en[1:]
            return None
    return None


def label_en(label):
    u"""Filed 議案名 -> English, or None when any part of it is unrecognised."""
    if not label:
        return None
    s = _norm(label)
    prefix = ""
    m = PREFIX_RANGE.match(s)
    if m:
        prefix = "Resolutions %s-%s: " % (m.group(1), m.group(2))
        s = s[m.end():]
    else:
        m = PREFIX.match(s)
        if m:
            prefix = "Resolution %s: " % m.group(1)
            s = s[m.end():]
    tag = ""
    for ja, en in ((u"(株主提案)", " (shareholder proposal)"),
                   (u"(会社提案)", " (company proposal)"),
                   (u"(株主提案に基づく議案)", " (shareholder proposal)")):
        if ja in s:
            s = s.replace(ja, "")
            tag = en
    s = NUMBERING.sub("", s)
    s = TRAILER.sub("", s).strip(u"　 ・")
    if not s:
        return None
    body = _topic_en(s)
    if not body:
        return None
    return prefix + body + tag
