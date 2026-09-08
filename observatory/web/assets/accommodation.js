/* Guest nights and occupancy. The question this screen answers:
   "How many nights are being slept in this area, how many of them by foreign
   guests, and how full are the rooms?" — the four tiles and the guest-nights
   chart lead; everything below is a cut of the same nights.

   Two measures live on this page and never share an axis: guest nights are a
   count of person-nights, room occupancy is a published percentage. Guest
   nights are shown in millions (an exact ÷1,000,000) and say so; occupancy is
   shown exactly as published and is differenced, never divided.

   Everything that crosses the wire is official. Growth, shares, the 2019
   recovery index and the nationality mix are computed here and carry their
   formula under "Show calculation". Missing is "—", never zero. */
"use strict";

const DATASET = "accommodation-jp";
const API = "/api/v1/" + DATASET;
const PER_MN = 1e6;

let AC = null;            // /accommodation payload for the current area
let PERIODS = [];         // ISO months, oldest first
let LAST = 0;             // index of the newest month with a headline value
let nightsChart = null, occChart = null, natChart = null, mixChart = null;

const CALCS = {
  yoy: "yoy[t] = (guest nights[t] / guest nights[t−12 months] − 1) × 100, from published values.",
  occ: "occupancy change[t] = occupancy[t] − occupancy[t−12 months], in percentage points. " +
       "An occupancy rate is a ratio: it is differenced, never divided.",
  rec: "recovery[t] = (guest nights[t] / guest nights[same month of 2019]) × 100. " +
       "100 = the same month of 2019, the last full year before the border closed.",
  share: "foreign share[t] = (foreign guest nights[t] / guest nights[t]) × 100, " +
         "both published counts for the same month and the same universe.",
  natshare: "share[nationality, t] = (foreign guest nights[nationality, t] / foreign guest " +
            "nights[larger properties, t]) × 100. The denominator is the nationality table's " +
            "own published total, which covers larger properties only.",
  unknown: "unidentified[t] = foreign guest nights[larger properties, t] − Σ foreign guest " +
           "nights[named nationalities, t]. Always shown, never spread across the named categories.",
};

function mn(v) { return v === null || v === undefined ? null : v / PER_MN; }

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    area: p.get("area") || "jp",
    view: p.get("view") || "total",
    range: p.get("range") || "8",
    orange: p.get("orange") || "8",
    types: p.get("types") || "",
    nat: p.get("nat") || "bar",
    mix: p.get("mix") || "purpose",
    sort: p.get("sort") || "nights",
    dir: p.get("dir") || "desc",
  };
}

const DEFAULTS = { area: "jp", view: "total", range: "8", orange: "8", types: "",
                   nat: "bar", mix: "purpose", sort: "nights", dir: "desc" };

function setUrlState(next) {
  const st = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  Object.keys(DEFAULTS).forEach(k => { if (st[k] !== DEFAULTS[k]) p.set(k, st[k]); });
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function $(id) { return document.getElementById(id); }

/* ---- reading the payload ---------------------------------------------- */

function col(code) {
  return (AC.backbone && AC.backbone[code]) || (AC.detail && AC.detail[code]) || null;
}

function at(code, i) {
  const c = col(code);
  return c && c[i] !== undefined ? c[i] : null;
}

function pts(code, from, transform) {
  const c = col(code);
  if (!c) return [];
  const out = [];
  for (let i = from; i <= LAST; i++) {
    const v = c[i];
    out.push([PERIODS[i], v === null || v === undefined ? null
                          : (transform ? transform(v) : v)]);
  }
  return out;
}

/* Index of the same month `n` years back, or −1. */
function yearsBack(i, n) {
  const target = (Number(PERIODS[i].slice(0, 4)) - n) + PERIODS[i].slice(4);
  return PERIODS.indexOf(target);
}

function growth(code, i, years) {
  const j = yearsBack(i, years || 1);
  if (j < 0) return null;
  const now = at(code, i), then = at(code, j);
  if (now === null || then === null || !then) return null;
  return (now / then - 1) * 100;
}

function ppChange(code, i) {
  const j = yearsBack(i, 1);
  if (j < 0) return null;
  const now = at(code, i), then = at(code, j);
  if (now === null || then === null) return null;
  return now - then;
}

function areaCode() { return AC.area; }
function nightsCode() { return "nights." + areaCode(); }
function foreignCode() { return "nights." + areaCode() + ".fx"; }
function occCode() { return "occ." + areaCode(); }

function rangeStart(years) {
  if (years === "max") return 0;
  const first = Math.max(0, LAST - (Number(years) * 12) + 1);
  return first;
}

function areaName() {
  const hit = (AC.areas || []).filter(a => a.code === AC.area)[0];
  return hit ? hit.name_en : AC.area;
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
    "Japan Data Observatory — " + what,
    "Area: " + areaName(),
    "Source: Japan Tourism Agency, Accommodation Survey (観光庁『宿泊旅行統計調査』), " + rel.source_name,
    "Source page: " + rel.source_page,
    "Release: " + rel.label + " (sha256 " + rel.sha256 + ")",
    "Retrieved: " + fmtStamp(rel.retrieved_at),
    "Guest nights are official person-night counts and occupancy is an official " +
      "percentage, both exactly as published. Blank means the survey published no value.",
    "Estimates grossed up from a sample survey; the Agency publishes standard errors by prefecture.",
    "Stratification break: " + AC.break_period + " — property-size bands begin here, the " +
      "nationality list widens from 21 categories to 24, and year-on-year comparisons " +
      "spanning the boundary may reflect the change in method rather than demand.",
  ].concat(formulas || []);
}

function renderHeader() {
  const rel = AC.release;
  $("header-asof").textContent = "Data through " + fmtPeriodLong(rel.latest_period);
  $("page-asof").textContent = "Ingested " + fmtStamp(rel.ingested_at);
  $("page-sub").textContent =
    "Monthly guest nights and room occupancy, " + PERIODS[0].slice(0, 4) +
    "–present · person-nights and percent · " + AC.areas.length +
    " areas · Japan Tourism Agency, Accommodation Survey";
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
          '<div class="prov-sub">One release is built from the Agency’s trend workbook, ' +
            'its annual definitive workbooks and the monthly second-preliminary files, ' +
            'archived together under one checksum.</div>' +
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

function deltaHtml(value, dp, unit) {
  if (value === null) return MISSING;
  const rounded = Number(value.toFixed(dp));
  const dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
  const arrow = rounded === 0 ? ""
    : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
      '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
  return { html: arrow + fmtNum(Math.abs(rounded), dp) + unit + " year on year", dir: dir };
}

function renderTiles() {
  const i = LAST;
  const nights = at(nightsCode(), i);
  const fx = at(foreignCode(), i);
  const occ = at(occCode(), i);
  const share = (nights && fx !== null) ? (fx / nights) * 100 : null;

  const jPrev = yearsBack(i, 1);
  const prevNights = jPrev < 0 ? null : at(nightsCode(), jPrev);
  const prevFx = jPrev < 0 ? null : at(foreignCode(), jPrev);
  const prevShare = (prevNights && prevFx !== null) ? (prevFx / prevNights) * 100 : null;

  const dNights = deltaHtml(growth(nightsCode(), i), 1, "%");
  const dFx = deltaHtml(growth(foreignCode(), i), 1, "%");
  const dShare = deltaHtml(share !== null && prevShare !== null ? share - prevShare : null, 1, " pp");
  const dOcc = deltaHtml(ppChange(occCode(), i), 1, " pp");

  $("tiles").innerHTML =
    tileCell("Guest nights",
      nights === null ? MISSING : fmtNum(mn(nights), 2) + " mn",
      dNights.html, dNights.dir,
      "Person-nights slept in " + areaName() + " in " + fmtPeriodLong(PERIODS[i])) +
    tileCell("Foreign guest nights",
      fx === null ? MISSING : fmtNum(mn(fx), 2) + " mn",
      dFx.html, dFx.dir,
      "Person-nights slept by foreign guests") +
    tileCell("Foreign share",
      share === null ? MISSING : fmtNum(share, 1) + "%",
      dShare.html, dShare.dir,
      "Foreign guest nights as a share of all guest nights") +
    tileCell("Room occupancy",
      occ === null ? MISSING : fmtNum(occ, 1) + "%",
      dOcc.html, dOcc.dir,
      "Published room occupancy rate, all property types");

  $("strip-foot").textContent =
    areaName() + " · " + fmtPeriodLong(PERIODS[i]) + " · guest nights and occupancy are " +
    "official statistics as published; the year-on-year figures beneath them are calculated. " +
    "Guest nights are shown in millions of person-nights, an exact conversion." +
    (spansBreak(i) ? " " + BREAK_NOTE : "");
  const calc = $("strip-calc");
  calc.style.display = "";
  calc.innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(CALCS.yoy) + "</code><br><code>" +
    escapeHtml(CALCS.share) + "</code><br><code>" + escapeHtml(CALCS.occ) +
    "</code><br>" + escapeHtml(spansBreak(i) ? BREAK_NOTE : "") +
    "<br>Inputs: official values from release “" + escapeHtml(AC.release.label) +
    "” (sha256 " + AC.release.sha256.slice(0, 12) + "…).</div>";
}

/* ---- guest nights chart ------------------------------------------------ */

function renderNights() {
  const st = urlState();
  const from = rangeStart(st.range);
  let cfg;

  if (st.view === "split") {
    cfg = {
      series: [
        { name: "Japanese guests", points: pts("nights." + areaCode() + ".jp", from, mn) },
        { name: "Foreign guests", points: pts(foreignCode(), from, mn) },
      ],
      unit: "", dp: 2, yAxisName: "Million person-nights",
      trust: "official", eventLines: breakEventLines(PERIODS[from]),
      sourceLine: sourceLine("million person-nights (published in person-nights)", "official"),
    };
  } else if (st.view === "rec") {
    const base = {};
    PERIODS.forEach((p, i) => {
      if (p.slice(0, 4) === String(AC.baseline_year)) base[p.slice(5, 7)] = at(nightsCode(), i);
    });
    const points = [];
    for (let i = from; i <= LAST; i++) {
      const b = base[PERIODS[i].slice(5, 7)];
      const v = at(nightsCode(), i);
      points.push([PERIODS[i], (b && v !== null) ? (v / b) * 100 : null]);
    }
    cfg = {
      series: [{ name: "Guest nights vs " + AC.baseline_year, points: points }],
      unit: "", dp: 1, yAxisName: AC.baseline_year + " = 100",
      trust: "derived", refLine: { y: 100, label: String(AC.baseline_year) + " = 100" },
      eventLines: breakEventLines(PERIODS[from]),
      sourceLine: sourceLine("index, same month of " + AC.baseline_year + " = 100", "derived"),
    };
  } else {
    cfg = {
      series: [{ name: "Guest nights", points: pts(nightsCode(), from, mn) }],
      unit: "", dp: 2, yAxisName: "Million person-nights",
      trust: "official", eventLines: breakEventLines(PERIODS[from]),
      sourceLine: sourceLine("million person-nights (published in person-nights)", "official"),
    };
  }

  if (nightsChart) nightsChart.dispose();
  nightsChart = obsChart($("nights-chart"), "line", cfg);
  $("nights-note").textContent =
    areaName() + " · " + fmtPeriod(PERIODS[from]) + " – " + fmtPeriod(PERIODS[LAST]);
  $("nights-source").textContent = cfg.sourceLine;
  $("nights-calc").innerHTML = st.view === "rec"
    ? "<summary>Show calculation</summary><div class=\"calc-body\"><code>" +
      escapeHtml(CALCS.rec) + "</code></div>"
    : "<summary>Show calculation</summary><div class=\"calc-body\">" +
      "Published person-nights, divided by 1,000,000 for display. No other transformation.</div>";
}

/* ---- occupancy chart --------------------------------------------------- */

const DEFAULT_TYPES = ["all", "business", "city", "resort", "ryokan"];

function selectedTypes() {
  const st = urlState();
  if (!st.types) return DEFAULT_TYPES.slice();
  return st.types.split(",").filter(Boolean);
}

function occSeriesCode(type) {
  return type === "all" ? occCode() : "occ." + areaCode() + ".type." + type;
}

function renderTypePicker() {
  const chosen = selectedTypes();
  const options = [{ code: "all", label: "All types" }].concat(AC.dimensions.facility_types);
  const box = $("type-picker");
  box.innerHTML = '<span class="band-toggles-label">Types</span>' +
    options.map(o => {
      const has = !!col(occSeriesCode(o.code));
      return '<label' + (has ? "" : ' class="is-disabled"') + '>' +
        '<input type="checkbox" value="' + escapeHtml(o.code) + '"' +
        (chosen.indexOf(o.code) >= 0 && has ? " checked" : "") +
        (has ? "" : " disabled") + "> " + escapeHtml(o.label) + "</label>";
    }).join("") +
    '<span class="band-toggles-note">Occupancy is a rate — never averaged across areas here.</span>';

  Array.prototype.forEach.call(box.querySelectorAll("input"), input => {
    input.addEventListener("change", () => {
      const picked = Array.prototype.filter.call(box.querySelectorAll("input"), i => i.checked)
        .map(i => i.value);
      // One series must stay on: an empty chart is not a view.
      setUrlState({ types: (picked.length ? picked : DEFAULT_TYPES).join(",") });
      renderTypePicker();
      renderOccupancy();
    });
  });
}

function renderOccupancy() {
  const st = urlState();
  const from = rangeStart(st.orange);
  const labels = { all: "All types" };
  AC.dimensions.facility_types.forEach(t => { labels[t.code] = t.label; });

  const series = selectedTypes()
    .filter(t => col(occSeriesCode(t)))
    .map(t => ({ name: labels[t] || t, points: pts(occSeriesCode(t), from) }));

  const cfg = {
    series: series.length ? series
      : [{ name: "All types", points: pts(occCode(), from) }],
    unit: "%", dp: 1, yAxisName: "Room occupancy (%)",
    trust: "official", legendFloor: 640, eventLines: breakEventLines(PERIODS[from]),
    sourceLine: sourceLine("percent, as published", "official"),
  };
  if (occChart) occChart.dispose();
  occChart = obsChart($("occ-chart"), "line", cfg);
  $("occ-note").textContent =
    areaName() + " · " + fmtPeriod(PERIODS[from]) + " – " + fmtPeriod(PERIODS[LAST]);
  $("occ-source").textContent = cfg.sourceLine;
  $("occ-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body">Published occupancy rates, plotted as released. Nothing is ' +
    "recomputed. A gap in a line is a month the survey published no rate for that type, " +
    "never a zero.<br><code>" + escapeHtml(CALCS.occ) + "</code></div>";
}

/* ---- nationality ------------------------------------------------------- */

function natCode(code) { return "nightsfx." + areaCode() + ".nat." + code; }

/* Categories the payload actually carries values for, newest month first. */
function natRows(i) {
  const base = at(natCode("all"), i);
  const rows = (AC.dimensions.nationalities || []).map(n => {
    const v = at(natCode(n.code), i);
    return {
      code: n.code, name: n.label, era: n.era,
      nights: v,
      share: (base && v !== null) ? (v / base) * 100 : null,
      yoy: growth(natCode(n.code), i),
      vs19: (function () {
        const j = PERIODS.indexOf(AC.baseline_year + PERIODS[i].slice(4));
        if (j < 0) return null;
        const then = at(natCode(n.code), j);
        return (then && v !== null) ? (v / then) * 100 : null;
      })(),
      spark: pts(natCode(n.code), Math.max(0, i - 47)),
    };
  }).filter(r => r.nights !== null);
  const named = rows.reduce((a, r) => a + r.nights, 0);
  return { rows: rows, base: base, unknown: base === null ? null : base - named };
}

function renderNationality() {
  const st = urlState();
  const i = LAST;
  const data = natRows(i);
  const ranked = data.rows.slice().sort((a, b) => (b.nights || 0) - (a.nights || 0));

  let cfg, kind;
  if (st.nat === "trend") {
    const top = ranked.slice(0, 6);
    kind = "line";
    cfg = {
      series: top.map(r => ({
        name: r.name,
        points: pts(natCode(r.code), rangeStart("8"), mn),
      })),
      unit: "", dp: 3, yAxisName: "Million person-nights",
      trust: "official", legendFloor: 640,
      eventLines: breakEventLines(PERIODS[rangeStart("8")]),
      sourceLine: sourceLine("million person-nights, larger properties only", "official"),
    };
  } else {
    const top = ranked.slice(0, 12);
    kind = "cols";
    cfg = {
      categories: top.map(r => r.name),
      series: [{ name: "Foreign guest nights", slot: 1,
                 points: top.map(r => mn(r.nights)) }],
      dp: 3, unitSuffix: "mn", yAxisName: "Million person-nights",
      trust: "official",
      sourceLine: sourceLine("million person-nights, larger properties only", "official"),
    };
  }
  if (natChart) natChart.dispose();
  natChart = obsChart($("nat-chart"), kind, cfg);
  $("nat-source").textContent = cfg.sourceLine;

  const body = ranked.map(r =>
    "<tr>" +
    '<td><div class="cell-item"><div class="en">' + escapeHtml(r.name) + "</div>" +
      (r.era === "new"
        ? '<div class="ja" title="Published from January 2026, when the survey widened ' +
          'its nationality list">published from 2026</div>'
        : r.era === "old"
        ? '<div class="ja" title="The pre-2026 residual also contained the Nordic region, ' +
          'the Middle East and Mexico">basis to 2025</div>'
        : "") +
    "</div></td>" +
    '<td class="num">' + (r.nights === null ? MISSING : fmtNum(r.nights, 0)) + "</td>" +
    '<td class="num">' + (r.share === null ? MISSING : fmtNum(r.share, 1)) + "</td>" +
    '<td class="num">' + fmtSigned(r.yoy, 1, "%") + "</td>" +
    '<td class="num">' + (r.vs19 === null ? MISSING : fmtNum(r.vs19, 0)) + "</td>" +
    "<td>" + sparkSVG(r.spark, 110, 26) + "</td>" +
    "</tr>").join("");

  const unknownRow = data.unknown === null ? "" :
    '<tr><td><div class="cell-item"><div class="en">Nationality not identified</div>' +
    '<div class="ja">Published total less the named categories</div></div></td>' +
    '<td class="num">' + fmtNum(data.unknown, 0) + "</td>" +
    '<td class="num">' + (data.base ? fmtNum((data.unknown / data.base) * 100, 1) : MISSING) + "</td>" +
    '<td class="num">' + MISSING + "</td><td class=\"num\">" + MISSING + "</td><td></td></tr>";

  const wrap = $("nat-table");
  wrap.innerHTML =
    '<table class="data tbl-series"><thead><tr>' +
      '<th scope="col">Nationality</th>' +
      '<th scope="col" class="num">Guest nights</th>' +
      '<th scope="col" class="num">Share (%)</th>' +
      '<th scope="col" class="num">Year on year (%)</th>' +
      '<th scope="col" class="num">vs ' + AC.baseline_year + ' (=100)</th>' +
      '<th scope="col">4 years</th>' +
    "</tr></thead><tbody>" + body + unknownRow + "</tbody></table>";
  enhanceTable(wrap, { placeholder: "Filter nationalities…" });

  $("nat-note").textContent = ranked.length + " categories · " + fmtPeriodLong(PERIODS[i]);
  $("nat-foot").textContent =
    "Foreign guest nights for " + areaName() + " in " + fmtPeriodLong(PERIODS[i]) +
    ", for properties with 20 rooms or more (10 or more employees before 2026). " +
    "Guest nights are official counts; share, year-on-year and the " + AC.baseline_year +
    " comparison are calculated from them. The unidentified row is the published total " +
    "less the named categories and is always shown. — means the survey published no value. " +
    "Click any column to rank by it.";
  $("nat-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(CALCS.natshare) + "</code><br><code>" +
    escapeHtml(CALCS.yoy) + "</code><br><code>" + escapeHtml(CALCS.rec) + "</code><br><code>" +
    escapeHtml(CALCS.unknown) + "</code><br>Inputs: official values from release “" +
    escapeHtml(AC.release.label) + "”.</div>";
}

/* ---- demand mix -------------------------------------------------------- */

const MIX_DEFS = {
  purpose: {
    codes: d => d.dimensions.purposes.map(p => ({
      code: "nights." + AC.area + ".purpose." + p.code, label: p.label })),
    kind: "line",
    note: "Properties are classified, not guests: “leisure-majority” means at least half of " +
          "that property’s guests stayed for leisure. The two do not sum to total guest " +
          "nights — the survey also publishes nights at properties whose mix is unknown — " +
          "so they are drawn as separate lines, never stacked into a false whole.",
  },
  res: {
    codes: () => AC.dimensions.residence.map(r => ({
      code: "nights." + AC.area + ".res." + r.code, label: r.label })),
    kind: "line",
    note: "Where the guest lives, not where they slept. These two also fall short of total " +
          "guest nights, because the survey reports nights whose residence is unknown, so " +
          "they are drawn as lines rather than stacked.",
  },
  rooms: {
    codes: () => AC.dimensions.room_bands.map(b => ({
      code: "nights." + AC.area + ".rooms." + b.code, label: b.label })),
    kind: "cols",
    note: "Published from January 2026 only. Before that the survey stratified properties by " +
          "employee count, which measures something else, so the two are deliberately not " +
          "spliced into one series. These five bands do sum to total guest nights.",
  },
};

function renderMix() {
  const st = urlState();
  const def = MIX_DEFS[st.mix] || MIX_DEFS.purpose;
  const entries = def.codes(AC).filter(e => col(e.code));

  if (!entries.length) {
    $("mix-chart").innerHTML =
      '<p class="table-foot">The survey publishes no property-size breakdown for ' +
      escapeHtml(areaName()) + ".</p>";
    $("mix-source").textContent = "";
    $("mix-note").textContent = areaName();
    $("mix-calc").innerHTML = "";
    if (mixChart) { mixChart.dispose(); mixChart = null; }
    return;
  }

  // The first month any of these series carries a value: the size bands start
  // at the stratification break, not at the top of the history.
  let first = LAST;
  entries.forEach(e => {
    const c = col(e.code);
    for (let i = 0; i < c.length; i++) {
      if (c[i] !== null && c[i] !== undefined) { first = Math.min(first, i); break; }
    }
  });
  const from = def.kind === "cols" ? first : Math.max(first, rangeStart("8"));

  let cfg;
  if (def.kind === "cols") {
    const categories = [];
    for (let i = from; i <= LAST; i++) categories.push(fmtPeriod(PERIODS[i]));
    cfg = {
      categories: categories,
      series: entries.map((e, n) => {
        const c = col(e.code);
        const points = [];
        for (let i = from; i <= LAST; i++) points.push(mn(c[i] === undefined ? null : c[i]));
        return { name: e.label, slot: n + 1, points: points };
      }),
      dp: 2, unitSuffix: "mn", yAxisName: "Million person-nights",
      trust: "official",
      sourceLine: sourceLine("million person-nights (published in person-nights)", "official"),
    };
  } else {
    cfg = {
      series: entries.map(e => ({ name: e.label, points: pts(e.code, from, mn) })),
      unit: "", dp: 2, yAxisName: "Million person-nights",
      trust: "official", legendFloor: 640, eventLines: breakEventLines(PERIODS[from]),
      sourceLine: sourceLine("million person-nights (published in person-nights)", "official"),
    };
  }

  if (mixChart) mixChart.dispose();
  mixChart = obsChart($("mix-chart"), def.kind, cfg);
  $("mix-note").textContent =
    areaName() + " · " + fmtPeriod(PERIODS[from]) + " – " + fmtPeriod(PERIODS[LAST]);
  $("mix-source").textContent = cfg.sourceLine;
  $("mix-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body">Published person-nights, divided by 1,000,000 for display. ' +
    escapeHtml(def.note) + "</div>";
}

/* ---- wiring ------------------------------------------------------------ */

function pressed(container, attr, value) {
  Array.prototype.forEach.call(container.querySelectorAll("button"), b => {
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

let areaPickerBuilt = false;

function renderAreaPicker() {
  const select = $("area-select");
  if (areaPickerBuilt) { select.value = AC.area; return; }
  areaPickerBuilt = true;
  const groups = { national: [], prefecture: [], region: [] };
  AC.areas.forEach(a => groups[a.kind].push(a));
  const optionsFor = list => list.map(a =>
    '<option value="' + escapeHtml(a.code) + '"' +
    (a.code === AC.area ? " selected" : "") + ">" + escapeHtml(a.name_en) + "</option>").join("");
  select.innerHTML =
    optionsFor(groups.national) +
    '<optgroup label="Prefectures">' + optionsFor(groups.prefecture) + "</optgroup>" +
    '<optgroup label="Transport-bureau regions (a republication of the same nights)">' +
      optionsFor(groups.region) + "</optgroup>";
  select.addEventListener("change", () => {
    setUrlState({ area: select.value });
    load();
  });
}

function renderAll() {
  renderHeader();
  renderStale();
  renderBreakNotice();
  renderTiles();
  renderNights();
  renderTypePicker();
  renderOccupancy();
  renderNationality();
  renderMix();
  renderProvenance();
}

async function load() {
  const st = urlState();
  const r = await fetch(API + "/accommodation?area=" + encodeURIComponent(st.area));
  if (!r.ok) throw new Error("accommodation " + r.status);
  AC = await r.json();
  PERIODS = AC.periods;
  LAST = PERIODS.length - 1;
  const headline = col("nights." + AC.area);
  if (headline) {
    for (let i = headline.length - 1; i >= 0; i--) {
      if (headline[i] !== null && headline[i] !== undefined) { LAST = i; break; }
    }
  }
  renderAreaPicker();
  renderAll();
}

function boot() {
  initThemeToggle(() => {
    if (nightsChart) renderNights();
    if (occChart) renderOccupancy();
    if (natChart) renderNationality();
    if (mixChart) renderMix();
  });
  wireSeg("nights-seg", "data-view", "view", renderNights);
  wireSeg("nights-range", "data-range", "range", renderNights);
  wireSeg("occ-range", "data-orange", "orange", renderOccupancy);
  wireSeg("nat-seg", "data-nat", "nat", renderNationality);
  wireSeg("mix-seg", "data-mix", "mix", renderMix);

  $("nights-png").addEventListener("click", () =>
    nightsChart.exportPNG("guest-nights-" + AC.area + ".png"));
  $("nights-csv").addEventListener("click", () =>
    nightsChart.exportCSV("guest-nights-" + AC.area + ".csv",
      csvHeader("Guest nights by month", [CALCS.rec])));
  $("occ-png").addEventListener("click", () =>
    occChart.exportPNG("room-occupancy-" + AC.area + ".png"));
  $("occ-csv").addEventListener("click", () =>
    occChart.exportCSV("room-occupancy-" + AC.area + ".csv",
      csvHeader("Room occupancy by hotel type", [CALCS.occ])));
  $("nat-png").addEventListener("click", () =>
    natChart.exportPNG("foreign-guest-nights-by-nationality-" + AC.area + ".png"));
  $("nat-csv").addEventListener("click", () =>
    natChart.exportCSV("foreign-guest-nights-by-nationality-" + AC.area + ".csv",
      csvHeader("Foreign guest nights by nationality", [CALCS.natshare, CALCS.unknown])));
  $("mix-png").addEventListener("click", () =>
    mixChart.exportPNG("demand-mix-" + AC.area + ".png"));
  $("mix-csv").addEventListener("click", () =>
    mixChart.exportCSV("demand-mix-" + AC.area + ".csv",
      csvHeader("Guest nights by " + urlState().mix)));
}

load().catch(err => {
  document.getElementById("tiles").innerHTML =
    '<div class="strip-cell">Could not load the accommodation data: ' +
    escapeHtml(err.message) + "</div>";
});
boot();
