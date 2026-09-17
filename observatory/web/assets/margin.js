/* Margin balances. The question this screen answers: "How leveraged is the
   Japanese market right now, long and short, and how has that changed?"

   One dataset (margin-jp): JPX's weekly 信用取引現在高, cut by whose account
   the balance sits in and by which kind of margin it is. Every level is an
   official figure exactly as published; the sale/purchase ratio and every
   change are calculated here and carry their formula on the page and in every
   export. A week the exchange did not publish is "—", never zero. */
"use strict";

const API = "/api/v1/margin-jp";

/* The two headline balances, in slot order. Purchases first: it is the larger
   side by an order of magnitude and sets the scale. */
const SIDES = [
  { side: "purchases", label: "Bought on margin (long)", slot: 1 },
  { side: "sales", label: "Sold short (short)", slot: 2 },
];

/* The two cuts, each of which adds to the same published total. */
const CUTS = [
  { title: "By account", rows: [
    ["customer", "Customers' account"],
    ["proprietary", "Members' own account"],
    ["total", "Total"],
  ] },
  { title: "By kind of margin", rows: [
    ["negotiable", "Negotiable (一般信用取引)"],
    ["standardized", "Standardised (制度信用取引)"],
    ["total", "Total"],
  ] },
];

/* Published in 千株 and 百万円; charted in millions of shares and ¥ trillion,
   which are exact divisions and legible on an axis. The published unit is
   named in every calculation note and every export header. */
const UNITS = {
  shares: { divisor: 1000, suffix: "m shares", dp: 0,
            axis: "Outstanding balance, millions of shares",
            note: "thousands of shares (千株), shown here in millions" },
  value: { divisor: 1e6, suffix: "¥tn", dp: 1,
           axis: "Outstanding balance, ¥ trillion",
           note: "¥ million (百万円) struck at contract prices, shown here in ¥ trillion" },
};

/* The week the Osaka cash equity market merged into Tokyo: figures before it
   cover three markets, after it two. The step in the level is real and is
   marked on the chart rather than smoothed. */
const MARKET_BREAK = { x: "2013-07-19", label: "Osaka merged into Tokyo" };

const RATIO_CALC =
  "margin ratio[t] = total shares bought on margin[t] ÷ total shares sold short[t], from " +
  "published share counts — the 信用倍率. Above one, more stock is held long on borrowed money " +
  "than is held short on borrowed stock. It is the reciprocal of the exchange's own 取組比率, " +
  "which is published per issue and divides the other way round. A week missing either side " +
  "shows —, never zero.";
const CHANGE_CALC =
  "change[t] = value[t] − value[t−1 week], and percent change = (value[t] ÷ value[t−1 week] − 1) " +
  "× 100, from published levels. A week missing either side shows —, never zero.";

function $(id) { return document.getElementById(id); }

const D = { rel: null, stale: false, series: {} };

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

/* The API refuses a request mixing series of different published units — a
   share count and a yen value must not share an axis — and caps a request at
   eight codes and about 190 characters of them. So codes are grouped by the
   unit their code ends in, then chunked. */
function batch(codes) {
  const groups = {};
  codes.forEach(c => {
    const unit = c.slice(c.lastIndexOf(".") + 1);
    (groups[unit] = groups[unit] || []).push(c);
  });
  const out = [];
  Object.keys(groups).forEach(unit => {
    let current = [], length = 0;
    groups[unit].forEach(c => {
      const cost = c.length + (current.length ? 1 : 0);
      if (current.length && (current.length >= 8 || length + cost > 190)) {
        out.push(current); current = []; length = 0;
      }
      current.push(c); length += cost;
    });
    if (current.length) out.push(current);
  });
  return out;
}

async function loadSeries(codes) {
  const want = codes.filter(c => !(c in D.series));
  for (const chunk of batch(want)) {
    const payload = await getJSON(API + "/observations?series=" + encodeURIComponent(chunk.join(",")));
    payload.series.forEach(s => { D.series[s.code] = s.points; });
  }
  codes.forEach(c => { if (!(c in D.series)) D.series[c] = []; });
}

function code(stem, side, unit) { return stem + "." + side + "." + unit; }
function pts(c) { return D.series[c] || []; }

function at(c, period) {
  const p = pts(c);
  for (let i = 0; i < p.length; i++) if (p[i][0] === period) return p[i][1];
  return null;
}

function weeks(c) { return pts(c).map(p => p[0]); }

function weekBefore(period) {
  const all = weeks(code("total", "purchases", "shares"));
  const i = all.indexOf(period);
  return i > 0 ? all[i - 1] : null;
}

/* "2026-08-28" -> "28 Aug 2026". A weekly period is a day, not a month, and
   must never be shown as one. */
const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function week(period) {
  if (!period) return MISSING;
  return Number(period.slice(8, 10)) + " " + MONTH_ABBR[Number(period.slice(5, 7)) - 1] +
    " " + period.slice(0, 4);
}

/* ---- URL state ---- */

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    unit: p.get("unit") === "value" ? "value" : "shares",
    range: ["5", "10", "max"].includes(p.get("range")) ? p.get("range") : "max",
    ratioRange: ["5", "10", "max"].includes(p.get("rratio")) ? p.get("rratio") : "max",
  };
}

function setUrlState(next) {
  const s = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (s.unit !== "shares") p.set("unit", s.unit);
  if (s.range !== "max") p.set("range", s.range);
  if (s.ratioRange !== "max") p.set("rratio", s.ratioRange);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function cutoff(range) {
  if (range === "max") return null;
  const d = new Date();
  d.setFullYear(d.getFullYear() - Number(range));
  return d.toISOString().slice(0, 10);
}

/* ---- head, staleness, provenance ---- */

function renderHead() {
  const latest = D.rel.latest_period;
  const buy = at(code("total", "purchases", "shares"), latest);
  const sell = at(code("total", "sales", "shares"), latest);
  const buyYen = at(code("total", "purchases", "value"), latest);
  $("page-asof").textContent = "Week of " + week(latest);
  const asof = $("header-asof");
  if (asof) asof.textContent = week(latest);
  $("page-sub").innerHTML =
    "At the " + escapeHtml(week(latest)) + " application date the market held <strong class=\"num\">" +
    fmtNum(buy === null ? null : buy / 1000, 1) + "m</strong> shares bought on margin — ¥" +
    fmtNum(buyYen === null ? null : buyYen / 1e6, 1) + "tn at contract prices — against <strong class=\"num\">" +
    fmtNum(sell === null ? null : sell / 1000, 1) + "m</strong> shares sold short. " +
    trustBadge("official");
}

function renderStale() {
  const el = $("stale-banner");
  if (!D.stale) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the margin balances ' +
    "run through " + escapeHtml(week(D.rel.latest_period)) + ", older than the exchange's own " +
    "weekly cadence allows. If this persists, run the ingestion.</div>";
}

function renderProvenance() {
  const rel = D.rel;
  $("prov-cards").innerHTML =
    '<div class="prov-card">' +
    '<div class="prov-card-head">' +
      '<div class="prov-card-title">Outstanding Margin Transactions</div>' +
      '<div class="prov-card-id">' + escapeHtml(rel.source_id || "") + "</div>" +
    "</div>" +
    '<div class="prov-grid">' +
      '<div class="prov-field full">' +
        '<div class="prov-label">Official source</div>' +
        '<div class="prov-value"><a href="' + escapeHtml(rel.source_page || "#") +
          '" rel="noopener">' + escapeHtml(rel.source_name || "") + "</a></div>" +
        '<div class="prov-sub">Both long-run workbooks — by account and by kind of margin — ' +
        "archived together under one checksum. Each restates the same total, and the two are " +
        "reconciled at every ingest.</div>" +
      "</div>" +
      '<div class="prov-field">' +
        '<div class="prov-label">Release</div>' +
        '<div class="prov-value">Data through ' + escapeHtml(week(rel.latest_period)) + "</div>" +
        '<div class="prov-sub">Published weekly, by application date</div>' +
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
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' + escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + valueHtml + "</div>" +
    '<div class="strip-delta num ' + dir + '">' + deltaHtml + "</div>" +
    "</div>";
}

/* A signed change, with the sign printed. Direction is not P&L here: a rising
   margin balance is neither good nor bad, so the arrow carries no colour
   meaning beyond up and down. */
function delta(v, dp, unit) {
  if (v === null || v === undefined) return { html: MISSING, dir: "flat" };
  const rounded = Number(v.toFixed(dp));
  const dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
  const arrow = rounded === 0 ? ""
    : '<span aria-hidden="true">' + (rounded > 0 ? "▲" : "▼") + "</span> " +
      '<span class="visually-hidden">' + (rounded > 0 ? "up " : "down ") + "</span>";
  return { html: arrow + fmtNum(Math.abs(rounded), dp) + " " + unit, dir: dir };
}

function ratioAt(period) {
  const buy = at(code("total", "purchases", "shares"), period);
  const sell = at(code("total", "sales", "shares"), period);
  return buy === null || sell === null || sell === 0 ? null : buy / sell;
}

function renderTiles() {
  const latest = D.rel.latest_period;
  const prior = weekBefore(latest);
  const cells = [];
  SIDES.forEach(s => {
    const now = at(code("total", s.side, "shares"), latest);
    const was = prior === null ? null : at(code("total", s.side, "shares"), prior);
    const d = delta(now === null || was === null ? null : (now - was) / 1000, 1, "m shares");
    cells.push(tileCell(s.label,
      fmtNum(now === null ? null : now / 1000, 1) + '<span class="unit">m shares</span>',
      d.html, d.dir,
      "Total outstanding balance, published in thousands of shares and shown in millions. " +
      "Week of " + week(latest) + "."));
  });
  const r = ratioAt(latest), rWas = prior === null ? null : ratioAt(prior);
  const dr = delta(r === null || rWas === null ? null : r - rWas, 2, "×");
  cells.push(tileCell("Margin Ratio (信用倍率)",
    fmtNum(r, 2) + '<span class="unit">×</span>', dr.html, dr.dir,
    "Shares bought on margin ÷ shares sold short — the 信用倍率. Calculated from the two " +
    "published balances."));
  const yen = at(code("total", "purchases", "value"), latest);
  const yenWas = prior === null ? null : at(code("total", "purchases", "value"), prior);
  const dy = delta(yen === null || yenWas === null ? null : (yen - yenWas) / 1e6, 2, "¥tn");
  cells.push(tileCell("Long Balance, Value",
    fmtNum(yen === null ? null : yen / 1e6, 2) + '<span class="unit">¥tn</span>',
    dy.html, dy.dir,
    "Value of the total margin-buy balance, published in ¥ million and shown in ¥ trillion. " +
    "Struck at contract prices, not marked to market."));
  $("tiles").className = "strip-grid cols-4";
  $("tiles").innerHTML = cells.join("");
  $("strip-foot").innerHTML =
    "Balances are official figures as published by JPX, at the week's application date " +
    "(申込日). " + trustBadge("official") +
    " The ratio and every change above are calculated.";
  $("strip-calc").innerHTML = "<summary>Show calculation</summary><p>" +
    escapeHtml(RATIO_CALC) + "</p><p>" + escapeHtml(CHANGE_CALC) + "</p>";
}

/* ---- balances chart ---- */

let balChart = null;

function periodsIn(range) {
  const from = cutoff(range);
  return weeks(code("total", "purchases", "shares")).filter(p => !from || p >= from);
}

function renderBalances() {
  const st = urlState();
  const u = UNITS[st.unit];
  const periods = periodsIn(st.range);
  const cfg = {
    series: SIDES.map(s => ({
      name: s.label, slot: s.slot,
      points: periods.map(p => {
        const v = at(code("total", s.side, st.unit), p);
        return [p, v === null ? null : v / u.divisor];
      }),
    })),
    unitSuffix: u.suffix, dp: u.dp, yAxisName: u.axis, isoPeriods: true,
    trust: "official", legendFloor: 760,
    eventLines: st.range === "max" ? [MARKET_BREAK] : [],
    sourceLine: "Source: Japan Exchange Group — Outstanding margin transactions (信用取引現在高). " +
      "Tokyo and Nagoya markets, weekly by application date. Data through " +
      week(D.rel.latest_period) + ".",
  };
  if (balChart) balChart.render(cfg); else balChart = obsChart($("bal-chart"), "line", cfg);
  $("bal-note").textContent = periods.length
    ? week(periods[0]) + " – " + week(periods[periods.length - 1]) : "";
  $("bal-source").innerHTML = escapeHtml(cfg.sourceLine) + " " + trustBadge("official");
  $("bal-calc").innerHTML = "<summary>Show calculation</summary><p>Published balances in " +
    escapeHtml(u.note) + ", exactly as released. Not computed here. Figures up to the " +
    "2013-07-12 application date cover the Tokyo, Osaka and Nagoya markets; from 2013-07-19 " +
    "they cover Tokyo and Nagoya. The step at that week is the change in coverage, not a " +
    "change in positioning, and it is marked on the chart rather than smoothed away.</p>";
  $("bal-csv").onclick = () => balChart.exportCSV("jpx-margin-balances.csv", csvHeader([
    "Measure: outstanding margin balance, total, in " + u.note,
    "Range: " + (st.range === "max" ? "full history" : "last " + st.range + " years"),
  ]));
  $("bal-png").onclick = () => balChart.exportPNG("jpx-margin-balances.png");
}

/* ---- ratio chart ---- */

let ratioChart = null;

function renderRatio() {
  const st = urlState();
  const periods = periodsIn(st.ratioRange);
  const cfg = {
    series: [{ name: "Margin ratio (信用倍率)", slot: 1,
               points: periods.map(p => [p, ratioAt(p)]) }],
    unitSuffix: "×", dp: 2, yAxisName: "Margin ratio — shares long ÷ shares short",
    isoPeriods: true, trust: "derived",
    refLine: { y: 1, label: "1× — long equals short" },
    eventLines: st.ratioRange === "max" ? [MARKET_BREAK] : [],
    sourceLine: "Calculated from published balances. Source: Japan Exchange Group — " +
      "Outstanding margin transactions (信用取引現在高). Data through " +
      week(D.rel.latest_period) + ".",
  };
  if (ratioChart) ratioChart.render(cfg);
  else ratioChart = obsChart($("ratio-chart"), "line", cfg);
  $("ratio-note").textContent = periods.length
    ? week(periods[0]) + " – " + week(periods[periods.length - 1]) : "";
  $("ratio-source").textContent = cfg.sourceLine;
  $("ratio-calc").innerHTML = "<summary>Show calculation</summary><p>" +
    escapeHtml(RATIO_CALC) + "</p>";
  $("ratio-csv").onclick = () => ratioChart.exportCSV("jpx-margin-ratio.csv", csvHeader([
    "Measure: margin ratio (信用倍率), calculated",
    "Formula: " + RATIO_CALC,
  ]));
  $("ratio-png").onclick = () => ratioChart.exportPNG("jpx-margin-ratio.png");
}

/* ---- detail table ---- */

function csvHeader(extra) {
  return [
    "Plover Analytics — margin balances (信用取引現在高), Japan Exchange Group",
    "Source: " + (D.rel.source_name || ""),
    "Official as published: every outstanding balance, in thousands of shares (千株) and " +
      "¥ million (百万円)",
    "Calculated: the margin ratio (信用倍率) and every change",
    "Coverage: Tokyo, Osaka and Nagoya to the 2013-07-12 application date; Tokyo and Nagoya from " +
      "2013-07-19",
    "Missing is empty, never 0",
    "Release: data through " + D.rel.latest_period + ", SHA-256 " + (D.rel.sha256 || ""),
    "Retrieved: " + (D.rel.retrieved_at || ""),
  ].concat(extra || []);
}

function cell(v, dp) { return v === null || v === undefined ? MISSING : fmtNum(v, dp); }

function renderCut() {
  const latest = D.rel.latest_period;
  const prior = weekBefore(latest);
  const rows = [];
  CUTS.forEach(cut => {
    rows.push({ head: cut.title });
    cut.rows.forEach(([stem, label]) => {
      const row = { label: label };
      ["purchases", "sales"].forEach(side => {
        const now = at(code(stem, side, "shares"), latest);
        const was = prior === null ? null : at(code(stem, side, "shares"), prior);
        row[side + "_shares"] = now;
        row[side + "_change"] = now === null || was === null ? null : now - was;
        row[side + "_value"] = at(code(stem, side, "value"), latest);
      });
      rows.push(row);
    });
  });

  $("cut-table").innerHTML =
    '<table class="data" data-no-enhance><thead><tr>' +
    "<th></th>" +
    '<th class="num">Long, k shares</th><th class="num">Long, week change</th>' +
    '<th class="num">Long, ¥mn</th>' +
    '<th class="num">Short, k shares</th><th class="num">Short, week change</th>' +
    '<th class="num">Short, ¥mn</th>' +
    "</tr></thead><tbody>" +
    rows.map(r => {
      if (r.head) {
        return '<tr class="group-row"><th colspan="7">' + escapeHtml(r.head) + "</th></tr>";
      }
      return "<tr><td>" + escapeHtml(r.label) + "</td>" +
        '<td class="num">' + cell(r.purchases_shares, 0) + "</td>" +
        '<td class="num">' + (r.purchases_change === null ? MISSING : fmtSigned(r.purchases_change, 0)) + "</td>" +
        '<td class="num">' + cell(r.purchases_value, 0) + "</td>" +
        '<td class="num">' + cell(r.sales_shares, 0) + "</td>" +
        '<td class="num">' + (r.sales_change === null ? MISSING : fmtSigned(r.sales_change, 0)) + "</td>" +
        '<td class="num">' + cell(r.sales_value, 0) + "</td></tr>";
    }).join("") + "</tbody></table>";

  $("cut-note").textContent = "Week of " + week(latest);
  $("cut-foot").innerHTML = "Levels are official as published " + trustBadge("official") +
    " — thousands of shares (千株) and ¥ million (百万円), never rescaled. The week change is " +
    "calculated. Each cut adds to the same published total.";
  $("cut-calc").innerHTML = "<summary>Show calculation</summary><p>" + escapeHtml(CHANGE_CALC) +
    "</p><p>The two cuts are of one balance: customers plus members' own account equals the " +
    "total, and negotiable plus standardised equals the same total. Both identities are " +
    "checked at every ingest, in both units and on both sides, and a file that breaks one is " +
    "not published.</p>";

  $("cut-csv").onclick = () => {
    const body = rows.filter(r => !r.head);
    const lines = csvHeader(["Week: " + latest, "Change: on the week before, " + prior])
      .map(l => "# " + l);
    lines.push("cut_row,long_k_shares,long_week_change,long_jpy_mn," +
               "short_k_shares,short_week_change,short_jpy_mn");
    body.forEach(r => {
      lines.push([r.label, r.purchases_shares, r.purchases_change, r.purchases_value,
                  r.sales_shares, r.sales_change, r.sales_value]
        .map(v => v === null || v === undefined ? "" :
          (typeof v === "number" ? v : '"' + String(v).replace(/"/g, '""') + '"')).join(","));
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    a.download = "jpx-margin-detail.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
}

/* ---- boot ---- */

function segment(id, attr, apply) {
  $(id).addEventListener("click", ev => {
    const b = ev.target.closest("button");
    if (!b) return;
    Array.from($(id).querySelectorAll("button")).forEach(x =>
      x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    apply(b.getAttribute(attr));
  });
}

function markSegment(id, attr, value) {
  Array.from($(id).querySelectorAll("button")).forEach(b =>
    b.setAttribute("aria-pressed", b.getAttribute(attr) === value ? "true" : "false"));
}

async function boot() {
  const st = urlState();
  markSegment("bal-unit", "data-unit", st.unit);
  markSegment("bal-range", "data-range", st.range);
  markSegment("ratio-range", "data-range", st.ratioRange);

  const meta = await getJSON(API + "/series");
  D.rel = meta.release;
  const health = await getJSON("/api/v1/catalog/health").catch(() => null);
  if (health) {
    const row = (health.datasets || []).find(d => d.dataset === "margin-jp");
    D.stale = !!(row && row.stale);
  }

  const codes = [];
  CUTS.forEach(cut => cut.rows.forEach(([stem]) =>
    ["purchases", "sales"].forEach(side =>
      ["shares", "value"].forEach(unit => {
        const c = code(stem, side, unit);
        if (!codes.includes(c)) codes.push(c);
      }))));
  await loadSeries(codes);

  renderHead();
  renderStale();
  renderTiles();
  renderBalances();
  renderRatio();
  renderCut();
  renderProvenance();

  segment("bal-unit", "data-unit", v => { setUrlState({ unit: v }); renderBalances(); });
  segment("bal-range", "data-range", v => { setUrlState({ range: v }); renderBalances(); });
  segment("ratio-range", "data-range", v => { setUrlState({ ratioRange: v }); renderRatio(); });
  initThemeToggle(() => { renderBalances(); renderRatio(); });
}

boot().catch(err => {
  $("stale-banner").innerHTML = '<div class="banner" role="alert">Data unavailable — ' +
    escapeHtml(err.message) + ". The last good state is unaffected; try reloading.</div>";
});
