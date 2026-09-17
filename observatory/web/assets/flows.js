/* Trading by investor type. The question this screen answers: "Who bought and
   who sold Japanese equities last week?"

   One dataset (investor-flows-jp): JPX's weekly 投資部門別売買状況. Sales and
   purchases are official figures exactly as published; the net — what a reader
   means by "foreigners bought ¥X" — is purchases minus sales, calculated here
   and carrying its formula on the page and in every export. A week the
   exchange did not publish is "—", never zero. */
"use strict";

const API = "/api/v1/investor-flows-jp";

const MARKETS = [
  { code: "two-markets", label: "Tokyo and Nagoya (all)" },
  { code: "prime", label: "TSE Prime" },
  { code: "standard", label: "TSE Standard" },
  { code: "growth", label: "TSE Growth" },
];

/* The full hierarchy JPX publishes, with the depth each row sits at. Every
   level adds to the one above it. */
const ROWS = [
  ["total", "Total", 0],
  ["proprietary", "Proprietary (member firms' own account)", 1],
  ["brokerage", "Brokerage (customer orders)", 1],
  ["institutions", "Institutions", 2],
  ["investment-trusts", "Investment trusts", 3],
  ["business-cos", "Business corporations", 3],
  ["other-cos", "Other corporations", 3],
  ["financials", "Financial institutions", 3],
  ["insurers", "Life and non-life insurers", 4],
  ["banks", "City and regional banks", 4],
  ["trust-banks", "Trust banks", 4],
  ["other-financials", "Other financial institutions", 4],
  ["individuals", "Individuals", 2],
  ["foreigners", "Foreigners", 2],
  ["securities-cos", "Securities companies", 2],
];

/* The six categories the chart plots — the ceiling for one chart, and the six
   a desk actually watches. Slot order is fixed so a category keeps its colour
   across every view. */
const PLOTTED = [
  { code: "foreigners", label: "Foreigners", slot: 1 },
  { code: "individuals", label: "Individuals", slot: 2 },
  { code: "trust-banks", label: "Trust banks", slot: 3 },
  { code: "business-cos", label: "Business corporations", slot: 4 },
  { code: "investment-trusts", label: "Investment trusts", slot: 5 },
  { code: "securities-cos", label: "Securities companies", slot: 6 },
];

const UNITS = {
  /* Published in ¥ thousand; shown in ¥ billion, an exact division by 1e6. */
  value: { divisor: 1e6, suffix: "¥bn", dp: 1,
           axis: "Net purchases, ¥ billion",
           note: "¥ thousand (千円) as published, shown in ¥ billion" },
  /* Published in thousands of shares; shown in millions, an exact division by 1e3. */
  volume: { divisor: 1e3, suffix: "m shares", dp: 1,
            axis: "Net purchases, millions of shares",
            note: "thousands of shares (千株) as published, shown in millions" },
};

const NET_CALC =
  "net[investor, t] = purchases[investor, t] − sales[investor, t], from published gross " +
  "figures. It equals the 差引き balance column JPX prints. Negative means net selling. A week " +
  "missing either side shows —, never zero.";

function $(id) { return document.getElementById(id); }

const D = { rel: null, stale: false, series: {}, weeks: [] };

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

function code(market, category, side, unit) {
  return [market, category, side, unit].join(".");
}
function pts(c) { return D.series[c] || []; }

function at(c, period) {
  const p = pts(c);
  for (let i = 0; i < p.length; i++) if (p[i][0] === period) return p[i][1];
  return null;
}

function net(market, category, unit, period) {
  const buy = at(code(market, category, "purchases", unit), period);
  const sell = at(code(market, category, "sales", unit), period);
  return buy === null || sell === null ? null : buy - sell;
}

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/* A weekly period is the Monday the week begins — a day, not a month, and
   never shown as one. */
function week(period) {
  if (!period) return MISSING;
  return Number(period.slice(8, 10)) + " " + MONTH_ABBR[Number(period.slice(5, 7)) - 1] +
    " " + period.slice(0, 4);
}
function weekShort(period) {
  return period ? Number(period.slice(8, 10)) + " " + MONTH_ABBR[Number(period.slice(5, 7)) - 1] : "";
}

/* ---- URL state ---- */

function urlState() {
  const p = new URLSearchParams(location.search);
  const m = MARKETS.find(x => x.code === p.get("market"));
  const w = MARKETS.find(x => x.code === p.get("wmarket"));
  return {
    market: m ? m.code : "two-markets",
    weekMarket: w ? w.code : "two-markets",
    unit: p.get("unit") === "volume" ? "volume" : "value",
  };
}

function setUrlState(next) {
  const s = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (s.market !== "two-markets") p.set("market", s.market);
  if (s.weekMarket !== "two-markets") p.set("wmarket", s.weekMarket);
  if (s.unit !== "value") p.set("unit", s.unit);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

/* ---- coverage, staleness, head ---- */

function renderCoverage() {
  const el = $("coverage");
  const first = D.weeks[0], last = D.weeks[D.weeks.length - 1];
  el.className = "coverage-bar" + (D.stale ? " is-stale" : "");
  el.innerHTML =
    (D.stale ? "<b>The weekly file has not advanced since " + escapeHtml(week(last)) +
       "</b>. Everything below is the record as it stood then. " : "") +
    "This record holds <b>" + fmtNum(D.weeks.length, 0) + " weeks</b>, " +
    escapeHtml(week(first)) + " to " + escapeHtml(week(last)) + ". " +
    "JPX keeps only the current month of weekly files on its site — the monthly page holds this " +
    "year and the annual page ten yearly totals — so <b>a weekly history of this series does not " +
    "exist to be downloaded</b>. This one begins when capture began and grows a week at a time.";
}

function renderStale() {
  const el = $("stale-banner");
  if (!D.stale) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the weekly investor ' +
    "survey runs through " + escapeHtml(week(D.rel.latest_period)) + ", older than the " +
    "exchange's own weekly cadence allows. If this persists, run the ingestion.</div>";
}

function renderHead() {
  const latest = D.rel.latest_period;
  const foreign = net("two-markets", "foreigners", "value", latest);
  const individuals = net("two-markets", "individuals", "value", latest);
  $("page-asof").textContent = "Week of " + week(latest);
  const asof = $("header-asof");
  if (asof) asof.textContent = week(latest);
  const verb = v => v === null ? "" : (v >= 0 ? "bought" : "sold");
  $("page-sub").innerHTML =
    "In the week beginning " + escapeHtml(week(latest)) + ", foreigners net " + verb(foreign) +
    " <strong class=\"num\">¥" + fmtNum(foreign === null ? null : Math.abs(foreign) / 1e6, 1) +
    "bn</strong> of Japanese equities on the Tokyo and Nagoya markets, while individuals net " +
    verb(individuals) + " ¥" +
    fmtNum(individuals === null ? null : Math.abs(individuals) / 1e6, 1) + "bn. " +
    "Net purchases are calculated from the published gross figures.";
}

function renderProvenance() {
  const rel = D.rel;
  $("prov-cards").innerHTML =
    '<div class="prov-card">' +
    '<div class="prov-card-head">' +
      '<div class="prov-card-title">Trading by Type of Investors</div>' +
      '<div class="prov-card-id">' + escapeHtml(rel.source_id || "") + "</div>" +
    "</div>" +
    '<div class="prov-grid">' +
      '<div class="prov-field full">' +
        '<div class="prov-label">Official source</div>' +
        '<div class="prov-value"><a href="' + escapeHtml(rel.source_page || "#") +
          '" rel="noopener">' + escapeHtml(rel.source_name || "") + "</a></div>" +
        '<div class="prov-sub">Every weekly workbook is archived under its own SHA-256 as it ' +
        "appears, because the exchange deletes it within the month. Two files publish each " +
        "week and both copies must agree before either is stored.</div>" +
      "</div>" +
      '<div class="prov-field">' +
        '<div class="prov-label">Release</div>' +
        '<div class="prov-value">Data through ' + escapeHtml(week(rel.latest_period)) + "</div>" +
        '<div class="prov-sub">Published weekly, on the Thursday after</div>' +
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

function renderTiles() {
  const latest = D.rel.latest_period;
  const prior = D.weeks.length > 1 ? D.weeks[D.weeks.length - 2] : null;
  const cells = PLOTTED.slice(0, 4).map(c => {
    const now = net("two-markets", c.code, "value", latest);
    const was = prior === null ? null : net("two-markets", c.code, "value", prior);
    const shown = now === null ? null : now / 1e6;
    /* The previous week's net, not a change in it: a change in a flow is a
       second derivative and means very little week to week. */
    const priorText = was === null ? MISSING
      : fmtSigned(was / 1e6, 1) + " ¥bn the week before";
    /* Deliberately unstyled: this line is the previous week's own net, not a
       change in it, so an up/down colour would be claiming a direction the
       number does not carry. */
    return tileCell(c.label + ", Net",
      fmtSigned(shown, 1) + '<span class="unit">¥bn</span>',
      escapeHtml(priorText), "flat",
      "Purchases less sales on the Tokyo and Nagoya markets, week of " + week(latest) +
      ". Calculated from published gross figures.");
  });
  $("tiles").className = "strip-grid cols-4";
  $("tiles").innerHTML = cells.join("");
  $("strip-foot").innerHTML =
    "Sales and purchases are official figures as published by JPX " + trustBadge("official") +
    " for the week beginning " + escapeHtml(week(latest)) +
    ". The net shown here is calculated from them.";
  $("strip-calc").innerHTML = "<summary>Show calculation</summary><p>" +
    escapeHtml(NET_CALC) + "</p>";
}

/* ---- net chart ---- */

let netChart = null;

function csvHeader(extra) {
  return [
    "Plover Analytics — weekly trading by investor type (投資部門別売買状況), Japan Exchange Group",
    "Source: " + (D.rel.source_name || ""),
    "Official as published: sales and purchases, in ¥ thousand (千円) and thousands of shares (千株)",
    "Calculated: net = purchases − sales, equal to the 差引き column JPX prints",
    "Survey: trading participants with capital of ¥3bn or more; domestic common stocks only; " +
      "ToSTNeT trades included",
    "Weeks are dated by the Monday they begin. Missing is empty, never 0",
    "Release: data through " + D.rel.latest_period + ", SHA-256 " + (D.rel.sha256 || ""),
    "Retrieved: " + (D.rel.retrieved_at || ""),
  ].concat(extra || []);
}

function renderNet() {
  const st = urlState();
  const u = UNITS[st.unit];
  const market = MARKETS.find(m => m.code === st.market);
  const cfg = {
    categories: D.weeks.map(weekShort),
    series: PLOTTED.map(c => ({
      name: c.label, slot: c.slot,
      points: D.weeks.map(p => {
        const v = net(st.market, c.code, st.unit, p);
        return v === null ? null : v / u.divisor;
      }),
    })),
    dp: u.dp, unitSuffix: u.suffix, yAxisName: u.axis, trust: "derived",
    legendFloor: 900, legendBottomNarrow: 96,
    sourceLine: "Calculated from published gross figures. Source: Japan Exchange Group — " +
      "Trading by type of investors (投資部門別売買状況), " + market.label + ". Weeks beginning " +
      week(D.weeks[0]) + " to " + week(D.weeks[D.weeks.length - 1]) + ".",
  };
  if (netChart) netChart.render(cfg); else netChart = obsChart($("net-chart"), "cols", cfg);
  $("net-note").textContent = market.label + " · " +
    weekShort(D.weeks[0]) + " – " + weekShort(D.weeks[D.weeks.length - 1]);
  $("net-source").textContent = cfg.sourceLine;
  $("net-calc").innerHTML = "<summary>Show calculation</summary><p>" + escapeHtml(NET_CALC) +
    "</p><p>Gross figures are published in " + escapeHtml(u.note) + ". Six categories are " +
    "plotted; every category the exchange publishes is in the table below and in the export.</p>";
  $("net-csv").onclick = () => netChart.exportCSV("jpx-investor-net.csv", csvHeader([
    "Market: " + market.label,
    "Measure: net purchases, " + u.note,
    "Formula: " + NET_CALC,
  ]));
  $("net-png").onclick = () => netChart.exportPNG("jpx-investor-net.png");
}

/* ---- latest week table ---- */

function cellNum(v, divisor, dp) {
  return v === null || v === undefined ? MISSING : fmtNum(v / divisor, dp);
}

function renderWeek() {
  const st = urlState();
  const latest = D.rel.latest_period;
  const market = MARKETS.find(m => m.code === st.weekMarket);
  const rows = ROWS.map(([cat, label, depth]) => ({
    label: label, depth: depth,
    sales: at(code(st.weekMarket, cat, "sales", "value"), latest),
    purchases: at(code(st.weekMarket, cat, "purchases", "value"), latest),
    net: net(st.weekMarket, cat, "value", latest),
    salesVol: at(code(st.weekMarket, cat, "sales", "volume"), latest),
    purchasesVol: at(code(st.weekMarket, cat, "purchases", "volume"), latest),
    netVol: net(st.weekMarket, cat, "volume", latest),
  }));

  $("week-table").innerHTML =
    '<table class="data" data-no-enhance><thead><tr><th>Investor type</th>' +
    '<th class="num">Sales, ¥bn</th><th class="num">Purchases, ¥bn</th>' +
    '<th class="num">Net, ¥bn</th>' +
    '<th class="num">Sales, m shares</th><th class="num">Purchases, m shares</th>' +
    '<th class="num">Net, m shares</th></tr></thead><tbody>' +
    rows.map(r =>
      "<tr><td style=\"padding-left:" + (12 + r.depth * 18) + "px\">" +
      escapeHtml(r.label) + "</td>" +
      '<td class="num">' + cellNum(r.sales, 1e6, 1) + "</td>" +
      '<td class="num">' + cellNum(r.purchases, 1e6, 1) + "</td>" +
      '<td class="num">' + (r.net === null ? MISSING : fmtSigned(r.net / 1e6, 1)) + "</td>" +
      '<td class="num">' + cellNum(r.salesVol, 1e3, 1) + "</td>" +
      '<td class="num">' + cellNum(r.purchasesVol, 1e3, 1) + "</td>" +
      '<td class="num">' + (r.netVol === null ? MISSING : fmtSigned(r.netVol / 1e3, 1)) + "</td>" +
      "</tr>").join("") + "</tbody></table>";

  $("week-note").textContent = market.label + " · week of " + week(latest);
  $("week-foot").innerHTML = "Sales and purchases are official as published " +
    trustBadge("official") + " — ¥ thousand and thousands of shares, shown here in ¥ billion " +
    "and millions of shares, exact divisions. The net is calculated.";
  $("week-calc").innerHTML = "<summary>Show calculation</summary><p>" + escapeHtml(NET_CALC) +
    "</p><p>Indentation is the exchange's own hierarchy: proprietary and brokerage add to the " +
    "total; institutions, individuals, foreigners and securities companies add to brokerage; " +
    "investment trusts, business corporations, other corporations and financial institutions " +
    "add to institutions; insurers, banks, trust banks and other financials add to financial " +
    "institutions. All four identities are checked at every ingest, in both units and on both " +
    "sides, and a file that breaks one is not published.</p>";

  $("week-csv").onclick = () => {
    const lines = csvHeader(["Market: " + market.label, "Week beginning: " + latest])
      .map(l => "# " + l);
    lines.push("investor_type,sales_jpy_thousand,purchases_jpy_thousand,net_jpy_thousand," +
               "sales_k_shares,purchases_k_shares,net_k_shares");
    rows.forEach(r => {
      lines.push(['"' + r.label.replace(/"/g, '""') + '"', r.sales, r.purchases, r.net,
                  r.salesVol, r.purchasesVol, r.netVol]
        .map(v => v === null || v === undefined ? "" : v).join(","));
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    a.download = "jpx-investor-week.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
}

/* ---- boot ---- */

function fillMarkets(id, selected) {
  $(id).innerHTML = MARKETS.map(m =>
    '<option value="' + m.code + '"' + (m.code === selected ? " selected" : "") + ">" +
    escapeHtml(m.label) + "</option>").join("");
}

async function codesFor(market) {
  const codes = [];
  ROWS.forEach(([cat]) =>
    ["sales", "purchases"].forEach(side =>
      ["value", "volume"].forEach(unit => codes.push(code(market, cat, side, unit)))));
  await loadSeries(codes);
}

async function boot() {
  const st = urlState();
  const meta = await getJSON(API + "/series");
  D.rel = meta.release;
  const health = await getJSON("/api/v1/catalog/health").catch(() => null);
  if (health) {
    const row = (health.datasets || []).find(d => d.dataset === "investor-flows-jp");
    D.stale = !!(row && row.stale);
  }

  fillMarkets("net-market", st.market);
  fillMarkets("week-market", st.weekMarket);
  Array.from($("net-unit").querySelectorAll("button")).forEach(b =>
    b.setAttribute("aria-pressed", b.getAttribute("data-unit") === st.unit ? "true" : "false"));

  await codesFor("two-markets");
  D.weeks = pts(code("two-markets", "total", "purchases", "value")).map(p => p[0]).sort();
  if (st.market !== "two-markets") await codesFor(st.market);
  if (st.weekMarket !== "two-markets" && st.weekMarket !== st.market) {
    await codesFor(st.weekMarket);
  }

  renderHead();
  renderStale();
  renderCoverage();
  renderTiles();
  renderNet();
  renderWeek();
  renderProvenance();

  $("net-market").onchange = async function () {
    setUrlState({ market: this.value });
    await codesFor(this.value);
    renderNet();
  };
  $("week-market").onchange = async function () {
    setUrlState({ weekMarket: this.value });
    await codesFor(this.value);
    renderWeek();
  };
  $("net-unit").addEventListener("click", ev => {
    const b = ev.target.closest("button");
    if (!b) return;
    Array.from($("net-unit").querySelectorAll("button")).forEach(x =>
      x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    setUrlState({ unit: b.getAttribute("data-unit") });
    renderNet();
  });
  initThemeToggle(() => renderNet());
}

boot().catch(err => {
  $("stale-banner").innerHTML = '<div class="banner" role="alert">Data unavailable — ' +
    escapeHtml(err.message) + ". The last good state is unaffected; try reloading.</div>";
});
