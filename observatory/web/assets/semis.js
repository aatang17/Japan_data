/* Semiconductor trade page. The question this screen answers:
   "Is Japan still shipping chips and chipmaking equipment to China, and
   where else is that trade going?" — the tiles lead with the two export
   lines and the balance, and the mix chart is where a shift in destination
   actually shows up.

   One /trade payload carries every partner × every month for the commodity
   and direction being read, plus world totals for all eleven commodity-flows
   so the tiles and the commodity chart need no second request. Switching
   commodity or direction fetches a new payload and caches it.

   Two properties of the source shape this page and must not be smoothed over.
   Export and import commodities are separate vocabularies whose codes do not
   correspond, so the commodity picker is rebuilt whenever the direction
   changes rather than carried across it. And a published group is never the
   sum of the items shown beneath it: the Ministry publishes components inside
   a group that this dataset does not carry, so the two levels are drawn
   together but never added.

   Values are published in thousands of yen and shown here in billions
   (÷1,000,000). Nothing else about a published figure is altered; world
   totals, twelve-month sums, shares, growth rates and unit values are all
   calculated here and carry their formula under "Show calculation" and in
   every export. */
"use strict";

const DATASET = "trade-semis";
const API = "/api/v1/" + DATASET;

const THOUSAND_YEN_PER_BILLION = 1e6;   // ¥1,000 units in one ¥bn

let TR = null;              // the /trade payload for the current slice
let PERIODS = [], PIDX = {}, LAST = 0;
let PARTNER = {};           // code -> partner record
const CACHE = {};           // "flow|commodity" -> payload
let partnerChart = null, mixChart = null, commodityChart = null;

/* One colour per partner for the whole page. Slot 1 is the platform's navy
   and always means the aggregate — the world total on the partner chart, the
   bundled residual on the mix chart — and the two never share a chart. The
   named partners keep their slot everywhere, so China is the same colour
   whether you are reading levels, shares or the mix. */
const AGGREGATE_SLOT = 1;
const PARTNER_SLOTS = {
  "50105": 2,   // China
  "50106": 3,   // Taiwan
  "50103": 4,   // Korea
  "50108": 5,   // Hong Kong
  "50304": 6,   // United States
};
const ROTATING_SLOTS = [2, 3, 4, 5, 6];
const WORLD = "world";
const MAX_SERIES = 6;       // more than six lines on one chart is unreadable
const MIX_NAMED = 5;        // partners named individually in the mix stack
const RESIDUAL_NAME = "All other partners";

/* ---- calculations, stated once and reused in the UI and every export ---- */

const CALCS = {
  units: "Values are published in thousands of yen and shown here in billions " +
    "of yen (value ÷ 1,000,000). No other transformation is applied to a " +
    "published figure.",
  world: "world[t] = Σ value[partner, t] over every partner the Ministry " +
    "publishes for that commodity, including the non-country entries (goods " +
    "shipped to order, unknown destinations, bonded areas). This table " +
    "publishes no world row, so the total is summed here.",
  ttm: "12-month total[t] = Σ value[t−11 … t]. A month in which the Ministry " +
    "records no customs entry for that partner contributes nothing to the " +
    "sum, which is what the absence of an entry means; the sum is left blank " +
    "until twelve months of history exist.",
  share: "share[partner, t] = (12-month total[partner, t] / 12-month " +
    "total[world, t]) × 100, in percent. Both totals are over the same twelve " +
    "months, so a single strong month cannot move the share on its own.",
  yoy: "growth[t] = (value[t] / value[t−12 months] − 1) × 100, in percent, " +
    "from published values.",
  ttmyoy: "growth[t] = (12-month total[t] / 12-month total[t−12 months] − 1) " +
    "× 100, in percent.",
  unit: "unit value[t] = (12-month total of value[t] × 1,000) / 12-month total " +
    "of quantity[t], in yen per unit shipped. Value is published in thousands " +
    "of yen and quantity in the commodity's own published unit, so this is an " +
    "average realised price across a year of shipments, not a price index and " +
    "not comparable between commodities.",
  balance: "balance[t] = exports[semiconductors & electronic components, t] − " +
    "imports[semiconductors & electronic components, t], on 12-month totals. " +
    "The two directions are published under separate commodity codes that " +
    "carry the same name and are treated by the Ministry as counterparts; " +
    "they are not two readings of one series.",
};

/* ---- lookups ---- */

function col(code) {
  return (TR.values && TR.values[code]) || null;
}

function worldCol(flow, commodity) {
  return (TR.world && TR.world[flow + "." + commodity]) || null;
}

function at(column, i) {
  if (!column || i < 0 || i >= column.length) return null;
  const v = column[i];
  return v === undefined ? null : v;
}

/* trailing twelve-month sum, in the published unit; null before month 12 */
function ttm(column, i) {
  if (!column || i < 11) return null;
  let total = 0;
  for (let k = i - 11; k <= i; k++) {
    const v = at(column, k);
    if (v !== null) total += v;
  }
  return total;
}

function pctChange(now, then) {
  if (now === null || then === null || !then) return null;
  return (now / then - 1) * 100;
}

function bn(v) { return v === null ? null : v / THOUSAND_YEN_PER_BILLION; }

/* A partner shipping ¥30m rounds to 0.0 at this scale, and a rounded zero
   beside a real one is exactly the confusion the trust contract forbids. */
function fmtSmall(v, dp) {
  if (v === null || v === undefined) return MISSING;
  const floor = Math.pow(10, -dp) / 2;
  if (v > 0 && v < floor) return "<" + fmtNum(floor * 2, dp);
  if (v < 0 && v > -floor) return MINUS + "<" + fmtNum(floor * 2, dp);
  return fmtNum(v, dp);
}

/* index of the same calendar month twelve months earlier, or −1 */
function yearBack(i) {
  const iso = PERIODS[i];
  const hit = PIDX[(Number(iso.slice(0, 4)) - 1) + iso.slice(4)];
  return hit === undefined ? -1 : hit;
}

/* Colours for one chart's partners, honouring each named partner's fixed slot
   but never handing the same slot to two series. Rotating through the palette
   by position was silently painting Korea and the Netherlands the same gold,
   and the United States and Malaysia the same crimson, whenever an unnamed
   partner's turn landed on a slot a named one already owned. */
function assignSlots(codes) {
  const used = {}, out = {};
  codes.forEach(code => {
    const want = code === WORLD ? AGGREGATE_SLOT : PARTNER_SLOTS[code];
    if (want && !used[want]) { used[want] = true; out[code] = want; }
  });
  codes.forEach(code => {
    if (out[code]) return;
    const free = ROTATING_SLOTS.filter(slot => !used[slot]);
    const slot = free.length ? free[0]
      : ROTATING_SLOTS[codes.indexOf(code) % ROTATING_SLOTS.length];
    used[slot] = true;
    out[code] = slot;
  });
  return out;
}

function partnerName(code) {
  if (code === WORLD) return "World";
  const p = PARTNER[code];
  return p ? p.name_en : code;
}

/* ---- URL state ---- */

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    flow: p.get("flow") === "imp" ? "imp" : "exp",
    commodity: p.get("commodity") || "",
    view: ["value", "ttm", "share", "unit"].indexOf(p.get("view")) !== -1
      ? p.get("view") : "value",
    range: p.get("range") || "10",
    partners: p.get("partners") || "",
    mrange: p.get("mrange") || "10",
    crange: p.get("crange") || "10",
    rows: p.get("rows") === "all" ? "all" : "countries",
    sort: p.get("sort") || "",
    dir: p.get("dir") === "asc" ? "asc" : "desc",
  };
}

function setUrlState(next) {
  const s = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (s.flow !== "exp") p.set("flow", s.flow);
  if (s.commodity) p.set("commodity", s.commodity);
  if (s.view !== "value") p.set("view", s.view);
  if (s.range !== "10") p.set("range", s.range);
  if (s.partners) p.set("partners", s.partners);
  if (s.mrange !== "10") p.set("mrange", s.mrange);
  if (s.crange !== "10") p.set("crange", s.crange);
  if (s.rows !== "countries") p.set("rows", s.rows);
  if (s.sort) p.set("sort", s.sort);
  if (s.dir !== "desc") p.set("dir", s.dir);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function selectedPartners() {
  const raw = urlState().partners;
  const chosen = raw ? raw.split(",").filter(Boolean) : [WORLD, "50105", "50106"];
  return chosen.filter(c => c === WORLD || PARTNER[c]).slice(0, MAX_SERIES);
}

/* ---- provenance chrome ---- */

function sourceLine(extra) {
  const rel = TR.release;
  return "Source: Ministry of Finance, Japan · " + rel.source_id +
    " · Data through " + fmtPeriodLong(rel.latest_period) +
    " · Retrieved " + fmtStamp(rel.retrieved_at) +
    " · Official customs values; world totals and rates calculated" +
    (extra ? " · " + extra : "");
}

function csvHeader(what, formulas) {
  const rel = TR.release;
  return [
    "Japan Data Observatory — " + what,
    "Source: Ministry of Finance, Japan, " + rel.source_name,
    "Source page: " + rel.source_page,
    "Release: " + rel.label + " (sha256 " + rel.sha256 + ")",
    "Retrieved: " + fmtStamp(rel.retrieved_at),
    "Commodity: " + TR.commodity.label + " (" + TR.commodity.code + ", " +
      TR.commodity.label_ja + "), " +
      (TR.flow === "exp" ? "exports" : "imports"),
    "Values and quantities are official customs figures, exactly as published.",
    CALCS.units,
  ].concat(formulas || []);
}

function calcBlock(el, lines) {
  document.getElementById(el).innerHTML =
    "<summary>Show calculation</summary><div class='calc-body'>" +
    lines.map(l => "<p>" + escapeHtml(l) + "</p>").join("") + "</div>";
}

function renderHeader() {
  const rel = TR.release;
  document.getElementById("header-asof").textContent =
    "Data through " + fmtPeriodLong(rel.latest_period);
  document.getElementById("page-asof").textContent =
    "Ingested " + fmtStamp(rel.ingested_at);
  document.getElementById("page-sub").textContent =
    "Monthly trade in semiconductors, components and chipmaking equipment by " +
    "partner country, " + fmtPeriodLong(rel.coverage_start).replace(/^\w+ /, "") +
    "–present · value in ¥ and quantity in the commodity's published unit · " +
    "Ministry of Finance, Trade Statistics of Japan";
  if (TR.credit_line) {
    document.getElementById("credit-line").textContent = TR.credit_line;
  }
}

function renderStale() {
  const el = document.getElementById("stale-banner");
  if (!TR.stale) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
    "ingested data is for " + fmtPeriodLong(TR.release.latest_period) +
    ", ingested " + fmtStamp(TR.release.ingested_at) +
    ". The Ministry adds a month to this table around the end of the following " +
    "month — if this persists, run the ingestion.</div>";
}

function renderProvenance() {
  const rel = TR.release;
  const countries = TR.partners.filter(p => p.is_country).length;
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
          '<div class="prov-sub">Coverage ' + fmtPeriodLong(rel.coverage_start) +
            " – " + fmtPeriodLong(rel.latest_period) + " · principal-commodity " +
            "by country tables of the Trade Statistics of Japan, retrieved " +
            "through the e-Stat API</div>" +
        "</div>" +
        '<div class="prov-field">' +
          '<div class="prov-label">Release</div>' +
          '<div class="prov-value">' + escapeHtml(rel.label) + "</div>" +
          '<div class="prov-sub">A new vintage is stored whenever the Ministry ' +
            "republishes any year of the table</div>" +
        "</div>" +
        '<div class="prov-field">' +
          '<div class="prov-label">Revision status</div>' +
          '<div class="prov-value">Revised in published stages</div>' +
          '<div class="prov-sub">Preliminary, then confirmed, then revised, then ' +
            "final — the current year moves through all four</div>" +
        "</div>" +
        '<div class="prov-field">' +
          '<div class="prov-label">Retrieved</div>' +
          '<div class="prov-value num">' + fmtStamp(rel.retrieved_at) + "</div>" +
          '<div class="prov-sub">Archived ' + fmtStamp(rel.ingested_at) + "</div>" +
        "</div>" +
        '<div class="prov-field">' +
          '<div class="prov-label">Partners</div>' +
          '<div class="prov-value num">' + fmtNum(countries, 0) + "</div>" +
          '<div class="prov-sub">countries, plus ' +
            fmtNum(TR.partners.length - countries, 0) +
            " non-country entries · " + fmtNum(PERIODS.length, 0) +
            " months published</div>" +
        "</div>" +
        '<div class="prov-field full">' +
          '<div class="prov-label">Archived checksum (SHA-256)</div>' +
          '<div class="prov-hash">' + escapeHtml(rel.sha256) + "</div>" +
        "</div>" +
      "</div>" +
    "</div>";
}

/* ---- stat strip ---- */

/* Direction is carried by the arrow and the sign, never by colour alone. More
   exports is not a warning, and less is not an alarm. */
function tile(label, valueBn, delta, comparison, title) {
  let deltaHtml = MISSING;
  if (delta !== null && delta !== undefined) {
    const rounded = Number(delta.toFixed(1));
    const arrow = rounded === 0 ? ""
      : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
        '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
    deltaHtml = arrow + fmtNum(Math.abs(delta), 1) + "%";
  }
  return '<div class="strip-cell">' +
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' +
      escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + (valueBn === null ? MISSING : fmtNum(valueBn, 1)) +
      '<span class="unit"> ¥bn</span></div>' +
    '<div class="strip-delta flat num">' + deltaHtml + " " +
      '<span style="font-weight:400">' + escapeHtml(comparison) + "</span></div>" +
    "</div>";
}

function renderTiles() {
  const i = LAST, back = yearBack(i);
  const month = fmtPeriodLong(PERIODS[i]);
  const prior = back >= 0 ? fmtPeriodLong(PERIODS[back]) : MISSING;

  function monthly(flow, commodity) {
    const c = worldCol(flow, commodity);
    return { value: bn(at(c, i)),
             delta: back < 0 ? null : pctChange(at(c, i), at(c, back)) };
  }

  const icExp = monthly("exp", "70323050");
  const equip = monthly("exp", "70131000");
  const icImp = monthly("imp", "70311030");

  // Net position in the whole component group, on twelve-month sums: a single
  // month's balance is dominated by shipment timing.
  const expGroup = worldCol("exp", "70323000");
  const impGroup = worldCol("imp", "70311000");
  const balNow = ttm(expGroup, i) === null || ttm(impGroup, i) === null ? null
    : ttm(expGroup, i) - ttm(impGroup, i);
  const balThen = back < 0 || ttm(expGroup, back) === null || ttm(impGroup, back) === null
    ? null : ttm(expGroup, back) - ttm(impGroup, back);

  document.getElementById("tiles").innerHTML =
    tile("Integrated Circuit Exports", icExp.value, icExp.delta, "vs " + prior,
         "World total of Japan's integrated-circuit exports in " + month) +
    tile("Chipmaking Equipment Exports", equip.value, equip.delta, "vs " + prior,
         "World total of Japan's semiconductor machinery and equipment exports in " + month) +
    tile("Integrated Circuit Imports", icImp.value, icImp.delta, "vs " + prior,
         "World total of Japan's integrated-circuit imports in " + month) +
    tile("Components: Exports − Imports", bn(balNow),
         pctChange(balNow, balThen),
         "12 months to " + month + " vs 12 months to " + prior,
         "Semiconductors and electronic components, exports less imports, " +
         "over the twelve months to " + month);

  document.getElementById("strip-foot").textContent =
    "World totals for " + month + ", summed from every partner the Ministry " +
    "publishes. The first three tiles are single months and move with shipment " +
    "timing; the balance is a twelve-month sum.";
  const calc = document.getElementById("strip-calc");
  calc.style.display = "";
  calc.innerHTML = "<summary>Show calculation</summary><div class='calc-body'>" +
    [CALCS.world, CALCS.yoy, CALCS.ttm, CALCS.balance, CALCS.units]
      .map(l => "<p>" + escapeHtml(l) + "</p>").join("") + "</div>";
}

/* ---- partner chart ---- */

function rangeStart(years) {
  if (years === "max") return 0;
  return Math.max(0, LAST - (Number(years) * 12 - 1));
}

function partnerPoints(code, view, from) {
  const value = code === WORLD ? worldCol(TR.flow, TR.commodity.code) : col(code);
  const qty = code === WORLD ? null : (TR.quantities || {})[code];
  const worldValue = worldCol(TR.flow, TR.commodity.code);
  const points = [];
  for (let i = from; i <= LAST; i++) {
    let v = null;
    if (view === "value") {
      v = bn(at(value, i));
    } else if (view === "ttm") {
      v = bn(ttm(value, i));
    } else if (view === "share") {
      const w = ttm(worldValue, i), p = ttm(value, i);
      v = p === null || w === null || !w ? null : (p / w) * 100;
    } else if (view === "unit") {
      const q = code === WORLD ? worldQuantity(i) : ttm(qty, i);
      const p = ttm(value, i);
      v = p === null || q === null || !q ? null : (p * 1000) / q;
    }
    points.push([PERIODS[i], v === null || Number.isNaN(v) ? null : v]);
  }
  return points;
}

/* The world's quantity is not served (only its value is), so a world unit
   value is summed here from the partner quantities actually loaded. */
function worldQuantity(i) {
  const q = TR.quantities || {};
  let total = null;
  Object.keys(q).forEach(code => {
    const v = ttm(q[code], i);
    if (v !== null) total = (total === null ? 0 : total) + v;
  });
  return total;
}

const VIEW_META = {
  value: { axis: "¥bn", unitSuffix: "¥bn", dp: 1, label: "Monthly value" },
  ttm: { axis: "¥bn, 12-month total", unitSuffix: "¥bn", dp: 1, label: "12-month total" },
  share: { axis: "% of world total", unit: "%", dp: 1, label: "Share of world" },
  unit: { axis: "¥ per unit", unitSuffix: "¥", dp: 0, label: "Unit value" },
  // "per unit" is the fallback; the real denominator is whatever the Ministry
  // publishes the quantity in — pieces for a chip, kilograms for a machine.
};

function renderPartnerChart() {
  const st = urlState();
  const view = st.view === "unit" && !TR.units.quantity ? "value" : st.view;
  const meta = Object.assign({}, VIEW_META[view]);
  if (view === "unit") {
    const per = TR.units.quantity || "unit";
    meta.axis = "¥ per " + per;
    meta.unitSuffix = "¥ per " + per;
    meta.label = "Unit value, ¥ per " + per;
  }
  const from = rangeStart(st.range);
  const codes = selectedPartners();
  const slots = assignSlots(codes);

  const cfg = {
    series: codes.map(code => ({
      name: partnerName(code),
      slot: slots[code],
      points: partnerPoints(code, view, from),
    })),
    unit: meta.unit,
    unitSuffix: meta.unitSuffix,
    dp: meta.dp,
    yAxisName: meta.axis,
    legendFloor: 1000,   // up to six partner names, some of them long
    trust: "derived",
    sourceLine: sourceLine(meta.label),
  };
  const el = document.getElementById("partner-chart");
  el.innerHTML = "";
  if (partnerChart) partnerChart.dispose();
  partnerChart = obsChart(el, "line", cfg);

  document.getElementById("partner-source").textContent = cfg.sourceLine;
  document.getElementById("partner-note").textContent =
    TR.commodity.label + " · " + (TR.flow === "exp" ? "exports" : "imports");
  const formulas = [CALCS.units, CALCS.world];
  if (view === "ttm" || view === "share" || view === "unit") formulas.push(CALCS.ttm);
  if (view === "share") formulas.push(CALCS.share);
  if (view === "unit") formulas.push(CALCS.unit);
  calcBlock("partner-calc", formulas);

  const name = "japan-" + TR.flow + "-" + TR.commodity.code + "-" + view;
  wire("partner-png", () => partnerChart.exportPNG(name + ".png"));
  wire("partner-csv", () => partnerChart.exportCSV(name + ".csv",
    csvHeader(TR.commodity.label + " by partner, " + meta.label, formulas)));
}

/* ---- destination mix ---- */

function renderMixChart() {
  const st = urlState();
  const from = rangeStart(st.mrange);
  const worldValue = worldCol(TR.flow, TR.commodity.code);

  // The largest partners on the latest month, so the bands name whoever
  // matters now rather than whoever mattered at the start of the window.
  const ranked = Object.keys(TR.values || {})
    .map(code => ({ code: code, total: ttm(col(code), LAST) || 0 }))
    .sort((a, b) => b.total - a.total)
    .slice(0, MIX_NAMED)
    .map(r => r.code);

  const mixSlots = assignSlots(ranked);
  const series = ranked.map(code => ({
    name: partnerName(code),
    slot: mixSlots[code],
    points: [],
  }));
  const residual = { name: RESIDUAL_NAME, slot: AGGREGATE_SLOT, points: [] };

  for (let i = from; i <= LAST; i++) {
    const w = ttm(worldValue, i);
    let named = 0;
    series.forEach((s, n) => {
      const p = ttm(col(ranked[n]), i);
      const share = p === null || w === null || !w ? null : (p / w) * 100;
      if (share !== null) named += share;
      s.points.push([PERIODS[i], share]);
    });
    // Derived from the world total, so the bands sum to exactly 100 in every
    // month rather than to whatever the named partners happen to cover.
    residual.points.push([PERIODS[i], w === null || !w ? null : 100 - named]);
  }

  const cfg = {
    series: series.concat([residual]),
    unit: "%", unsigned: true, yMax: 100,
    yAxisName: "% of world total, 12-month",
    legendFloor: 1100,   // five partner names plus the residual
    trust: "derived",
    sourceLine: sourceLine("Share of world total, trailing 12 months"),
  };
  const el = document.getElementById("mix-chart");
  el.innerHTML = "";
  if (mixChart) mixChart.dispose();
  mixChart = obsChart(el, "stack", cfg);

  document.getElementById("mix-source").textContent = cfg.sourceLine;
  document.getElementById("mix-title").textContent = TR.flow === "exp"
    ? "How the Destination Mix Has Shifted"
    : "Where the Imports Come From";
  document.getElementById("mix-note").textContent =
    TR.commodity.label + " · " + (TR.flow === "exp" ? "destinations" : "sources");
  const formulas = [CALCS.units, CALCS.world, CALCS.ttm, CALCS.share,
    "residual[t] = 100 − Σ share[named partners, t], so the bands sum to 100% " +
    "in every month and no partner is dropped."];
  calcBlock("mix-calc", formulas);

  const name = "japan-" + TR.flow + "-" + TR.commodity.code + "-mix";
  wire("mix-png", () => mixChart.exportPNG(name + ".png"));
  wire("mix-csv", () => mixChart.exportCSV(name + ".csv",
    csvHeader(TR.commodity.label + ", share of world total by partner", formulas)));
}

/* ---- commodity comparison ---- */

function renderCommodityChart() {
  const st = urlState();
  const from = rangeStart(st.crange);
  const catalogue = TR.commodities[TR.flow];

  const series = catalogue.map((c, n) => {
    const column = worldCol(TR.flow, c.code);
    const points = [];
    for (let i = from; i <= LAST; i++) points.push([PERIODS[i], bn(ttm(column, i))]);
    // The navy slot belongs to the aggregate, and here that is the published
    // group the rest sit inside; the items take the palette in order.
    return { name: c.short || c.label,
             slot: n === 0 ? AGGREGATE_SLOT
                           : ROTATING_SLOTS[(n - 1) % ROTATING_SLOTS.length],
             points: points };
  });

  const cfg = {
    series: series,
    unitSuffix: "¥bn", dp: 1,
    yAxisName: "¥bn (12-month)",
    legendFloor: 1150,   // every commodity published in this direction
    trust: "derived",
    sourceLine: sourceLine("World totals, trailing 12 months"),
  };
  const el = document.getElementById("commodity-chart");
  el.innerHTML = "";
  if (commodityChart) commodityChart.dispose();
  commodityChart = obsChart(el, "line", cfg);

  document.getElementById("commodity-source").textContent = cfg.sourceLine;
  document.getElementById("commodity-note").textContent =
    TR.flow === "exp" ? "exports" : "imports";
  const formulas = [CALCS.units, CALCS.world, CALCS.ttm,
    "A published group and the items listed beneath it are shown together and " +
    "must never be added: the Ministry publishes components inside a group " +
    "that this dataset does not carry, so a group always exceeds the sum of " +
    "the items shown."];
  calcBlock("commodity-calc", formulas);

  const name = "japan-" + TR.flow + "-semiconductor-commodities";
  wire("commodity-png", () => commodityChart.exportPNG(name + ".png"));
  wire("commodity-csv", () => commodityChart.exportCSV(name + ".csv",
    csvHeader("Semiconductor commodities, world totals", formulas)));
}

/* ---- partner table ---- */

function partnerRows() {
  const i = LAST, back = yearBack(i);
  const worldTtm = ttm(worldCol(TR.flow, TR.commodity.code), i);
  return TR.partners.map(p => {
    const c = col(p.code);
    const latest = at(c, i);
    const total = ttm(c, i);
    return {
      code: p.code,
      name: p.name_en,
      region: p.region,
      is_country: p.is_country,
      latest: bn(latest),
      yoy: back < 0 ? null : pctChange(latest, at(c, back)),
      ttm: bn(total),
      share: total === null || worldTtm === null || !worldTtm
        ? null : (total / worldTtm) * 100,
      spark: c ? c.slice(Math.max(0, i - 59), i + 1)
        .map((v, n) => [n, v === undefined ? null : v]) : [],
    };
  });
}

function renderPartnersTable() {
  const st = urlState();
  const regionLabel = {};
  (TR.regions || []).forEach(r => { regionLabel[r.key] = r.label; });
  let rows = partnerRows();
  if (st.rows === "countries") rows = rows.filter(r => r.is_country);
  rows.sort((a, b) => (b.ttm === null ? -Infinity : b.ttm) -
                      (a.ttm === null ? -Infinity : a.ttm));

  const month = fmtPeriod(PERIODS[LAST]);
  const head =
    "<tr><th>Partner</th><th>Region</th>" +
    '<th class="num">' + month + " (¥bn)</th>" +
    '<th class="num">YoY (%)</th>' +
    '<th class="num">12-Month Total (¥bn)</th>' +
    '<th class="num">Share (%)</th>' +
    "<th>Last 5 Years</th></tr>";

  const body = rows.map(r =>
    "<tr><td>" + escapeHtml(r.name) +
      (r.is_country ? "" : ' <span class="badge">Not a country</span>') + "</td>" +
    "<td>" + escapeHtml(regionLabel[r.region] || MISSING) + "</td>" +
    '<td class="num" data-sort="' + (r.latest === null ? -1e18 : r.latest) + '">' +
      fmtSmall(r.latest, 1) + "</td>" +
    '<td class="num" data-sort="' + (r.yoy === null ? -1e18 : r.yoy) + '">' +
      (r.yoy === null ? MISSING : fmtSigned(r.yoy, 1, "%")) + "</td>" +
    '<td class="num" data-sort="' + (r.ttm === null ? -1e18 : r.ttm) + '">' +
      fmtSmall(r.ttm, 1) + "</td>" +
    '<td class="num" data-sort="' + (r.share === null ? -1e18 : r.share) + '">' +
      fmtSmall(r.share, 2) + "</td>" +
    "<td>" + sparkSVG(r.spark, 110, 26) + "</td></tr>").join("");

  document.getElementById("partners-table").innerHTML =
    '<table class="data"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>";

  document.getElementById("partners-note").textContent =
    fmtNum(rows.length, 0) + " partners · " + TR.commodity.label;
  document.getElementById("partners-foot").textContent =
    "Ranked by the twelve-month total to " + fmtPeriodLong(PERIODS[LAST]) +
    ". A dash means the Ministry recorded no customs entry for that partner in " +
    "that month — it is not a zero, and a figure too small to show at this " +
    "scale reads as \u201c<0.1\u201d rather than rounding to zero. Shares are " +
    "of the world total, which includes the non-country entries.";
  calcBlock("partners-calc", [CALCS.units, CALCS.world, CALCS.yoy, CALCS.ttm, CALCS.share]);

  wire("partners-csv", () => {
    const lines = csvHeader("Semiconductor trade by partner",
      [CALCS.world, CALCS.yoy, CALCS.ttm, CALCS.share]).map(l => "# " + l);
    lines.push("partner_code,partner,region,is_country,month,value_bn_yen," +
               "yoy_pct,ttm_bn_yen,share_pct");
    rows.forEach(r => lines.push([
      r.code, '"' + r.name.replace(/"/g, '""') + '"',
      '"' + (regionLabel[r.region] || "") + '"', r.is_country, month,
      r.latest === null ? "" : r.latest.toFixed(3),
      r.yoy === null ? "" : r.yoy.toFixed(2),
      r.ttm === null ? "" : r.ttm.toFixed(3),
      r.share === null ? "" : r.share.toFixed(3),
    ].join(",")));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    a.download = "japan-" + TR.flow + "-" + TR.commodity.code + "-partners.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

/* ---- controls ---- */

function wire(id, handler) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.dataset.wired) el.replaceWith(el.cloneNode(true));
  const fresh = document.getElementById(id);
  fresh.dataset.wired = "1";
  fresh.addEventListener("click", e => { e.preventDefault(); handler(); });
}

function pressGroup(groupId, attr, value) {
  const group = document.getElementById(groupId);
  if (!group) return;
  Array.prototype.forEach.call(group.querySelectorAll("button"), b => {
    b.setAttribute("aria-pressed", b.getAttribute(attr) === String(value) ? "true" : "false");
  });
}

function bindSeg(groupId, attr, key, after) {
  const group = document.getElementById(groupId);
  if (!group) return;
  group.addEventListener("click", e => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const patch = {};
    patch[key] = btn.getAttribute(attr);
    setUrlState(patch);
    pressGroup(groupId, attr, btn.getAttribute(attr));
    after();
  });
}

function renderPartnerPicker() {
  const chosen = selectedPartners();
  const featured = [WORLD].concat(
    (TR.feature_partners || []).filter(c => PARTNER[c]));
  // Anything picked from the long list stays visible as a checkbox.
  chosen.forEach(c => { if (featured.indexOf(c) === -1) featured.push(c); });
  const full = chosen.length >= MAX_SERIES;

  const box = document.getElementById("partner-picker");
  box.innerHTML = '<span class="band-toggles-label">Partners</span>' +
    featured.map(code => {
      const on = chosen.indexOf(code) !== -1;
      const disabled = !on && full;
      return '<label class="' + (disabled ? "is-disabled" : "") + '">' +
        '<input type="checkbox" value="' + escapeHtml(code) + '"' +
        (on ? " checked" : "") + (disabled ? " disabled" : "") + "> " +
        escapeHtml(partnerName(code)) + "</label>";
    }).join("") +
    '<span class="band-toggles-note">' +
      (full ? "Six series is the maximum one chart can carry legibly"
            : chosen.length + " of " + MAX_SERIES + " shown") + "</span>";

  box.onchange = e => {
    if (!e.target.matches("input[type=checkbox]")) return;
    const code = e.target.value;
    let next = selectedPartners().slice();
    if (e.target.checked) {
      if (next.indexOf(code) === -1) next.push(code);
    } else {
      next = next.filter(c => c !== code);
    }
    if (!next.length) next = [WORLD];
    setUrlState({ partners: next.join(",") });
    renderPartnerPicker();
    renderPartnerChart();
  };

  const add = document.getElementById("partner-add");
  add.innerHTML = '<option value="">Add any partner…</option>' +
    TR.partners.slice()
      .sort((a, b) => a.name_en.localeCompare(b.name_en))
      .map(p => '<option value="' + escapeHtml(p.code) + '">' +
        escapeHtml(p.name_en) + "</option>").join("");
  add.disabled = full;
  add.onchange = () => {
    const code = add.value;
    add.value = "";
    if (!code) return;
    const next = selectedPartners().slice();
    if (next.indexOf(code) !== -1 || next.length >= MAX_SERIES) return;
    next.push(code);
    setUrlState({ partners: next.join(",") });
    renderPartnerPicker();
    renderPartnerChart();
  };
}

function renderCommodityPicker() {
  const select = document.getElementById("commodity-select");
  select.innerHTML = TR.commodities[TR.flow].map(c =>
    '<option value="' + escapeHtml(c.code) + '"' +
    (c.code === TR.commodity.code ? " selected" : "") + ">" +
    escapeHtml(c.label) + (c.level === "group" ? " (group)" : "") +
    "</option>").join("");
  select.onchange = () => load(TR.flow, select.value);
}

function renderViewControls() {
  const st = urlState();
  pressGroup("flow-seg", "data-flow", TR.flow);
  pressGroup("view-seg", "data-view", st.view);
  pressGroup("range-seg", "data-range", st.range);
  pressGroup("mixrange-seg", "data-mrange", st.mrange);
  pressGroup("crange-seg", "data-crange", st.crange);
  pressGroup("rows-seg", "data-rows", st.rows);

  const unitBtn = document.querySelector('#view-seg button[data-view="unit"]');
  if (unitBtn) {
    // A commodity the Ministry publishes without a quantity has no unit value
    // to show, so the view is disabled rather than drawn empty.
    unitBtn.disabled = !TR.units.quantity;
    unitBtn.title = TR.units.quantity
      ? "Average yen per " + TR.units.quantity + " shipped, over 12 months"
      : "No quantity is published for this commodity";
  }
}

/* ---- load ---- */

function renderAll() {
  renderHeader();
  renderStale();
  renderTiles();
  renderCommodityPicker();
  renderViewControls();
  renderPartnerPicker();
  renderPartnerChart();
  renderMixChart();
  renderCommodityChart();
  renderPartnersTable();
  renderProvenance();
}

function load(flow, commodity) {
  const key = flow + "|" + (commodity || "");
  const apply = payload => {
    TR = payload;
    PERIODS = payload.periods;
    PIDX = {};
    PERIODS.forEach((p, i) => { PIDX[p] = i; });
    LAST = PERIODS.length - 1;
    PARTNER = {};
    payload.partners.forEach(p => { PARTNER[p.code] = p; });
    setUrlState({ flow: payload.flow, commodity: payload.commodity.code });
    renderAll();
  };
  if (CACHE[key]) { apply(CACHE[key]); return; }
  const qs = "?flow=" + encodeURIComponent(flow) +
    (commodity ? "&commodity=" + encodeURIComponent(commodity) : "");
  fetch(API + "/trade" + qs)
    .then(r => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(payload => { CACHE[key] = payload; apply(payload); })
    .catch(err => {
      document.getElementById("stale-banner").innerHTML =
        '<div class="banner" role="alert">This surface could not load its data (' +
        escapeHtml(err.message) + "). The ingestion may not have run yet — " +
        "nothing here is showing a stale number in the meantime.</div>";
    });
}

(function init() {
  initThemeToggle(() => {
    if (partnerChart) renderPartnerChart();
    if (mixChart) renderMixChart();
    if (commodityChart) renderCommodityChart();
  });

  const st = urlState();
  bindSeg("flow-seg", "data-flow", "flow", () => load(urlState().flow, ""));
  bindSeg("view-seg", "data-view", "view", renderPartnerChart);
  bindSeg("range-seg", "data-range", "range", renderPartnerChart);
  bindSeg("mixrange-seg", "data-mrange", "mrange", renderMixChart);
  bindSeg("crange-seg", "data-crange", "crange", renderCommodityChart);
  bindSeg("rows-seg", "data-rows", "rows", renderPartnersTable);

  load(st.flow, st.commodity);
})();
