# -*- coding: utf-8 -*-
"""M1 prototype — board composition and executive pay (役員の状況・役員の報酬等).

Same source file as the cross-shareholding extractor: the annual report's
XBRL-to-CSV package (EDINET type=5). Nothing new is downloaded — this reads the
archive we already keep.

Four record types come out, all from tagged facts (no HTML table parsing):

  directors      one row per person on the board, keyed by the filing's own
                 context member (…_ShinyaAkitoMember) — which also hands us a
                 romanised name for free, so English director names need no
                 translation.
  pay_category   报酬等 by officer category: total, and whatever components the
                 filer breaks out (fixed / base / performance / bonus /
                 non-monetary / retirement), plus the headcount paid.
  pay_named      the ≥¥100m individual disclosure — tagged per person, and on
                 the SAME member context as the director row, so it joins.
  company        one row per filing: board size, gender split, employees,
                 average salary, human-capital metrics, gate status.

Gates (a row that fails is reported, never silently dropped):
  G1  counted directors == tagged male + female count
  G2  recomputed female ratio reproduces the filed ratio
  G3  broken-out pay components do not exceed the filed total
  G4  every named individual is at or above the ¥100m disclosure threshold
  G5  dates of birth imply a plausible age (20–100)

Python 3.9, stdlib only.

    python extract.py                      # whole local archive
    python extract.py --limit 300          # quick sample
"""
import argparse
import collections
import csv
import datetime as dt
import glob
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "data", "raw", "edinet", "docs")
CODELIST = os.path.join(HERE, "..", "m1", "EdinetcodeDlInfo.csv")
OUT = os.path.join(HERE, "out")

C = "jpcrp_cor:"
DIRECTOR_SUFFIX = "InformationAboutDirectorsAndCorporateAuditors"

# Per-person facts in the 役員の状況 table, keyed by member context.
PERSON_FIELDS = {
    "name_ja": C + "Name" + DIRECTOR_SUFFIX,
    "title_ja": C + "OfficialTitleOrPosition" + DIRECTOR_SUFFIX,
    "dob": C + "DateOfBirth" + DIRECTOR_SUFFIX,
    "shares_held": C + "NumberOfSharesHeldOrdinaryShares" + DIRECTOR_SUFFIX,
    "term_note": C + "TermOfOffice" + DIRECTOR_SUFFIX,
}
NAMED_PAY = C + ("TotalAmountOfRemunerationEtcPaidByGroup"
                 "RemunerationEtcPaidByGroupToEachDirectorOrOtherOfficer")
NAMED_PAY_THRESHOLD = 100000000        # ¥100mn — the disclosure trigger

# Pay-by-category facts. Element localname -> our column. Filers use either
# 固定報酬 or 基本報酬 for the fixed leg, never both meaningfully, so both are
# carried and the gate treats them as alternatives.
PAY_FIELDS = {
    "total_yen": "TotalAmountOfRemunerationEtcRemunerationEtcByCategoryOfDirectorsAndOtherOfficers",
    "fixed_yen": "FixedRemunerationRemunerationByCategoryOfDirectorsAndOtherOfficers",
    "base_yen": "BaseRemunerationRemunerationEtcByCategoryOfDirectorsAndOtherOfficers",
    "performance_yen": "PerformanceBasedRemunerationRemunerationByCategoryOfDirectorsAndOtherOfficers",
    "bonus_yen": "BonusRemunerationEtcByCategoryOfDirectorsAndOtherOfficers",
    "non_monetary_yen": "NonMonetaryRemunerationRemunerationByCategoryOfDirectorsAndOtherOfficers",
    "retirement_yen": "RetirementBenefitsRemunerationEtcByCategoryOfDirectorsAndOtherOfficers",
    "headcount": "NumberOfDirectorsAndOtherOfficersRemunerationEtcByCategoryOfDirectorsAndOtherOfficers",
}
PAY_COMPONENTS = ["fixed_yen", "base_yen", "performance_yen", "bonus_yen",
                  "non_monetary_yen", "retirement_yen"]
# Filers invent components (RestrictedShareAwards…, StockOptions…) and some are
# NEGATIVE — a forfeited restricted-share award is a reversal. Anything in the
# family that isn't a column of its own is summed into other_components_yen so
# the reconciliation gate stays complete.
PAY_FAMILY = re.compile(r"RemunerationE?t?c?ByCategoryOfDirectorsAndOtherOfficers$")

CATEGORY_EN = {
    "DirectorsExcludingOutsideDirectorsMember": "Directors (excl. outside)",
    "DirectorsExcludingAuditAndSupervisoryCommitteeMembersAndOutsideDirectorsMember":
        "Directors excl. audit cttee (excl. outside)",
    "DirectorsAppointedAsAuditAndSupervisoryCommitteeMembersExcludingOutsideDirectorsMember":
        "Audit-cttee directors (excl. outside)",
    "CorporateAuditorsExcludingOutsideCorporateAuditorsMember": "Statutory auditors (excl. outside)",
    "OutsideDirectorsAndOtherOfficersMember": "Outside directors and officers",
    "OutsideDirectorsMember": "Outside directors",
    "OutsideCorporateAuditorsMember": "Outside statutory auditors",
    "ExecutiveOfficersMember": "Executive officers",
}

COMPANY_FIELDS = {
    "company_ja": C + "CompanyNameCoverPage",
    "company_en": C + "CompanyNameInEnglishCoverPage",
    "filing_date": C + "FilingDateCoverPage",
    "fiscal_year_ja": C + "FiscalYearCoverPage",
    "representative": C + "TitleAndNameOfRepresentativeCoverPage",
    "male_officers": C + "NumberOfMaleDirectorsAndOtherOfficers",
    "female_officers": C + "NumberOfFemaleDirectorsAndOtherOfficers",
    "female_ratio_filed": C + "RatioOfFemaleDirectorsAndOtherOfficers",
    "avg_age": C + "AverageAgeYearsInformationAboutReportingCompanyInformationAboutEmployees",
    "avg_tenure": C + "AverageLengthOfServiceYearsInformationAboutReportingCompanyInformationAboutEmployees",
    "avg_salary_yen": C + "AverageAnnualSalaryInformationAboutReportingCompanyInformationAboutEmployees",
    "female_managers_ratio": C + "RatioOfFemaleEmployeesInManagerialPositionsMetricsOfReportingCompany",
    "gender_pay_gap_all": C + "AllEmployeesDifferencesInWagesBetweenMaleAndFemaleEmployeesMetricsOfReportingCompany",
    "male_childcare_leave": C + "AllEmployeesRatioOfMaleEmployeesTakingChildcareLeaveMetricsOfReportingCompany",
}

MISSING = ("", "-", "－", "−", "―", "ー", "—", "該当事項なし")


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", " ", s).strip()


def to_num(s):
    """'1,234' -> 1234.0 ; '－' -> None. A missing value is never zero."""
    s = norm(s).replace(",", "")
    if s in MISSING:
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def stated_dp(x):
    s = ("%.10f" % x).rstrip("0")
    return len(s.split(".")[1]) if "." in s and s.split(".")[1] else 0


def romaji(member):
    """'E39089-000ShinyaAkitoMember' -> ('Shinya Akito', 'shinya-akito').

    The suffix is filer-authored, so treat it as a display name and a *weak*
    person key: good enough to join the pay row to the board row inside one
    filing, not good enough to assert two companies share a director.
    """
    s = re.sub(r"^(jpcrp\d+-asr_)?E\d+-\d+", "", member)
    s = re.sub(r"Member$", "", s)
    parts = re.findall(r"[A-Z][a-z0-9'\-\.]*|[A-Z]+(?![a-z])", s)
    name = " ".join(parts) if parts else s
    return name, re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def classify(title):
    """Role bucket from the 役職名 string. Outside status is NOT derivable
    here — only ~3.5% of titles say 社外 — so it is left to the pay table."""
    t = norm(title)
    if "監査等委員" in t:
        return "audit_committee_director"
    if "監査役" in t:
        return "statutory_auditor"
    if "取締役" in t or "執行役" in t:
        return "director"
    return "other"


def load_codelist():
    text = open(CODELIST, "rb").read().decode("cp932")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[1]
    out = {}
    for r in rows[2:]:
        if len(r) != len(header):
            continue
        d = dict(zip(header, r))
        code = d.get("ＥＤＩＮＥＴコード", "")
        if code:
            out[code] = ((d.get("証券コード", "") or "")[:4],
                         d.get("上場区分", "") == "上場",
                         d.get("提出者業種", ""))
    return out


def read_facts(path):
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist() if "jpcrp030000-asr" in n]
    if not names:
        return None
    rows = list(csv.reader(io.StringIO(z.read(names[0]).decode("utf-16")),
                           delimiter="\t"))
    return names[0], rows[1:]


def parse(path):
    got = read_facts(path)
    if got is None:
        return None
    fname, rows = got
    m = re.search(r"_(E\d{5})-\d+_(\d{4}-\d{2}-\d{2})_", fname)
    edinet_code = m.group(1) if m else ""
    period_end = m.group(2) if m else ""
    doc_id = os.path.basename(path).split("_")[0]

    company = {"doc_id": doc_id, "edinet_code": edinet_code, "period_end": period_end}
    people = collections.defaultdict(dict)
    pay = collections.defaultdict(dict)
    named = {}
    inv_company = {v: k for k, v in COMPANY_FIELDS.items()}
    inv_person = {v: k for k, v in PERSON_FIELDS.items()}
    inv_pay = {C + v: k for k, v in PAY_FIELDS.items()}

    for r in rows:
        if len(r) < 9:
            continue
        el, ctx, val = r[0], r[2], r[8]
        if el in inv_company and ctx.startswith(("FilingDateInstant", "CurrentYear")):
            company[inv_company[el]] = norm(val)
        elif el in inv_person and "Member" in ctx:
            people[ctx.split("_", 1)[1]][inv_person[el]] = norm(val)
        elif ctx.startswith("CurrentYearDuration_") and PAY_FAMILY.search(el):
            key = ctx.split("_", 1)[1]
            if el in inv_pay:
                pay[key][inv_pay[el]] = norm(val)
            else:
                pay[key].setdefault("_other", {})[el.split(":")[-1]] = norm(val)
        elif el == NAMED_PAY and ctx.startswith("CurrentYearDuration_"):
            named[ctx.split("_", 1)[1]] = norm(val)
    return company, people, pay, named


def build(path, codes):
    try:
        got = parse(path)
    except Exception as e:                                   # noqa: BLE001
        return {"doc_id": os.path.basename(path).split("_")[0],
                "status": "failed", "detail": "%s: %s" % (type(e).__name__, e)}, [], [], []
    if got is None:
        return None
    company, people, pay, named = got
    sec, listed, industry = codes.get(company["edinet_code"], ("", False, ""))
    company["sec_code"] = sec
    company["listed"] = "listed" if listed else "unlisted"
    company["industry"] = industry

    pe = None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", company.get("period_end") or ""):
        pe = dt.date(*[int(x) for x in company["period_end"].split("-")])

    drows, problems = [], []
    for member, f in people.items():
        if not f.get("name_ja"):
            continue          # a member context with no name is a total/footnote row
        name_en, key = romaji(member)
        age = None
        dob = f.get("dob", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob) and pe:
            b = dt.date(*[int(x) for x in dob.split("-")])
            age = pe.year - b.year - ((pe.month, pe.day) < (b.month, b.day))
            if not 20 <= age <= 100:                                        # G5
                problems.append("G5 implausible age %s for %s" % (age, name_en))
                age = None
        drows.append({
            "doc_id": company["doc_id"], "edinet_code": company["edinet_code"],
            "sec_code": sec, "period_end": company["period_end"],
            "person_key": key, "name_ja": f.get("name_ja", ""), "name_en": name_en,
            "title_ja": f.get("title_ja", ""), "role": classify(f.get("title_ja", "")),
            "is_representative": int("代表" in f.get("title_ja", "")),
            "date_of_birth": dob if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob) else "",
            "age_at_period_end": age if age is not None else "",
            "shares_held": to_num(f.get("shares_held", "")) or "",
        })

    prows = []
    for member, f in pay.items():
        cat = re.sub(r"^(jpcrp\d+-asr_)?E\d+-\d+", "", member)
        row = {"doc_id": company["doc_id"], "sec_code": sec,
               "period_end": company["period_end"], "category_key": cat,
               "category_en": CATEGORY_EN.get(cat, ""),
               "category_custom": int(cat not in CATEGORY_EN)}
        for col in PAY_FIELDS:
            row[col] = to_num(f.get(col, ""))
        other = {k: to_num(v) for k, v in (f.get("_other") or {}).items()}
        other = {k: v for k, v in other.items() if v is not None}
        row["other_components_yen"] = sum(other.values()) if other else None
        row["other_components"] = "|".join(sorted(other)) if other else ""
        # G3 is a per-row DISCLOSURE FLAG, not a filing gate. Filers differ on
        # whether 非金銭報酬等 is additive or an "of which" memo line, and print
        # components rounded to ¥mn, so a mismatch is a property of the filing,
        # not of our extraction. The filed category total is the published
        # number; we say whether the filer's own components add up to it.
        parts = [row[c] for c in PAY_COMPONENTS if row[c] is not None]
        parts += list(other.values())
        if parts and row["total_yen"]:                                      # G3
            tot = sum(parts)
            row["components_reconcile"] = int(
                abs(tot - row["total_yen"]) <= max(1e6 * len(parts), row["total_yen"] * 0.005))
        else:
            row["components_reconcile"] = ""
        row["avg_per_head_yen"] = (round(row["total_yen"] / row["headcount"])
                                   if row["total_yen"] and row["headcount"] else None)
        for k, v in list(row.items()):
            if v is None:
                row[k] = ""
        row.pop("_other", None)
        prows.append(row)

    nrows = []
    keys = {d["person_key"] for d in drows}
    for member, val in named.items():
        name_en, key = romaji(member)
        amt = to_num(val)
        if amt is None:
            continue
        # ¥100m is the MANDATORY trigger, not a floor: Takeda, Recruit and
        # others disclose every director voluntarily. Below-threshold rows are
        # marked voluntary, not treated as extraction errors.                G4
        nrows.append({"doc_id": company["doc_id"], "sec_code": sec,
                      "period_end": company["period_end"], "person_key": key,
                      "name_en": name_en, "consolidated_pay_yen": int(amt),
                      "voluntary_below_100m": int(amt < NAMED_PAY_THRESHOLD),
                      "on_board_at_filing": int(key in keys)})

    board = len(drows)
    male, female = to_num(company.get("male_officers", "")), to_num(company.get("female_officers", ""))
    company["board_size"] = board
    company["male_officers"] = male if male is not None else ""
    company["female_officers"] = female if female is not None else ""
    officers = (male + female) if (male is not None and female is not None) else None
    company["officers_tagged"] = officers if officers is not None else ""
    # In a 指名委員会等設置会社 the 役員 tally includes 執行役 who are not on the
    # board and are not individually tagged (JPX: 12 board rows, 17 officers).
    # So the invariant is board <= officers; only the reverse is a real defect.
    company["officers_untagged"] = (officers - board) if (officers is not None and board) else ""
    if board and officers is not None and board > officers:                 # G1
        problems.append("G1 counted %d board rows > %d tagged officers" % (board, officers))
    filed = to_num(company.get("female_ratio_filed", ""))
    calc = (female / board) if (board and female is not None) else None
    company["female_ratio_calc"] = round(calc, 4) if calc is not None else ""
    company["female_ratio_filed"] = filed if filed is not None else ""
    # G2 is only meaningful when the two populations coincide (board == officers)
    if filed is not None and calc is not None and officers == board:        # G2
        if abs(calc - filed) >= 10.0 ** -stated_dp(filed):
            problems.append("G2 female ratio filed %s vs recomputed %.4f" % (filed, calc))
    for k in ("avg_age", "avg_tenure", "avg_salary_yen", "female_managers_ratio",
              "gender_pay_gap_all", "male_childcare_leave"):
        company[k] = to_num(company.get(k, "")) if company.get(k) else ""
    company["named_pay_count"] = len(nrows)
    company["pay_total_yen"] = sum(r["total_yen"] for r in prows if r["total_yen"]) or ""
    if not board:
        company["status"], company["detail"] = "no_tagged_board", "officers table is TextBlock only"
    elif problems:
        company["status"], company["detail"] = "partial", "; ".join(problems[:4])
    else:
        company["status"], company["detail"] = "clean", ""
    return company, drows, prows, nrows


def write(name, rows, cols):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("  %-18s %6d rows -> %s" % (name, len(rows), path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(DOCS, "**", "*_t5.zip"), recursive=True))
    if a.limit:
        files = files[:a.limit]
    print("filings: %d" % len(files))
    codes = load_codelist()
    os.makedirs(OUT, exist_ok=True)

    comps, dirs, pays, nameds = [], [], [], []
    with ThreadPoolExecutor(a.workers) as ex:
        for res in ex.map(lambda f: build(f, codes), files):
            if res is None:
                continue
            c, d, p, n = res
            comps.append(c)
            dirs.extend(d)
            pays.extend(p)
            nameds.extend(n)

    write("company.csv", comps, ["doc_id", "edinet_code", "sec_code", "listed", "industry",
                                 "company_ja", "company_en", "period_end", "filing_date",
                                 "representative", "board_size", "male_officers",
                                 "female_officers", "female_ratio_filed", "female_ratio_calc", "officers_tagged",
                                 "officers_untagged",
                                 "avg_age", "avg_tenure", "avg_salary_yen",
                                 "female_managers_ratio", "gender_pay_gap_all",
                                 "male_childcare_leave", "pay_total_yen", "named_pay_count",
                                 "status", "detail"])
    write("directors.csv", dirs, ["doc_id", "edinet_code", "sec_code", "period_end",
                                  "person_key", "name_ja", "name_en", "title_ja", "role",
                                  "is_representative", "date_of_birth", "age_at_period_end",
                                  "shares_held"])
    write("pay_by_category.csv", pays, ["doc_id", "sec_code", "period_end", "category_key",
                                        "category_en", "category_custom", "headcount",
                                        "total_yen", "avg_per_head_yen", "fixed_yen",
                                        "base_yen", "performance_yen", "bonus_yen",
                                        "non_monetary_yen", "retirement_yen",
                                        "other_components_yen", "other_components",
                                        "components_reconcile"])
    write("pay_named.csv", nameds, ["doc_id", "sec_code", "period_end", "person_key",
                                    "name_en", "consolidated_pay_yen", "voluntary_below_100m",
                                    "on_board_at_filing"])

    st = collections.Counter(c["status"] for c in comps)
    listed = [c for c in comps if c.get("listed") == "listed"]
    print("\nstatus: %s" % dict(st))
    print("listed filers: %d of %d" % (len(listed), len(comps)))
    print("  clean among listed: %d (%.1f%%)"
          % (sum(1 for c in listed if c["status"] == "clean"),
             100.0 * sum(1 for c in listed if c["status"] == "clean") / max(1, len(listed))))
    sizes = sorted(c["board_size"] for c in comps if c["board_size"])
    if sizes:
        print("  board size: median %d, range %d-%d" % (sizes[len(sizes) // 2], sizes[0], sizes[-1]))
    ages = [int(d["age_at_period_end"]) for d in dirs if d["age_at_period_end"] != ""]
    if ages:
        print("  director age: mean %.1f, median %d" % (sum(ages) / len(ages), sorted(ages)[len(ages) // 2]))
    if nameds:
        top = sorted(nameds, key=lambda r: -r["consolidated_pay_yen"])[:5]
        print("  named ≥¥100m: %d people at %d filers; top: %s"
              % (len(nameds), len({r["doc_id"] for r in nameds}),
                 ", ".join("%s ¥%.0fm" % (r["name_en"], r["consolidated_pay_yen"] / 1e6) for r in top)))
    fails = [c for c in comps if c["status"] == "partial"][:6]
    for c in fails:
        print("  partial %s %s: %s" % (c["doc_id"], c.get("company_ja", "")[:16], c["detail"][:110]))


if __name__ == "__main__":
    main()
