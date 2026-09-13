/* Quarterly GDP. The question this screen answers:
   "How fast is Japan's economy growing right now, and what is driving it?"
   — the annualized-growth tile and the growth bars lead; contributions
   answer the second half.

   Levels arrive exactly as the Cabinet Office publishes them, in ¥ billion
   at seasonally adjusted annual rates; every growth rate and contribution
   on this page is arithmetic done here, and each one states its formula.
   The Cabinet Office's own published rates are computed from unrounded
   levels and can differ from these by about a tenth of a point. */
"use strict";

const DATASET = "gdp-jp";
const API = "/api/v1/" + DATASET;

let OV = null;        // /overview payload (release, tiles, staleness)
let LEVELS = null;    // {code: {iso: value}} for the three GDP bases
let COMPS = null;     // {code: {iso: value}} for the real demand components
let SERIES = null;    // /series payload
let growthChart = null;
let contribChart = null;

const HEAD = { real: "gdp.real_sa", nominal: "gdp.nominal_sa", deflator: "gdp.deflator_sa" };

// The demand components, grouped into six so the stacked bars stay readable:
// six is the palette's limit and eight lines of ±0.1pp would be noise.
// Legend names are short on purpose: six of them share one line with the
// axis label, and the grouping is spelled out under Show calculation.
const GROUPS = [
  { key: "consumption", label: "Consumption", slot: 1,
    codes: ["private_consumption.real_sa"] },
  { key: "investment", label: "Private investment", slot: 2,
    codes: ["residential_investment.real_sa", "business_investment.real_sa"] },
  { key: "inventories", label: "Inventories", slot: 3,
    codes: ["private_inventories.real_sa", "public_inventories.real_sa"] },
  { key: "government", label: "Government", slot: 4,
    codes: ["government_consumption.real_sa", "public_investment.real_sa"] },
  { key: "net_exports", label: "Net exports", slot: 5,
    codes: ["net_exports.real_sa"] },
  { key: "residual", label: "Residual", slot: 6, codes: [] },
];
const COMPONENT_CODES = GROUPS.reduce((a, g) => a.concat(g.codes), []);

// The formulas, verbatim from the dataset card so the two never drift.
const CALC = {
  qoq: "qoq % = (level[t] ÷ level[t − 1 quarter] − 1) × 100",
  ann: "annualized % = ((level[t] ÷ level[t − 1 quarter]) ^ 4 − 1) × 100",
  yoy: "yoy % = (level[t] ÷ level[t − 4 quarters] − 1) × 100",
  contribution: "contribution pp = (component[t] − component[t − 1 quarter]) ÷ GDP[t − 1 quarter] × 100",
  contribution_yoy: "contribution pp = (component[t] − component[t − 4 quarters]) ÷ GDP[t − 4 quarters] × 100",
  residual: "residual pp = GDP growth % − Σ contributions pp",
};

/* ---------- url state ---------- */

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    measure: ["ann", "qoq", "yoy", "level"].indexOf(p.get("measure")) >= 0 ? p.get("measure") : "ann",
    range: p.get("range") || "10",
    cbasis: p.get("cbasis") === "yoy" ? "yoy" : "qoq",
    crange: p.get("crange") || "5",
    basis: ["real_sa", "nominal_sa", "deflator_sa"].indexOf(p.get("basis")) >= 0 ? p.get("basis") : "real_sa",
  };
}

function setUrlState(next) {
  const s = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (s.measure !== "ann") p.set("measure", s.measure);
  if (s.range !== "10") p.set("range", s.range);
  if (s.cbasis !== "qoq") p.set("cbasis", s.cbasis);
  if (s.crange !== "5") p.set("crange", s.crange);
  if (s.basis !== "real_sa") p.set("basis", s.basis);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

/* ---------- periods ---------- */

/* "2026-04-01" -> "2026 Q2". Seven characters, so a CSV keeps it whole. */
function qLabel(iso) {
  return iso.slice(0, 4) + " Q" + ((Number(iso.slice(5, 7)) - 1) / 3 + 1);
}
function qLabelLong(iso) {
  const q = (Number(iso.slice(5, 7)) - 1) / 3 + 1;
  const m = ["January–March", "April–June", "July–September", "October–December"][q - 1];
  return m + " " + iso.slice(0, 4);
}
function quartersAgo(iso, n) {
  let y = Number(iso.slice(0, 4)), m = Number(iso.slice(5, 7)) - 3 * n;
  while (m <= 0) { y -= 1; m += 12; }
  return y + "-" + String(m).padStart(2, "0") + "-01";
}
function tn(v) { return v === null || v === undefined ? null : v / 1000; }   // ¥bn -> ¥tn, exact

/* Growth of one level series at a lag in quarters, as {iso: %}. Missing is
   missing: a quarter with no predecessor gets null, never zero. */
function growth(levels, lag, annualize) {
  const out = {};
  Object.keys(levels).sort().forEach(iso => {
    const cur = levels[iso], prev = levels[quartersAgo(iso, lag)];
    if (cur === null || cur === undefined || prev === null || prev === undefined || !prev) {
      out[iso] = null;
      return;
    }
    const r = cur / prev;
    out[iso] = annualize ? (Math.pow(r, 4) - 1) * 100 : (r - 1) * 100;
  });
  return out;
}

/* ---------- loading ---------- */

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " " + r.status + " " + (await r.text()).slice(0, 200));
  return r.json();
}

function toMap(payload) {
  const out = {};
  payload.series.forEach(s => {
    out[s.code] = {};
    s.points.forEach(p => { out[s.code][p[0].slice(0, 10)] = p[1]; });
  });
  return out;
}

async function loadLevels() {
  if (LEVELS) return LEVELS;
  // Two calls, not one: the API refuses to serve a yen level and an index
  // on one axis, and it is right to — they are different kinds of number.
  const [money, deflator] = await Promise.all([
    getJSON(API + "/observations?series=" + [HEAD.real, HEAD.nominal].join(",") + "&measure=index"),
    getJSON(API + "/observations?series=" + HEAD.deflator + "&measure=index"),
  ]);
  LEVELS = Object.assign(toMap(money), toMap(deflator));
  return LEVELS;
}

async function loadComponents() {
  if (COMPS) return COMPS;
  // Two calls: the API's series parameter is capped at 200 characters and
  // eight of these codes run past it.
  const half = Math.ceil(COMPONENT_CODES.length / 2);
  const parts = await Promise.all([COMPONENT_CODES.slice(0, half), COMPONENT_CODES.slice(half)]
    .map(codes => getJSON(API + "/observations?series=" + codes.join(",") + "&measure=index")));
  COMPS = Object.assign({}, toMap(parts[0]), toMap(parts[1]));
  return COMPS;
}

/* ---------- head, tiles ---------- */

function latestIso() { return OV.release.latest_period; }

function tileCell(label, value, delta, unit, title) {
  let html = MISSING, dir = "flat";
  if (delta !== null && delta !== undefined) {
    const dp = unit === "pp" ? 2 : 1;
    const rounded = Number(delta.toFixed(dp));
    dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
    const arrow = rounded === 0 ? ""
      : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
        '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
    html = arrow + fmtNum(Math.abs(delta), dp) + " " + unit;
  }
  return '<div class="strip-cell">' +
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' + escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + value + "</div>" +
    '<div class="strip-delta num ' + dir + '">' + html + "</div>" +
    "</div>";
}

function renderHead() {
  const latest = latestIso();
  document.getElementById("page-asof").textContent = "Data through " + qLabel(latest);
  document.getElementById("page-sub").textContent =
    "Japan's GDP on the expenditure side, " + qLabelLong(latest) + " and every quarter " +
    "back to 1994, seasonally adjusted, exactly as the Cabinet Office publishes it — " +
    "and revised at every release, each one kept.";
  if (OV.credit_line) document.getElementById("credit-line").textContent = OV.credit_line;
}

function renderStale() {
  const el = document.getElementById("stale-banner");
  if (!OV.stale) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
    "ingested quarter is " + qLabelLong(OV.release.latest_period) + ", ingested " +
    fmtStamp(OV.release.ingested_at) + ". The Cabinet Office publishes a first estimate " +
    "about six weeks after each quarter — if this persists, run the ingestion.</div>";
}

function renderTiles() {
  const latest = latestIso(), prior = quartersAgo(latest, 1);
  const real = LEVELS[HEAD.real], nominal = LEVELS[HEAD.nominal], deflator = LEVELS[HEAD.deflator];
  const ann = growth(real, 1, true), yoy = growth(real, 4, false), defYoy = growth(deflator, 4, false);
  const pp = (a, b) => (a === null || a === undefined || b === null || b === undefined) ? null : a - b;

  document.getElementById("tiles").innerHTML =
    tileCell("Real GDP, Annualized", fmtSigned(ann[latest], 1, "%"),
      pp(ann[latest], ann[prior]), "pp",
      qLabel(latest) + " on " + qLabel(prior) + ", at an annual rate. " + CALC.ann) +
    tileCell("Real GDP, Year on Year", fmtSigned(yoy[latest], 1, "%"),
      pp(yoy[latest], yoy[prior]), "pp",
      qLabel(latest) + " on " + qLabel(quartersAgo(latest, 4)) + ". " + CALC.yoy) +
    tileCell("Nominal GDP", fmtNum(tn(nominal[latest]), 1) + '<span class="unit">¥tn</span>',
      pp(tn(nominal[latest]), tn(nominal[prior])), "¥tn",
      "Seasonally adjusted annual rate, " + qLabel(latest) + ", exactly as published " +
      "(¥ billion shown as ¥ trillion, ÷1,000)") +
    tileCell("GDP Deflator, Year on Year", fmtSigned(defYoy[latest], 1, "%"),
      pp(defYoy[latest], defYoy[prior]), "pp",
      "The economy-wide price index (2020 = 100), " + qLabel(latest) + " on a year earlier");

  document.getElementById("strip-foot").textContent =
    "Changes vs " + qLabel(prior) + " · levels are official statistics as published; " +
    "the rates are calculated from them and can differ from the Cabinet Office's own " +
    "published rates by about a tenth of a point, because those are computed before rounding.";
  const calc = document.getElementById("strip-calc");
  calc.style.display = "";
  calc.innerHTML = "<summary>Show calculation</summary><div class=\"calc-body\">" +
    "<code>" + escapeHtml(CALC.ann) + "</code><br><code>" + escapeHtml(CALC.yoy) + "</code><br>" +
    "Inputs: official levels from release “" + escapeHtml(OV.release.label) + "” (sha256 " +
    OV.release.sha256.slice(0, 12) + "…). A quarter is dated by its first month.</div>";
}

/* ---------- growth chart ---------- */

function rangeFilter(range, latest) {
  if (range === "max") return () => true;
  const from = quartersAgo(latest, Number(range) * 4 - 1);
  return iso => iso >= from;
}

function sourceLine(trust) {
  return (TRUST_LABELS[trust] ? trustBadge(trust) + " " : "") +
    escapeHtml(OV.credit_line || "") + " Release “" + escapeHtml(OV.release.label) +
    "”, ingested " + fmtStamp(OV.release.ingested_at) + ".";
}

function growthConfig() {
  const st = urlState();
  const latest = latestIso();
  const keep = rangeFilter(st.range, latest);
  const real = LEVELS[HEAD.real];
  const quarters = Object.keys(real).sort().filter(keep);
  if (st.measure === "level") {
    return {
      kind: "line",
      cfg: {
        series: [
          { name: "Real GDP (chained 2020 prices)", slot: 1,
            points: quarters.map(q => [q, tn(real[q])]) },
          { name: "Nominal GDP", slot: 2,
            points: quarters.map(q => [q, tn(LEVELS[HEAD.nominal][q])]) },
        ],
        unit: "¥tn", unitSuffix: "¥tn", dp: 1, yAxisName: "¥tn, annual rate",
        showPoints: true, trust: "official",
        sourceLine: (OV.credit_line || "") + " Seasonally adjusted annual rates, ¥ trillion.",
      },
      label: "level, ¥tn", trust: "official",
    };
  }
  const rate = st.measure === "ann" ? growth(real, 1, true)
             : st.measure === "qoq" ? growth(real, 1, false) : growth(real, 4, false);
  const name = { ann: "Real GDP growth, annualized", qoq: "Real GDP growth, quarter on quarter",
                 yoy: "Real GDP growth, year on year" }[st.measure];
  return {
    kind: "stack",
    cfg: {
      series: [{ name: name, slot: 1, points: quarters.map(q => [q, rate[q]]) }],
      unit: "%", yAxisName: "%", trust: "derived",
      sourceLine: (OV.credit_line || "") + " Growth calculated from published levels.",
    },
    label: { ann: "annualized %", qoq: "quarter on quarter %", yoy: "year on year %" }[st.measure],
    trust: "derived",
  };
}

function renderGrowth() {
  const st = urlState();
  const g = growthConfig();
  const el = document.getElementById("growth-chart");
  el.innerHTML = "";
  if (growthChart) growthChart.dispose();
  growthChart = obsChart(el, g.kind, g.cfg);

  const latest = latestIso();
  document.getElementById("growth-note").textContent =
    g.label + " · " + (st.range === "max" ? "since 1994" : "last " + st.range + " years") +
    " · through " + qLabel(latest);
  document.getElementById("growth-source").innerHTML = sourceLine(g.trust) +
    (g.trust === "derived" ? " Growth rates are calculated on this page; the formula is under Show calculation." : "");
  document.getElementById("growth-calc").innerHTML =
    "<summary>Show calculation</summary><div class=\"calc-body\">" +
    (st.measure === "level"
      ? "Levels are published values, in ¥ billion at seasonally adjusted annual rates, " +
        "shown in ¥ trillion (÷1,000, exact). Real GDP is at chained 2020 prices."
      : "<code>" + escapeHtml(CALC[st.measure]) + "</code><br>" +
        "From the published seasonally adjusted real levels. The Cabinet Office computes its " +
        "own rate before rounding the levels, so the two can differ by about a tenth of a point.") +
    "</div>";

  document.getElementById("growth-png").onclick = () =>
    growthChart.exportPNG("japan-gdp-" + st.measure + ".png");
  document.getElementById("growth-csv").onclick = () =>
    growthChart.exportCSV("japan-gdp-" + st.measure + ".csv", [
      "Japan Data Observatory — quarterly GDP, " + g.label,
      "Trust: " + (g.trust === "official" ? "official statistics as published"
                   : "calculated from official levels — " + CALC[st.measure]),
      "Source: " + (OV.credit_line || ""),
      "Release: " + OV.release.label + " (sha256 " + OV.release.sha256 + ")",
      "Permalink: " + location.href,
    ]);
}

/* ---------- contributions ---------- */

function contribConfig() {
  const st = urlState();
  const latest = latestIso();
  const lag = st.cbasis === "yoy" ? 4 : 1;
  const keep = rangeFilter(st.crange, latest);
  const real = LEVELS[HEAD.real];
  const quarters = Object.keys(real).sort().filter(keep);
  const gdpGrowth = growth(real, lag, false);

  const contrib = q => code => {
    const cur = COMPS[code] ? COMPS[code][q] : undefined;
    const prev = COMPS[code] ? COMPS[code][quartersAgo(q, lag)] : undefined;
    const base = real[quartersAgo(q, lag)];
    if (cur === null || cur === undefined || prev === null || prev === undefined || !base) return null;
    return (cur - prev) / base * 100;
  };
  const series = GROUPS.filter(g => g.codes.length).map(g => ({
    name: g.label, slot: g.slot,
    points: quarters.map(q => {
      const parts = g.codes.map(contrib(q));
      return [q, parts.some(x => x === null) ? null : parts.reduce((a, b) => a + b, 0)];
    }),
  }));
  // The residual closes the identity: what the bars miss of the line is the
  // chain-linking gap plus rounding, shown as its own bar, never hidden.
  const residual = { name: GROUPS[5].label, slot: GROUPS[5].slot,
    points: quarters.map((q, i) => {
      const g = gdpGrowth[q];
      const parts = series.map(s => s.points[i][1]);
      if (g === null || parts.some(x => x === null)) return [q, null];
      return [q, g - parts.reduce((a, b) => a + b, 0)];
    }) };
  return {
    series: series.concat([residual]),
    line: { name: "GDP growth", points: quarters.map(q => [q, gdpGrowth[q]]) },
    unit: "pp",
    yAxisName: "pp (line: %)",
    // Seven legend entries: below the plot at anything under a wide desktop.
    legendFloor: 1300,
    trust: "derived",
    sourceLine: (OV.credit_line || "") + " Contributions calculated from published levels.",
  };
}

async function renderContrib() {
  await loadComponents();
  const st = urlState();
  const cfg = contribConfig();
  const el = document.getElementById("contrib-chart");
  el.innerHTML = "";
  if (contribChart) contribChart.dispose();
  contribChart = obsChart(el, "stack", cfg);

  document.getElementById("contrib-note").textContent =
    (st.cbasis === "yoy" ? "year on year" : "quarter on quarter") + " · last " + st.crange +
    " years · through " + qLabel(latestIso());
  document.getElementById("contrib-source").innerHTML = sourceLine("derived") +
    " Every bar is calculated on this page from the published real levels.";
  document.getElementById("contrib-calc").innerHTML =
    "<summary>Show calculation</summary><div class=\"calc-body\">" +
    "<code>" + escapeHtml(st.cbasis === "yoy" ? CALC.contribution_yoy : CALC.contribution) + "</code><br>" +
    "<code>" + escapeHtml(CALC.residual) + "</code><br>" +
    "Groups: consumption is private final consumption; private investment is housing plus " +
    "business investment; inventories are private plus public stock-building; government is " +
    "consumption plus public investment; the line is real GDP growth in %. " +
    "In chained-price accounts the components do not add exactly to GDP, so the residual " +
    "bar carries the Cabinet Office's published chain-linking gap together with rounding — " +
    "it is bundled and shown, never dropped.</div>";

  document.getElementById("contrib-png").onclick = () =>
    contribChart.exportPNG("japan-gdp-contributions-" + st.cbasis + ".png");
  document.getElementById("contrib-csv").onclick = () =>
    contribChart.exportCSV("japan-gdp-contributions-" + st.cbasis + ".csv", [
      "Japan Data Observatory — contributions to real GDP growth, " +
        (st.cbasis === "yoy" ? "year on year" : "quarter on quarter") + " (percentage points)",
      "Trust: calculated from official levels — " +
        (st.cbasis === "yoy" ? CALC.contribution_yoy : CALC.contribution),
      "Residual: " + CALC.residual,
      "Source: " + (OV.credit_line || ""),
      "Release: " + OV.release.label + " (sha256 " + OV.release.sha256 + ")",
      "Permalink: " + location.href,
    ]);
}

/* ---------- component table ---------- */

function pctOf(delta, latest) {
  if (delta === null || delta === undefined || latest === null || latest === undefined) return null;
  const prev = latest - delta;
  return prev > 0 ? delta / prev * 100 : null;
}

// Lines that are themselves changes or balances — stock-building, net
// exports, the chain-linking gap, net income — sit around zero, and a
// percentage change of one is arithmetic noise. They are shown as levels
// only, never as growth rates.
const NO_RATE = new Set(["private_inventories", "public_inventories", "chain_discrepancy",
                         "net_exports", "trading_gains", "net_income_from_abroad"]);

async function renderSeriesTable() {
  if (!SERIES) SERIES = await getJSON(API + "/series");
  const st = urlState();
  const deflator = st.basis === "deflator_sa";
  const rows = SERIES.series.filter(s => s.code.endsWith("." + st.basis));
  const refLines = new Set((OV.reference_lines || []));
  const cols = [
    { key: "name", label: "Line" },
    { key: "latest", label: deflator ? "Latest (2020 = 100)" : "Latest ¥tn", num: true },
    { key: "qoq", label: "QoQ %", num: true },
    { key: "ann", label: "Annualized %", num: true },
    { key: "yoy", label: "YoY %", num: true },
  ];
  const body = rows.map(s => {
    const concept = s.code.split(".")[0];
    const isRef = refLines.has(concept);
    const noRate = NO_RATE.has(concept);
    const qoq = noRate ? null : pctOf(s.delta_1m, s.latest);
    const ann = qoq === null ? null : (Math.pow(1 + qoq / 100, 4) - 1) * 100;
    const yoy = noRate ? null : pctOf(s.delta_12m, s.latest);
    const name = s.name_en.split(" — ")[0];
    return "<tr" + (isRef ? ' class="muted"' : "") + ">" +
      "<td>" + escapeHtml(name) + (isRef ? ' <span class="muted">· reference</span>' : "") + "</td>" +
      '<td class="num">' + (deflator ? fmtNum(s.latest, 1) : fmtNum(tn(s.latest), 1)) + "</td>" +
      '<td class="num">' + (qoq === null ? MISSING : fmtSigned(qoq, 1, "%")) + "</td>" +
      '<td class="num">' + (ann === null ? MISSING : fmtSigned(ann, 1, "%")) + "</td>" +
      '<td class="num">' + (yoy === null ? MISSING : fmtSigned(yoy, 1, "%")) + "</td>" +
      "</tr>";
  }).join("");
  const wrap = document.getElementById("series-table");
  wrap.innerHTML = '<table class="data tbl-series"><thead><tr>' +
    cols.map(c => '<th' + (c.num ? ' class="num"' : "") + '>' + c.label + "</th>").join("") +
    "</tr></thead><tbody>" + body + "</tbody></table>";
  enhanceTable(wrap, { placeholder: "Filter lines…" });

  document.getElementById("series-note").textContent =
    rows.length + " lines · " + { real_sa: "real, chained 2020 prices", nominal_sa: "nominal",
                                  deflator_sa: "deflator, 2020 = 100" }[st.basis] +
    " · " + qLabel(latestIso());
  document.getElementById("series-foot").textContent =
    "Levels are seasonally adjusted annual rates in ¥ billion as published, shown in ¥ " +
    "trillion (÷1,000, exact). Stock-building, net exports, the chain-linking gap and net " +
    "income are changes or balances that sit around zero, so no growth rate is shown for " +
    "them (" + MISSING + "); the same mark appears wherever a previous value is missing. " +
    "Reference lines are published aggregates, not components of GDP.";
  document.getElementById("series-calc").innerHTML =
    "<summary>Show calculation</summary><div class=\"calc-body\">" +
    "<code>" + escapeHtml(CALC.qoq) + "</code><br><code>" + escapeHtml(CALC.ann) +
    "</code><br><code>" + escapeHtml(CALC.yoy) + "</code><br>" +
    "From the published levels of release “" + escapeHtml(OV.release.label) + "”.</div>";

  document.getElementById("series-csv").onclick = () => {
    const lines = ["# Japan Data Observatory — quarterly GDP components, " + st.basis +
                     ", " + qLabel(latestIso()),
                   "# Source: " + (OV.credit_line || ""),
                   "# Release: " + OV.release.label + " (sha256 " + OV.release.sha256 + ")",
                   "# Levels in " + (deflator ? "index points (2020 = 100)" : "¥ billion, as published") +
                     "; qoq/ann/yoy calculated: " + CALC.qoq + "; " + CALC.ann + "; " + CALC.yoy,
                   "code,line,latest,qoq_pct,annualized_pct,yoy_pct"];
    rows.forEach(s => {
      const noRate = NO_RATE.has(s.code.split(".")[0]);
      const qoq = noRate ? null : pctOf(s.delta_1m, s.latest);
      const ann = qoq === null ? "" : (Math.pow(1 + qoq / 100, 4) - 1) * 100;
      const yoy = noRate ? null : pctOf(s.delta_12m, s.latest);
      lines.push([s.code, '"' + s.name_en.split(" — ")[0].replace(/"/g, '""') + '"',
                  s.latest, qoq === null ? "" : qoq, ann, yoy === null ? "" : yoy].join(","));
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
    a.download = "japan-gdp-components-" + st.basis + ".csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
}

/* ---------- provenance ---------- */

/* What real-time history exists, read from /releases rather than asserted:
   a page that claimed a vintage range while the store held another would be
   the worst kind of wrong on this platform. */
async function vintageNote() {
  let releases;
  try {
    releases = (await getJSON(API + "/releases")).releases || [];
  } catch (err) {
    return "";
  }
  if (releases.length < 2) return "";
  const at = releases.map(r => r.known_at).filter(Boolean).sort();
  const archived = releases.filter(r => r.known_at_basis === "agency publication");
  const ours = releases.length - archived.length;
  return " <b>" + releases.length + " vintages</b> are on file, from " +
    escapeHtml(at[0].slice(0, 10)) + " to " + escapeHtml(at[at.length - 1].slice(0, 10)) +
    ": " + archived.length + " estimates the Cabinet Office published, carrying its own " +
    "publication dates, and " + ours + " captured by this platform since it began ingesting " +
    "this dataset. Add <code>?as_of=YYYY-MM-DD</code> to any API call to read the numbers as " +
    "they stood on that morning. Levels are not comparable across vintages — the price base " +
    "and the SNA vintage change — so a difference between two of them can be a rebasing " +
    "rather than a revision; the Methodology page sets out which is which.";
}

async function renderProvenance() {
  const rel = OV.release;
  const rows = [
    ["Source", rel.source_name],
    ["Release", rel.label],
    ["Reference period", qLabelLong(rel.latest_period) + " (newest quarter)"],
    ["Ingested", fmtStamp(rel.ingested_at)],
    ["Artifact sha256", rel.sha256.slice(0, 24) + "…"],
  ];
  document.getElementById("prov-card").innerHTML =
    '<div class="prov-card"><div class="prov-card-head">' +
      '<div class="prov-card-title">Data Source</div>' +
      '<div class="prov-card-id">' + escapeHtml(rel.source_id) + "</div></div>" +
    rows.map(r => '<div class="prov-row"><span class="prov-label">' + escapeHtml(r[0]) +
      '</span><span class="prov-value">' + escapeHtml(String(r[1])) + "</span></div>").join("") +
    '<p class="prov-sub">' + trustBadge("official") +
    " Levels are the Cabinet Office's own, stored and served unchanged. The same three tables " +
    "are overwritten at every release, so each revision is kept as a new vintage." +
    (await vintageNote()) + "</p></div>";
}

/* ---------- wiring ---------- */

function wireSeg(id, attr, current, onPick) {
  const root = document.getElementById(id);
  if (!root) return;
  root.querySelectorAll("button").forEach(b => {
    b.setAttribute("aria-pressed", String(b.getAttribute(attr) === current));
    b.addEventListener("click", () => {
      root.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
      onPick(b.getAttribute(attr));
    });
  });
}

function sectionError(id, what, err) {
  document.getElementById(id).innerHTML =
    '<div class="state-error">' + what + " failed to load." +
    "<details><summary>See details</summary><pre>" + escapeHtml(String(err)) + "</pre></details></div>";
}

function wire() {
  const st = urlState();
  wireSeg("measure-seg", "data-measure", st.measure, v => { setUrlState({ measure: v }); renderGrowth(); });
  wireSeg("range-seg", "data-range", st.range, v => { setUrlState({ range: v }); renderGrowth(); });
  wireSeg("cbasis-seg", "data-cbasis", st.cbasis, v => {
    setUrlState({ cbasis: v }); renderContrib().catch(e => sectionError("contrib-chart", "Contributions", e)); });
  wireSeg("crange-seg", "data-range", st.crange, v => {
    setUrlState({ crange: v }); renderContrib().catch(e => sectionError("contrib-chart", "Contributions", e)); });
  wireSeg("basis-seg", "data-basis", st.basis, v => {
    setUrlState({ basis: v }); renderSeriesTable().catch(e => sectionError("series-table", "The table", e)); });
}

async function init() {
  initThemeToggle(() => {
    if (growthChart) renderGrowth();
    if (contribChart) renderContrib();
  });
  try {
    OV = await getJSON(API + "/overview");
    await loadLevels();
  } catch (err) {
    document.getElementById("tiles").innerHTML =
      '<div class="state-error" style="grid-column:1/-1">This page failed to load. ' +
      "The data service may not be running." +
      "<details><summary>See details</summary><pre>" + escapeHtml(String(err)) + "</pre></details></div>";
    return;
  }
  renderHead();
  renderStale();
  renderTiles();
  renderProvenance().catch(() => {});
  wire();
  renderGrowth();
  renderContrib().catch(e => sectionError("contrib-chart", "Contributions", e));
  renderSeriesTable().catch(e => sectionError("series-table", "The table", e));
}

init();
