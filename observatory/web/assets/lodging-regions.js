/* Guest nights by region. The question this screen answers:
   "Which prefectures and towns are gaining and losing guest nights, and where
   are foreign guests concentrated?" — the contribution chart and the
   prefecture table lead.

   Two measures appear here and never share an axis or a ranking: guest nights
   are person-nights, room occupancy is a published percentage. Guest nights are
   official; contributions, growth, shares and the 2019 comparison are computed
   here and carry their formula. Missing is "—", never zero. */
"use strict";

const DATASET = "accommodation-jp";
const API = "/api/v1/" + DATASET;
const PER_MN = 1e6;
const RESIDUAL = "All other prefectures";
const TOP_N = 10;

let AC = null;
let PERIODS = [], LAST = 0;
let contribChart = null;

const CALCS = {
  contrib: "contribution[prefecture, t] = (guest nights[prefecture, t] − guest nights" +
    "[prefecture, t−12 months]) / guest nights[All Japan, t−12 months] × 100, in percentage " +
    "points. The residual is growth[All Japan, t] − Σ contribution[named prefectures, t], so " +
    "the bars sum to the national growth rate exactly.",
  yoy: "yoy[t] = (guest nights[t] / guest nights[t−12 months] − 1) × 100, from published values.",
  share: "share[prefecture] = (guest nights[prefecture] / guest nights[All Japan]) × 100, both " +
    "for the same month. The 47 prefectures partition the country; the transport-bureau regions " +
    "republish the same nights and are excluded from any share or sum.",
  fxshare: "foreign share[t] = (foreign guest nights[t] / guest nights[t]) × 100, both published " +
    "counts for the same month.",
  rec: "recovery[t] = (guest nights[t] / guest nights[same month of 2019]) × 100. 100 = the same " +
    "month of 2019, the last full year before the border closed.",
  occ: "Published room occupancy rate, exactly as released. A rate is never averaged across areas " +
    "here — the national figure is the Agency's own, not a mean of the prefectures.",
};

function mn(v) { return v === null || v === undefined ? null : v / PER_MN; }
function $(id) { return document.getElementById(id); }

const DEFAULTS = { cmeasure: "all", rows: "pref", sort: "nights", dir: "desc",
                   msort: "nights", mdir: "desc" };

function urlState() {
  const p = new URLSearchParams(location.search);
  const st = {};
  Object.keys(DEFAULTS).forEach(k => { st[k] = p.get(k) || DEFAULTS[k]; });
  return st;
}

function setUrlState(next) {
  const st = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  Object.keys(DEFAULTS).forEach(k => { if (st[k] !== DEFAULTS[k]) p.set(k, st[k]); });
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

/* ---- payload access ---------------------------------------------------- */

function col(code) { return (AC.backbone && AC.backbone[code]) || null; }

function at(code, i) {
  const c = col(code);
  return c && c[i] !== undefined && c[i] !== null ? c[i] : null;
}

function muniAt(code, i) {
  const c = AC.municipal[code];
  return c && c[i] !== undefined && c[i] !== null ? c[i] : null;
}

function yearsBack(i, n) {
  return PERIODS.indexOf((Number(PERIODS[i].slice(0, 4)) - n) + PERIODS[i].slice(4));
}

function growthOf(code, i, years) {
  const j = yearsBack(i, years || 1);
  if (j < 0) return null;
  const now = at(code, i), then = at(code, j);
  return (now === null || then === null || !then) ? null : (now / then - 1) * 100;
}

function recoveryOf(code, i) {
  const j = PERIODS.indexOf(AC.baseline_year + PERIODS[i].slice(4));
  if (j < 0) return null;
  const now = at(code, i), then = at(code, j);
  return (now === null || then === null || !then) ? null : (now / then) * 100;
}

function areasOf(kind) { return AC.areas.filter(a => a.kind === kind); }
function areaName(code) {
  const hit = AC.areas.filter(a => a.code === code)[0];
  return hit ? hit.name_en : code;
}

/* ---- chrome ------------------------------------------------------------ */

function sourceLine(unitText, trust) {
  const rel = AC.release;
  return "Source: Japan Tourism Agency · " + rel.source_id + " · " + unitText +
    " · Data through " + fmtPeriod(rel.latest_period) +
    " · Retrieved " + fmtStamp(rel.retrieved_at) +
    (TRUST_LABELS[trust] ? " · " + TRUST_LABELS[trust] : "");
}

function csvHeader(what, formulas) {
  const rel = AC.release;
  return [
    "Plover Analytics — " + what,
    "Source: Japan Tourism Agency, Accommodation Survey (観光庁『宿泊旅行統計調査』), " + rel.source_name,
    "Source page: " + rel.source_page,
    "Release: " + rel.label + " (sha256 " + rel.sha256 + ")",
    "Retrieved: " + fmtStamp(rel.retrieved_at),
    "Guest nights are official person-night counts and occupancy is an official percentage, " +
      "both exactly as published. Blank means the survey published no value.",
    "The 47 prefectures partition the country; the 10 transport-bureau regions republish the " +
      "same nights and must never be added to them.",
    "Stratification break: from the January 2026 survey the Agency stratifies by room " +
      "count rather than employee count; year-on-year comparisons spanning that boundary " +
      "may reflect the change rather than demand.",
  ].concat(formulas || []);
}

function renderHeader() {
  const rel = AC.release;
  $("header-asof").textContent = "Data through " + fmtPeriodLong(rel.latest_period);
  $("page-asof").textContent = "Ingested " + fmtStamp(rel.ingested_at);
  $("page-sub").textContent =
    "Monthly guest nights and room occupancy by area, " + PERIODS[0].slice(0, 4) +
    "–present · person-nights and percent · 47 prefectures, 10 bureau regions and " +
    AC.municipalities.length + " named municipalities · Japan Tourism Agency";
  $("credit-line").textContent = AC.credit_line;
}

function renderStale() {
  const el = $("stale-banner");
  if (!AC.stale) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
    "ingested data is for " + fmtPeriodLong(AC.release.latest_period) +
    ", ingested " + fmtStamp(AC.release.ingested_at) +
    ". The Agency publishes the second preliminary about two months in arrears — " +
    "if this persists, run the ingestion.</div>";
}

function renderProvenance() {
  const rel = AC.release;
  $("prov-card").innerHTML =
    '<div class="prov-card">' +
      '<div class="prov-card-head">' +
        '<div class="prov-card-title">Data Source</div>' +
        '<div class="prov-card-id">' + escapeHtml(rel.source_id) + "</div>" +
      "</div>" +
      '<div class="prov-grid">' +
        '<div class="prov-field full">' +
          '<div class="prov-label">Official source</div>' +
          '<div class="prov-value"><a href="' + escapeHtml(rel.source_page) +
            '" rel="noopener">' + escapeHtml(rel.source_name) + "</a></div>" +
          '<div class="prov-sub">One release is built from the Agency’s trend workbook, its ' +
            'annual definitive workbooks and the monthly second-preliminary files, archived ' +
            'together under one checksum.</div>' +
        "</div>" +
        '<div class="prov-field">' +
          '<div class="prov-label">Release</div>' +
          '<div class="prov-value">Data through ' + fmtPeriodLong(rel.latest_period) + "</div>" +
          '<div class="prov-sub">Published ' + escapeHtml(rel.frequency || "") + "</div>" +
        "</div>" +
        '<div class="prov-field">' +
          '<div class="prov-label">Retrieved</div>' +
          '<div class="prov-value num">' + fmtStamp(rel.retrieved_at) + "</div>" +
          '<div class="prov-sub">Archived ' + fmtStamp(rel.ingested_at) + "</div>" +
        "</div>" +
        '<div class="prov-field full">' +
          '<div class="prov-label">Archived checksum (SHA-256)</div>' +
          '<div class="prov-hash">' + escapeHtml(rel.sha256) + "</div>" +
        "</div>" +
      "</div>" +
    "</div>";
}


/* ---- the January 2026 stratification break -----------------------------

   From the January 2026 survey the Agency stratifies properties by room count
   instead of employee count, and says in its own trend workbook that
   year-on-year comparisons spanning the change may carry the effect of the
   change rather than of demand. Every year-on-year figure on this page
   currently spans it, so the disclosure is a banner and a rule on the charts,
   not a footnote. */

const BREAK_NOTE =
  "The Agency changed how it stratifies properties — from employee count to " +
  "room count — with the January 2026 survey, and states that year-on-year " +
  "comparisons spanning the change may reflect the change itself rather than " +
  "demand. Comparisons across that boundary are shown as published and are " +
  "not adjusted here.";

function breakIndex() {
  return AC.break_period ? PERIODS.indexOf(AC.break_period) : -1;
}

/* A year-on-year figure for month `i` straddles the break when the break falls
   in the twelve months behind it. */
function spansBreak(i) {
  const b = breakIndex();
  if (b < 0) return false;
  const j = yearsBack(i, 1);
  return j >= 0 && j < b && i >= b;
}

function breakEventLines(firstIso) {
  if (!AC.break_period) return [];
  if (firstIso && firstIso > AC.break_period) return [];
  // Kept short: at 390px an "end"-positioned label is clipped by the
  // plot edge, and a half-printed annotation is worse than a terse one.
  return [{ x: AC.break_period, label: "Method change" }];
}

function renderBreakNotice() {
  const el = document.getElementById("break-banner");
  if (!el) return;
  if (!spansBreak(LAST)) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner banner-note">Year-on-year figures on this page ' +
    "compare " + fmtPeriodLong(PERIODS[LAST]) + " with " +
    fmtPeriodLong(PERIODS[yearsBack(LAST, 1)]) + ", spanning a change in survey " +
    "method. " + escapeHtml(BREAK_NOTE) + "</div>";
}

/* ---- stat strip -------------------------------------------------------- */

function tileCell(label, valueHtml, deltaHtml, dir, title) {
  return '<div class="strip-cell">' +
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' +
      escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + valueHtml + "</div>" +
    '<div class="strip-delta num ' + dir + '">' + deltaHtml + "</div>" +
    "</div>";
}

function delta(value, dp, unit) {
  if (value === null) return { html: MISSING, dir: "flat" };
  const rounded = Number(value.toFixed(dp));
  const dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
  const arrow = rounded === 0 ? ""
    : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
      '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
  return { html: arrow + fmtNum(Math.abs(rounded), dp) + unit + " year on year", dir: dir };
}

function renderTiles() {
  const i = LAST;
  const nights = at("nights.jp", i);
  const fx = at("nights.jp.fx", i);
  const occ = at("occ.jp", i);
  const share = (nights && fx !== null) ? (fx / nights) * 100 : null;

  const j = yearsBack(i, 1);
  const prevNights = j < 0 ? null : at("nights.jp", j);
  const prevFx = j < 0 ? null : at("nights.jp.fx", j);
  const prevShare = (prevNights && prevFx !== null) ? (prevFx / prevNights) * 100 : null;

  // Which prefecture added the most nights, in level terms — the question a
  // reader asks straight after the national number.
  let leader = null;
  areasOf("prefecture").forEach(a => {
    const code = "nights." + a.code;
    const now = at(code, i), then = j < 0 ? null : at(code, j);
    if (now === null || then === null) return;
    if (!leader || (now - then) > leader.add) leader = { name: a.name_en, add: now - then };
  });

  const dNights = delta(growthOf("nights.jp", i), 1, "%");
  const dFx = delta(growthOf("nights.jp.fx", i), 1, "%");
  const dShare = delta(share !== null && prevShare !== null ? share - prevShare : null, 1, " pp");
  const occPrev = j < 0 ? null : at("occ.jp", j);

  $("tiles").innerHTML =
    tileCell("National guest nights",
      nights === null ? MISSING : fmtNum(mn(nights), 2) + " mn",
      dNights.html, dNights.dir, "Person-nights slept in Japan in " + fmtPeriodLong(PERIODS[i])) +
    tileCell("Foreign guest nights",
      fx === null ? MISSING : fmtNum(mn(fx), 2) + " mn",
      dFx.html, dFx.dir, "Person-nights slept by foreign guests") +
    tileCell("Foreign share",
      share === null ? MISSING : fmtNum(share, 1) + "%",
      dShare.html, dShare.dir, "Foreign guest nights as a share of all guest nights") +
    tileCell("Largest gain",
      leader ? escapeHtml(leader.name) : MISSING,
      leader ? "+" + fmtNum(mn(leader.add), 2) + " mn nights year on year" : MISSING,
      leader ? "up" : "flat",
      "The prefecture that added the most guest nights against the same month a year earlier");

  $("strip-foot").textContent =
    "All Japan · " + fmtPeriodLong(PERIODS[i]) + " · national room occupancy " +
    (occ === null ? MISSING : fmtNum(occ, 1) + "%") +
    (occ !== null && occPrev !== null
      ? " (" + fmtSigned(occ - occPrev, 1, " pp") + " year on year)" : "") +
    ". Guest nights and occupancy are official statistics as published; growth, share and the " +
    "largest gain are calculated. Guest nights are shown in millions of person-nights, an " +
    "exact conversion." + (spansBreak(i) ? " " + BREAK_NOTE : "");
  const calc = $("strip-calc");
  calc.style.display = "";
  calc.innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(CALCS.yoy) + "</code><br><code>" +
    escapeHtml(CALCS.fxshare) + "</code><br><code>" + escapeHtml(CALCS.occ) +
    "</code><br>" + escapeHtml(spansBreak(i) ? BREAK_NOTE : "") +
    "<br>Inputs: official values from release “" + escapeHtml(AC.release.label) +
    "” (sha256 " + AC.release.sha256.slice(0, 12) + "…).</div>";
}

/* ---- contributions -----------------------------------------------------

   Contributions are signed: a prefecture that lost nights pulls the national
   rate down. They are drawn as stacked bars over time with the published
   headline growth as a line on top, the platform's standing pattern for a
   decomposition — a single-month grouped column chart would force a zero
   floor and silently hide every negative contribution. */

const CONTRIB_MONTHS = 24;

function contribSuffix() { return urlState().cmeasure === "fx" ? ".fx" : ""; }

/* The prefectures worth naming: the largest absolute contributors in the
   newest month. Everything else is one disclosed residual. */
function contribPrefectures(i, suffix) {
  const j = yearsBack(i, 1);
  const base = j < 0 ? null : at("nights.jp" + suffix, j);
  if (!base) return [];
  return areasOf("prefecture").map(a => {
    const now = at("nights." + a.code + suffix, i);
    const then = at("nights." + a.code + suffix, j);
    return {
      code: a.code, name: a.name_en,
      pp: (now === null || then === null) ? 0 : ((now - then) / base) * 100,
    };
  }).sort((x, y) => Math.abs(y.pp) - Math.abs(x.pp)).slice(0, 5);
}

function contribConfig() {
  const suffix = contribSuffix();
  const named = contribPrefectures(LAST, suffix).map((p, n) => ({
    code: p.code, name: p.name, slot: n + 1, points: [],
  }));
  const residual = { name: RESIDUAL, slot: 6, points: [] };
  const line = { name: "National, year over year", points: [] };
  const national = "nights.jp" + suffix;
  const from = Math.max(0, LAST - CONTRIB_MONTHS + 1);

  for (let i = from; i <= LAST; i++) {
    const j = yearsBack(i, 1);
    const base = j < 0 ? null : at(national, j);
    const now = at(national, i);
    const iso = PERIODS[i];
    if (!base || now === null) {
      named.forEach(sr => sr.points.push([iso, null]));
      residual.points.push([iso, null]);
      line.points.push([iso, null]);
      continue;
    }
    const headline = (now / base - 1) * 100;
    let accounted = 0, ok = true;
    named.forEach(sr => {
      const a = at("nights." + sr.code + suffix, i);
      const b = at("nights." + sr.code + suffix, j);
      if (a === null || b === null) { sr.points.push([iso, null]); ok = false; return; }
      const c = ((a - b) / base) * 100;
      sr.points.push([iso, c]);
      accounted += c;
    });
    // Taken from the published headline rather than by summing the
    // prefectures we did not name, so it stays exact even where one is
    // unpublished.
    residual.points.push([iso, ok ? headline - accounted : null]);
    line.points.push([iso, headline]);
  }

  const label = urlState().cmeasure === "fx" ? "foreign guest nights" : "guest nights";
  return {
    series: named.concat([residual]),
    line: line,
    unit: "pp",
    yAxisName: "Contribution to year-over-year growth, pp",
    trust: "derived",
    eventLines: breakEventLines(PERIODS[from]),
    sourceLine: sourceLine("percentage points of national " + label + " growth", "derived"),
  };
}

function renderContributions() {
  const cfg = contribConfig();
  const el = $("contrib-chart");
  el.innerHTML = "";
  if (contribChart) contribChart.dispose();
  contribChart = obsChart(el, "stack", cfg);

  const headline = growthOf("nights.jp" + contribSuffix(), LAST);
  $("contrib-note").textContent =
    fmtPeriodLong(PERIODS[LAST]) + " · national " + fmtSigned(headline, 1, "%");
  $("contrib-source").textContent = cfg.sourceLine + " · segments sum to the line";
  $("contrib-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(CALCS.contrib) + "</code><br>" +
    "The five prefectures shown are those with the largest contribution by absolute " +
    "size in the newest month; every other prefecture is bundled into “" + RESIDUAL +
    "”, which is disclosed rather than dropped, so the segments sum to the line exactly." +
    "<br>" + escapeHtml(BREAK_NOTE) +
    "<br>Inputs: official values from release “" + escapeHtml(AC.release.label) +
    "” (sha256 " + AC.release.sha256.slice(0, 12) + "…).</div>";
}

/* ---- prefecture table -------------------------------------------------- */

const PREF_COLS = [
  { key: "name", label: "Area", type: "text" },
  { key: "nights", label: "Guest nights", num: true },
  { key: "fx", label: "Foreign guest nights", num: true },
  { key: "fxshare", label: "Foreign share (%)", num: true },
  { key: "share", label: "Share of Japan (%)", num: true },
  { key: "yoy", label: "Year on year (%)", num: true },
  { key: "vs19", label: "vs 2019 (=100)", num: true },
  { key: "occ", label: "Room occupancy (%)", num: true },
  { key: "spark", label: "4 years", nosort: true },
];

function prefRows(kind, i) {
  const national = at("nights.jp", i);
  return areasOf(kind).map(a => {
    const nights = at("nights." + a.code, i);
    const fx = at("nights." + a.code + ".fx", i);
    const c = col("nights." + a.code) || [];
    const spark = [];
    for (let k = Math.max(0, i - 47); k <= i; k++) {
      spark.push([PERIODS[k], c[k] === undefined ? null : c[k]]);
    }
    return {
      code: a.code,
      name: a.name_en,
      nights: nights,
      fx: fx,
      fxshare: (nights && fx !== null) ? (fx / nights) * 100 : null,
      // A bureau region republishes the same nights, so a "share of Japan"
      // for it would double-count. Only prefectures partition the country.
      share: (kind === "prefecture" && national && nights !== null)
        ? (nights / national) * 100 : null,
      yoy: growthOf("nights." + a.code, i),
      vs19: recoveryOf("nights." + a.code, i),
      occ: at("occ." + a.code, i),
      spark: spark,
    };
  });
}

function renderPrefTable() {
  const st = urlState();
  const i = LAST;
  const kind = st.rows === "region" ? "region" : "prefecture";
  const rows = sortRows(prefRows(kind, i), st.sort, st.dir);

  const body = rows.map(r =>
    "<tr>" +
    "<td>" + escapeHtml(r.name) + "</td>" +
    '<td class="num">' + (r.nights === null ? MISSING : fmtNum(r.nights, 0)) + "</td>" +
    '<td class="num">' + (r.fx === null ? MISSING : fmtNum(r.fx, 0)) + "</td>" +
    '<td class="num">' + (r.fxshare === null ? MISSING : fmtNum(r.fxshare, 1)) + "</td>" +
    '<td class="num">' + (r.share === null ? MISSING : fmtNum(r.share, 1)) + "</td>" +
    '<td class="num">' + fmtSigned(r.yoy, 1, "%") + "</td>" +
    '<td class="num">' + (r.vs19 === null ? MISSING : fmtNum(r.vs19, 0)) + "</td>" +
    '<td class="num">' + (r.occ === null ? MISSING : fmtNum(r.occ, 1)) + "</td>" +
    "<td>" + sparkSVG(r.spark, 110, 26) + "</td>" +
    "</tr>").join("");

  const wrap = $("pref-table");
  wrap.innerHTML = '<table class="data tbl-series"><thead>' +
    sortableHead(PREF_COLS, st.sort, st.dir) + "</thead><tbody>" + body + "</tbody></table>";
  wireSort(wrap, st.sort, st.dir, (key, dir) => {
    setUrlState({ sort: key, dir: dir });
    renderPrefTable();
  });
  enhanceTable(wrap, { sort: false, placeholder: "Filter areas…" });

  $("pref-note").textContent = rows.length + " rows · " + fmtPeriodLong(PERIODS[i]);
  $("pref-foot").textContent =
    (kind === "region"
      ? "The Agency's ten transport-bureau regions. These republish the same nights as the " +
        "prefectures, so no share of Japan is shown for them and they must never be added to " +
        "the prefecture rows. Nagano is counted in Hokuriku-Shinetsu and Fukui in Chubu. "
      : "All 47 prefectures, which together partition the country. ") +
    "Guest nights and occupancy are official values for " + fmtPeriodLong(PERIODS[i]) +
    "; share, year-on-year and the 2019 comparison are calculated from them. Guest nights " +
    "are person-nights and occupancy is a percentage — two different measures, never ranked " +
    "against each other. — means the survey published no value. Click any column to rank by " +
    "it, and again to reverse; rows with no published figure stay at the bottom either way." +
    (spansBreak(i) ? " " + BREAK_NOTE : "");
  $("pref-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(CALCS.yoy) + "</code><br><code>" +
    escapeHtml(CALCS.share) + "</code><br><code>" + escapeHtml(CALCS.fxshare) +
    "</code><br><code>" + escapeHtml(CALCS.rec) + "</code><br><code>" +
    escapeHtml(CALCS.occ) + "</code><br>" +
    escapeHtml(spansBreak(i) ? BREAK_NOTE : "") + "</div>";
}

/* ---- municipality table ------------------------------------------------ */

const MUNI_COLS = [
  { key: "name", label: "Municipality", type: "text" },
  { key: "pref", label: "Prefecture", type: "text" },
  { key: "nights", label: "Guest nights", num: true },
  { key: "fx", label: "Foreign guest nights", num: true },
  { key: "fxshare", label: "Foreign share (%)", num: true },
  { key: "occ", label: "Room occupancy (%)", num: true },
];

function muniRows(i) {
  return AC.municipalities.map(m => {
    const nights = muniAt("muni." + m.code + ".nights", i);
    const fx = muniAt("muni." + m.code + ".nightsfx", i);
    return {
      // The survey names each municipality in Japanese only; label_en is the
      // published romanisation attached by the API. English leads, the filed
      // Japanese sits beside it.
      name: m.label_en || m.label,
      name_ja: m.label_en ? m.label : null,
      pref: m.prefecture_label,
      nights: nights,
      fx: fx,
      fxshare: (nights && fx !== null) ? (fx / nights) * 100 : null,
      occ: muniAt("muni." + m.code + ".occ", i),
    };
  }).filter(r => r.nights !== null || r.fx !== null || r.occ !== null);
}

function renderMuniTable() {
  const st = urlState();
  const periods = AC.municipal_periods || [];
  if (!periods.length) {
    $("muni-table").innerHTML =
      '<p class="table-foot">No municipality tables are published in this release.</p>';
    return;
  }
  const i = periods.length - 1;
  const rows = sortRows(muniRows(i), st.msort, st.mdir);

  const body = rows.map(r =>
    "<tr>" +
    '<td data-sort="' + escapeHtml(r.name) + '">' +
      '<span class="name-part">' + escapeHtml(r.name) + "</span>" +
      (r.name_ja ? ' <span class="muted name-part">' + escapeHtml(r.name_ja) +
        "</span>" : "") + "</td>" +
    "<td>" + escapeHtml(r.pref) + "</td>" +
    '<td class="num">' + (r.nights === null ? MISSING : fmtNum(r.nights, 0)) + "</td>" +
    '<td class="num">' + (r.fx === null ? MISSING : fmtNum(r.fx, 0)) + "</td>" +
    '<td class="num">' + (r.fxshare === null ? MISSING : fmtNum(r.fxshare, 1)) + "</td>" +
    '<td class="num">' + (r.occ === null ? MISSING : fmtNum(r.occ, 1)) + "</td>" +
    "</tr>").join("");

  const wrap = $("muni-table");
  wrap.innerHTML = '<table class="data tbl-series"><thead>' +
    sortableHead(MUNI_COLS, st.msort, st.mdir) + "</thead><tbody>" + body + "</tbody></table>";
  wireSort(wrap, st.msort, st.mdir, (key, dir) => {
    setUrlState({ msort: key, mdir: dir });
    renderMuniTable();
  });
  enhanceTable(wrap, { sort: false, placeholder: "Filter municipalities…" });

  $("muni-note").textContent = rows.length + " reporting · " + fmtPeriodLong(periods[i]);
  $("muni-foot").textContent =
    "Municipality figures are official counts for " + fmtPeriodLong(periods[i]) +
    ", published from " + fmtPeriodLong(periods[0]) + " onward — the survey began naming " +
    "municipalities when it changed its stratification. " + rows.length + " of the " +
    AC.municipalities.length + " municipalities on record reported in this month; the rest " +
    "had fewer than ten responding properties and are missing, not zero. Foreign share is " +
    "calculated from the two published counts. Click any column to rank by it.";
  $("muni-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(CALCS.fxshare) + "</code><br><code>" +
    escapeHtml(CALCS.occ) + "</code><br>These figures are counted, not grossed up: the Agency " +
    "publishes municipality rows as responses received rather than as an estimate for the " +
    "whole municipality, so they are not comparable with the prefecture totals above.</div>";
}

/* ---- exports ----------------------------------------------------------- */

function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function quote(s) { return '"' + String(s).replace(/"/g, '""') + '"'; }
function cell(v) { return v === null || v === undefined ? "" : v; }

function exportPrefCSV() {
  const st = urlState();
  const kind = st.rows === "region" ? "region" : "prefecture";
  const rows = sortRows(prefRows(kind, LAST), st.sort, st.dir);
  const head = csvHeader(
    (kind === "region" ? "Guest nights by transport-bureau region, "
                       : "Guest nights by prefecture, ") + fmtPeriod(PERIODS[LAST]),
    ["Rows in the order shown on the page: sorted by " + st.sort + ", " +
      (st.dir === "desc" ? "highest first." : "lowest first."),
     "Columns: guest_nights, foreign_guest_nights and room_occupancy_pct are official; " +
       "foreign_share_pct, share_of_japan_pct, yoy_pct and vs_2019_index are calculated.",
     CALCS.yoy, CALCS.share, CALCS.fxshare, CALCS.rec, CALCS.occ]);
  let csv = head.map(l => "# " + l).join("\n") + "\n";
  csv += "area,guest_nights,foreign_guest_nights,foreign_share_pct," +
         "share_of_japan_pct,yoy_pct,vs_2019_index,room_occupancy_pct\n";
  rows.forEach(r => {
    csv += [quote(r.name), cell(r.nights), cell(r.fx),
            r.fxshare === null ? "" : r.fxshare.toFixed(1),
            r.share === null ? "" : r.share.toFixed(1),
            r.yoy === null ? "" : r.yoy.toFixed(1),
            r.vs19 === null ? "" : r.vs19.toFixed(0),
            cell(r.occ)].join(",") + "\n";
  });
  download("guest-nights-by-" + kind + "-" + fmtPeriod(PERIODS[LAST]) + ".csv", csv);
}

function exportMuniCSV() {
  const st = urlState();
  const periods = AC.municipal_periods || [];
  if (!periods.length) return;
  const i = periods.length - 1;
  const rows = sortRows(muniRows(i), st.msort, st.mdir);
  const head = csvHeader("Guest nights by municipality, " + fmtPeriod(periods[i]),
    ["Municipality names are as published by the Agency, in Japanese. The English " +
       "column is Japan Post's published romanisation of the same municipality, " +
       "matched on the name; the Agency itself publishes none.",
     "These rows are responses received, not grossed up to the whole municipality, and are " +
       "therefore not comparable with the prefecture totals.",
     "A municipality absent from a month had fewer than ten responding properties.",
     CALCS.fxshare, CALCS.occ]);
  let csv = head.map(l => "# " + l).join("\n") + "\n";
  csv += "municipality,municipality_ja,prefecture,guest_nights,foreign_guest_nights," +
         "foreign_share_pct,room_occupancy_pct\n";
  rows.forEach(r => {
    csv += [quote(r.name), quote(r.name_ja || ""), quote(r.pref), cell(r.nights),
            cell(r.fx), r.fxshare === null ? "" : r.fxshare.toFixed(1),
            cell(r.occ)].join(",") + "\n";
  });
  download("guest-nights-by-municipality-" + fmtPeriod(periods[i]) + ".csv", csv);
}

/* ---- wiring ------------------------------------------------------------ */

function pressed(box, attr, value) {
  Array.prototype.forEach.call(box.querySelectorAll("button"), b => {
    b.setAttribute("aria-pressed", b.getAttribute(attr) === value ? "true" : "false");
  });
}

function wireSeg(id, attr, key, after) {
  const box = $(id);
  if (!box) return;
  pressed(box, attr, urlState()[key]);
  box.addEventListener("click", e => {
    const button = e.target.closest("button[" + attr + "]");
    if (!button) return;
    const value = button.getAttribute(attr);
    const next = {}; next[key] = value;
    setUrlState(next);
    pressed(box, attr, value);
    after();
  });
}

function renderAll() {
  renderHeader();
  renderStale();
  renderBreakNotice();
  renderTiles();
  renderContributions();
  renderPrefTable();
  renderMuniTable();
  renderProvenance();
}

fetch(API + "/accommodation")
  .then(r => { if (!r.ok) throw new Error("accommodation " + r.status); return r.json(); })
  .then(payload => {
    AC = payload;
    PERIODS = AC.periods;
    LAST = PERIODS.length - 1;
    const headline = col("nights.jp") || [];
    for (let i = headline.length - 1; i >= 0; i--) {
      if (headline[i] !== null && headline[i] !== undefined) { LAST = i; break; }
    }
    renderAll();
    initThemeToggle(() => renderContributions());
    wireSeg("contrib-seg", "data-cmeasure", "cmeasure", renderContributions);
    wireSeg("rows-seg", "data-rows", "rows", renderPrefTable);
    $("contrib-png").addEventListener("click", () =>
      contribChart.exportPNG("guest-night-contributions.png"));
    $("contrib-csv").addEventListener("click", () =>
      contribChart.exportCSV("guest-night-contributions.csv",
        csvHeader("Contributions to national guest-night growth", [CALCS.contrib])));
    $("pref-csv").addEventListener("click", exportPrefCSV);
    $("muni-csv").addEventListener("click", exportMuniCSV);
  })
  .catch(err => {
    $("tiles").innerHTML = '<div class="strip-cell">Could not load the accommodation data: ' +
      escapeHtml(err.message) + "</div>";
  });
