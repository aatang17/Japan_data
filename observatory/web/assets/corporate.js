/* Corporate finance. The question this screen answers:
   "Are Japanese companies' profits and investment growing, and for whom?"
   — the year-on-year tiles for the chosen industry and size lead; the
   margin-by-size chart answers the second half.

   Amounts arrive exactly as the Ministry of Finance publishes them, in
   ¥ million and not seasonally adjusted; the page shows ¥ billion (÷1,000,
   exact) and reads every flow year on year. Every rate and margin here is
   arithmetic done on this page, and each one states its formula. */
"use strict";

const DATASET = "corporate-finance-jp";
const API = "/api/v1/" + DATASET;

let OV = null;          // /overview payload: release, industries, sizes, items
let SERIES = null;      // /series payload: every series' latest reading
let growthChart = null;
let marginChart = null;
const OBS = {};         // cache of /observations payloads by URL

// Formulas, verbatim from the dataset card so the two never drift.
const CALC = {
  yoy: "(value[t] / value[t−12 months] − 1) × 100, from published values.",
  margin: "margin % = ordinary profit ÷ sales × 100",
  ttm: "ttm = sum of the four most recent published quarters, flows only",
};

/* ---------- url state ---------- */

function industries() { return OV.industries || []; }
function sizes() { return OV.sizes || []; }

function urlState() {
  const p = new URLSearchParams(location.search);
  const ind = p.get("industry"), size = p.get("size");
  return {
    industry: industries().some(i => i.code === ind) ? ind : "all",
    size: sizes().some(s => s.code === size) ? size : "all",
    range: p.get("range") || "10",
    mrange: p.get("mrange") || "20",
  };
}

function setUrlState(next) {
  const s = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (s.industry !== "all") p.set("industry", s.industry);
  if (s.size !== "all") p.set("size", s.size);
  if (s.range !== "10") p.set("range", s.range);
  if (s.mrange !== "20") p.set("mrange", s.mrange);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

/* ---------- periods and units ---------- */

function qLabel(iso) {
  return iso.slice(0, 4) + " Q" + ((Number(iso.slice(5, 7)) - 1) / 3 + 1);
}
function qLabelLong(iso) {
  const q = (Number(iso.slice(5, 7)) - 1) / 3 + 1;
  return ["January–March", "April–June", "July–September", "October–December"][q - 1] +
    " " + iso.slice(0, 4);
}
function quartersAgo(iso, n) {
  let y = Number(iso.slice(0, 4)), m = Number(iso.slice(5, 7)) - 3 * n;
  while (m <= 0) { y -= 1; m += 12; }
  return y + "-" + String(m).padStart(2, "0") + "-01";
}
function bn(v) { return v === null || v === undefined ? null : v / 1000; }   // ¥mn -> ¥bn, exact
function code(item, ind, size) { return item + "." + ind + "." + size; }
function industryLabel(c) { const i = industries().find(x => x.code === c); return i ? i.label : c; }
function sizeLabel(c) { const s = sizes().find(x => x.code === c); return s ? s.label : c; }

/* ---------- loading ---------- */

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " " + r.status + " " + (await r.text()).slice(0, 200));
  return r.json();
}

async function observations(codes, measure) {
  const url = API + "/observations?series=" + codes.join(",") + "&measure=" + measure;
  if (!OBS[url]) OBS[url] = await getJSON(url);
  return OBS[url];
}

function toMap(payload) {
  const out = {};
  payload.series.forEach(s => {
    out[s.code] = {};
    s.points.forEach(p => { out[s.code][p[0].slice(0, 10)] = p[1]; });
  });
  return out;
}

/* ---------- head, tiles ---------- */

function latestIso() { return OV.release.latest_period; }

function tileCell(label, value, delta, unit, title) {
  let html = MISSING, dir = "flat";
  if (delta !== null && delta !== undefined) {
    const dp = unit === "pp" ? 1 : 1;
    const rounded = Number(delta.toFixed(dp));
    dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
    const arrow = rounded === 0 ? ""
      : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
        '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
    html = arrow + fmtNum(Math.abs(delta), dp) + (unit === "%" ? "%" : " " + unit);
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
    "What Japanese companies with capital of ¥10 million or more sold, earned, invested and " +
    "held in " + qLabelLong(latest) + ", by industry and by size, from the Ministry of " +
    "Finance's quarterly survey — every quarter back to 1954.";
  if (OV.credit_line) document.getElementById("credit-line").textContent = OV.credit_line;
}

function renderStale() {
  const el = document.getElementById("stale-banner");
  if (!OV.stale) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
    "ingested quarter is " + qLabelLong(OV.release.latest_period) + ", ingested " +
    fmtStamp(OV.release.ingested_at) + ". The Ministry publishes each quarter about two " +
    "months after it ends — if this persists, run the ingestion.</div>";
}

/* Year on year from levels. A base that is zero or negative gives no
   meaningful percentage, so that quarter is null — a gap, never a number. */
function yoyOf(m, iso) {
  const cur = m[iso], prev = m[quartersAgo(iso, 4)];
  if (cur === null || cur === undefined || prev === null || prev === undefined || !(prev > 0)) return null;
  return (cur / prev - 1) * 100;
}

async function renderTiles() {
  const st = urlState();
  const latest = latestIso();
  const codes = ["sales", "ordinary_profit", "capex", "cash"].map(i => code(i, st.industry, st.size));
  const levels = toMap(await observations(codes, "index"));
  const L = k => levels[code(k, st.industry, st.size)] || {};
  const sales = L("sales"), profit = L("ordinary_profit"), capex = L("capex"), cash = L("cash");
  const margin = iso => (sales[iso] && profit[iso] !== undefined && profit[iso] !== null)
    ? profit[iso] / sales[iso] * 100 : null;
  const yearAgo = quartersAgo(latest, 4);
  const pp = (a, b) => (a === null || b === null || a === undefined || b === undefined) ? null : a - b;

  document.getElementById("tiles").innerHTML =
    tileCell("Ordinary Profit", fmtNum(bn(profit[latest]), 0) + '<span class="unit">¥bn</span>',
      yoyOf(profit, latest), "%",
      qLabel(latest) + ", ¥ billion; change on " + qLabel(yearAgo)) +
    tileCell("Sales", fmtNum(bn(sales[latest]), 0) + '<span class="unit">¥bn</span>',
      yoyOf(sales, latest), "%",
      qLabel(latest) + ", ¥ billion; change on " + qLabel(yearAgo)) +
    tileCell("Capital Investment", fmtNum(bn(capex[latest]), 0) + '<span class="unit">¥bn</span>',
      yoyOf(capex, latest), "%",
      "New fixed assets including software, " + qLabel(latest) + "; change on " + qLabel(yearAgo)) +
    tileCell("Profit Margin", fmtRate(margin(latest), 1),
      pp(margin(latest), margin(yearAgo)), "pp",
      CALC.margin + "; change on " + qLabel(yearAgo));

  document.getElementById("strip-foot").textContent =
    industryLabel(st.industry) + " · " + sizeLabel(st.size).toLowerCase() + " · changes are " +
    qLabel(latest) + " on " + qLabel(yearAgo) + " — the survey is not seasonally adjusted, so " +
    "a year earlier is the only fair comparison. Amounts are official statistics in ¥ million, " +
    "shown in ¥ billion (÷1,000, exact).";
  const calc = document.getElementById("strip-calc");
  calc.style.display = "";
  calc.innerHTML = "<summary>Show calculation</summary><div class=\"calc-body\">" +
    "<code>" + escapeHtml(CALC.yoy) + "</code><br><code>" + escapeHtml(CALC.margin) + "</code><br>" +
    "Inputs: official amounts from release “" + escapeHtml(OV.release.label) + "” (sha256 " +
    OV.release.sha256.slice(0, 12) + "…). A quarter is dated by its first month.</div>";
}

/* ---------- year-on-year chart ---------- */

function rangeFilter(range, latest) {
  if (range === "max") return () => true;
  const from = quartersAgo(latest, Number(range) * 4 - 1);
  return iso => iso >= from;
}

function sourceLine(trust, extra) {
  return (TRUST_LABELS[trust] ? trustBadge(trust) + " " : "") +
    escapeHtml(OV.credit_line || "") + " Release “" + escapeHtml(OV.release.label) +
    "”, ingested " + fmtStamp(OV.release.ingested_at) + "." + (extra ? " " + extra : "");
}

async function renderGrowth() {
  const st = urlState();
  const latest = latestIso();
  const codes = ["sales", "ordinary_profit", "capex"].map(i => code(i, st.industry, st.size));
  // Year on year is computed here from the published levels rather than
  // asked of the API: the API refuses a percentage change on any flow series
  // that has ever crossed zero, and all-industry ordinary profit did, once,
  // decades ago. The same rule is applied quarter by quarter instead — a
  // quarter whose base is zero or negative is a gap, never a number.
  const levels = toMap(await observations(codes, "index"));
  const keep = rangeFilter(st.range, latest);
  const names = { sales: "Sales", ordinary_profit: "Ordinary profit", capex: "Capital investment" };
  const series = codes.map((c, i) => {
    const m = levels[c] || {};
    const quarters = Object.keys(m).sort().filter(keep);
    return { name: names[c.split(".")[0]], slot: i + 1,
             points: quarters.map(q => [q, yoyOf(m, q)]) };
  });
  const cfg = {
    series: series, unit: "%", dp: 1, yAxisName: "% change on a year earlier",
    showPoints: true, trust: "derived",
    sourceLine: (OV.credit_line || "") + " " + industryLabel(st.industry) + ", " +
      sizeLabel(st.size).toLowerCase() + ". Year on year, calculated from published amounts.",
  };
  const el = document.getElementById("growth-chart");
  el.innerHTML = "";
  if (growthChart) growthChart.dispose();
  growthChart = obsChart(el, "line", cfg);

  document.getElementById("growth-note").textContent =
    industryLabel(st.industry) + " · " + sizeLabel(st.size).toLowerCase() + " · year on year · " +
    (st.range === "max" ? "since 1955" : "last " + st.range + " years");
  document.getElementById("growth-source").innerHTML = sourceLine("derived",
    "Rates are calculated from the published amounts; the formula is under Show calculation.");
  document.getElementById("growth-calc").innerHTML =
    "<summary>Show calculation</summary><div class=\"calc-body\"><code>" + escapeHtml(CALC.yoy) +
    "</code><br>Each quarter against the same quarter a year earlier, from published ¥ million " +
    "amounts. Ordinary profit can be negative in a bad year, and a percent change across a " +
    "sign change is meaningless — such quarters are left as gaps.</div>";

  document.getElementById("growth-png").onclick = () =>
    growthChart.exportPNG("japan-corporate-" + st.industry + "-" + st.size + "-yoy.png");
  document.getElementById("growth-csv").onclick = () =>
    growthChart.exportCSV("japan-corporate-" + st.industry + "-" + st.size + "-yoy.csv", [
      "Plover Analytics — corporate sales, ordinary profit and capital investment, " +
        "year on year (%) · " + industryLabel(st.industry) + ", " + sizeLabel(st.size),
      "Trust: calculated from official amounts — " + CALC.yoy,
      "Source: " + (OV.credit_line || ""),
      "Release: " + OV.release.label + " (sha256 " + OV.release.sha256 + ")",
      "Permalink: " + location.href,
    ]);
}

/* ---------- margin by size ---------- */

async function renderMargin() {
  const st = urlState();
  const latest = latestIso();
  const keep = rangeFilter(st.mrange, latest);
  // Two calls, one per line: eight of these codes run past the API's
  // 200-character series parameter for the longer industry keys.
  const sizeCodes = sizes().map(s => s.code);
  const [salesPayload, profitPayload] = await Promise.all([
    observations(sizeCodes.map(sz => code("sales", st.industry, sz)), "index"),
    observations(sizeCodes.map(sz => code("ordinary_profit", st.industry, sz)), "index"),
  ]);
  const levels = Object.assign(toMap(salesPayload), toMap(profitPayload));
  const series = sizes().map((sz, i) => {
    const sales = levels[code("sales", st.industry, sz.code)] || {};
    const profit = levels[code("ordinary_profit", st.industry, sz.code)] || {};
    const quarters = Object.keys(sales).sort().filter(keep);
    return { name: sz.label, slot: i + 1,
      points: quarters.map(q => [q, sales[q] && profit[q] !== undefined && profit[q] !== null
                                    ? profit[q] / sales[q] * 100 : null]) };
  }).filter(s => s.points.length);
  const cfg = {
    series: series, unit: "%", dp: 2, yAxisName: "ordinary profit ÷ sales, %",
    showPoints: false, trust: "derived",
    sourceLine: (OV.credit_line || "") + " " + industryLabel(st.industry) +
      ". Margin calculated from published amounts.",
  };
  const el = document.getElementById("margin-chart");
  el.innerHTML = "";
  if (marginChart) marginChart.dispose();
  marginChart = obsChart(el, "line", cfg);

  document.getElementById("margin-note").textContent =
    industryLabel(st.industry) + " · " + (st.mrange === "max" ? "since 1954" : "last " + st.mrange + " years");
  document.getElementById("margin-source").innerHTML = sourceLine("derived",
    "The margin is calculated on this page from published sales and ordinary profit.");
  document.getElementById("margin-calc").innerHTML =
    "<summary>Show calculation</summary><div class=\"calc-body\"><code>" + escapeHtml(CALC.margin) +
    "</code><br>Quarterly, not seasonally adjusted, so each line has a seasonal saw-tooth: read " +
    "the same quarter across years, or the level of one line against another. Capital classes " +
    "are the survey's own: ¥10 million to under ¥100 million, ¥100 million to under ¥1 billion, " +
    "and ¥1 billion and over.</div>";

  document.getElementById("margin-png").onclick = () =>
    marginChart.exportPNG("japan-corporate-" + st.industry + "-margin-by-size.png");
  document.getElementById("margin-csv").onclick = () =>
    marginChart.exportCSV("japan-corporate-" + st.industry + "-margin-by-size.csv", [
      "Plover Analytics — ordinary profit margin by capital size (%) · " + industryLabel(st.industry),
      "Trust: calculated from official amounts — " + CALC.margin,
      "Source: " + (OV.credit_line || ""),
      "Release: " + OV.release.label + " (sha256 " + OV.release.sha256 + ")",
      "Permalink: " + location.href,
    ]);
}

/* ---------- industry table ---------- */

function pctOf(delta, latest) {
  if (delta === null || delta === undefined || latest === null || latest === undefined) return null;
  const prev = latest - delta;
  return prev > 0 ? delta / prev * 100 : null;
}

const TABLE_COLS = [
  { key: "name", label: "Industry", type: "text" },
  { key: "sales", label: "Sales ¥bn", num: true },
  { key: "sales_yoy", label: "Sales YoY %", num: true },
  { key: "profit", label: "Ordinary profit ¥bn", num: true },
  { key: "profit_yoy", label: "Profit YoY %", num: true },
  { key: "margin", label: "Margin %", num: true },
  { key: "capex", label: "Capex ¥bn", num: true },
  { key: "capex_yoy", label: "Capex YoY %", num: true },
  { key: "companies", label: "Companies", num: true },
];

function tableRows() {
  const st = urlState();
  const byCode = {};
  SERIES.series.forEach(s => { byCode[s.code] = s; });
  const get = (item, ind) => byCode[code(item, ind, st.size)] || {};
  return industries().map(ind => {
    const sales = get("sales", ind.code), profit = get("ordinary_profit", ind.code),
          capex = get("capex", ind.code), companies = get("companies", ind.code);
    const aggregate = ["all", "manufacturing", "non_manufacturing"].indexOf(ind.code) >= 0;
    return {
      code: ind.code, name: ind.label, aggregate: aggregate,
      sales: bn(sales.latest), sales_yoy: pctOf(sales.delta_12m, sales.latest),
      profit: bn(profit.latest), profit_yoy: pctOf(profit.delta_12m, profit.latest),
      margin: (sales.latest && profit.latest !== undefined && profit.latest !== null)
        ? profit.latest / sales.latest * 100 : null,
      capex: bn(capex.latest), capex_yoy: pctOf(capex.delta_12m, capex.latest),
      companies: companies.latest === undefined ? null : companies.latest,
      as_of: sales.as_of,
    };
  });
}

function cell(row, key) {
  const v = row[key];
  if (key === "name") {
    return "<td>" + escapeHtml(row.name) + (row.aggregate ? ' <span class="muted">· total</span>' : "") + "</td>";
  }
  if (key.endsWith("_yoy")) return '<td class="num">' + (v === null ? MISSING : fmtSigned(v, 1, "%")) + "</td>";
  if (key === "margin") return '<td class="num">' + fmtRate(v, 1) + "</td>";
  return '<td class="num">' + fmtNum(v, 0) + "</td>";
}

let tableSort = { key: "sales", dir: "desc" };

async function renderTable() {
  if (!SERIES) SERIES = await getJSON(API + "/series");
  const st = urlState();
  const rows = sortRows(tableRows(), tableSort.key, tableSort.dir);
  const wrap = document.getElementById("ind-table");
  wrap.innerHTML = '<table class="data tbl-series"><thead>' +
    sortableHead(TABLE_COLS, tableSort.key, tableSort.dir) + "</thead><tbody>" +
    rows.map(r => '<tr class="clickable' + (r.aggregate ? " muted" : "") + '" data-code="' + r.code + '">' +
      TABLE_COLS.map(c => cell(r, c.key)).join("") + "</tr>").join("") +
    "</tbody></table>";
  wireSort(wrap, tableSort.key, tableSort.dir, (key, dir) => { tableSort = { key, dir }; renderTable(); });
  wrap.querySelectorAll("tr.clickable").forEach(tr => {
    tr.addEventListener("click", () => selectIndustry(tr.getAttribute("data-code")));
  });
  enhanceTable(wrap, { sort: false, placeholder: "Filter industries…" });

  document.getElementById("table-note").textContent =
    rows.length + " industries · " + sizeLabel(st.size).toLowerCase() + " · " + qLabel(latestIso());
  document.getElementById("table-foot").textContent =
    "Amounts are ¥ million as published, shown in ¥ billion (÷1,000, exact); companies is the " +
    "Ministry's estimate of the population. YoY is against the same quarter a year earlier. " +
    MISSING + " means the comparison quarter is missing or the base is zero or negative. Click " +
    "a row to put that industry in the charts above.";
  document.getElementById("table-calc").innerHTML =
    "<summary>Show calculation</summary><div class=\"calc-body\"><code>" + escapeHtml(CALC.yoy) +
    "</code><br><code>" + escapeHtml(CALC.margin) + "</code><br>The three total rows are the " +
    "Ministry's own aggregates; the industry rows beneath them sum to manufacturing and " +
    "non-manufacturing only where every industry is listed, and this table lists the major " +
    "ones.</div>";

  document.getElementById("table-csv").onclick = () => {
    const lines = ["# Plover Analytics — corporate finance by industry, " + sizeLabel(st.size) +
                     ", " + qLabel(latestIso()),
                   "# Source: " + (OV.credit_line || ""),
                   "# Release: " + OV.release.label + " (sha256 " + OV.release.sha256 + ")",
                   "# Amounts in ¥ billion (published ¥ million ÷ 1,000); yoy: " + CALC.yoy +
                     "; margin: " + CALC.margin,
                   "industry_code,industry,sales_bn,sales_yoy_pct,ordinary_profit_bn,profit_yoy_pct," +
                     "margin_pct,capex_bn,capex_yoy_pct,companies"];
    rows.forEach(r => lines.push([r.code, '"' + r.name.replace(/"/g, '""') + '"', r.sales, r.sales_yoy,
      r.profit, r.profit_yoy, r.margin, r.capex, r.capex_yoy, r.companies]
      .map(v => v === null || v === undefined ? "" : v).join(",")));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
    a.download = "japan-corporate-finance-" + st.size + ".csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
}

/* ---------- provenance ---------- */

function renderProvenance() {
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
    " Amounts are the Ministry's own, stored and served unchanged in ¥ million. A pinned " +
    "subset of the Ministry's time-series table — 21 lines, 31 industry aggregates, four " +
    "capital classes — not seasonally adjusted. Growth rates and margins on this page are " +
    "calculated from those amounts and show their formula.</p></div>";
}

/* ---------- wiring ---------- */

function selectIndustry(c) {
  if (!industries().some(i => i.code === c)) return;
  setUrlState({ industry: c });
  document.getElementById("industry-select").value = c;
  rerender();
}

function rerender() {
  renderTiles().catch(e => sectionError("tiles", "The summary", e));
  renderGrowth().catch(e => sectionError("growth-chart", "The growth chart", e));
  renderMargin().catch(e => sectionError("margin-chart", "The margin chart", e));
  renderTable().catch(e => sectionError("ind-table", "The table", e));
}

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
  const select = document.getElementById("industry-select");
  select.innerHTML = industries().map(i =>
    '<option value="' + i.code + '">' + escapeHtml(i.label) + "</option>").join("");
  select.value = st.industry;
  select.addEventListener("change", () => { setUrlState({ industry: select.value }); rerender(); });

  const seg = document.getElementById("size-seg");
  seg.innerHTML = sizes().map(s =>
    '<button type="button" data-size="' + s.code + '">' +
    escapeHtml({ all: "All Sizes", large: "¥1bn+", medium: "¥100mn–1bn", small: "¥10–100mn" }[s.code] || s.label) +
    "</button>").join("");
  wireSeg("size-seg", "data-size", st.size, v => { setUrlState({ size: v }); rerender(); });
  wireSeg("range-seg", "data-range", st.range, v => {
    setUrlState({ range: v }); renderGrowth().catch(e => sectionError("growth-chart", "The growth chart", e)); });
  wireSeg("mrange-seg", "data-range", st.mrange, v => {
    setUrlState({ mrange: v }); renderMargin().catch(e => sectionError("margin-chart", "The margin chart", e)); });
}

async function init() {
  initThemeToggle(() => {
    if (growthChart) renderGrowth();
    if (marginChart) renderMargin();
  });
  try {
    OV = await getJSON(API + "/overview");
  } catch (err) {
    document.getElementById("tiles").innerHTML =
      '<div class="state-error" style="grid-column:1/-1">This page failed to load. ' +
      "The data service may not be running." +
      "<details><summary>See details</summary><pre>" + escapeHtml(String(err)) + "</pre></details></div>";
    return;
  }
  renderHead();
  renderStale();
  renderProvenance();
  wire();
  rerender();
}

init();
