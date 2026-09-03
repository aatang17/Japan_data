# -*- coding: utf-8 -*-
u"""Bootstrap the party registry with the group structure, once.

    ./.venv/bin/python -m app.parties_seed [--dry-run]

What it seeds is deliberately narrow: the twenty families already hand-mapped
in `filer_labels.GROUPS`, and the filing arms belonging to them. That is the
part of curation a person cannot type quickly -- eighty-odd EDINET codes
resolved into parents, each arm named from its own filings -- and it is the
part that is already a matter of public record rather than a judgement.

Everything that IS a judgement is left blank: no strategy, no activist stance,
no thesis, and `party_class` set from the filed 事業内容 only where the filing
is unambiguous. An 投資事業 vehicle could be a hedge fund, a buyout fund or a
founder's holding company, and the filing does not say which, so it seeds as
`unknown` and sorts to the top of the work queue. Every seeded profile records
`source` saying so, so a seeded value is never mistaken for a reviewed one.

Re-running is safe: a party whose EDINET code already belongs to a profile is
left alone, so this never overwrites a reviewed profile.
"""
from __future__ import print_function

import sys

import duckdb

from . import filer_labels, parties
from .equity_api import DB_PATH as EQUITY_DB_PATH

SEED_SOURCE = u"seeded from filer_labels.GROUPS + filed 事業内容 — not reviewed"

# Derived filed type -> party_class. Only the unambiguous ones map; the rest
# seed as unknown BECAUSE the filing genuinely does not say. A licence to run
# a securities business tells you what a firm may do, not what kind of
# investor it is.
CLASS_FROM_FILED = {
    "asset_manager": "asset_manager",
    "broker_dealer": "broker_dealer",
    "trust_bank": "trust_bank",
    "bank": "bank",
    "insurer": "insurer",
    "operating_company": "operating_company",
    "individual": "individual",
    "investment_vehicle": "unknown",
    "not_stated": "unknown",
}
ROLE_FROM_FILED = {
    "asset_manager": "asset_management",
    "broker_dealer": "securities",
    "bank": "banking",
    "trust_bank": "trust",
    "insurer": "insurance",
    "operating_company": "operating",
    "investment_vehicle": "fund_vehicle",
}
# A holder that is on the register for someone else. Seeded conservatively:
# only a trust bank is presumed to be holding for others, and even that is
# flagged for review rather than trusted.
ROLE_ON_REGISTER = {"trust_bank": "nominee"}


def _entities():
    if not EQUITY_DB_PATH.exists():
        raise SystemExit("equity database not built yet: %s" % EQUITY_DB_PATH)
    con = duckdb.connect(str(EQUITY_DB_PATH), read_only=True)
    try:
        rows = con.execute("""
            WITH ranked AS (
                SELECT h.holder_edinet_code AS code, h.name_raw, h.name_en,
                       COALESCE(h.is_individual, FALSE) AS is_individual,
                       h.business_ja,
                       ROW_NUMBER() OVER (
                           PARTITION BY h.holder_edinet_code
                           ORDER BY (h.business_ja IS NOT NULL) DESC,
                                    f.filed_date DESC) AS rn
                FROM eq_lvh_holders h JOIN eq_lvh_filings f USING (doc_id)
                WHERE h.holder_edinet_code IS NOT NULL
            ), n AS (
                SELECT holder_edinet_code AS code, COUNT(DISTINCT doc_id) AS filings
                FROM eq_lvh_holders WHERE holder_edinet_code IS NOT NULL GROUP BY 1
            )
            SELECT r.code, r.name_raw, r.name_en, r.is_individual, r.business_ja,
                   n.filings
            FROM ranked r JOIN n ON n.code = r.code
            WHERE r.rn = 1
        """).fetchall()
    finally:
        con.close()
    return {r[0]: {"code": r[0], "name_ja": r[1], "name_en": r[2],
                   "is_individual": r[3], "business_ja": r[4], "filings": r[5]}
            for r in rows}


def _clean_en(name_en, name_ja):
    u"""The filings put the English name in brackets after the katakana one;
    `name_en` is already split out where the extractor found it."""
    return (name_en or "").strip() or None


def build(dry_run=False):
    doc = parties.load()
    doc = {"schema": parties.SCHEMA_VERSION,
           "parties": dict(doc["parties"])}
    entities = _entities()
    taken = parties.alias_index(doc)

    # Which groups have arms that actually appear in the 5% archive. A family
    # whose codes never filed would seed an empty parent.
    families = {}
    for code, group in filer_labels.GROUPS.items():
        if code in entities:
            families.setdefault(group, []).append(code)

    created_parents, created_arms, skipped = [], [], 0
    for group in sorted(families):
        codes = sorted(families[group], key=lambda c: -entities[c]["filings"])
        parent_id = None
        for pid, party in doc["parties"].items():
            if party.get("group_name") == group and not party.get("parent_id"):
                parent_id = pid
                break
        if parent_id is None:
            parent_id = parties.new_id(doc, group)
            doc["parties"][parent_id] = parties.normalise({
                "display_name": group, "group_name": group,
                "party_class": "unknown", "group_role": "holding_company",
                "coverage_tier": "a", "lifecycle": "active", "public": False,
                "source": SEED_SOURCE, "confidence": u"unreviewed",
                "notes": u"Group parent. Seeded from filer_labels.GROUPS, "
                         u"which is curated from the codes present in the "
                         u"archive; no filing names a parent.",
            }, doc)
            doc["parties"][parent_id]["created_at"] = parties._now()
            doc["parties"][parent_id]["updated_at"] = parties._now()
            doc["parties"][parent_id]["updated_by"] = "parties_seed"
            created_parents.append((parent_id, group, len(codes)))

        for code in codes:
            if ("edinet_code", code) in taken:
                skipped += 1
                continue
            ent = entities[code]
            filed, _ = filer_labels.type_of(ent["business_ja"], ent["is_individual"])
            profile = {
                "display_name": _clean_en(ent["name_en"], ent["name_ja"]) or ent["name_ja"],
                "legal_name_ja": ent["name_ja"],
                "legal_name_en": _clean_en(ent["name_en"], ent["name_ja"]),
                "party_class": CLASS_FROM_FILED.get(filed, "unknown"),
                "group_role": ROLE_FROM_FILED.get(filed, "other"),
                "holder_role": ROLE_ON_REGISTER.get(filed, "beneficial_owner"),
                "parent_id": parent_id,
                "coverage_tier": "a" if ent["filings"] >= 20 else "b",
                "lifecycle": "active",
                "public": False,
                "source": SEED_SOURCE,
                "confidence": u"unreviewed",
                "aliases": [{"key_type": "edinet_code", "key_value": code,
                             "note": u"filed as %s" % (ent["name_ja"] or "")}],
            }
            party_id = parties.new_id(doc, profile["legal_name_en"]
                                      or profile["display_name"] or code)
            doc["parties"][party_id] = parties.normalise(profile, doc, party_id)
            doc["parties"][party_id]["created_at"] = parties._now()
            doc["parties"][party_id]["updated_at"] = parties._now()
            doc["parties"][party_id]["updated_by"] = "parties_seed"
            taken[("edinet_code", code)] = party_id
            created_arms.append((party_id, group, code, ent["filings"]))

    print("groups with arms in the archive: %d" % len(families))
    print("parents created:  %d" % len(created_parents))
    print("arms created:     %d" % len(created_arms))
    print("codes already profiled (left alone): %d" % skipped)
    for pid, group, n in created_parents:
        print("  + %-28s %-24s %d arms" % (pid, group, n))
    if dry_run:
        print("\n--dry-run: nothing written")
        return doc
    parties.save(doc)
    print("\nwrote %s (%d parties)" % (parties.STORE_PATH, len(doc["parties"])))
    return doc


if __name__ == "__main__":
    build(dry_run="--dry-run" in sys.argv[1:])
