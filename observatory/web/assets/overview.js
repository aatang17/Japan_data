/* Overview page. The question this screen answers:
   "What is Japanese inflation right now?" — the headline YoY tile leads. */
"use strict";

const DATASET = "cpi-jp";
const API = "/api/v1/" + DATASET;

const ITEMS_DATASET = "cpi-jp-items";   // breadth reads the detailed-item table

let OV = null;          // /overview payload
let CONTRIB = null;     // /contributions payload
let BREADTH = null;     // /breadth payload (cpi-jp-items)
let mainChart = null;
let groupsChart = null;
let contribChart = null;
let breadthChart = null;
let obsCache = {};      // measure -> observations payload

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    measure: p.get("measure") || "yoy",
    range: p.get("range") || "5",
    crange: p.get("crange") || "3",
    groups: p.get("groups") || "yoy",
    brange: p.get("brange") || "10",
  };
}

function setUrlState(next) {
  const state = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (state.measure !== "yoy") p.set("measure", state.measure);
  if (state.range !== "5") p.set("range", state.range);
  if (state.crange !== "3") p.set("crange", state.crange);
  if (state.groups !== "yoy") p.set("groups", state.groups);
  if (state.brange !== "10") p.set("brange", state.brange);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function sourceLine(rel, trust) {
  const label = TRUST_LABELS[trust];
  return "Source: Statistics Bureau of Japan · " + rel.source_id +
    " · 2020 = 100 · Data through " + fmtPeriod(rel.latest_period) +
    " · Retrieved " + fmtStamp(rel.retrieved_at) +
    (label ? " · " + label : "");
}

/* The API label carries the full definition ("Core CPI (less fresh food) · YoY").
   A strip cell is one line, so the parenthetical moves to the footnote and the
   "CPI" that every cell repeats is dropped. Full label stays on the tooltip. */
function shortLabel(label) {
  return label
    .replace(/\s*\([^)]*\)/g, "")
    .replace(/\bCPI\b/g, "")
    .replace("3m Annualized", "3m ann.")
    .replace(/\s+/g, " ")
    .replace(/\s+([,;:])/g, "$1")   // "Headline CPI, adjusted" must not leave " ,"
    .trim();
}

/* What the cell labels drop when they abbreviate. Fixed copy for this dataset,
   like the sub-line in renderHeader — the API sends the definitions inside the
   labels, not as prose. */
const STRIP_NOTE = "Core excludes fresh food; core-core also excludes energy";

function renderTiles() {
  const tiles = OV.tiles;

  // Every cell is a rate in the same unit, so one shared scale makes the bars
  // comparable; the largest reading on the strip sets full width.
  const scale = Math.max.apply(null,
    tiles.map(t => (t.value === null ? 0 : Math.abs(t.value))).concat([0]));

  // The delta baseline is the same month for every cell in practice; when it
  // is, it belongs in the footnote rather than repeated five times.
  const comparisons = [];
  tiles.forEach(t => {
    if (t.delta_pp !== null && comparisons.indexOf(t.comparison) === -1) {
      comparisons.push(t.comparison);
    }
  });
  const sharedComparison = comparisons.length === 1 ? comparisons[0] : null;

  document.getElementById("tiles").innerHTML = tiles.map(t => {
    const val = t.value === null ? MISSING : fmtNum(t.value, 1);
    const unit = t.value === null || t.unit !== "%" ? ""
      : '<span class="unit">%</span>';

    // Direction reads off the arrow and the colour, which a screen reader gets
    // neither of — the hidden word is the same fact in text.
    let delta = MISSING;
    let dir = "flat";
    if (t.delta_pp !== null) {
      const rounded = Number(t.delta_pp.toFixed(1));
      dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
      const arrow = rounded === 0 ? ""
        : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
          '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
      delta = arrow + fmtNum(Math.abs(t.delta_pp), 1) + " pp" +
        (sharedComparison ? "" : " " + escapeHtml(t.comparison));
    }

    const width = t.value === null || scale === 0 ? 0
      : Math.abs(t.value) / scale * 100;

    return '<div class="strip-cell">' +
      '<div class="strip-label" title="' + escapeHtml(t.label) + '">' +
        escapeHtml(shortLabel(t.label)) + "</div>" +
      '<div class="strip-value num">' + val + unit + "</div>" +
      '<div class="strip-delta num ' + dir + '">' + delta + "</div>" +
      '<div class="strip-meter" aria-hidden="true"><i style="width:' +
        width.toFixed(1) + '%"></i></div>' +
      "</div>";
  }).join("");

  document.getElementById("strip-foot").textContent =
    "Change " + (sharedComparison || "vs the prior month") +
    ", in percentage points · " + STRIP_NOTE;
}

function renderStale() {
  const el = document.getElementById("stale-banner");
  if (OV.stale) {
    el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
      "ingested data is for " + fmtPeriodLong(OV.release.latest_period) +
      ", ingested " + fmtStamp(OV.release.ingested_at) +
      ". Official releases arrive roughly three weeks after the reference month; run the ingestion to refresh.</div>";
  } else {
    el.innerHTML = "";
  }
}

function renderHeader() {
  const rel = OV.release;
  document.getElementById("header-asof").textContent =
    "Data through " + fmtPeriod(rel.latest_period);
  document.getElementById("page-asof").textContent = "Ingested " + fmtStamp(rel.ingested_at);
  document.getElementById("page-sub").textContent =
    "National, middle-class indices · 2020 = 100 · Statistics Bureau of Japan";
}

function measureUnitName(measure) {
  return measure === "index" ? "Index (2020 = 100)" : "%";
}

async function loadObservations(measure) {
  if (obsCache[measure]) return obsCache[measure];
  const codes = OV.main_series.map(s => s.code).join(",");
  const r = await fetch(API + "/observations?series=" + codes + "&measure=" + measure);
  if (!r.ok) throw new Error("observations " + r.status);
  const data = await r.json();
  obsCache[measure] = data;
  return data;
}

function rangeStart(range, latestIso) {
  if (range === "max") return null;
  const y = Number(latestIso.slice(0, 4)) - Number(range);
  return latestIso.slice(0, 4).replace(/^\d{4}$/, String(y)) + latestIso.slice(4, 7);
}

async function renderMain() {
  const state = urlState();
  const data = await loadObservations(state.measure);
  const start = rangeStart(state.range, OV.release.latest_period);

  const bySlot = {};
  OV.main_series.forEach(m => { bySlot[m.code] = m; });

  const series = data.series.map(s => ({
    name: bySlot[s.code] ? bySlot[s.code].label : s.name_en,
    slot: bySlot[s.code] ? bySlot[s.code].slot : 6,
    points: s.points.filter(p => !start || p[0] >= start),
  }));

  const cfg = {
    series: series,
    unit: data.unit,
    yAxisName: measureUnitName(state.measure),
    trust: data.trust,
    sourceLine: sourceLine(OV.release, data.trust),
  };
  const el = document.getElementById("main-chart");
  el.innerHTML = "";
  if (mainChart) mainChart.dispose();
  mainChart = obsChart(el, "line", cfg);

  document.getElementById("main-source").innerHTML =
    sourceLine(OV.release, data.trust).replace("Source: ",
      'Source: <a href="' + escapeHtml(OV.release.source_page) + '" rel="noopener">')
      .replace(" · " + OV.release.source_id, "</a> · " + OV.release.source_id);

  const calcEl = document.getElementById("main-calc");
  if (data.trust === "derived") {
    calcEl.style.display = "";
    calcEl.innerHTML = "<summary>Show calculation</summary>" +
      '<div class="calc-body">' + MEASURE_LABELS[state.measure] + ": <code>" +
      escapeHtml(data.calc) + "</code><br>Inputs: official index values from " +
      escapeHtml(data.release.source_name) + " (sha256 " +
      data.release.sha256.slice(0, 12) + "…), release “" + escapeHtml(data.release.label) +
      "”. Full precision shown in tooltips; displayed figures are rounded to one decimal.</div>";
  } else {
    calcEl.style.display = "none";
  }

  document.getElementById("main-png").onclick = () =>
    mainChart.exportPNG("japan-cpi-" + state.measure + ".png");
  document.getElementById("main-csv").onclick = () =>
    mainChart.exportCSV("japan-cpi-" + state.measure + ".csv", [
      "Japan CPI — " + MEASURE_LABELS[state.measure],
      TRUST_LABELS[data.trust] ? "Trust: " + TRUST_LABELS[data.trust]
        : "Trust: calculated from official index values (formula below)",
      "Calculation: " + data.calc,
      "Source: Statistics Bureau of Japan via e-Stat, " + OV.release.source_id,
      "Release: " + OV.release.label + " (2020 = 100)",
      "Retrieved: " + fmtStamp(OV.release.retrieved_at),
      "Permalink: " + location.href,
    ]);
}

function latestValue(points) {
  for (let i = points.length - 1; i >= 0; i--) {
    if (points[i][1] !== null) return points[i][1];
  }
  return null;
}

function renderGroups() {
  const view = urlState().groups;
  if (view === "contrib" && !CONTRIB) return;   // re-rendered once contributions arrive
  const contribByCode = {};
  if (CONTRIB) CONTRIB.groups.forEach(g => { contribByCode[g.code] = latestValue(g.points); });

  const items = OV.groups.map(g => {
    const c = contribByCode[g.code];
    if (view === "contrib") {
      return { name: g.name_en, value: c, weight: g.weight,
               note: g.yoy === null ? null : "Group YoY: " + fmtSigned(g.yoy, 1, "%") };
    }
    return { name: g.name_en, value: g.yoy, weight: g.weight,
             note: c === null || c === undefined ? null
               : "Contribution to headline: " + fmtSigned(c, 2, "pp") };
  });
  document.getElementById("groups-note").textContent =
    (view === "contrib" ? "Contribution to headline YoY, " : "YoY, ") +
    fmtPeriodLong(OV.release.latest_period) + " · sorted by value";
  const el = document.getElementById("groups-chart");
  el.innerHTML = "";
  if (groupsChart) groupsChart.dispose();
  groupsChart = obsChart(el, "bar", {
    items: items,
    unit: view === "contrib" ? "pp" : "%",
    valueLabel: view === "contrib" ? "Contribution" : MEASURE_SHORT.yoy,
    trust: "derived",
    sourceLine: sourceLine(OV.release, "derived"),
  });
  document.getElementById("groups-source").textContent =
    sourceLine(OV.release, "derived");
}

function contribCfg() {
  const state = urlState();
  const start = rangeStart(state.crange, CONTRIB.release.latest_period);
  const cut = pts => pts.filter(p => !start || p[0] >= start);

  // five largest current contributors keep their own colour; the rest and
  // the rounding residual are bundled so the palette is never exceeded
  const ranked = CONTRIB.groups.slice().sort((a, b) =>
    Math.abs(latestValue(b.points) ?? 0) - Math.abs(latestValue(a.points) ?? 0));
  const top = ranked.slice(0, 5);
  const rest = ranked.slice(5);

  const periods = CONTRIB.headline.points.map(p => p[0]);
  const otherByPeriod = {};
  periods.forEach(p => { otherByPeriod[p] = 0; });
  rest.forEach(g => g.points.forEach(p => {
    if (p[1] !== null && otherByPeriod[p[0]] !== undefined) otherByPeriod[p[0]] += p[1];
  }));
  CONTRIB.residual.points.forEach(p => {
    if (p[1] !== null && otherByPeriod[p[0]] !== undefined) otherByPeriod[p[0]] += p[1];
  });

  return {
    series: top.map((g, i) => ({ name: g.name_en, slot: i + 1, points: cut(g.points) }))
      .concat([{ name: "Other & residual", slot: 6,
                 points: cut(periods.map(p => [p, otherByPeriod[p]])) }]),
    line: { name: "Headline CPI YoY (%)", points: cut(CONTRIB.headline.points) },
    unit: "pp",
    yAxisName: "pp",
    trust: CONTRIB.trust,
    sourceLine: sourceLine(CONTRIB.release, CONTRIB.trust),
  };
}

function renderContrib() {
  if (!CONTRIB) return;
  const el = document.getElementById("contrib-chart");
  el.innerHTML = "";
  if (contribChart) contribChart.dispose();
  contribChart = obsChart(el, "stack", contribCfg());

  document.getElementById("contrib-source").textContent =
    sourceLine(CONTRIB.release, CONTRIB.trust);
  const calcEl = document.getElementById("contrib-calc");
  calcEl.innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(CONTRIB.calc) + "</code><br>" +
    "Inputs: official index values and weights, release “" +
    escapeHtml(CONTRIB.release.label) + "” (sha256 " +
    CONTRIB.release.sha256.slice(0, 12) + "…). The five largest current contributors are " +
    "shown; the remaining groups and the rounding residual are summed into " +
    "“Other &amp; residual”, so the bars always sum to headline YoY.</div>";

  document.getElementById("contrib-png").onclick = () =>
    contribChart.exportPNG("japan-cpi-contributions.png");
  document.getElementById("contrib-csv").onclick = () =>
    contribChart.exportCSV("japan-cpi-contributions.csv", [
      "Japan CPI — contribution to headline YoY by major group (pp)",
      "Trust: calculated from official index values and weights (formula below)",
      "Calculation: " + CONTRIB.calc,
      "Source: Statistics Bureau of Japan via e-Stat, " + CONTRIB.release.source_id,
      "Release: " + CONTRIB.release.label + " (2020 = 100)",
      "Retrieved: " + fmtStamp(CONTRIB.release.retrieved_at),
      "Permalink: " + location.href,
    ]);
}

function renderBreadth() {
  if (!BREADTH) return;
  const state = urlState();
  const start = rangeStart(state.brange, BREADTH.release.latest_period);
  const pts = BREADTH.points.filter(p => !start || p.period >= start);

  const latest = BREADTH.points[BREADTH.points.length - 1];
  document.getElementById("breadth-note").textContent =
    fmtNum(latest.n, 0) + " priced items · " + fmtPeriodLong(latest.period);

  const cfg = {
    series: [
      { name: "Rising ≥ 2% YoY", slot: 1,
        points: pts.map(p => [p.period, p.above_pct]) },
      { name: "Falling YoY", slot: 2,
        points: pts.map(p => [p.period, p.falling_pct]) },
    ],
    unit: "%",
    yAxisName: "% of items",
    trust: BREADTH.trust,
    sourceLine: sourceLine(BREADTH.release, BREADTH.trust),
  };
  const el = document.getElementById("breadth-chart");
  el.innerHTML = "";
  if (breadthChart) breadthChart.dispose();
  breadthChart = obsChart(el, "line", cfg);

  document.getElementById("breadth-source").textContent =
    sourceLine(BREADTH.release, BREADTH.trust);
  const calcEl = document.getElementById("breadth-calc");
  calcEl.innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(BREADTH.calc) + "</code><br>" +
    "Universe: the " + fmtNum(BREADTH.item_universe, 0) + " individually priced items of the " +
    "detailed-item table (aggregates excluded); items without a value a year earlier drop " +
    "out of that month's denominator. Threshold: " + BREADTH.threshold + "%.</div>";

  document.getElementById("breadth-png").onclick = () =>
    breadthChart.exportPNG("japan-cpi-breadth.png");
  document.getElementById("breadth-csv").onclick = () =>
    breadthChart.exportCSV("japan-cpi-breadth.csv", [
      "Japan CPI — inflation breadth over detailed items (% of items)",
      "Trust: calculated from official index values (definition below)",
      "Calculation: " + BREADTH.calc,
      "Source: Statistics Bureau of Japan via e-Stat, " + BREADTH.release.source_id,
      "Release: " + BREADTH.release.label + " (2020 = 100)",
      "Retrieved: " + fmtStamp(BREADTH.release.retrieved_at),
      "Permalink: " + location.href,
    ]);
}

function renderProvenance() {
  const rel = OV.release;
  const base = (rel.base || "").replace("=", " = ");
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
            " – latest month" + (base ? " · " + escapeHtml(base) : "") + "</div>" +
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

function wireSeg(segId, stateKey, current, onChange) {
  const seg = document.getElementById(segId);
  seg.querySelectorAll("button").forEach(b => {
    const key = b.dataset.range || b.dataset.view;
    b.setAttribute("aria-pressed", String(key === current));
    b.addEventListener("click", () => {
      seg.querySelectorAll("button").forEach(x =>
        x.setAttribute("aria-pressed", String(x === b)));
      const next = {};
      next[stateKey] = key;
      setUrlState(next);
      onChange();
    });
  });
}

function wireControls() {
  const state = urlState();
  const sel = document.getElementById("measure-select");
  sel.value = state.measure;
  sel.addEventListener("change", () => {
    setUrlState({ measure: sel.value });
    renderMain().catch(showError);
  });
  wireSeg("range-seg", "range", state.range, () => renderMain().catch(showError));
  wireSeg("contrib-seg", "crange", state.crange, renderContrib);
  wireSeg("groups-seg", "groups", state.groups, renderGroups);
  wireSeg("breadth-seg", "brange", state.brange, renderBreadth);
}

function showError(err) {
  document.getElementById("tiles").innerHTML =
    '<div class="state-error" style="grid-column:1/-1">The overview failed to load. ' +
    "The data service may not be running — start it and reload this page." +
    "<details><summary>See details</summary><pre>" + escapeHtml(String(err)) +
    "</pre></details></div>";
}

function sectionError(chartId, what, err) {
  document.getElementById(chartId).innerHTML =
    '<div class="state-error">' + what + " failed to load." +
    "<details><summary>See details</summary><pre>" + escapeHtml(String(err)) +
    "</pre></details></div>";
}

async function init() {
  initThemeToggle(() => {
    if (mainChart) renderMain().catch(showError);
    if (groupsChart) renderGroups();
    if (contribChart) renderContrib();
    if (breadthChart) renderBreadth();
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
  renderGroups();
  renderProvenance();
  wireControls();

  // analysis panels load independently — one failing must not blank the page
  fetch(API + "/contributions")
    .then(r => { if (!r.ok) throw new Error("contributions " + r.status); return r.json(); })
    .then(d => { CONTRIB = d; renderContrib(); renderGroups(); })
    .catch(err => sectionError("contrib-chart", "The contribution breakdown", err));
  fetch("/api/v1/" + ITEMS_DATASET + "/breadth")
    .then(r => { if (!r.ok) throw new Error("breadth " + r.status); return r.json(); })
    .then(d => { BREADTH = d; renderBreadth(); })
    .catch(err => sectionError("breadth-chart", "The breadth panel", err));

  await renderMain().catch(showError);
}

init();
