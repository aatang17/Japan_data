"""Japanese era years -> Western years, for the Ministry of Finance tables.

Shared rather than copied into each adapter because the Ministry writes the
same fiscal year six different ways inside one publication: 「明治8年度」, a
bare 「22年度」 sitting under a 「昭和」 heading in the column to its left, a
sheet named 「平成元」, another named 「Ｓ60」 in full-width Latin and 「H28」 in
half-width, and 「令和8年度」. Every one of them has to land on the same axis
as every other number on the platform, and a one-year slip in an era base
misdates a whole table without anything looking wrong.

The bases below are the year BEFORE each era's first year, so 元年 ("year
one") is base + 1: 明治元年 = 1868, 大正元年 = 1912, 昭和元年 = 1926,
平成元年 = 1989, 令和元年 = 2019.

**A fiscal year is dated to the 1 April it begins on**, the platform's
convention for every Japanese fiscal-year series, and before 1886 that is a
convention rather than a fact: the Meiji fiscal year began in October, then
in July, and only from 明治19年度 (1886) has it begun in April. The adapters
disclose this; nothing here pretends otherwise.

The eight pre-1875 accounting periods (明治第1期 … 第8期) are not annual at
all — they run from four to fifteen months — so `fiscal_year` returns None
for them instead of inventing a year for a period that has none.
"""
import datetime
import re


class EraError(Exception):
    pass


# base + N = the Western year of 「<era>N年」. 元年 is N = 1.
ERA_BASE = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}
# The Ministry's sheet tabs abbreviate the era to its initial.
ERA_INITIAL = {"M": "明治", "T": "大正", "S": "昭和", "H": "平成", "R": "令和"}

# The first fiscal year any of these tables covers, and a ceiling that allows
# for a budget published two years ahead. A year outside this is a parsing
# failure, not a datum.
MIN_YEAR = 1868
MAX_YEAR = datetime.date.today().year + 2

_WIDE = dict((0xFF10 + i, chr(0x30 + i)) for i in range(10))
_WIDE.update((0xFF21 + i, chr(0x41 + i)) for i in range(26))
_WIDE.update((0xFF41 + i, chr(0x61 + i)) for i in range(26))
_WIDE[0x3000] = " "

_SPACE = re.compile(r"\s+")
_ERA_NAMES = "|".join(ERA_BASE)
_ERA_HEAD = re.compile(r"^(%s)" % _ERA_NAMES)
_INITIAL_HEAD = re.compile(r"^([MTSHR])(?=元|\d)")
# 「平成14-平成23」, 「昭和5-昭和16」 — a sheet covering a span starts at the
# first of them.
_SPAN = re.compile(r"^(.+?)[-–~〜]")
_YEAR = re.compile(r"^(?:(%s)|([MTSHR]))?(元|\d{1,4})(?:年度|年|事業年度|)$"
                   % _ERA_NAMES)


def normalize(text):
    """Trim every kind of space and fold full-width digits and Latin letters."""
    return _SPACE.sub("", (text or "").translate(_WIDE))


def era_of(text):
    """The era a label announces, or None. Accepts 「昭和」 and 「Ｓ60」 alike."""
    text = normalize(text)
    head = _ERA_HEAD.match(text)
    if head:
        return head.group(1)
    initial = _INITIAL_HEAD.match(text)
    if initial:
        return ERA_INITIAL[initial.group(1)]
    return None


def fiscal_year(label, era=None):
    """A fiscal-year label -> the Western year it begins in, or None.

    `era` carries the heading a bare number sits under — the Ministry writes
    「昭和」 once in column A and then 22, 23, 24 down the rows beneath it. A
    bare number with no era in hand is ambiguous, so it returns None rather
    than guessing: 「22年度」 is 1947 under 昭和 and 2010 under 平成.

    A four-digit number is read as a Western year, which is how the e-Stat
    tables and the newer Ministry files write it.
    """
    text = normalize(label)
    if not text:
        return None
    span = _SPAN.match(text)
    if span:
        text = span.group(1)
    match = _YEAR.match(text)
    if not match:
        return None
    name, initial, digits = match.groups()
    if initial:
        name = ERA_INITIAL[initial]
    number = 1 if digits == "元" else int(digits)
    if name is None and era is None:
        # A four-digit number is a Western year on its own; anything shorter
        # needs an era to mean anything.
        return number if len(digits) == 4 and MIN_YEAR <= number <= MAX_YEAR else None
    if name is None:
        name = normalize(era)
        name = ERA_INITIAL.get(name, name)
    if name not in ERA_BASE:
        return None
    if len(digits) == 4:
        # 「令和2019年度」 never occurs; a four-digit number under an era
        # heading is the Western year written out.
        return number if MIN_YEAR <= number <= MAX_YEAR else None
    return ERA_BASE[name] + number


def check(year, where=""):
    """A parsed year is inside the range these tables can possibly cover."""
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise EraError("fiscal year %s%s is outside %d-%d — the era was read wrong"
                       % (year, " (%s)" % where if where else "", MIN_YEAR, MAX_YEAR))
    return year


def period(year):
    """The date a fiscal year is stored at: the 1 April it begins on."""
    return datetime.date(check(year), 4, 1)
