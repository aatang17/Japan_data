/* JGB yield curve page. The question this screen answers:
   "What does the JGB curve look like now, and how has it shifted?" —
   the tiles and the scrubbable curve lead.

   One /curve payload carries the whole published history (every business
   day × every maturity); everything on the page is sliced from it
   client-side. Yields are official values to three decimals, shown
   exactly as published; spreads and changes are calculated here and
   carry their formula on the page and in every export. Missing is "—";
   a maturity absent on a date breaks the line — never interpolated. */
"use strict";

const DATASET = "jgb-yields";
const API = "/api/v1/" + DATASET;

let CV = null;          // /curve payload
let DATES = [];         // CV.dates
let MATS = [];          // CV.maturities
let activeIdx = 0;      // slider position into DATES
let curveChart = null;  // echarts instance (custom mount — value x-axis)
let histChart = null;   // obsChart handle
let playTimer = null;
let monthStarts = [];   // indices of the first business day of each month

/* ---- verified BOJ policy dates for the history chart ----
   Sources: Bank of Japan statements (boj.or.jp, "Change in the Guideline
   for Money Market Operations" / policy statements), checked Aug 2026.
   major: shown at every range; the rest only when the visible span is
   short enough that the labels stay legible. */
const POLICY_EVENTS = [
  { x: "1999-02-12", label: "ZIRP", major: true },
  { x: "2001-03-19", label: "QE", major: true },
  { x: "2006-03-09", label: "QE ends", major: false },
  { x: "2013-04-04", label: "QQE", major: true },
  { x: "2016-01-29", label: "NIRP", major: true },
  { x: "2016-09-21", label: "YCC", major: true, stagger: true },
  { x: "2022-12-20", label: "Band ±0.5", major: false },
  { x: "2024-03-19", label: "YCC ends", major: true },
  { x: "2024-07-31", label: "0.25%", major: false, stagger: true },
  { x: "2025-01-24", label: "0.5%", major: false },
  { x: "2025-12-19", label: "0.75%", major: false, stagger: true },
  { x: "2026-06-16", label: "1.0%", major: false },
];

/* stable series identity across the platform's rate charts:
   10Y is the headline (slot 1), 30Y second (slot 2), 2Y third (slot 3) */
const HIST_SLOTS = { "10Y": 1, "30Y": 2, "2Y": 3 };

/* comparison curves: offset in months, chart slot, dash style */
const CMP_DEFS = {
  "1m": { months: 1, slot: 5, label: "1M earlier" },
  "1y": { months: 12, slot: 3, label: "1Y earlier" },
  "5y": { months: 60, slot: 4, label: "5Y earlier" },
};
const PIN_SLOTS = [2, 6];   // up to two pinned dates

const SPREAD_CALCS = {
  s2s10: "2s10s spread[t] = 10Y yield[t] − 2Y yield[t], in percentage points, " +
    "from published yields.",
  s10s30: "10s30s spread[t] = 30Y yield[t] − 10Y yield[t], in percentage points, " +
    "from published yields.",
  delta: "change[t] = value[t] − value[b], where b is the latest business day " +
    "on or before the same date 1 month (or 1 year) earlier.",
};

/* ---- date helpers (daily data; format.js is monthly-minded) ---- */

/* "2026-08-27" -> "27 Aug 2026" */
function fmtDay(iso) {
  if (!iso) return MISSING;
  return Number(iso.slice(8, 10)) + " " +
    MONTHS[Number(iso.slice(5, 7)) - 1].slice(0, 3) + " " + iso.slice(0, 4);
}

/* iso date minus n months, day clamped to the target month's length */
function monthsEarlier(iso, n) {
  const y = Number(iso.slice(0, 4)), m = Number(iso.slice(5, 7)),
        d = Number(iso.slice(8, 10));
  let ty = y, tm = m - n;
  while (tm <= 0) { ty -= 1; tm += 12; }
  const last = new Date(Date.UTC(ty, tm, 0)).getUTCDate();
  const td = Math.min(d, last);
  return String(ty).padStart(4, "0") + "-" + String(tm).padStart(2, "0") +
    "-" + String(td).padStart(2, "0");
}

/* largest index with DATES[i] <= iso, or -1 */
function idxOnOrBefore(iso) {
  let lo = 0, hi = DATES.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (DATES[mid] <= iso) { ans = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  return ans;
}

function val(code, idx) {
  if (idx === null || idx < 0) return null;
  const v = CV.values[code][idx];
  return v === undefined ? null : v;
}

/* ---- URL state ---- */

const CMP_DEFAULT = "1m,1y";

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    d: p.get("d") || "",
    cmp: p.get("cmp") !== null ? p.get("cmp") : CMP_DEFAULT,
    pins: (p.get("pins") || "").split(",").filter(Boolean),
    hrange: p.get("hrange") || "10",
  };
}

function setUrlState(next) {
  const state = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (state.d && state.d !== DATES[DATES.length - 1]) p.set("d", state.d);
  if (state.cmp !== CMP_DEFAULT) p.set("cmp", state.cmp);
  if (state.pins.length) p.set("pins", state.pins.join(","));
  if (state.hrange !== "10") p.set("hrange", state.hrange);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function sourceLine(rel) {
  return "Source: Ministry of Finance, Japan · " + rel.source_id +
    " · % per year · Data through " + fmtDay(rel.latest_period) +
    " · Retrieved " + fmtStamp(rel.retrieved_at) +
    " · " + TRUST_LABELS.official;
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

function deltaHtml(delta) {
  if (delta === null) return { html: MISSING, dir: "flat" };
  const rounded = Number(delta.toFixed(3));
  const dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
  const arrow = rounded === 0 ? ""
    : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
      '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
  return { html: arrow + fmtNum(Math.abs(delta), 3) + " pp", dir: dir };
}

function renderTiles() {
  const last = DATES.length - 1;
  const m1 = idxOnOrBefore(monthsEarlier(DATES[last], 1));
  const cells = [];

  function yieldTile(code, label) {
    const cur = val(code, last);
    const d = deltaHtml(cur === null || val(code, m1) === null
      ? null : cur - val(code, m1));
    cells.push(tileCell(label,
      (cur === null ? MISSING : fmtNum(cur, 3)) + '<span class="unit">%</span>',
      d.html, d.dir,
      label + " — published constant-maturity yield, exactly as released"));
  }
  function spreadTile(longCode, shortCode, label, calcKey) {
    const cur = (val(longCode, last) === null || val(shortCode, last) === null)
      ? null : val(longCode, last) - val(shortCode, last);
    const prev = (val(longCode, m1) === null || val(shortCode, m1) === null)
      ? null : val(longCode, m1) - val(shortCode, m1);
    const d = deltaHtml(cur === null || prev === null ? null : cur - prev);
    cells.push(tileCell(label,
      (cur === null ? MISSING : fmtSigned(cur, 3)) + '<span class="unit">pp</span>',
      d.html, d.dir, label + " — " + SPREAD_CALCS[calcKey]));
  }

  yieldTile("10Y", "10-Year Yield");
  yieldTile("2Y", "2-Year Yield");
  spreadTile("10Y", "2Y", "2s10s Spread", "s2s10");
  spreadTile("30Y", "10Y", "10s30s Spread", "s10s30");

  document.getElementById("tiles").innerHTML = cells.join("");
  document.getElementById("strip-foot").textContent =
    "Yields to three decimals, exactly as published · changes vs " +
    fmtDay(DATES[m1]) + ", the latest business day one month earlier · " +
    "spreads are calculated (see calculation) · pp = percentage points";

  document.getElementById("strip-calc").style.display = "";
  document.getElementById("strip-calc").innerHTML =
    "<summary>Show calculation</summary>" +
    '<div class="calc-body">' +
    "<b>2s10s Spread</b>: <code>" + escapeHtml(SPREAD_CALCS.s2s10) + "</code><br>" +
    "<b>10s30s Spread</b>: <code>" + escapeHtml(SPREAD_CALCS.s10s30) + "</code><br>" +
    "<b>Changes</b>: <code>" + escapeHtml(SPREAD_CALCS.delta) + "</code><br>" +
    "Inputs: official yields from " + escapeHtml(CV.release.source_name) +
    " (sha256 " + CV.release.sha256.slice(0, 12) + "…), release “" +
    escapeHtml(CV.release.label) + "”.</div>";
}

/* ---- chrome ---- */

function renderHeader() {
  const rel = CV.release;
  document.getElementById("header-asof").textContent =
    "Data through " + fmtDay(rel.latest_period);
  document.getElementById("page-asof").textContent =
    "Ingested " + fmtStamp(rel.ingested_at);
  document.getElementById("page-sub").textContent =
    "Daily constant-maturity JGB yields, 1974–present · % per year · " +
    "Ministry of Finance, computed from JSDA reference prices";
  if (CV.credit_line) {
    document.getElementById("credit-line").textContent = CV.credit_line;
  }
}

function renderStale() {
  const el = document.getElementById("stale-banner");
  if (CV.stale) {
    el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
      "ingested data is for " + fmtDay(CV.release.latest_period) +
      ", ingested " + fmtStamp(CV.release.ingested_at) +
      ". The Ministry publishes each business day; the platform refreshes on its " +
      "daily restart — if this persists, run the ingestion.</div>";
  } else {
    el.innerHTML = "";
  }
}

function renderProvenance() {
  const rel = CV.release;
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
          '<div class="prov-sub">Coverage ' + fmtDay(rel.coverage_start) +
            " – latest business day · constant-maturity par yields in %, " +
            "computed by the Ministry from JSDA reference prices</div>" +
        "</div>" +
        '<div class="prov-field">' +
          '<div class="prov-label">Release</div>' +
          '<div class="prov-value">Data through ' + fmtDay(rel.latest_period) + "</div>" +
          '<div class="prov-sub">Published each business day; a new vintage is ' +
            "stored per changed file</div>" +
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

/* ---- the curve chart (custom: numeric maturity x-axis) ---- */

/* the set of curves currently on the chart: active first, then
   comparisons and pins, each {name, iso, idx, slot, dashed, width} */
function curveSet() {
  const state = urlState();
  const out = [{
    name: fmtDay(DATES[activeIdx]), iso: DATES[activeIdx], idx: activeIdx,
    slot: 1, dashed: false, width: 2.5,
  }];
  const on = state.cmp.split(",").filter(Boolean);
  on.forEach(key => {
    const def = CMP_DEFS[key];
    if (!def) return;
    const idx = idxOnOrBefore(monthsEarlier(DATES[activeIdx], def.months));
    if (idx < 0) return;
    out.push({
      name: fmtDay(DATES[idx]) + " (" + def.label + ")", iso: DATES[idx],
      idx: idx, slot: def.slot, dashed: true, width: 1.5,
    });
  });
  state.pins.forEach((iso, i) => {
    if (i >= PIN_SLOTS.length) return;
    const idx = idxOnOrBefore(iso);
    if (idx < 0) return;
    out.push({
      name: fmtDay(DATES[idx]) + " (pinned)", iso: DATES[idx], idx: idx,
      slot: PIN_SLOTS[i], dashed: false, width: 1.5,
    });
  });
  return out;
}

function curvePoints(idx) {
  // null keeps its slot so a missing tenor breaks the line (never a
  // straight segment drawn across a maturity that has no published value)
  return MATS.map(m => [m.years, val(m.code, idx)]);
}

const TICK_YEARS = { 1: 1, 2: 1, 3: 1, 5: 1, 7: 1, 10: 1, 15: 1, 20: 1, 25: 1, 30: 1, 40: 1 };
const TICK_YEARS_NARROW = { 1: 1, 5: 1, 10: 1, 20: 1, 30: 1, 40: 1 };

function curveOptions(pal, narrow, fixedY) {
  const curves = curveSet();
  const yearsToCode = {};
  MATS.forEach(m => { yearsToCode[m.years] = m.code; });

  return {
    animation: false,
    legend: Object.assign(
      { show: true, itemWidth: 16, itemHeight: 8, itemGap: narrow ? 10 : 18,
        textStyle: { color: pal.text, fontSize: narrow ? 11 : 12, padding: [0, 0, 0, 2] },
        data: curves.map(c => c.name) },
      narrow ? { bottom: 0, left: 0 } : { top: 0, right: 0 }),
    grid: narrow
      ? { left: 8, right: 12, top: 26, bottom: 44, containLabel: true }
      : { left: 8, right: 20, top: 34, bottom: 8, containLabel: true },
    xAxis: Object.assign(axisCommon(pal), {
      type: "value", min: 0, max: 41, interval: 1,
      splitLine: { show: false },
      axisLabel: { color: pal.muted, fontSize: 11,
                   formatter: v =>
                     (narrow ? TICK_YEARS_NARROW : TICK_YEARS)[v] ? v + "Y" : "" },
    }),
    yAxis: Object.assign(axisCommon(pal), {
      type: "value",
      name: "% per year",
      nameTextStyle: { color: pal.muted, fontSize: 11, align: "left" },
      min: fixedY ? fixedY[0] : undefined,
      max: fixedY ? fixedY[1] : undefined,
      axisLine: { show: false },
      splitLine: { show: true, lineStyle: { color: pal.grid, width: 1 } },
    }),
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: pal.muted, width: 1 } },
      backgroundColor: pal.surface,
      borderColor: pal.border,
      textStyle: { color: pal.text, fontSize: 12 },
      formatter: params => {
        const years = params[0].value[0];
        const rows = params.map(p => {
          const v = p.value[1];
          return p.marker + " " + escapeHtml(p.seriesName) +
            ' <span class="num" style="float:right;margin-left:16px;font-weight:600">' +
            (v === null || v === undefined ? MISSING : fmtNum(v, 3) + "%") + "</span>";
        });
        return '<div style="font-weight:600;margin-bottom:2px">' +
          escapeHtml(yearsToCode[years] || years + "Y") + " maturity</div>" +
          rows.join("<br>") +
          '<div style="margin-top:4px;font-size:11px;color:' + pal.muted + '">' +
          TRUST_LABELS.official + "</div>";
      },
    },
    series: curves.map(c => ({
      name: c.name,
      type: "line",
      showSymbol: true,
      symbolSize: c.slot === 1 ? 5 : 4,
      connectNulls: false,
      z: c.slot === 1 ? 10 : 2,
      lineStyle: { width: c.width, type: c.dashed ? "dashed" : "solid",
                   color: pal.series[(c.slot - 1) % 6] },
      itemStyle: { color: pal.series[(c.slot - 1) % 6] },
      emphasis: { focus: "none" },
      data: curvePoints(c.idx),
    })),
  };
}

/* y-axis bounds over the full history, so the axis holds still while the
   curve animates (a rescaling axis makes motion unreadable) */
function globalYBounds() {
  let lo = 0, hi = 1;
  MATS.forEach(m => {
    CV.values[m.code].forEach(v => {
      if (v === null) return;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    });
  });
  return [Math.floor(lo * 2) / 2, Math.ceil(hi * 2) / 2];
}

function renderCurve() {
  const el = document.getElementById("curve-chart");
  if (!curveChart) {
    el.innerHTML = "";
    curveChart = echarts.init(el, null, { renderer: "canvas" });
    window.addEventListener("resize", () => curveChart && curveChart.resize());
  }
  const narrow = el.clientWidth < 520;
  curveChart.setOption(
    curveOptions(readPalette(), narrow, playTimer ? globalYBounds() : null),
    { notMerge: true });

  document.getElementById("curve-date").textContent = fmtDay(DATES[activeIdx]);
  document.getElementById("curve-note").textContent =
    fmtDay(DATES[activeIdx]) + " · " +
    curvePoints(activeIdx).filter(p => p[1] !== null).length + " tenors";
  document.getElementById("curve-source").innerHTML =
    sourceLine(CV.release).replace("Source: ",
      'Source: <a href="' + escapeHtml(CV.release.source_page) +
      '" rel="noopener">').replace(" · " + CV.release.source_id,
      "</a> · " + CV.release.source_id);
}

function exportCurvePNG() {
  const pal = paletteFor("light");
  const off = document.createElement("div");
  off.style.cssText = "position:fixed;left:-99999px;width:1200px;height:560px";
  document.body.appendChild(off);
  const tmp = echarts.init(off, null, { renderer: "canvas" });
  const opts = curveOptions(pal, false, null);
  opts.graphic = [{
    type: "text", left: 10, bottom: 6,
    style: { text: sourceLine(CV.release), fontSize: 11, fill: pal.muted },
  }];
  opts.grid.bottom = 30;
  tmp.setOption(opts);
  const url = tmp.getDataURL({ pixelRatio: 2, backgroundColor: pal.surface });
  tmp.dispose();
  off.remove();
  const a = document.createElement("a");
  a.href = url;
  a.download = "jgb-yield-curve-" + DATES[activeIdx] + ".png";
  a.click();
}

function exportCurveCSV() {
  const curves = curveSet();
  const head = [
    "JGB yield curve — constant-maturity yields (% per year)",
    "Trust: " + TRUST_LABELS.official + " — yields exactly as published; " +
      "empty = no published value (tenor not quoted on that date)",
    "Source: Ministry of Finance, Japan, " + CV.release.source_id,
    "Vintage: " + CV.release.label,
    "Retrieved: " + fmtStamp(CV.release.retrieved_at),
    "Permalink: " + location.href,
    CV.credit_line || "",
  ].map(l => "# " + l).join("\n");
  let csv = head + "\nmaturity_years,tenor," +
    curves.map(c => c.iso).join(",") + "\n";
  MATS.forEach(m => {
    csv += m.years + "," + m.code + "," +
      curves.map(c => { const v = val(m.code, c.idx); return v === null ? "" : v; })
        .join(",") + "\n";
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "jgb-yield-curve-" + DATES[activeIdx] + ".csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---- play ---- */

function stopPlay() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  const btn = document.getElementById("play-btn");
  btn.textContent = "▶ Play";
  btn.setAttribute("aria-pressed", "false");
  renderCurve();   // back to an auto-scaled axis
}

function startPlay() {
  // step over month-starts: 620 frames over the full history, not 13,000
  const btn = document.getElementById("play-btn");
  btn.textContent = "⏸ Pause";
  btn.setAttribute("aria-pressed", "true");
  let pos = 0;
  while (pos < monthStarts.length && monthStarts[pos] <= activeIdx) pos++;
  if (pos >= monthStarts.length) pos = 0;   // at the end: replay from the start
  playTimer = setInterval(() => {
    if (pos >= monthStarts.length) { stopPlay(); return; }
    activeIdx = monthStarts[pos];
    pos += 1;
    document.getElementById("date-slider").value = activeIdx;
    setUrlState({ d: DATES[activeIdx] });
    renderCurve();
  }, 90);
  renderCurve();   // switch to the fixed axis before the first tick
}

/* ---- history chart ---- */

function histStart(range) {
  if (range === "max") return null;
  const latest = CV.release.latest_period;
  return (Number(latest.slice(0, 4)) - Number(range)) + latest.slice(4);
}

function renderHistory() {
  const state = urlState();
  const start = histStart(state.hrange);
  const startIdx = start ? Math.max(0, idxOnOrBefore(start)) : 0;

  const el = document.getElementById("hist-chart");
  const narrow = el.clientWidth < 520;
  const spanYears = (DATES.length - startIdx) / 245;
  const events = POLICY_EVENTS
    .filter(e => e.x >= DATES[startIdx]
              && (narrow ? e.major : (spanYears <= 16 || e.major)));

  const series = CV.history_series.map(code => {
    const m = MATS.find(x => x.code === code);
    return {
      name: m ? m.name_en.replace(" JGB yield", "") : code,
      slot: HIST_SLOTS[code] || 4,
      points: DATES.slice(startIdx).map((d, i) =>
        [d, val(code, startIdx + i)]),
    };
  });

  const cfg = {
    series: series,
    unit: "%",
    dp: 3,
    yAxisName: "% per year",
    trust: "official",
    eventLines: events,
    isoPeriods: true,
    sourceLine: sourceLine(CV.release) + " · dashed rules mark BOJ policy dates",
  };
  el.innerHTML = "";
  if (histChart) histChart.dispose();
  histChart = obsChart(el, "line", cfg);

  document.getElementById("hist-source").innerHTML =
    sourceLine(CV.release).replace("Source: ",
      'Source: <a href="' + escapeHtml(CV.release.source_page) +
      '" rel="noopener">').replace(" · " + CV.release.source_id,
      "</a> · " + CV.release.source_id) +
    " · dashed rules mark Bank of Japan policy dates";

  document.getElementById("hist-calc").innerHTML =
    "<summary>About the policy markers</summary>" +
    '<div class="calc-body">Vertical rules mark Bank of Japan policy decisions, ' +
    "dated by the announcement: ZIRP (Feb 1999), quantitative easing (Mar 2001, " +
    "ended Mar 2006), QQE (Apr 2013), the negative rate (Jan 2016), yield curve " +
    "control (Sep 2016, band widened Dec 2022, ended Mar 2024) and the subsequent " +
    "rate rises to 0.25% (Jul 2024), 0.5% (Jan 2025), 0.75% (Dec 2025) and 1.0% " +
    "(Jun 2026). Markers are dates only; the yield lines are official values as " +
    "published.</div>";

  document.getElementById("hist-png").onclick = () =>
    histChart.exportPNG("jgb-yields-history.png");
  document.getElementById("hist-csv").onclick = () =>
    histChart.exportCSV("jgb-yields-history.csv", [
      "JGB yields over time — 2Y, 10Y, 30Y constant-maturity (% per year)",
      "Trust: " + TRUST_LABELS.official + " — yields exactly as published; " +
        "empty = no published value",
      "Source: Ministry of Finance, Japan, " + CV.release.source_id,
      "Vintage: " + CV.release.label,
      "Retrieved: " + fmtStamp(CV.release.retrieved_at),
      "Permalink: " + location.href,
      CV.credit_line || "",
    ]);
}

/* ---- all-maturities table ---- */

function renderTable() {
  const last = DATES.length - 1;
  const m1 = idxOnOrBefore(monthsEarlier(DATES[last], 1));
  const y1 = idxOnOrBefore(monthsEarlier(DATES[last], 12));
  const y5 = idxOnOrBefore(monthsEarlier(DATES[last], 60));

  const rows = MATS.map(m => {
    const cur = val(m.code, last);
    const d1m = (cur === null || val(m.code, m1) === null)
      ? null : cur - val(m.code, m1);
    const d1y = (cur === null || val(m.code, y1) === null)
      ? null : cur - val(m.code, y1);
    // 5y sparkline, thinned to roughly weekly points
    const spark = [];
    for (let i = Math.max(0, y5); i <= last; i += 5) {
      spark.push([DATES[i], val(m.code, i)]);
    }
    return "<tr>" +
      '<td title="' + escapeHtml(m.name_en) + '">' + escapeHtml(m.code) + "</td>" +
      '<td class="num">' + (cur === null ? MISSING : fmtNum(cur, 3)) + "</td>" +
      '<td class="num">' + fmtSigned(d1m, 3) + "</td>" +
      '<td class="num">' + fmtSigned(d1y, 3) + "</td>" +
      "<td>" + sparkSVG(spark, 110, 26) + "</td>" +
      '<td class="num">' + fmtPeriod(m.first_period) + "</td>" +
      "</tr>";
  });

  document.getElementById("mat-note").textContent =
    MATS.length + " tenors · " + fmtDay(CV.release.latest_period);
  document.getElementById("mat-table").innerHTML =
    '<table class="data tbl-series"><thead><tr>' +
    "<th>Tenor</th>" +
    '<th class="num">Yield (%)</th>' +
    '<th class="num">Δ 1m (pp)</th>' +
    '<th class="num">Δ 1y (pp)</th>' +
    "<th>5y trend</th>" +
    '<th class="num">Since</th>' +
    "</tr></thead><tbody>" + rows.join("") + "</tbody></table>";

  var matEl = document.getElementById("mat-table");
  var ths = matEl.querySelectorAll("thead th");
  if (ths.length) ths[ths.length - 2].setAttribute("data-nosort", "");  // sparkline
  enhanceTable(matEl, { placeholder: "Filter tenors…" });

  document.getElementById("mat-foot").textContent =
    "Yields are official statistics to three decimals, exactly as published; " +
    "Δ columns are calculated in percentage points vs the latest business day " +
    "1 month and 1 year earlier. — means no published value. Since = first " +
    "published date for the tenor.";

  document.getElementById("mat-calc").innerHTML =
    "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(SPREAD_CALCS.delta) + "</code>" +
    "<br>Inputs: official yields from release “" + escapeHtml(CV.release.label) +
    "” (sha256 " + CV.release.sha256.slice(0, 12) + "…).</div>";

  document.getElementById("mat-csv").onclick = () => {
    const head = [
      "JGB yield curve — all tenors, latest business day (% per year)",
      "Trust: yield_pct is " + TRUST_LABELS.official + " as published; " +
        "delta columns are calculated (formula below)",
      "Calculation: " + SPREAD_CALCS.delta,
      "Unit: % per year; deltas in percentage points; empty = not published",
      "Source: Ministry of Finance, Japan, " + CV.release.source_id,
      "Vintage: " + CV.release.label,
      "Retrieved: " + fmtStamp(CV.release.retrieved_at),
      "Permalink: " + location.href,
      CV.credit_line || "",
    ].map(l => "# " + l).join("\n");
    let csv = head + "\ntenor,maturity_years,as_of,yield_pct,delta_1m_pp,delta_1y_pp,first_published\n";
    MATS.forEach(m => {
      const cur = val(m.code, last);
      const d1m = (cur === null || val(m.code, m1) === null) ? "" : cur - val(m.code, m1);
      const d1y = (cur === null || val(m.code, y1) === null) ? "" : cur - val(m.code, y1);
      csv += [m.code, m.years, DATES[last], cur === null ? "" : cur,
              d1m === "" ? "" : d1m.toFixed(3), d1y === "" ? "" : d1y.toFixed(3),
              m.first_period].join(",") + "\n";
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "jgb-yields-all-tenors.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
}

/* ---- wiring ---- */

function renderPins() {
  const state = urlState();
  document.getElementById("pin-chips").innerHTML = state.pins.map(iso =>
    '<button type="button" class="pin-chip num" data-pin="' + escapeHtml(iso) +
    '" title="Remove this pinned date">' + fmtDay(iso) +
    ' <span class="x" aria-hidden="true">✕</span>' +
    '<span class="visually-hidden">— remove</span></button>').join("");
  document.querySelectorAll(".pin-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const pins = urlState().pins.filter(p => p !== chip.dataset.pin);
      setUrlState({ pins: pins });
      renderPins();
      renderCurve();
    });
  });
}

function wireControls() {
  const state = urlState();
  const slider = document.getElementById("date-slider");
  slider.max = DATES.length - 1;
  slider.value = activeIdx;
  slider.addEventListener("input", () => {
    stopPlay();
    activeIdx = Number(slider.value);
    setUrlState({ d: DATES[activeIdx] });
    renderCurve();
  });

  document.getElementById("play-btn").addEventListener("click", () => {
    if (playTimer) stopPlay(); else startPlay();
  });
  document.getElementById("latest-btn").addEventListener("click", () => {
    stopPlay();
    activeIdx = DATES.length - 1;
    slider.value = activeIdx;
    setUrlState({ d: "" });
    renderCurve();
  });

  document.querySelectorAll("#cmp-toggles input").forEach(box => {
    box.checked = state.cmp.split(",").indexOf(box.dataset.cmp) !== -1;
    box.addEventListener("change", () => {
      const on = Array.prototype.slice.call(
        document.querySelectorAll("#cmp-toggles input"))
        .filter(b => b.checked).map(b => b.dataset.cmp);
      setUrlState({ cmp: on.join(",") });
      renderCurve();
    });
  });

  document.getElementById("pin-btn").addEventListener("click", () => {
    const iso = DATES[activeIdx];
    let pins = urlState().pins.filter(p => p !== iso);
    pins.push(iso);
    if (pins.length > PIN_SLOTS.length) pins = pins.slice(-PIN_SLOTS.length);
    setUrlState({ pins: pins });
    renderPins();
    renderCurve();
  });

  document.getElementById("curve-png").addEventListener("click", exportCurvePNG);
  document.getElementById("curve-csv").addEventListener("click", exportCurveCSV);

  const seg = document.getElementById("hist-seg");
  seg.querySelectorAll("button").forEach(b => {
    b.setAttribute("aria-pressed", String(b.dataset.range === state.hrange));
    b.addEventListener("click", () => {
      seg.querySelectorAll("button").forEach(x =>
        x.setAttribute("aria-pressed", String(x === b)));
      setUrlState({ hrange: b.dataset.range });
      renderHistory();
    });
  });
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
    if (curveChart) renderCurve();
    if (histChart) renderHistory();
  });
  try {
    const r = await fetch(API + "/curve");
    if (!r.ok) throw new Error("curve " + r.status + " " + (await r.text()).slice(0, 300));
    CV = await r.json();
  } catch (err) {
    showError(err);
    return;
  }
  DATES = CV.dates;
  MATS = CV.maturities;

  monthStarts = [];
  let lastMonth = "";
  DATES.forEach((d, i) => {
    const ym = d.slice(0, 7);
    if (ym !== lastMonth) { monthStarts.push(i); lastMonth = ym; }
  });

  const state = urlState();
  const fromUrl = state.d ? idxOnOrBefore(state.d) : -1;
  activeIdx = fromUrl >= 0 ? fromUrl : DATES.length - 1;

  renderHeader();
  renderStale();
  renderTiles();
  renderProvenance();
  renderPins();
  wireControls();
  renderTable();
  renderHistory();
  renderCurve();
}

init();
