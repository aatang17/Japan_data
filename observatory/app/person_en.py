# -*- coding: utf-8 -*-
u"""Repair a director's English name that was split on the wrong boundary.

A filing gives an officer's Latin name only inside its own XBRL context id --
``E39089-000ShinyaAkitoMember`` -- so the extractor reads the words back out of
the CamelCase. Two filer habits defeat that read, and until `board_extract.romaji`
was taught about them it produced names that were not names:

  * a name typed **entirely in capitals** (``SATOMASAHIKOMember``) has no
    boundary to split on, and splitting anyway gave "S A T O M A S A H I K O";
  * a **trailing digit** (``OkitaFumio09Member``) is the filer disambiguating
    two context ids, and came through as "Okita Fumio09".

The extractor no longer makes either mistake, but 2,076 rows were written before
it was fixed and an incremental run will not revisit those filings. So the same
repair is applied on the way out, where it is a no-op for every correctly parsed
name and for every row written from now on.

Nothing is romanized or translated here. Letters are only ever joined or
dropped, never invented: "SATOMASAHIKO" stays one word because the filing
states no boundary inside it, and finding "Sato Masahiko" would need a kana
table no filing carries. The Japanese name is returned beside it, as always.
"""
import re

__all__ = ["name_en", "fix_rows"]

# Three or more single letters in a row is not a person's name in any language;
# it is a capitalised run that was split letter by letter. Two is left alone --
# "Joseph A B Smith" is a real shape.
_SPACED_RUN = re.compile(r"(?:(?<=^)|(?<= ))[A-Z](?: [A-Z]){2,}(?= |$)")
_TRAILING_DIGITS = re.compile(r"\d+$")


def name_en(value):
    u"""The stored English name, with a mis-split boundary undone."""
    if not value:
        return value
    fixed = _TRAILING_DIGITS.sub("", value).strip()
    fixed = _SPACED_RUN.sub(lambda m: m.group(0).replace(" ", ""), fixed)
    return re.sub(r"\s+", " ", fixed).strip() or value


def fix_rows(rows, key="name_en"):
    u"""Apply `name_en` in place to a list of dict rows; returns the list."""
    for row in rows or ():
        if key in row:
            row[key] = name_en(row[key])
    return rows
