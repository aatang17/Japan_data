/* Bank of Japan page. The question this screen answers:
   "How fast is the BOJ's JGB book shrinking right now?" — the holdings tile
   and the peak-annotated holdings chart lead.

   Values arrive exactly as published, in ¥100 million; every surface here
   displays ¥ trillion (an exact ÷10,000), and says so. Missing is "—". */
"use strict";

const DATASET = "boj-assets";
const API = "/api/v1/" + DATASET;

const PER_TN = 10000;   // published ¥100mn per displayed ¥tn — exact conversion

let OV = null;          // /overview payload
let heroChart = null;
let heroObs = null;     // /observations payload for the headline series
let flowChart = null;
let flowObs = null;     // /observations payload for the JGB flow series

// JGB flow series: gross purchases and redemptions are published; the net
// flow is published too, and the two components do NOT fully account for it
// (some components have no live flow series), so the chart carries an exact
// balancing item rather than pretending purchases − redemptions = net.
const FLOW_PURCHASES = "MA030210341F";
const FLOW_REDEMPTIONS = "MA030210342F";
const FLOW_NET = "MA03021034F";

function tn(v) { return v === null || v === undefined ? null : v / PER_TN; }

function urlState() {
  const p = new URLSearchParams(location.search);
  return { range: p.get("range") || "max", frange: p.get("frange") || "3" };
}

function setUrlState(next) {
  const state = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (state.range !== "max") p.set("range", state.range);
  if (state.frange !== "3") p.set("frange", state.frange);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

/* "2023-11-01" -> "Nov 2023" (annotations, tile sublines) */
function fmtPeriodShort(iso) {
  if (!iso) return MISSING;
  return MONTHS[Number(iso.slice(5, 7)) - 1].slice(0, 3) + " " + iso.slice(0, 4);
}

function sourceLine(rel, trust) {
  const label = TRUST_LABELS[trust];
  return "Source: Bank of Japan · " + rel.source_id +
    " · ¥tn (published in ¥100mn) · Data through " + fmtPeriod(rel.latest_period) +
    " · Retrieved " + fmtStamp(rel.retrieved_at) +
    (label ? " · " + label : "");
}

/* ---- stat strip ---- */

function stripDelta(deltaTn, dp, suffix) {
  if (deltaTn === null) return { html: MISSING, dir: "flat" };
  const rounded = Number(deltaTn.toFixed(dp));
  const dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
  const arrow = rounded === 0 ? ""
    : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
      '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
  return { html: arrow + fmtNum(Math.abs(deltaTn), dp) + " ¥tn" + (suffix || ""), dir: dir };
}

function tileCell(label, valueHtml, deltaHtml, dir, title) {
  return '<div class="strip-cell">' +
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' +
      escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + valueHtml + "</div>" +
    '<div class="strip-delta num ' + dir + '">' + deltaHtml + "</div>" +
    "</div>";
}

function renderTiles() {
  const byKey = {};
  OV.tiles.forEach(t => { byKey[t.key] = t; });
  const cells = [];

  // The month-on-month baseline is the same for both level tiles, so it
  // lives once in the strip footnote rather than wrapping inside the cells.
  const holdings = byKey.holdings;
  if (holdings) {
    const d = stripDelta(tn(holdings.delta), 1);
    cells.push(tileCell(holdings.label,
      fmtNum(tn(holdings.value), 1) + '<span class="unit">¥tn</span>',
      d.html, d.dir,
      holdings.series_name + " — " + holdings.calc));
  }

  const peak = byKey.from_peak;
  if (peak) {
    cells.push(tileCell(peak.label,
      fmtSigned(tn(peak.value), 1) + '<span class="unit">¥tn</span>',
      fmtSigned(peak.pct, 1, "%") + " · peak " + fmtPeriodShort(peak.peak_period) +
        " (" + fmtNum(tn(peak.peak_value), 1) + " ¥tn)",
      (peak.value ?? 0) < 0 ? "down" : "up",
      peak.series_name + " — " + peak.calc));
  }

  const pace = byKey.pace_12m;
  if (pace) {
    const d = stripDelta(tn(pace.delta), 2);
    cells.push(tileCell(pace.label,
      fmtSigned(tn(pace.value), 2) + '<span class="unit">¥tn/mo</span>',
      d.html + " vs prior window", d.dir,
      pace.series_name + " — " + pace.calc));
  }

  const buy = byKey.purchases;
  if (buy) {
    const d = stripDelta(tn(buy.delta), 1);
    cells.push(tileCell(buy.label,
      fmtNum(tn(buy.value), 1) + '<span class="unit">¥tn</span>',
      d.html, d.dir,
      buy.series_name + " — " + buy.calc));
  }

  document.getElementById("tiles").innerHTML = cells.join("");
  document.getElementById("strip-foot").textContent =
    "Changes " + (holdings ? holdings.comparison : "vs the prior month") +
    " unless stated · shown in ¥ trillion, converted exactly from the published " +
    "¥100 million · a negative net flow is balance-sheet runoff (QT)";

  // Derived tiles show their formula, per the trust contract.
  const derived = OV.tiles.filter(t => t.trust === "derived");
  const calcEl = document.getElementById("strip-calc");
  if (derived.length) {
    calcEl.style.display = "";
    calcEl.innerHTML = "<summary>Show calculation</summary>" +
      '<div class="calc-body">' + derived.map(t =>
        "<b>" + escapeHtml(t.label) + "</b>: <code>" + escapeHtml(t.calc) + "</code>"
      ).join("<br>") +
      "<br>Inputs: official values from " + escapeHtml(OV.release.source_name) +
      " (sha256 " + OV.release.sha256.slice(0, 12) + "…), release “" +
      escapeHtml(OV.release.label) + "”. Levels and flows are published in ¥100mn; " +
      "figures shown are converted to ¥tn (÷10,000, exact).</div>";
  }
}

/* ---- chrome ---- */

function renderHeader() {
  const rel = OV.release;
  document.getElementById("header-asof").textContent =
    "Data through " + fmtPeriod(rel.latest_period);
  document.getElementById("page-asof").textContent = "Ingested " + fmtStamp(rel.ingested_at);
  document.getElementById("page-sub").textContent =
    "End-of-month stocks and during-month flows · ¥ trillion · Bank of Japan, table MD09";
  if (OV.credit_line) {
    document.getElementById("credit-line").textContent = OV.credit_line;
  }
}

function renderStale() {
  const el = document.getElementById("stale-banner");
  if (OV.stale) {
    el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
      "ingested data is for " + fmtPeriodLong(OV.release.latest_period) +
      ", ingested " + fmtStamp(OV.release.ingested_at) +
      ". The Bank publishes this table early in the following month; run the ingestion to refresh.</div>";
  } else {
    el.innerHTML = "";
  }
}

function renderProvenance() {
  const rel = OV.release;
  document.getElementById("prov-card").innerHTML =
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
          '<div class="prov-sub">Series coverage ' + fmtPeriodLong(rel.coverage_start) +
            " – latest month · published in ¥100 million</div>" +
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

/* ---- hero chart ---- */

function headlineSeries() {
  return OV.main_series.find(m => m.role === "headline");
}

async function loadHeroObservations() {
  if (heroObs) return heroObs;
  const head = headlineSeries();
  const r = await fetch(API + "/observations?series=" + head.code + "&measure=index");
  if (!r.ok) throw new Error("observations " + r.status);
  heroObs = await r.json();
  return heroObs;
}

function rangeStart(range, latestIso) {
  if (range === "max") return null;
  const y = Number(latestIso.slice(0, 4)) - Number(range);
  return String(y) + latestIso.slice(4, 7);
}

async function renderMain() {
  const state = urlState();
  const data = await loadHeroObservations();
  const start = rangeStart(state.range, OV.release.latest_period);
  const head = headlineSeries();

  const all = data.series[0].points.map(p => [p[0], tn(p[1])]);
  const points = all.filter(p => !start || p[0] >= start);

  // The peak is a published reading; annotate it only when it is on screen.
  let peak = null;
  all.forEach(p => { if (p[1] !== null && (peak === null || p[1] > peak[1])) peak = p; });
  const annotations = peak && (!start || peak[0] >= start)
    ? [{ x: peak[0], y: peak[1],
         text: "Peak " + fmtNum(peak[1], 1) + " ¥tn · " + fmtPeriodShort(peak[0]) }]
    : [];

  const cfg = {
    series: [{ name: head.label, slot: head.slot, points: points }],
    unit: "¥tn",
    unitSuffix: "¥tn",
    dp: 2,
    yAxisName: "¥tn",
    trust: data.trust,
    annotations: annotations,
    sourceLine: sourceLine(OV.release, data.trust),
  };
  const el = document.getElementById("main-chart");
  el.innerHTML = "";
  if (heroChart) heroChart.dispose();
  heroChart = obsChart(el, "line", cfg);

  document.getElementById("main-source").innerHTML =
    sourceLine(OV.release, data.trust).replace("Source: ",
      'Source: <a href="' + escapeHtml(OV.release.source_page) + '" rel="noopener">')
      .replace(" · " + OV.release.source_id, "</a> · " + OV.release.source_id);

  document.getElementById("main-png").onclick = () =>
    heroChart.exportPNG("boj-jgb-holdings.png");
  document.getElementById("main-csv").onclick = () =>
    heroChart.exportCSV("boj-jgb-holdings.csv", [
      "Bank of Japan — JGB holdings, end of month (¥tn)",
      "Trust: " + (TRUST_LABELS[data.trust] || "calculated (formula on the page)") +
        " — values exactly as published, converted from ¥100mn to ¥tn (÷10,000, exact)",
      "Source: Bank of Japan Time-Series Data Search, " + OV.release.source_id,
      "Vintage: " + OV.release.label,
      "Retrieved: " + fmtStamp(OV.release.retrieved_at),
      "Permalink: " + location.href,
      OV.credit_line || "",
    ]);
}

/* ---- purchases vs redemptions ---- */

async function loadFlowObservations() {
  if (flowObs) return flowObs;
  const codes = [FLOW_PURCHASES, FLOW_REDEMPTIONS, FLOW_NET].join(",");
  const r = await fetch(API + "/observations?series=" + codes + "&measure=index");
  if (!r.ok) throw new Error("observations " + r.status);
  flowObs = await r.json();
  return flowObs;
}

const FLOW_BALANCE_CALC =
  "balancing item[t] = net flow[t] − outright purchases[t] − redemptions[t], " +
  "so the bars sum exactly to the published net flow line.";

async function renderFlows() {
  const state = urlState();
  const data = await loadFlowObservations();
  const start = rangeStart(state.frange, OV.release.latest_period);

  const byCode = {};
  data.series.forEach(s => { byCode[s.code] = {}; s.points.forEach(p => {
    byCode[s.code][p[0]] = p[1];
  }); });
  const purch = byCode[FLOW_PURCHASES], red = byCode[FLOW_REDEMPTIONS],
        net = byCode[FLOW_NET];

  const periods = Object.keys(net).sort().filter(p => !start || p >= start);
  const balance = p =>
    (net[p] === null || purch[p] === null || purch[p] === undefined ||
     red[p] === null || red[p] === undefined)
      ? null : net[p] - purch[p] - red[p];

  const cfg = {
    series: [
      { name: "Outright purchases (gross)", slot: 1,
        points: periods.map(p => [p, tn(purch[p])]) },
      { name: "Redemptions", slot: 2,
        points: periods.map(p => [p, tn(red[p])]) },
      { name: "Other JGB flows (balancing)", slot: 6,
        points: periods.map(p => [p, tn(balance(p))]) },
    ],
    line: { name: "Net flow (published)",
            points: periods.map(p => [p, tn(net[p])]) },
    unit: "¥tn",
    yAxisName: "¥tn / month",
    // The balancing item is calculated, so the chart is not labelled official
    // as a whole; the source line and the calculation note carry the split.
    trust: "derived",
    sourceLine: sourceLine(OV.release, "official") + " · balancing item calculated",
  };
  const el = document.getElementById("flow-chart");
  el.innerHTML = "";
  if (flowChart) flowChart.dispose();
  flowChart = obsChart(el, "stack", cfg);

  document.getElementById("flow-source").innerHTML =
    sourceLine(OV.release, null).replace("Source: ",
      'Source: <a href="' + escapeHtml(OV.release.source_page) + '" rel="noopener">')
      .replace(" · " + OV.release.source_id, "</a> · " + OV.release.source_id) +
    " · purchases, redemptions and the net line are official values; the balancing item is calculated";

  document.getElementById("flow-calc").innerHTML =
    "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(FLOW_BALANCE_CALC) + "</code><br>" +
    "The balancing item contains the published “other transactions” flow together with " +
    "components that have no live flow series (for example repo sales to the government). " +
    "Purchases, redemptions and the net flow are official values from release “" +
    escapeHtml(OV.release.label) + "” (sha256 " + OV.release.sha256.slice(0, 12) +
    "…), published in ¥100mn and shown in ¥tn (÷10,000, exact).</div>";

  document.getElementById("flow-png").onclick = () =>
    flowChart.exportPNG("boj-jgb-purchases-redemptions.png");
  document.getElementById("flow-csv").onclick = () =>
    flowChart.exportCSV("boj-jgb-purchases-redemptions.csv", [
      "Bank of Japan — JGB outright purchases, redemptions and net flow, monthly (¥tn)",
      "Trust: purchases, redemptions and net flow are official values as published; " +
        "the balancing item is calculated (formula below)",
      "Calculation: " + FLOW_BALANCE_CALC,
      "Unit: ¥tn, converted from published ¥100mn (÷10,000, exact); " +
        "redemptions are negative as published",
      "Source: Bank of Japan Time-Series Data Search, " + OV.release.source_id,
      "Vintage: " + OV.release.label,
      "Retrieved: " + fmtStamp(OV.release.retrieved_at),
      "Permalink: " + location.href,
      OV.credit_line || "",
    ]);
}

/* ---- all-series tables ---- */

let seriesData = null;   // /series payload

async function loadSeriesList() {
  if (seriesData) return seriesData;
  const r = await fetch(API + "/series");
  if (!r.ok) throw new Error("series " + r.status);
  seriesData = await r.json();
  return seriesData;
}

/* One row cell layout shared by both tables: name, numbers, trend, as-of.
   The as-of column is where a frozen series declares itself — a row that
   ended early shows its own last month plus "ended", muted, so a 2025 value
   can never read as current. */
function seriesRow(s, cols) {
  const asOf = fmtPeriod(s.as_of) +
    (s.discontinued ? ' <span class="muted">· ended</span>' : "");
  return "<tr>" +
    '<td title="' + escapeHtml(s.code + " — " + s.name_en) + '">' +
      escapeHtml(s.name_en) + "</td>" +
    cols.map(c => '<td class="num">' + c + "</td>").join("") +
    "<td>" + sparkSVG(s.spark, 110, 26) + "</td>" +
    '<td class="num">' + asOf + "</td>" +
    "</tr>";
}

function seriesTable(headers, rowsHtml) {
  return '<table class="data tbl-series"><thead><tr>' +
    "<th>Series</th>" +
    headers.map(h => '<th class="num">' + h + "</th>").join("") +
    "<th>5y trend</th>" + '<th class="num">As of</th>' +
    "</tr></thead><tbody>" + rowsHtml + "</tbody></table>";
}

async function renderSeriesTables() {
  const d = await loadSeriesList();
  const stocks = d.series.filter(s => s.kind === "stock");
  const flows = d.series.filter(s => s.kind === "flow");

  document.getElementById("series-note").textContent =
    d.count + " series · data through " + fmtPeriod(d.release.latest_period);

  document.getElementById("stocks-table").innerHTML = seriesTable(
    ["Latest ¥tn", "Δ 1m ¥tn", "Δ 12m ¥tn"],
    stocks.map(s => seriesRow(s, [
      fmtNum(tn(s.latest), 2),
      fmtSigned(tn(s.delta_1m), 2),
      fmtSigned(tn(s.delta_12m), 2),
    ])).join(""));

  document.getElementById("flows-table").innerHTML = seriesTable(
    ["Latest ¥tn", "12m avg ¥tn/mo", "12m sum ¥tn"],
    flows.map(s => seriesRow(s, [
      fmtSigned(tn(s.latest), 2),
      fmtSigned(tn(s.avg_12m), 2),
      fmtSigned(tn(s.sum_12m), 2),
    ])).join(""));

  document.getElementById("series-foot").textContent =
    "Latest values are official statistics; Δ, averages and sums are calculated. " +
    "Shown in ¥ trillion (published ¥100 million ÷ 10,000, exact) to two decimals. " +
    "— means no published value. A trailing-12-month figure needs all twelve months; " +
    "a series that ended keeps its own last month in the As-of column.";

  document.getElementById("series-calc").innerHTML =
    "<summary>Show calculation</summary>" +
    '<div class="calc-body">' +
    ["delta_1m", "delta_12m", "avg_12m", "sum_12m"].map(k =>
      "<code>" + escapeHtml(d.calc[k]) + "</code>").join("<br>") +
    "<br>Inputs: official values from release “" + escapeHtml(d.release.label) +
    "” (sha256 " + d.release.sha256.slice(0, 12) + "…).</div>";

  document.getElementById("series-csv").onclick = () => {
    const head = [
      "Bank of Japan — all ingested MD09 series, latest readings (¥tn)",
      "Trust: latest values are official as published; delta/avg/sum columns are calculated",
      "Calculations: " + ["delta_1m", "delta_12m", "avg_12m", "sum_12m"]
        .map(k => k + " = " + d.calc[k]).join(" | "),
      "Unit: ¥tn, converted from published ¥100mn (÷10,000, exact); empty = not published",
      "Source: Bank of Japan Time-Series Data Search, " + d.release.source_id,
      "Vintage: " + d.release.label,
      "Retrieved: " + fmtStamp(d.release.retrieved_at),
      "Permalink: " + location.href,
      OV.credit_line || "",
    ].map(l => "# " + l).join("\n");
    const cols = ["code", "name", "kind", "as_of", "discontinued",
                  "latest_tn", "delta_1m_tn", "delta_12m_tn", "avg_12m_tn", "sum_12m_tn"];
    const body = d.series.map(s => [
      s.code, '"' + s.name_en.replace(/"/g, '""') + '"', s.kind, fmtPeriod(s.as_of),
      s.discontinued ? "yes" : "no",
      tn(s.latest) ?? "", tn(s.delta_1m) ?? "", tn(s.delta_12m) ?? "",
      tn(s.avg_12m) ?? "", tn(s.sum_12m) ?? "",
    ].join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(
      [head + "\n" + cols.join(",") + "\n" + body + "\n"], { type: "text/csv" }));
    a.download = "boj-assets-series.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
}

function sectionError(chartId, what, err) {
  document.getElementById(chartId).innerHTML =
    '<div class="state-error">' + what + " failed to load." +
    "<details><summary>See details</summary><pre>" + escapeHtml(String(err)) +
    "</pre></details></div>";
}

/* ---- wiring ---- */

function wireSeg(segId, stateKey, current, onChange) {
  const seg = document.getElementById(segId);
  seg.querySelectorAll("button").forEach(b => {
    b.setAttribute("aria-pressed", String(b.dataset.range === current));
    b.addEventListener("click", () => {
      seg.querySelectorAll("button").forEach(x =>
        x.setAttribute("aria-pressed", String(x === b)));
      const next = {};
      next[stateKey] = b.dataset.range;
      setUrlState(next);
      onChange();
    });
  });
}

function wireControls() {
  const state = urlState();
  wireSeg("range-seg", "range", state.range, () => renderMain().catch(showError));
  wireSeg("flow-seg", "frange", state.frange, () =>
    renderFlows().catch(err => sectionError("flow-chart", "The purchases panel", err)));
}

function showError(err) {
  document.getElementById("tiles").innerHTML =
    '<div class="state-error" style="grid-column:1/-1">This page failed to load. ' +
    "The data service may not be running — start it and reload this page." +
    "<details><summary>See details</summary><pre>" + escapeHtml(String(err)) +
    "</pre></details></div>";
}

async function init() {
  initThemeToggle(() => {
    if (heroChart) renderMain().catch(showError);
    if (flowChart) renderFlows().catch(err =>
      sectionError("flow-chart", "The purchases panel", err));
  });
  try {
    const r = await fetch(API + "/overview");
    if (!r.ok) throw new Error("overview " + r.status + " " + (await r.text()).slice(0, 300));
    OV = await r.json();
  } catch (err) {
    showError(err);
    return;
  }
  renderHeader();
  renderStale();
  renderTiles();
  renderProvenance();
  wireControls();

  // panels load independently — one failing must not blank the page
  renderFlows().catch(err => sectionError("flow-chart", "The purchases panel", err));
  renderSeriesTables().catch(err =>
    sectionError("stocks-table", "The series tables", err));
  await renderMain().catch(showError);
}

init();
