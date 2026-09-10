/* Japanese banks. The question this screen answers: "How are Japan's banks
   doing — bad loans, earnings — and what does any one bank's balance sheet
   look like?"

   Three datasets, one page: the FSA's bad-loan disclosure by bank group
   (fsa-npl), the FSA's results summary for the major and regional banks
   (fsa-bank-results), and the JBA's per-bank statements (jba-banks). Every
   figure is an official value as published; the only calculations here are
   changes, and they carry their formula on the page and in every export. A
   value a source does not publish is "—", never zero. */
"use strict";

const NPL = "/api/v1/fsa-npl";
const RES = "/api/v1/fsa-bank-results";
const JBA = "/api/v1/jba-banks";

/* Bad-loan ratio series shown, in slot order. Six is the platform's ceiling
   for one line chart; the two combined groups (major, all deposit-takers)
   are left to the API. */
const NPL_GROUPS = [
  { code: "all-banks", label: "All banks", slot: 1 },
  { code: "city", label: "City banks", slot: 2 },
  { code: "regional-1", label: "Regional banks (first association)", slot: 3 },
  { code: "regional-2", label: "Regional banks (second association)", slot: 4 },
  { code: "shinkin", label: "Shinkin banks", slot: 5 },
  { code: "shinkumi", label: "Credit co-operatives", slot: 6 },
];

/* Earnings measures: the same FSA line for both groups except net business
   profit, where the majors' consolidated 業務純益 and the regionals'
   non-consolidated 実質業務純益 are different measures and are named so. */
const MEASURES = {
  "net-income": { label: "Net income",
    major: ["major.net-income.fy", "Major banks (attributable to parent)"],
    regional: ["regional.net-income.fy", "Regional banks"] },
  "net-business-profit": { label: "Net business profit",
    major: ["major.net-business-profit.fy", "Major banks (consolidated net business profit)"],
    regional: ["regional.real-net-business-profit.fy", "Regional banks (real net business profit)"] },
  "credit-costs": { label: "Credit costs",
    major: ["major.credit-costs.fy", "Major banks"],
    regional: ["regional.credit-costs.fy", "Regional banks"] },
  "net-interest-income": { label: "Net interest income",
    major: ["major.net-interest-income.fy", "Major banks"],
    regional: ["regional.net-interest-income.fy", "Regional banks"] },
};

/* The principal lines of a statement, by basis, in the association's own
   order. The line code is the JBA reference code; the income statement is
   read on the fiscal-year (.fy) series. */
const LINES = {
  s: [
    ["Balance sheet", null],
    ["a015", "Deposits"], ["a135", "Negotiable certificates of deposit"],
    ["a345", "Borrowed money"], ["a480", "Bonds payable"], ["a980", "Total liabilities"],
    ["b050", "Share capital"], ["b300", "Retained earnings"],
    ["b700", "Valuation difference on available-for-sale securities"], ["b950", "Total net assets"],
    ["d005", "Cash and due from banks"], ["d275", "Securities"], ["d290", "of which government bonds", 1],
    ["d350", "of which stocks", 1], ["d395", "Loans and bills discounted"],
    ["d965", "Allowance for loan losses"], ["d990", "Total assets"],
    ["Income statement, fiscal year", null],
    ["e010.fy", "Ordinary income"], ["e020.fy", "Interest income", 1], ["e030.fy", "of which interest on loans", 2],
    ["e120.fy", "Fees and commissions", 1], ["e340.fy", "Ordinary expenses"], ["e350.fy", "Interest expenses", 1],
    ["e360.fy", "of which interest on deposits", 2], ["e680.fy", "General and administrative expenses", 1],
    ["e730.fy", "Provision of allowance for loan losses", 1], ["k400.fy", "Net business profit"],
    ["e800.fy", "Ordinary profit"], ["f450.fy", "Profit before income taxes"], ["f850.fy", "Net income"],
  ],
  c: [
    ["Balance sheet", null],
    ["a010", "Deposits"], ["a050", "Negotiable certificates of deposit"], ["a330", "Borrowed money"],
    ["a450", "Bonds payable"], ["a950", "Total liabilities"], ["b010", "Share capital"],
    ["b190", "Retained earnings"], ["b430", "Valuation difference on available-for-sale securities"],
    ["b970", "Total net assets"], ["d010", "Cash and due from banks"], ["d250", "Securities"],
    ["d310", "Loans and bills discounted"], ["d910", "Allowance for loan losses"], ["d970", "Total assets"],
    ["Income statement, fiscal year", null],
    ["e010.fy", "Ordinary income"], ["e025.fy", "Interest income", 1], ["e190.fy", "Fees and commissions", 1],
    ["e350.fy", "Ordinary expenses"], ["e380.fy", "Interest expenses", 1],
    ["e860.fy", "General and administrative expenses", 1], ["e920.fy", "Provision of allowance for loan losses", 1],
    ["e970.fy", "Ordinary profit"], ["f490.fy", "Profit before income taxes"], ["f790.fy", "Net income"],
    ["f940.fy", "Net income attributable to owners of parent"],
  ],
};
const DEPOSITS = { s: "a015", c: "a010" };
const LOANS = { s: "d395", c: "d310" };

const CHANGE_CALC =
  "change[t] = value[t] − value[t−12 months], from published values; percent change = " +
  "(value[t] ÷ value[t−12 months] − 1) × 100. A period missing either side shows —, never zero.";

function $(id) { return document.getElementById(id); }

const D = { rel: {}, stale: false, series: {}, banks: [], consolidated: {} };

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

/* /observations takes at most eight codes and 200 characters of them. */
const MAX_CODES = 8;
const MAX_SERIES_CHARS = 190;

function batchCodes(codes) {
  const batches = [];
  let current = [], length = 0;
  codes.forEach(c => {
    const cost = c.length + (current.length ? 1 : 0);
    if (current.length && (current.length >= MAX_CODES || length + cost > MAX_SERIES_CHARS)) {
      batches.push(current);
      current = []; length = 0;
    }
    current.push(c);
    length += cost;
  });
  if (current.length) batches.push(current);
  return batches;
}

/* Series are cached under "<api>|<code>". A code the release does not carry
   404s the whole batch, so unknown codes are requested one at a time and an
   absent series is stored as empty — it renders "—", never a zero. */
async function loadSeries(api, codes) {
  const want = codes.filter(c => !((api + "|" + c) in D.series));
  for (const chunk of batchCodes(want)) {
    try {
      const payload = await getJSON(api + "/observations?series=" + encodeURIComponent(chunk.join(",")));
      payload.series.forEach(s => { D.series[api + "|" + s.code] = s.points; });
    } catch (err) {
      if (chunk.length === 1) { D.series[api + "|" + chunk[0]] = []; continue; }
      for (const one of chunk) await loadSeries(api, [one]);
    }
  }
  codes.forEach(c => { if (!((api + "|" + c) in D.series)) D.series[api + "|" + c] = []; });
}

function pts(api, code) { return D.series[api + "|" + code] || []; }

function at(api, code, period) {
  const p = pts(api, code);
  for (let i = 0; i < p.length; i++) if (p[i][0] === period) return p[i][1];
  return null;
}

function latestOf(api, code) {
  const p = pts(api, code);
  for (let i = p.length - 1; i >= 0; i--) if (p[i][1] !== null) return p[i][0];
  return null;
}

/* "2026-03-01" -> "Mar 2026"; a half-year is dated to its closing month. */
function half(period) {
  if (!period) return MISSING;
  return (period.slice(5, 7) === "03" ? "Mar " : "Sep ") + period.slice(0, 4);
}
/* "2026-03-01" -> "FY2025": a March point closes the fiscal year that began
   the April before. */
function fyOf(period) { return period ? "FY" + (Number(period.slice(0, 4)) - 1) : MISSING; }
function yearBefore(period) { return String(Number(period.slice(0, 4)) - 1) + period.slice(4); }

/* ---- URL state ---- */

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    range: p.get("range") === "10" ? "10" : "max",
    measure: MEASURES[p.get("measure")] ? p.get("measure") : "net-income",
    bank: p.get("bank") || "0001",
    basis: p.get("basis") === "c" ? "c" : "s",
  };
}

function setUrlState(next) {
  const s = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (s.range !== "max") p.set("range", s.range);
  if (s.measure !== "net-income") p.set("measure", s.measure);
  if (s.bank !== "0001") p.set("bank", s.bank);
  if (s.basis !== "s") p.set("basis", s.basis);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

/* ---- head, staleness, provenance ---- */

function renderHead() {
  const latest = D.rel.npl.latest_period;
  $("page-asof").textContent = "Bad loans through " + half(latest) +
    " · results through " + half(D.rel.res.latest_period) +
    " · statements through " + half(D.rel.jba.latest_period);
  $("header-asof").textContent = half(latest);
  const ratio = at(NPL, "all-banks.npl-ratio", latest);
  const claims = at(NPL, "all-banks.disclosed", latest);
  const majorPeriod = latestOf(RES, "major.net-income.fy");
  const major = at(RES, "major.net-income.fy", majorPeriod);
  $("page-sub").innerHTML =
    "At " + half(latest) + " the banks' bad-loan ratio was <strong class=\"num\">" +
    fmtRate(ratio, 1) + "</strong> of total credit, on ¥" +
    fmtNum(claims === null ? null : claims / 10000, 1) + "tn of disclosed claims. The major " +
    "banks earned <strong class=\"num\">¥" + fmtNum(major === null ? null : major / 10, 0) +
    "bn</strong> in " + fyOf(majorPeriod) + ". " + trustBadge("official");
}

function renderStale() {
  const el = $("stale-banner");
  const stale = ["npl", "res", "jba"].filter(k => D.stale[k]);
  if (!stale.length) { el.innerHTML = ""; return; }
  const names = { npl: "bad-loan disclosure", res: "results summary", jba: "bank statements" };
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the ' +
    escapeHtml(stale.map(k => names[k] + " (through " + half(D.rel[k].latest_period) + ")").join(", ")) +
    " " + (stale.length > 1 ? "are" : "is") + " older than the source's own cadence allows. " +
    "If this persists, run the ingestion.</div>";
}

function provCard(rel, title, sub) {
  return '<div class="prov-card">' +
    '<div class="prov-card-head">' +
      '<div class="prov-card-title">' + escapeHtml(title) + "</div>" +
      '<div class="prov-card-id">' + escapeHtml(rel.source_id || "") + "</div>" +
    "</div>" +
    '<div class="prov-grid">' +
      '<div class="prov-field full">' +
        '<div class="prov-label">Official source</div>' +
        '<div class="prov-value"><a href="' + escapeHtml(rel.source_page || "#") +
          '" rel="noopener">' + escapeHtml(rel.source_name || "") + "</a></div>" +
        '<div class="prov-sub">' + escapeHtml(sub) + "</div>" +
      "</div>" +
      '<div class="prov-field">' +
        '<div class="prov-label">Release</div>' +
        '<div class="prov-value">Data through ' + escapeHtml(half(rel.latest_period)) + "</div>" +
        '<div class="prov-sub">Published half-yearly</div>' +
      "</div>" +
      '<div class="prov-field">' +
        '<div class="prov-label">Retrieved</div>' +
        '<div class="prov-value num">' + fmtStamp(rel.retrieved_at) + "</div>" +
        '<div class="prov-sub">Archived ' + fmtStamp(rel.ingested_at) + "</div>" +
      "</div>" +
      '<div class="prov-field full">' +
        '<div class="prov-label">Archived checksum (SHA-256)</div>' +
        '<div class="prov-hash">' + escapeHtml(rel.sha256 || "") + "</div>" +
      "</div>" +
    "</div></div>";
}

function renderProvenance() {
  $("prov-cards").innerHTML =
    provCard(D.rel.npl, "Bad Loans by Bank Group",
      "Table 1 of every FSA release since 2006, archived together under one checksum; " +
      "the newest release wins where two overlap.") +
    provCard(D.rel.res, "Bank Earnings by Group",
      "The FSA's two long-run workbooks (major banks, regional banks), archived together.") +
    provCard(D.rel.jba, "Bank Financial Statements",
      "The aggregate and per-bank workbooks of every JBA edition since fiscal 2006, " +
      "archived together under one checksum.");
}

/* ---- stat strip ---- */

function tileCell(label, valueHtml, deltaHtml, dir, title) {
  return '<div class="strip-cell">' +
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' + escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + valueHtml + "</div>" +
    '<div class="strip-delta num ' + dir + '">' + deltaHtml + "</div>" +
    "</div>";
}

function delta(v, dp, unit) {
  if (v === null || v === undefined) return { html: MISSING, dir: "flat" };
  const rounded = Number(v.toFixed(dp));
  const dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
  const arrow = rounded === 0 ? ""
    : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
      '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
  return { html: arrow + fmtNum(Math.abs(rounded), dp) + " " + unit, dir: dir };
}

function renderTiles() {
  const latest = D.rel.npl.latest_period;
  const prior = yearBefore(latest);
  const ratio = at(NPL, "all-banks.npl-ratio", latest), ratioWas = at(NPL, "all-banks.npl-ratio", prior);
  const claims = at(NPL, "all-banks.disclosed", latest), claimsWas = at(NPL, "all-banks.disclosed", prior);
  const dRatio = delta(ratio === null || ratioWas === null ? null : ratio - ratioWas, 1, "pp");
  const dClaims = delta(claims === null || claimsWas === null ? null : (claims - claimsWas) / 10000, 2, "¥tn");
  const cells = [
    tileCell("Bad-Loan Ratio, All Banks",
      fmtNum(ratio, 1) + '<span class="unit">%</span>', dRatio.html, dRatio.dir,
      "Disclosed claims as a share of total credit, all banks, " + half(latest) + ", as published by the FSA."),
    tileCell("Disclosed Claims, All Banks",
      fmtNum(claims === null ? null : claims / 10000, 1) + '<span class="unit">¥tn</span>',
      dClaims.html, dClaims.dir,
      "Claims disclosed under the Financial Reconstruction Act, all banks, published in ¥100mn and shown in ¥tn."),
  ];
  [["major", "Major Banks Net Income"], ["regional", "Regional Banks Net Income"]].forEach(([g, label]) => {
    const code = g + ".net-income.fy";
    const p = latestOf(RES, code);
    const now = at(RES, code, p), was = p ? at(RES, code, yearBefore(p)) : null;
    const d = delta(now === null || was === null ? null : (now - was) / 10, 0, "¥bn");
    cells.push(tileCell(label + ", " + fyOf(p),
      fmtSigned(now === null ? null : now / 10, 0) + '<span class="unit">¥bn</span>', d.html, d.dir,
      label + " for the fiscal year, published in ¥100mn and shown in ¥bn."));
  });
  $("tiles").innerHTML = cells.join("");
  $("strip-foot").textContent =
    "Changes are against the same half-year a year earlier (ratio in percentage points) or the " +
    "prior fiscal year · ¥tn = published ¥100mn ÷ 10,000 and ¥bn = ¥100mn ÷ 10, exact conversions";
  $("strip-calc").style.display = "";
  $("strip-calc").innerHTML = "<summary>Show calculation</summary><p>" + escapeHtml(CHANGE_CALC) +
    "</p><p>Ratios and amounts are published values, not recomputed.</p>";
}

/* ---- bad-loan ratio by group ---- */

let nplChart = null;

function nplPeriods() {
  const set = new Set();
  NPL_GROUPS.forEach(g => pts(NPL, g.code + ".npl-ratio").forEach(p => set.add(p[0])));
  const all = Array.from(set).sort();
  return urlState().range === "10" ? all.slice(-20) : all;
}

function renderNpl() {
  const periods = nplPeriods();
  const cfg = {
    series: NPL_GROUPS.map(g => ({
      name: g.label, slot: g.slot,
      points: periods.map(p => [half(p), at(NPL, g.code + ".npl-ratio", p)]),
    })),
    xType: "category", unit: "%", dp: 1,
    yAxisName: "Bad-loan ratio, % of total credit", yAxisDp: 0,
    trust: "official", legendFloor: 900, legendBottomNarrow: 118,
    sourceLine: "Source: FSA — Status of claims disclosed under the Financial Reconstruction Act " +
      "(金融再生法開示債権の状況等). Data through " + half(D.rel.npl.latest_period) + ".",
  };
  if (nplChart) nplChart.render(cfg); else nplChart = obsChart($("npl-chart"), "line", cfg);
  $("npl-note").textContent = periods.length ? half(periods[0]) + "–" + half(periods[periods.length - 1]) : "";
  $("npl-source").innerHTML = escapeHtml(cfg.sourceLine) + " " + trustBadge("official");
  $("npl-calc").innerHTML = "<summary>Show calculation</summary><p>Published ratio (不良債権比率) " +
    "for each lender group, as released by the FSA. Not computed here. Groups by bank type " +
    "separately begin at March 2002; all banks begin at March 1999. A half-year is dated to its " +
    "closing month.</p>";
}

/* ---- earnings by group ---- */

let earnChart = null;

function renderEarn() {
  const m = MEASURES[urlState().measure];
  const set = new Set();
  [m.major[0], m.regional[0]].forEach(c => pts(RES, c).forEach(p => set.add(p[0])));
  const periods = Array.from(set).sort();
  const cfg = {
    categories: periods.map(fyOf),
    series: [
      { name: m.major[1], slot: 1, points: periods.map(p => { const v = at(RES, m.major[0], p); return v === null ? null : v / 10; }) },
      { name: m.regional[1], slot: 3, points: periods.map(p => { const v = at(RES, m.regional[0], p); return v === null ? null : v / 10; }) },
    ],
    dp: 0, unitSuffix: "¥bn", yAxisName: m.label + ", ¥bn", trust: "official", legendFloor: 900,
    sourceLine: "Source: FSA — Summary of bank financial results (主要行等・地域銀行の決算の概要). " +
      "Data through " + fyOf(D.rel.res.latest_period) + ".",
  };
  if (earnChart) earnChart.render(cfg); else earnChart = obsChart($("earn-chart"), "cols", cfg);
  $("earn-note").textContent = periods.length ? fyOf(periods[0]) + "–" + fyOf(periods[periods.length - 1]) : "";
  $("earn-source").innerHTML = escapeHtml(cfg.sourceLine) + " " + trustBadge("official");
  $("earn-calc").innerHTML = "<summary>Show calculation</summary><p>" + escapeHtml(m.label) +
    " for the fiscal year as published by the FSA (the 3月期 figure), in ¥100mn, shown in ¥bn — " +
    "an exact division by 10. Credit costs carry the FSA's sign: a negative is a cost. The " +
    "major-bank figure is consolidated; the regional-bank figure is not.</p>";
}

/* ---- one bank's statement ---- */

let bankChart = null;

function bankLabel(code) {
  const b = D.banks.find(x => x.code === code);
  return b ? b.name : code;
}

function seriesCode(basis, bank, line) { return basis + "." + bank + "." + line; }

async function loadBank() {
  const st = urlState();
  const codes = LINES[st.basis].filter(l => l[1] !== null).map(l => seriesCode(st.basis, st.bank, l[0]));
  await loadSeries(JBA, codes);
}

function bankPeriods(basis, bank) {
  const set = new Set();
  pts(JBA, seriesCode(basis, bank, DEPOSITS[basis])).forEach(p => set.add(p[0]));
  return Array.from(set).sort();
}

function renderBank() {
  const st = urlState();
  const periods = bankPeriods(st.basis, st.bank);
  const marches = periods.filter(p => p.slice(5, 7) === "03");
  const latest = marches.length ? marches[marches.length - 1] : null;
  const prior = latest ? yearBefore(latest) : null;
  const name = bankLabel(st.bank) + (st.basis === "c" ? " (consolidated)" : "");
  $("bank-note").textContent = name;
  if (!latest) {
    $("bank-table").innerHTML = '<p class="table-foot">No ' + (st.basis === "c" ? "consolidated" : "non-consolidated") +
      " statements are published for this bank.</p>";
    $("bank-foot").textContent = "";
    $("bank-calc").innerHTML = "";
    return;
  }
  const head = "<thead><tr>" +
    '<th scope="col">Line</th>' +
    '<th scope="col" class="num">' + fyOf(latest) + " (" + half(latest) + "), ¥bn</th>" +
    '<th scope="col" class="num">' + fyOf(prior) + ", ¥bn</th>" +
    '<th scope="col" class="num">Change, ¥bn</th>' +
    '<th scope="col" class="num">Change, %</th>' +
    "</tr></thead>";
  const body = LINES[st.basis].map(([line, label, indent]) => {
    if (label === null) {
      return '<tr><th scope="rowgroup" colspan="5" style="text-align:left">' + escapeHtml(line) + "</th></tr>";
    }
    const c = seriesCode(st.basis, st.bank, line);
    const now = at(JBA, c, latest), was = at(JBA, c, prior);
    const change = (now === null || was === null) ? null : now - was;
    const pct = (change === null || !was) ? null : (change / Math.abs(was)) * 100;
    return "<tr>" +
      '<td' + (indent ? ' class="indent-' + indent + '"' : "") + '>' + escapeHtml(label) +
        ' <span class="muted">' + escapeHtml(line.replace(".fy", "")) + "</span></td>" +
      '<td class="num" data-sort="' + (now ?? "") + '">' + fmtNum(now === null ? null : now / 1000, 1) + "</td>" +
      '<td class="num" data-sort="' + (was ?? "") + '">' + fmtNum(was === null ? null : was / 1000, 1) + "</td>" +
      '<td class="num" data-sort="' + (change ?? "") + '">' + fmtSigned(change === null ? null : change / 1000, 1) + "</td>" +
      '<td class="num" data-sort="' + (pct ?? "") + '">' + (pct === null ? MISSING : fmtSigned(pct, 1, "%")) + "</td>" +
      "</tr>";
  }).join("");
  $("bank-table").innerHTML = '<table class="data" data-no-enhance>' + head + "<tbody>" + body + "</tbody></table>";
  $("bank-foot").textContent =
    "Published amounts in millions of yen, shown in ¥bn (÷ 1,000). The code beside each line is the " +
    "association's reference code — the key to the full statement in the API. A line the association " +
    "does not publish for this bank shows — and is not a zero. Release: statements through " +
    half(D.rel.jba.latest_period) + ".";
  $("bank-calc").innerHTML = "<summary>Show calculation</summary><p>" + escapeHtml(CHANGE_CALC) +
    "</p><p>Balance-sheet lines are the end of the fiscal year (March); income-statement lines are " +
    "the full fiscal year. Amounts are published values, not recomputed.</p>";

  const cfg = {
    series: [
      { name: "Deposits", slot: 1, points: periods.map(p => { const v = at(JBA, seriesCode(st.basis, st.bank, DEPOSITS[st.basis]), p); return [half(p), v === null ? null : v / 1e6]; }) },
      { name: "Loans and bills discounted", slot: 2, points: periods.map(p => { const v = at(JBA, seriesCode(st.basis, st.bank, LOANS[st.basis]), p); return [half(p), v === null ? null : v / 1e6]; }) },
    ],
    xType: "category", unit: "index", unitSuffix: "¥tn", dp: 2,
    yAxisName: "¥tn, end of half-year", yAxisDp: 1, trust: "official",
    sourceLine: "Source: JBA — Analysis of Financial Statements of All Banks (全国銀行財務諸表分析). " +
      name + ". Data through " + half(D.rel.jba.latest_period) + ".",
  };
  if (bankChart) bankChart.render(cfg); else bankChart = obsChart($("bank-chart"), "line", cfg);
  $("bank-chart-title").textContent = "Deposits and Loans — " + name;
  $("bank-source").innerHTML = escapeHtml(cfg.sourceLine) + " " + trustBadge("official");
  $("bank-chart-calc").innerHTML = "<summary>Show calculation</summary><p>Deposits (預金) and loans " +
    "and bills discounted (貸出金) at the end of each half-year, as published in millions of yen; " +
    "¥tn = millions ÷ 1,000,000, an exact conversion. A half-year the bank did not report is a gap " +
    "in the line.</p>";
}

function bankCSV() {
  const st = urlState();
  const periods = bankPeriods(st.basis, st.bank);
  const marches = periods.filter(p => p.slice(5, 7) === "03");
  if (!marches.length) return;
  const latest = marches[marches.length - 1], prior = yearBefore(latest);
  const name = bankLabel(st.bank) + (st.basis === "c" ? " (consolidated)" : "");
  const header = [
    "Japan Data Observatory — bank financial statement, principal lines",
    "Bank: " + name + " (金融機関コード " + st.bank + ", basis " + (st.basis === "c" ? "consolidated" : "non-consolidated") + ")",
    "Source: " + (D.rel.jba.source_name || ""),
    "Release: statements through " + half(D.rel.jba.latest_period),
    "Retrieved: " + fmtStamp(D.rel.jba.retrieved_at) + " · SHA-256 " + (D.rel.jba.sha256 || ""),
    "Unit: millions of yen, exactly as published (not the ¥bn shown on screen)",
    "Trust: amounts are official statistics as published; the change is calculated from them",
    CHANGE_CALC,
    "An empty cell is a line the association does not publish for this bank — never zero",
  ].map(l => "# " + l).join("\n");
  const rows = ["line_code,label," + latest + "_jpy_million," + prior + "_jpy_million,change_jpy_million,change_pct"];
  LINES[st.basis].forEach(([line, label]) => {
    if (label === null) return;
    const c = seriesCode(st.basis, st.bank, line);
    const now = at(JBA, c, latest), was = at(JBA, c, prior);
    const change = (now === null || was === null) ? "" : now - was;
    const pct = (change === "" || !was) ? "" : (change / Math.abs(was)) * 100;
    rows.push([line, '"' + label.replace(/"/g, '""') + '"', now ?? "", was ?? "", change, pct].join(","));
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([header + "\n" + rows.join("\n") + "\n"], { type: "text/csv" }));
  a.download = "bank-statement-" + st.bank + "-" + st.basis + "-" + latest.slice(0, 4) + ".csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---- exports ---- */

function exportHeader(rel, title, extra) {
  return [
    "Japan Data Observatory — " + title,
    "Source: " + (rel.source_name || ""),
    "Release: data through " + half(rel.latest_period),
    "Retrieved: " + fmtStamp(rel.retrieved_at) + " · SHA-256 " + (rel.sha256 || ""),
    "A half-year is dated to its closing month (March or September)",
  ].concat(extra || []).concat(["An empty cell is a value the source did not publish — never zero"]);
}

/* ---- wiring ---- */

function seg(id, attr, key, after) {
  $(id).querySelectorAll("button").forEach(b => {
    b.addEventListener("click", () => {
      const next = {}; next[key] = b.getAttribute(attr);
      setUrlState(next); syncSeg(id, attr, key); after();
    });
  });
  syncSeg(id, attr, key);
}

function syncSeg(id, attr, key) {
  const cur = String(urlState()[key]);
  $(id).querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.getAttribute(attr) === cur)));
}

async function boot() {
  initThemeToggle(() => { renderNpl(); renderEarn(); renderBank(); });

  const [npl, res, jba, listing] = await Promise.all([
    getJSON(NPL + "/overview"), getJSON(RES + "/overview"), getJSON(JBA + "/overview"),
    // The deposits line of every bank names every bank the release carries;
    // the listing is a search, and the codes tell the bases apart.
    getJSON(JBA + "/series?q=" + encodeURIComponent("deposits")),
  ]);
  D.rel = { npl: npl.release, res: res.release, jba: jba.release };
  D.stale = { npl: npl.stale, res: res.stale, jba: jba.stale };
  (listing.series || []).forEach(s => {
    const m = /^s\.(\d{4})\.a015$/.exec(s.code);
    if (m) D.banks.push({ code: m[1], name: s.name_en.split(" — ")[0] });
    const c = /^c\.(\d{4})\.a010$/.exec(s.code);
    if (c) D.consolidated[c[1]] = true;
  });
  if (!D.banks.some(b => b.code === urlState().bank)) setUrlState({ bank: D.banks.length ? D.banks[0].code : "0001" });

  await Promise.all([
    // One unit per request: the API refuses a ratio and an amount together.
    loadSeries(NPL, NPL_GROUPS.map(g => g.code + ".npl-ratio")),
    loadSeries(NPL, ["all-banks.disclosed"]),
    loadSeries(RES, Object.keys(MEASURES).map(k => MEASURES[k].major[0]).concat(Object.keys(MEASURES).map(k => MEASURES[k].regional[0]))),
    loadBank(),
  ]);

  const select = $("bank-select");
  select.innerHTML = D.banks.map(b => '<option value="' + escapeHtml(b.code) + '">' +
    escapeHtml(b.name) + " · " + escapeHtml(b.code) + "</option>").join("");
  select.value = urlState().bank;
  const measure = $("earn-measure");
  measure.innerHTML = Object.keys(MEASURES).map(k => '<option value="' + k + '">' +
    escapeHtml(MEASURES[k].label) + "</option>").join("");
  measure.value = urlState().measure;

  renderHead(); renderStale(); renderTiles(); renderNpl(); renderEarn(); renderBank(); renderProvenance();

  seg("npl-range", "data-range", "range", renderNpl);
  seg("bank-basis", "data-basis", "basis", async () => { await loadBank(); renderBank(); });
  select.addEventListener("change", async e => { setUrlState({ bank: e.target.value }); await loadBank(); renderBank(); });
  measure.addEventListener("change", e => { setUrlState({ measure: e.target.value }); renderEarn(); });

  $("npl-png").addEventListener("click", () => nplChart.exportPNG("bad-loan-ratio-by-bank-group.png"));
  $("npl-csv").addEventListener("click", () => nplChart.exportCSV("bad-loan-ratio-by-bank-group.csv",
    exportHeader(D.rel.npl, "bad-loan ratio by bank group", [
      "Unit: percent of total credit, official statistic as published (不良債権比率)"])));
  $("earn-png").addEventListener("click", () => earnChart.exportPNG("bank-earnings-by-group.png"));
  $("earn-csv").addEventListener("click", () => earnChart.exportCSV("bank-earnings-by-group.csv",
    exportHeader(D.rel.res, "bank earnings by group", [
      "Unit: ¥ billion (published ¥100mn ÷ 10, an exact conversion)",
      "Measure: " + MEASURES[urlState().measure].label + " for the fiscal year (3月期), official statistic as published",
      "The major-bank figure is consolidated; the regional-bank figure is non-consolidated"])));
  $("bank-png").addEventListener("click", () => bankChart && bankChart.exportPNG("bank-deposits-loans-" + urlState().bank + ".png"));
  $("bank-chart-csv").addEventListener("click", () => bankChart && bankChart.exportCSV("bank-deposits-loans-" + urlState().bank + ".csv",
    exportHeader(D.rel.jba, "bank deposits and loans", [
      "Bank: " + bankLabel(urlState().bank) + " (金融機関コード " + urlState().bank + ", " + (urlState().basis === "c" ? "consolidated" : "non-consolidated") + ")",
      "Unit: ¥ trillion (published millions of yen ÷ 1,000,000, an exact conversion)"])));
  $("bank-csv").addEventListener("click", bankCSV);
}

boot().catch(err => {
  $("stale-banner").innerHTML = '<div class="banner" role="alert">This page could not load its data. ' +
    escapeHtml(String(err.message || err)) + "</div>";
});
