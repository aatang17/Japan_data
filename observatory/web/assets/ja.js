/* JA co-operative segment income statement. The question this screen answers:
   "How much of JA's profit comes from banking, and how much does farming
   cost it?"

   One dataset, one grid: the ministry's own income statement for each of the
   five businesses the multi-purpose co-operatives run, by fiscal year since
   2004. Amounts are published values in thousands of yen and are shown as
   released; the change, the share and the group ratio are calculated here and
   carry their formula on the page and in every export. A line a business does
   not publish is "—", never zero. */
"use strict";

const DATASET = "ja-statistics";
const API = "/api/v1/" + DATASET;

/* The five businesses, plus the group total and the overhead that belongs to
   none of them. Slots pin a colour per business across both charts. */
const SEGMENTS = [
  { key: "all", label: "All businesses", slot: 1, group: true },
  { key: "credit", label: "Banking", slot: 2 },
  { key: "kyosai", label: "Mutual insurance", slot: 3 },
  { key: "agri", label: "Farm marketing and supply", slot: 4 },
  { key: "living", label: "Living services and other", slot: 5 },
  { key: "guidance", label: "Farm guidance", slot: 6 },
  { key: "overhead", label: "Common overhead", slot: 6, overhead: true },
];
const EARNING = ["credit", "kyosai", "agri", "living", "guidance"];

/* The income statement, in the order the ministry publishes it. */
const LINES = [
  ["revenue", "Business revenue"],
  ["cost-of-business", "Business costs"],
  ["gross-profit", "Gross business profit"],
  ["opex", "Operating expenses"],
  ["opex.depreciation", "of which depreciation"],
  ["opex.common", "of which common overhead"],
  ["opex.common.depreciation", "of which common overhead, depreciation"],
  ["operating-profit", "Operating profit"],
  ["non-operating-income", "Non-operating income"],
  ["non-operating-income.common", "of which common"],
  ["non-operating-expense", "Non-operating expenses"],
  ["non-operating-expense.common", "of which common"],
  ["ordinary-profit", "Ordinary profit"],
  ["extraordinary-gain", "Extraordinary gains"],
  ["extraordinary-gain.common", "of which common"],
  ["extraordinary-loss", "Extraordinary losses"],
  ["extraordinary-loss.common", "of which common"],
  ["pre-tax-profit", "Pre-tax profit"],
  ["guidance-charge", "Farm-guidance loss charged to this business"],
  ["pre-tax-profit-after-guidance", "Pre-tax profit after the charge"],
];
const INDENTED = {
  "opex.depreciation": 1, "opex.common": 1, "opex.common.depreciation": 2,
  "non-operating-income.common": 1, "non-operating-expense.common": 1,
  "extraordinary-gain.common": 1, "extraordinary-loss.common": 1,
};

const SHARE_CALC =
  "share of group revenue[t] = business revenue[t] ÷ all-businesses revenue[t] " +
  "× 100, from published amounts.";
const CHANGE_CALC =
  "change[t] = value[t] − value[t−1 fiscal year], from published amounts. " +
  "A fiscal year missing either side shows —, never a change of zero.";

/* Thousands of yen as published, read as billions on screen. The conversion is
   exact and is stated wherever a figure appears. */
const BN = 1e6;

function $(id) { return document.getElementById(id); }

const D = { release: null, stale: false, tiles: [], series: {}, years: [],
            published: {} };

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

function code(segment, line) { return "pl." + segment + "." + line; }

/* /observations takes at most eight codes AND caps the whole `series`
   parameter at 200 characters, so a batch has two limits, not one. Chunking
   by count alone is what broke this page in production: eight of these codes
   are over 200 characters together and the API answered 422, not 404. */
const MAX_CODES = 8;
const MAX_SERIES_CHARS = 190;   // 200, less room for a trailing comma

function batchCodes(codes) {
  const batches = [];
  let current = [], length = 0;
  codes.forEach(c => {
    const cost = c.length + (current.length ? 1 : 0);
    if (current.length && (current.length >= MAX_CODES ||
                           length + cost > MAX_SERIES_CHARS)) {
      batches.push(current);
      current = []; length = 0;
    }
    current.push(c);
    length += c.length + (current.length > 1 ? 1 : 0);
  });
  if (current.length) batches.push(current);
  return batches;
}

/* Only codes the release actually carries are requested: an unknown code 404s
   the whole batch, and not every income-statement line applies to every
   business — about 120 of the 140 combinations are published. */
async function loadSeries(codes) {
  const real = codes.filter(c => D.published[c] && !(c in D.series));
  for (const chunk of batchCodes(real)) {
    const payload = await getJSON(API + "/observations?series=" +
      encodeURIComponent(chunk.join(",")));
    payload.series.forEach(s => { D.series[s.code] = s.points; });
  }
  // A combination the ministry does not publish is an empty series, not a
  // failed request: it renders as "—" everywhere, never as a zero.
  codes.forEach(c => { if (!(c in D.series)) D.series[c] = []; });
  return codes.map(c => D.series[c]);
}

function at(seriesCode, period) {
  const pts = D.series[seriesCode] || [];
  for (let i = 0; i < pts.length; i++) if (pts[i][0] === period) return pts[i][1];
  return null;
}

/* "2023-04-01" -> "FY2023" — a fiscal year is dated to the 1 April it begins. */
function fy(period) { return period ? "FY" + period.slice(0, 4) : MISSING; }

/* ---- URL state ---- */

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    view: p.get("view") === "post" ? "post" : "pre",
    range: p.get("range") === "10" ? "10" : "max",
    crange: p.get("crange") === "max" ? "max" : "10",
    segment: p.get("segment") || "credit",
  };
}

function setUrlState(next) {
  const s = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (s.view !== "pre") p.set("view", s.view);
  if (s.range !== "max") p.set("range", s.range);
  if (s.crange !== "10") p.set("crange", s.crange);
  if (s.segment !== "credit") p.set("segment", s.segment);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function cutYears(years, range) {
  return range === "max" ? years : years.slice(-Number(range));
}

/* ---- header, staleness, provenance ---- */

function renderHead() {
  const rel = D.release;
  $("page-asof").textContent = "Data through " + fy(rel.latest_period);
  $("header-asof").textContent = fy(rel.latest_period) + " census";
  const latest = rel.latest_period;
  const group = at(code("all", "pre-tax-profit"), latest);
  const credit = at(code("credit", "pre-tax-profit"), latest);
  const guidance = at(code("guidance", "pre-tax-profit"), latest);
  $("page-sub").innerHTML =
    "In " + fy(latest) + " the co-operatives earned <strong class=\"num\">¥" +
    fmtNum(group / BN, 1) + "bn</strong> before tax across every business. " +
    "Banking alone earned <strong class=\"num\">¥" + fmtNum(credit / BN, 1) +
    "bn</strong>; farm guidance lost <strong class=\"num\">¥" +
    fmtNum(Math.abs(guidance) / BN, 1) + "bn</strong>. " + trustBadge("official");
}

function renderStale() {
  const el = $("stale-banner");
  if (!D.stale) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
    "ingested fiscal year is " + escapeHtml(fy(D.release.latest_period)) +
    ", ingested " + escapeHtml(fmtStamp(D.release.ingested_at)) +
    ". The census is confirmed well over a year after the year it covers — " +
    "if this persists, run the ingestion.</div>";
}

function renderProvenance() {
  const rel = D.release;
  $("prov-card").innerHTML =
    '<div class="prov-card">' +
      '<div class="prov-card-head">' +
        '<div class="prov-card-title">Data Source</div>' +
        '<div class="prov-card-id">' + escapeHtml(rel.source_id || DATASET) + "</div>" +
      "</div>" +
      '<div class="prov-grid">' +
        '<div class="prov-field full">' +
          '<div class="prov-label">Official source</div>' +
          '<div class="prov-value"><a href="' + escapeHtml(rel.source_page || "#") +
            '" rel="noopener">' + escapeHtml(rel.source_name || "") + "</a></div>" +
          '<div class="prov-sub">One release archives the long-run segment table and ' +
            'every later fiscal year’s own table together under a single checksum, ' +
            'retrieved through the e-Stat API.</div>' +
        "</div>" +
        '<div class="prov-field">' +
          '<div class="prov-label">Release</div>' +
          '<div class="prov-value">Data through ' + escapeHtml(fy(rel.latest_period)) +
            "</div>" +
          '<div class="prov-sub">Published ' + escapeHtml(rel.frequency || "annual") + "</div>" +
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

/* ---- stat strip ---- */

function tileCell(label, valueHtml, deltaHtml, dir, title) {
  return '<div class="strip-cell">' +
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' +
      escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + valueHtml + "</div>" +
    '<div class="strip-delta num ' + dir + '">' + deltaHtml + "</div>" +
    "</div>";
}

function bnDelta(delta) {
  if (delta === null || delta === undefined) return { html: MISSING, dir: "flat" };
  const bn = delta / BN;
  const rounded = Number(bn.toFixed(1));
  const dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
  const arrow = rounded === 0 ? ""
    : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
      '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
  return { html: arrow + fmtNum(Math.abs(bn), 1) + " ¥bn", dir: dir };
}

function renderTiles() {
  const latest = D.release.latest_period;
  const prior = String(Number(latest.slice(0, 4)) - 1) + latest.slice(4);
  const cells = SEGMENTS.filter(s => ["all", "credit", "agri", "guidance"].indexOf(s.key) !== -1)
    .map(s => {
      const c = code(s.key, "pre-tax-profit");
      const now = at(c, latest), was = at(c, prior);
      const d = bnDelta(now === null || was === null ? null : now - was);
      return tileCell(
        s.key === "all" ? "Group Pre-Tax" : s.label,
        fmtSigned(now === null ? null : now / BN, 1) + '<span class="unit">¥bn</span>',
        d.html, d.dir,
        s.label + " — pre-tax profit, published as released in thousands of yen " +
        "and shown here in billions.");
    });
  $("tiles").innerHTML = cells.join("");
  $("strip-foot").textContent =
    "Pre-tax profit before the farm-guidance charge is allocated · changes vs " +
    fy(prior) + " · amounts published in thousands of yen and shown in billions, " +
    "an exact conversion";
  $("strip-calc").style.display = "";
  $("strip-calc").innerHTML = "<summary>Show calculation</summary><p>" +
    escapeHtml(CHANGE_CALC) + "</p><p>Amounts are published values, not recomputed. " +
    "¥bn = published thousands of yen ÷ 1,000,000.</p>";
}

/* ---- profit by business ---- */

let segChart = null;

function renderSegments() {
  const st = urlState();
  const line = st.view === "post" ? "pre-tax-profit-after-guidance" : "pre-tax-profit";
  const years = cutYears(D.years, st.range);
  const shown = SEGMENTS.filter(s => !s.overhead);
  const cfg = {
    series: shown.map(s => ({
      name: s.label, slot: s.slot,
      points: years.map(p => {
        const v = at(code(s.key, line), p);
        return [fy(p), v === null ? null : v / BN];
      }),
    })),
    xType: "category",
    unit: "index", unitSuffix: "¥bn", dp: 1,
    yAxisName: "Pre-tax profit, ¥bn", yAxisDp: 0,
    trust: "official", legendFloor: 780,
    sourceLine: "Source: MAFF — Survey of Agricultural Co-operatives (総合農協統計表). " +
      "Data through " + fy(D.release.latest_period) + ".",
  };
  if (segChart) segChart.render(cfg); else segChart = obsChart($("seg-chart"), "line", cfg);

  $("segments-note").textContent = years.length
    ? fy(years[0]) + "–" + fy(years[years.length - 1]) : "";
  $("seg-source").innerHTML = escapeHtml(cfg.sourceLine) + " " + trustBadge("official");
  $("seg-calc").innerHTML = "<summary>Show calculation</summary>" +
    "<p>Published pre-tax profit " +
    (st.view === "post"
      ? "after the farm-guidance loss has been charged to the business. Both this "
      + "line and the charge above it are published by the ministry; neither is "
      + "computed here."
      : "before the farm-guidance loss is charged to the business.") +
    "</p><p>Amounts are published in thousands of yen; ¥bn = thousands ÷ 1,000,000, " +
    "an exact conversion. Common overhead belongs to no single business and is not " +
    "plotted; it is part of the all-businesses line.</p>";
}

/* ---- the farm-guidance charge ---- */

let chargeChart = null;

function renderCharge() {
  const st = urlState();
  const years = cutYears(D.years, st.crange);
  const borne = SEGMENTS.filter(s => ["credit", "kyosai", "agri", "living"].indexOf(s.key) !== -1);
  const cfg = {
    categories: years.map(fy),
    series: borne.map(s => ({
      name: s.label, slot: s.slot,
      points: years.map(p => {
        const v = at(code(s.key, "guidance-charge"), p);
        return v === null ? null : v / BN;
      }),
    })),
    dp: 1, unitSuffix: "¥bn",
    yAxisName: "Farm-guidance loss borne, ¥bn",
    trust: "official", legendFloor: 780,
    sourceLine: "Source: MAFF — Survey of Agricultural Co-operatives (総合農協統計表). " +
      "Data through " + fy(D.release.latest_period) + ".",
  };
  if (chargeChart) chargeChart.render(cfg);
  else chargeChart = obsChart($("charge-chart"), "cols", cfg);

  const latest = D.release.latest_period;
  const total = at(code("guidance", "guidance-charge"), latest);
  $("charge-note").textContent = total === null ? "" :
    "¥" + fmtNum(Math.abs(total) / BN, 1) + "bn allocated in " + fy(latest);
  $("charge-source").innerHTML = escapeHtml(cfg.sourceLine) + " " + trustBadge("official");
  $("charge-calc").innerHTML = "<summary>Show calculation</summary>" +
    "<p>営農指導事業分配賦額 as published: the farm-guidance loss charged to each " +
    "business, a line of the ministry's own statement. Not computed here.</p>" +
    "<p>Amounts are published in thousands of yen; ¥bn = thousands ÷ 1,000,000. " +
    "Farm guidance itself carries the whole allocation as a negative and is not " +
    "shown as a bar — it is the source of the charge, not a bearer of it.</p>";
}

/* ---- income statement table ---- */

function renderStatement() {
  const st = urlState();
  const latest = D.release.latest_period;
  const prior = String(Number(latest.slice(0, 4)) - 1) + latest.slice(4);
  const groupRevenue = at(code("all", "revenue"), latest);

  const head = "<thead><tr>" +
    '<th scope="col">Line</th>' +
    '<th scope="col" class="num">' + fy(latest) + ", ¥bn</th>" +
    '<th scope="col" class="num">' + fy(prior) + ", ¥bn</th>" +
    '<th scope="col" class="num">Change, ¥bn</th>' +
    '<th scope="col" class="num">Share of group revenue</th>' +
    "</tr></thead>";

  const body = LINES.map(([slug, label]) => {
    const c = code(st.segment, slug);
    const now = at(c, latest), was = at(c, prior);
    const change = (now === null || was === null) ? null : now - was;
    // A share only means something for the revenue line: dividing a cost or a
    // profit by group revenue would be a ratio nobody asked for.
    const share = (slug === "revenue" && now !== null && groupRevenue)
      ? (now / groupRevenue) * 100 : null;
    const indent = INDENTED[slug] || 0;
    // Amounts are levels: fmtNum still prints a true minus on a loss, but a
    // leading "+" on every revenue and cost line would be noise. Only the
    // change column is a signed quantity.
    return "<tr>" +
      '<td' + (indent ? ' class="indent-' + indent + '"' : "") + '>' + escapeHtml(label) + "</td>" +
      '<td class="num" data-sort="' + (now ?? "") + '">' +
        fmtNum(now === null ? null : now / BN, 1) + "</td>" +
      '<td class="num" data-sort="' + (was ?? "") + '">' +
        fmtNum(was === null ? null : was / BN, 1) + "</td>" +
      '<td class="num" data-sort="' + (change ?? "") + '">' +
        fmtSigned(change === null ? null : change / BN, 1) + "</td>" +
      '<td class="num" data-sort="' + (share ?? "") + '">' +
        (share === null ? MISSING : fmtRate(share, 1)) + "</td>" +
      "</tr>";
  }).join("");

  $("statement-table").innerHTML =
    '<table class="data" data-no-enhance>' + head + "<tbody>" + body + "</tbody></table>";

  const seg = SEGMENTS.find(s => s.key === st.segment);
  $("statement-note").textContent = seg ? seg.label : "";
  $("statement-foot").textContent =
    "Published amounts in thousands of yen, shown in billions. A line the ministry does not " +
    "publish for this business shows — and is not a zero. The share of group revenue is shown " +
    "only on the revenue line. Release: data through " + fy(latest) + ".";
  $("statement-calc").innerHTML = "<summary>Show calculation</summary><p>" +
    escapeHtml(CHANGE_CALC) + "</p><p>" + escapeHtml(SHARE_CALC) +
    "</p><p>¥bn = published thousands of yen ÷ 1,000,000, an exact conversion.</p>";
}

function statementCSV() {
  const st = urlState();
  const latest = D.release.latest_period;
  const prior = String(Number(latest.slice(0, 4)) - 1) + latest.slice(4);
  const seg = SEGMENTS.find(s => s.key === st.segment);
  const header = [
    "Japan Data Observatory — JA co-operative income statement",
    "Business: " + (seg ? seg.label : st.segment),
    "Source: " + (D.release.source_name || ""),
    "Release: data through " + fy(latest),
    "Retrieved: " + fmtStamp(D.release.retrieved_at) + " · SHA-256 " + (D.release.sha256 || ""),
    "Unit: thousands of yen, exactly as published (not the billions shown on screen)",
    "Trust: amounts are official statistics as published; the change and the share " +
      "are calculated from them",
    CHANGE_CALC,
    SHARE_CALC,
    "An empty cell is a line the ministry does not publish for this business — never zero",
  ].map(l => "# " + l).join("\n");
  const groupRevenue = at(code("all", "revenue"), latest);
  const rows = ["line,label," + latest.slice(0, 4) + "_jpy_1000," +
    prior.slice(0, 4) + "_jpy_1000,change_jpy_1000,share_of_group_revenue_pct"];
  LINES.forEach(([slug, label]) => {
    const c = code(st.segment, slug);
    const now = at(c, latest), was = at(c, prior);
    const change = (now === null || was === null) ? "" : now - was;
    const share = (slug === "revenue" && now !== null && groupRevenue)
      ? (now / groupRevenue) * 100 : "";
    rows.push([slug, '"' + label.replace(/"/g, '""') + '"',
      now ?? "", was ?? "", change, share].join(","));
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([header + "\n" + rows.join("\n") + "\n"],
    { type: "text/csv" }));
  a.download = "ja-income-statement-" + st.segment + "-" + latest.slice(0, 4) + ".csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---- exports ---- */

function exportHeader(extra) {
  return [
    "Japan Data Observatory — JA co-operative segment income statement",
    "Source: " + (D.release.source_name || ""),
    "Release: data through " + fy(D.release.latest_period),
    "Retrieved: " + fmtStamp(D.release.retrieved_at) + " · SHA-256 " + (D.release.sha256 || ""),
    "Fiscal years run April to March and are labelled by the April they begin",
  ].concat(extra || []).concat([
    "An empty cell is a value the ministry did not publish — never zero",
  ]);
}

/* ---- wiring ---- */

function seg(id, attr, key, after) {
  const wrap = $(id);
  wrap.querySelectorAll("button").forEach(b => {
    b.addEventListener("click", () => {
      const next = {};
      next[key] = b.getAttribute(attr);
      setUrlState(next);
      syncSeg(id, attr, key);
      after();
    });
  });
  syncSeg(id, attr, key);
}

function syncSeg(id, attr, key) {
  const cur = String(urlState()[key]);
  $(id).querySelectorAll("button").forEach(b => {
    b.setAttribute("aria-pressed", String(b.getAttribute(attr) === cur));
  });
}

async function boot() {
  initThemeToggle(() => { renderSegments(); renderCharge(); });

  // /series is one request and names every code the release actually carries,
  // which is what keeps the observation requests below from asking for a
  // combination the ministry does not publish.
  const [ov, listing] = await Promise.all([
    getJSON(API + "/overview"),
    getJSON(API + "/series"),
  ]);
  D.release = ov.release;
  D.stale = ov.stale;
  (listing.series || []).forEach(s => { D.published[s.code] = true; });

  // Every series the page can show, loaded once: 20 fiscal years across seven
  // businesses is a small grid, and loading it up front keeps every control
  // instant and every export consistent with what is on screen.
  const codes = [];
  SEGMENTS.forEach(s => LINES.forEach(([slug]) => codes.push(code(s.key, slug))));
  await loadSeries(codes);
  const periods = new Set();
  Object.keys(D.series).forEach(c => (D.series[c] || []).forEach(p => periods.add(p[0])));
  D.years = Array.from(periods).sort();

  const select = $("segment-select");
  select.innerHTML = SEGMENTS.filter(s => !s.group)
    .map(s => '<option value="' + escapeHtml(s.key) + '">' +
      escapeHtml(s.label) + "</option>").join("");
  select.value = urlState().segment;

  renderHead();
  renderStale();
  renderTiles();
  renderSegments();
  renderCharge();
  renderStatement();
  renderProvenance();

  seg("seg-view", "data-view", "view", renderSegments);
  seg("seg-range", "data-range", "range", renderSegments);
  seg("charge-range", "data-crange", "crange", renderCharge);
  select.addEventListener("change", e => {
    setUrlState({ segment: e.target.value });
    renderStatement();
  });

  $("seg-png").addEventListener("click", () =>
    segChart.exportPNG("ja-segment-profit.png"));
  $("seg-csv").addEventListener("click", () =>
    segChart.exportCSV("ja-segment-profit.csv", exportHeader([
      "Unit: ¥ billion (published thousands of yen ÷ 1,000,000, an exact conversion)",
      "Measure: pre-tax profit " + (urlState().view === "post"
        ? "after the farm-guidance loss is charged to the business"
        : "before the farm-guidance loss is charged to the business") +
        ", official statistic as published",
    ])));
  $("charge-png").addEventListener("click", () =>
    chargeChart.exportPNG("ja-farm-guidance-charge.png"));
  $("charge-csv").addEventListener("click", () =>
    chargeChart.exportCSV("ja-farm-guidance-charge.csv", exportHeader([
      "Unit: ¥ billion (published thousands of yen ÷ 1,000,000, an exact conversion)",
      "Measure: 営農指導事業分配賦額 — the farm-guidance loss charged to each business, " +
        "official statistic as published",
    ])));
  $("statement-csv").addEventListener("click", statementCSV);
}

boot().catch(err => {
  $("stale-banner").innerHTML = '<div class="banner" role="alert">This page could not load ' +
    'its data. ' + escapeHtml(String(err.message || err)) + "</div>";
});
