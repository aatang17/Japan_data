/* Equities overview: one row per dataset, filled from the same summary
   endpoints the product pages use. Figures are never baked into the markup;
   a row whose API cannot be reached drops its numbers and keeps its
   description and link, saying nothing it cannot back. */
"use strict";

function eqStat(label, value, note) {
  return '<div class="prod-stat">' +
    '<div class="prod-stat-label">' + escapeHtml(label) + "</div>" +
    '<div class="prod-stat-value">' + value + "</div>" +
    (note ? '<div class="prod-stat-note">' + escapeHtml(note) + "</div>" : "") +
    "</div>";
}

function dropStats(statsId, footId) {
  const stats = document.getElementById(statsId);
  const foot = document.getElementById(footId);
  if (stats) stats.remove();
  if (foot) foot.remove();
}

function getJSON(url) {
  return fetch(url).then(r => (r.ok ? r.json() : Promise.reject(new Error(url + " " + r.status))));
}

/* "31 December 2025 – 20 May 2026" from two ISO dates */
function dateRange(a, b) {
  const day = iso => Number(iso.slice(8, 10)) + " " + fmtPeriodLong(iso);
  return day(a) + " – " + day(b);
}

function fillHoldings() {
  return getJSON("/api/v1/equity/summary").then(d => {
    const tn = d.total_book_value_yen === null || d.total_book_value_yen === undefined
      ? null : d.total_book_value_yen / 1e12;
    document.getElementById("hold-stats").innerHTML = [
      eqStat("Named Policy Holdings", "¥" + fmtNum(tn, 2) + "tn", "at book, as filed"),
      eqStat("Filers Extracted", fmtNum(d.filers, 0), "of ~3,800 eventually"),
      eqStat("Positions Cut · Added", fmtNum(d.positions_reduced, 0) +
        " · " + fmtNum(d.positions_increased, 0), "year on year, calculated"),
    ].join("");
    document.getElementById("hold-foot").textContent =
      "From " + fmtNum(d.named_holdings, 0) + " named holdings in annual securities " +
      "reports · coverage grows as filings are extracted";
  }).catch(() => dropStats("hold-stats", "hold-foot"));
}

function fillOwnership() {
  return getJSON("/api/v1/equity/ownership/summary").then(d => {
    document.getElementById("own-stats").innerHTML = [
      eqStat("Companies", fmtNum(d.companies, 0), "latest filing each"),
      eqStat("Foreign Ownership", fmtRate(d.avg_foreign_pct, 1),
        "average across companies, calculated"),
      eqStat("Named Holders' Share", fmtRate(d.avg_top_holders_pct, 1),
        "top-10 table average, calculated"),
    ].join("");
    document.getElementById("own-foot").textContent =
      "From " + fmtNum(d.register_rows, 0) + " register rows · fiscal periods ending " +
      dateRange(d.earliest_period_end, d.latest_period_end) +
      " · registers as filed; averages calculated";
  }).catch(() => dropStats("own-stats", "own-foot"));
}

function fillStakes() {
  return getJSON("/api/v1/equity/stakes/summary").then(d => {
    const cur = d.current_positions || {};
    document.getElementById("stk-stats").innerHTML = [
      eqStat("Filings Parsed", fmtNum(d.filings, 0), "reports and amendments, as filed"),
      eqStat("Positions ≥ 5% Now", fmtNum(cur.at_or_above_5pct, 0),
        "across " + fmtNum(cur.issuers, 0) + " issuers, calculated"),
      eqStat("Activist Filings", fmtNum(d.activist_filings, 0),
        "state possible important proposals"),
    ].join("");
    document.getElementById("stk-foot").textContent =
      "From " + fmtNum(d.filers, 0) + " filers · median " +
      fmtNum(d.median_days_to_file, 0) + " days from trigger to filing · " +
      "the archive reaches back as far as EDINET's list API does (~5 years)";
  }).catch(() => dropStats("stk-stats", "stk-foot"));
}

function fillGovernance() {
  return getJSON("/api/v1/equity/governance/summary?listed=true").then(d => {
    document.getElementById("gov-stats").innerHTML = [
      eqStat("Companies", fmtNum(d.companies, 0), "latest filing each"),
      eqStat("Average Director Age", fmtNum(d.avg_director_age, 1) + " yrs",
        fmtNum(d.directors_70_plus_pct, 1) + "% aged 70+, calculated"),
      eqStat("Female Officers", fmtRate(d.avg_female_officer_pct, 1),
        fmtNum(d.boards_with_no_women, 0) + " boards with none"),
    ].join("");
    document.getElementById("gov-foot").textContent =
      "From " + fmtNum(d.board_seats, 0) + " board seats in annual securities reports · " +
      "names, titles and pay as filed; ages and ratios calculated";
  }).catch(() => dropStats("gov-stats", "gov-foot"));
}

function fillBuyback() {
  return getJSON("/api/v1/equity/buyback/summary").then(d => {
    document.getElementById("bb-stats").innerHTML = [
      eqStat("Authorised", "¥" + fmtNum(d.authorised_yen / 1e12, 2) + "tn",
        fmtNum(d.authorisations, 0) + " authorisations, as filed"),
      eqStat("Actually Bought", "¥" + fmtNum(d.acquired_yen / 1e12, 2) + "tn",
        "cumulative against those authorisations"),
      eqStat("Shares Retired", fmtNum(d.shares_retired / 1e9, 2) + "bn",
        "¥" + fmtNum(d.retired_yen / 1e12, 2) + "tn cancelled outright"),
    ].join("");
    document.getElementById("bb-foot").textContent =
      "From " + fmtNum(d.filings, 0) + " monthly buyback reports by " +
      fmtNum(d.companies, 0) + " companies · figures as filed; completion calculated";
  }).catch(() => dropStats("bb-stats", "bb-foot"));
}

function fillFacilities() {
  return getJSON("/api/v1/equity/facilities/summary").then(d => {
    const s = d.summary || d;
    document.getElementById("fac-stats").innerHTML = [
      eqStat("Companies", fmtNum(s.companies, 0), "one clean filing each"),
      eqStat("Land at Book", "¥" + fmtNum(s.land_book_yen / 1e12, 2) + "tn",
        "historical cost, as filed"),
      eqStat("Facilities Mapped", fmtNum(s.facility_rows_geocoded, 0),
        "of " + fmtNum(s.facility_rows, 0) + " disclosed"),
    ].join("");
    document.getElementById("fac-foot").textContent =
      "Fiscal periods ending " + dateRange(s.first_period_end, s.last_period_end) +
      " · book values are historical cost, not market value";
  }).catch(() => dropStats("fac-stats", "fac-foot"));
}

function fillFinancials() {
  return getJSON("/api/v1/equity/financials/summary").then(d => {
    const t = d.totals;
    const clean = (d.status.find(x => x.status === "clean") || {}).n || 0;
    const years = d.years.map(y => y.year);
    document.getElementById("fin-stats").innerHTML = [
      eqStat("Companies", fmtNum(t.companies, 0), "one accepted annual report each"),
      eqStat("Tagged Values", fmtNum(t.facts, 0), fmtNum(t.elements, 0) + " distinct line items"),
      eqStat("Balance Sheets Reconciled", fmtNum(clean, 0),
        "filings where assets = liabilities + net assets"),
    ].join("");
    document.getElementById("fin-foot").textContent =
      "Fiscal years ending " + (years.length ? years[years.length - 1] + "–" + years[0] : "—") +
      " · every value exactly as tagged; ratios are the filer's own";
  }).catch(() => dropStats("fin-stats", "fin-foot"));
}

fillHoldings();
fillOwnership();
fillStakes();
fillGovernance();
fillBuyback();
fillFacilities();
fillFinancials();

initThemeToggle();
