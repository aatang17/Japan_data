/* Vote weight by constituency — House of Councillors.

   The screen answers one question: how much more is one vote worth in the
   best-served constituency than in the worst? Everything else on the page
   exists to let a reader argue with that number rather than take it —
   which denominator it was computed on, how much the one estimated input
   moves it, and how far the map has drifted since it was drawn.

   Three kinds of fact are combined, and the page keeps them apart:

   - the seat complement is law (公職選挙法 別表第三), not a statistic. It
     has no vintage and carries its own citation;
   - the population counts are official statistics, served unchanged by
     population-jp and population-jp-history;
   - electors per seat, vote weight, disparity and the shares are all
     calculated here from those two, and every one of them shows its
     formula.

   One payload feeds the whole page. The ranking, the headline, the
   sensitivity block and the drift line are four views of one calculation,
   and fetching them separately could show four inconsistent numbers. */
"use strict";

var DATA = null;
var rankChart = null;
var driftChart = null;

var ENDPOINT = "/api/v1/representation/councillors";

/* ---------- url state ---------- */

function urlState() {
  var p = new URLSearchParams(location.search);
  var base = p.get("base");
  var known = (DATA ? DATA.bases : []).map(function (b) { return b.key; });
  return {
    base: known.indexOf(base) >= 0 ? base : "adults18",
    sort: p.get("sort") || "per_seat",
    dir: p.get("dir") === "asc" ? "asc" : "desc",
  };
}

function setUrlState(next) {
  var s = Object.assign(urlState(), next);
  var p = new URLSearchParams();
  if (s.base !== "adults18") p.set("base", s.base);
  if (s.sort !== "per_seat") p.set("sort", s.sort);
  if (s.dir !== "desc") p.set("dir", s.dir);
  var qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

/* ---------- small helpers ---------- */

function $(id) { return document.getElementById(id); }

function fmtCount(v) { return v === null || v === undefined ? MISSING : fmtNum(v, 0); }
function fmtTimes(v) { return v === null || v === undefined ? MISSING : fmtNum(v, 2) + "×"; }
function fmtWeight(v) { return v === null || v === undefined ? MISSING : fmtNum(v, 2); }

function period() { return DATA.period; }
function yearOf(iso) { return iso.slice(0, 4); }

/* The two lines the ranking is read against. The national average is where
   the chamber would sit if seats followed people exactly; twice the
   best-served district is the threshold the litigation has turned on. */
function rankRules() {
  var s = DATA.summary;
  // The two rules sit close together on the axis, so the second label is
  // staggered a line up rather than printed over the first.
  return [
    { value: s.best_served.per_seat * 2, text: "2× best served" },
    { value: s.per_seat_national, text: "National average", stagger: true },
  ];
}

function sourceLine(extra) {
  var rel = DATA.release;
  return [
    rel.source_name,
    "register at " + fmtPeriodLong(period()),
    "seats: " + DATA.seat_table.law,
    "release " + rel.label,
    extra,
  ].filter(Boolean).join(" · ");
}

/* ---------- head, tiles, staleness ---------- */

function renderStale() {
  var el = $("stale-banner");
  if (!DATA.stale) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="banner" role="alert">This surface is stale: the newest ' +
    "ingested register year is " + fmtPeriodLong(DATA.release.latest_period) +
    ", ingested " + fmtStamp(DATA.release.ingested_at) +
    ". The ministry publishes each January count in late July — if this " +
    "persists, run the ingestion.</div>";
}

function renderHead() {
  $("page-asof").textContent = "As of " + fmtPeriodLong(period());
  $("page-sub").textContent =
    "The " + DATA.seat_table.seats + " prefectural seats of the " +
    "House of Councillors against the people entitled to fill them, on the " +
    "Basic Resident Register at 1 January " + yearOf(period()) + ". " +
    "The other " + DATA.seat_table.seats_proportional + " seats are elected " +
    "from a single nationwide list and no prefecture's population bears on them.";
  if (DATA.credit_line) $("credit-line").textContent = DATA.credit_line;
}

/* Direction is carried by the sign and the label, never by colour: a district
   being over-represented is not a gain and being under-represented is not a
   loss. The explanation goes on the title, because a tile label never wraps. */
function tileCell(label, value, sub, title) {
  return '<div class="strip-cell">' +
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' +
      escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + value + "</div>" +
    '<div class="strip-delta num flat">' + (sub || "") + "</div>" +
    "</div>";
}

function renderTiles() {
  var s = DATA.summary;
  var base = DATA.base;

  $("tiles").innerHTML =
    tileCell("Widest Disparity", fmtTimes(s.max_disparity),
      escapeHtml(s.worst_served.name_en + " vs " + s.best_served.name_en),
      "The most diluted constituency against the least: " +
        fmtCount(s.worst_served.per_seat) + " electors per seat in " +
        s.worst_served.name_en + ", " + fmtCount(s.best_served.per_seat) +
        " in " + s.best_served.name_en + ". Counted as " + base.label + ".") +
    tileCell("Electors per Seat", fmtCount(s.per_seat_national),
      "National average",
      "Every elector on this basis divided by all " + s.seats +
        " prefectural seats — where the chamber would sit if seats " +
        "followed people exactly.") +
    tileCell("Above Twice the Best", String(s.districts_over_2x),
      "of " + s.districts + " constituencies",
      "Constituencies where an elector's vote is worth less than half of one " +
        "cast in " + s.best_served.name_en + ". " + s.districts_over_3x +
        " are above three times.") +
    tileCell("Electors Counted", fmtCount(s.electorate),
      escapeHtml(base.label),
      base.estimated
        ? "This basis estimates one quantity — the two single years 18 " +
          "and 19, taken as two-fifths of the published 15–19 band. " +
          "Every other year is a published count."
        : "Published counts only; nothing on this basis is estimated.");

  $("strip-foot").textContent =
    "Counts of residents are official statistics exactly as published, and the " +
    "seat complement is fixed in law; electors per seat, vote weight and " +
    "disparity are calculated from them. One vote in " +
    s.worst_served.name_en + " is worth " +
    fmtNum(1 / s.max_disparity, 2) + " of one cast in " +
    s.best_served.name_en + ", counting " + base.label + " at 1 January " +
    yearOf(period()) + ".";

  var calc = $("strip-calc");
  calc.style.display = "";
  calc.innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body">' +
      "<code>" + escapeHtml(DATA.calc) + "</code><br><br>" +
      "<b>" + escapeHtml(base.label) + ".</b> " + escapeHtml(base.formula) +
      "<br><br>" + escapeHtml(DATA.seat_table.note) +
      "<br><br>Inputs: official counts from release “" +
      escapeHtml(DATA.release.label) + "” (sha256 " +
      DATA.release.sha256.slice(0, 12) + "…); seat complement from " +
      escapeHtml(DATA.seat_table.law) + ", in force since " +
      fmtPeriodLong(DATA.seat_table.in_force_from) + ", last checked " +
      fmtPeriodLong(DATA.seat_table.checked) + ".</div>";
}

/* ---------- the ranking ---------- */

function rankConfig() {
  var rows = DATA.rows.filter(function (r) { return r.per_seat !== null; });
  return {
    items: rows.map(function (r) {
      return {
        name: r.name_en,
        value: r.per_seat,
        sub: fmtCount(r.electorate) + " electors ÷ " + r.seats + " seats" +
          (r.merged ? " (merged constituency)" : ""),
        note: "One vote here is worth " + fmtWeight(r.vote_weight) +
          " of one in " + DATA.summary.best_served.name_en +
          " (" + fmtTimes(r.disparity) + " disparity)",
      };
    }),
    rows: rows,
    columns: [
      { key: "name_en", label: "constituency" },
      { key: "seats", label: "seats" },
      { key: "electorate", label: "electors (" + DATA.base.key + ")" },
      { key: "per_seat", label: "electors_per_seat" },
      { key: "vote_weight", label: "vote_weight" },
      { key: "disparity", label: "disparity_x" },
    ],
    unit: "",
    dp: 0,
    valueLabel: "Electors per seat",
    xAxisName: "Electors per seat — " + DATA.base.label,
    rules: rankRules(),
    trust: "derived",
    sourceLine: sourceLine(),
  };
}

function csvHeader(extra) {
  var rel = DATA.release;
  return [
    "Plover Analytics — vote weight, House of Councillors prefectural constituencies",
    "Denominator: " + DATA.base.label + " (" + DATA.base.key + ")",
    "Formula: " + DATA.base.formula,
    "Calculation: " + DATA.calc,
    "Reference date: " + period() + " (Basic Resident Register, 1 January)",
    "Seats: " + DATA.seat_table.law + ", in force from " +
      DATA.seat_table.in_force_from + ", last checked " + DATA.seat_table.checked,
    "Source: " + rel.source_name + " · release " + rel.label +
      " · sha256 " + rel.sha256,
    "Trust: counts of residents are official statistics as published; the seat " +
      "complement is fixed in law; every ratio here is derived and its formula is above.",
    "Retrieved: " + new Date().toISOString(),
    "Permalink: " + location.href,
  ].concat(extra || []);
}

function renderRank() {
  var cfg = rankConfig();
  if (rankChart) rankChart.render(cfg);
  else rankChart = obsChart($("rank-chart"), "rank", cfg);

  $("rank-note").textContent = DATA.summary.districts + " constituencies · " +
    DATA.seat_table.seats + " seats · " + fmtPeriodLong(period());
  $("rank-source").textContent = sourceLine("Electors per seat is derived");
  $("rank-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(DATA.calc) + "</code><br><br>" +
    "<b>" + escapeHtml(DATA.base.label) + ".</b> " + escapeHtml(DATA.base.formula) +
    "<br><br>The dashed rules are <code>national average = total electors ÷ " +
    DATA.seat_table.seats + " seats</code> and <code>2 × the fewest " +
    "electors per seat of any constituency</code>.</div>";
}

/* ---------- sensitivity to the denominator ---------- */

function renderSensitivity() {
  var st = urlState();
  var head = "<thead><tr>" +
    '<th scope="col">Counted as</th>' +
    '<th scope="col" class="num">Electors</th>' +
    '<th scope="col" class="num">Widest disparity</th>' +
    '<th scope="col">Worst served</th>' +
    '<th scope="col">Best served</th>' +
    "</tr></thead>";
  var body = DATA.sensitivity.map(function (r) {
    var current = r.base === st.base;
    return "<tr" + (current ? ' aria-current="true"' : "") + ">" +
      "<td>" + escapeHtml(r.label) +
        (r.estimated ? ' <span class="tag-note">Estimated</span>' : "") + "</td>" +
      '<td class="num">' + fmtCount(r.electorate) + "</td>" +
      '<td class="num">' + fmtTimes(r.max_disparity) + "</td>" +
      "<td>" + escapeHtml(r.worst_served || MISSING) + "</td>" +
      "<td>" + escapeHtml(r.best_served || MISSING) + "</td>" +
      "</tr>";
  }).join("");
  $("sens-table").innerHTML = head + "<tbody>" + body + "</tbody>";

  var byKey = {};
  DATA.sensitivity.forEach(function (r) { byKey[r.base] = r; });
  var gap = Math.abs(byKey.adults18.max_disparity - byKey.adults20.max_disparity);
  $("sens-note").textContent = "4 denominators · " + fmtPeriodLong(period());
  $("sens-foot").textContent =
    "Splitting the 15–19 band moves the headline by " + fmtNum(gap, 3) +
    "× — the difference between the estimated 18-and-over basis and " +
    "the 20-and-over basis, which splits nothing. The estimate is not what " +
    "produces the result. Counting everyone on the register rather than " +
    "Japanese adults gives " + fmtTimes(byKey.residents.max_disparity) +
    ", because foreign residents and children are not evenly spread: seats " +
    "are apportioned over residents, but only Japanese adults vote.";
  $("sens-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body">' +
    DATA.bases.map(function (b) {
      return "<b>" + escapeHtml(b.label) + "</b>" +
        (b.estimated ? " (estimated)" : "") + "<br>" +
        escapeHtml(b.formula);
    }).join("<br><br>") +
    "<br><br><code>" + escapeHtml(DATA.calc) + "</code></div>";
}

/* ---------- drift under a fixed map ---------- */

function renderDrift() {
  var points = DATA.history.points;
  if (!points.length) {
    $("drift-chart").innerHTML = '<p class="table-empty">No long-run panel is published, so the drift cannot be shown.</p>';
    return;
  }
  var byPeriod = {};
  points.forEach(function (p) { byPeriod[p.period] = p; });
  var cfg = {
    series: [{
      name: "Widest disparity",
      slot: 1,
      points: points.map(function (p) { return [p.period, p.max_disparity]; }),
    }],
    unit: "",
    unitSuffix: "×",
    dp: 3,
    yAxisDp: 2,
    yAxisName: "Widest disparity (×)",
    // The two dates the map itself moved. Everything between them is
    // population moving under a map that did not.
    eventLines: [
      { x: "2016-01-01", label: "2016 mergers" },
      { x: "2019-01-01", label: "2019 table", stagger: true },
    ],
    trust: "derived",
    sourceLine: DATA.history.credit_line + " · " +
      DATA.history.label + " (" + DATA.history.indicator + ") · " +
      "current seat map applied to every year · derived",
    isoPeriods: true,
  };
  if (driftChart) driftChart.render(cfg);
  else driftChart = obsChart($("drift-chart"), "line", cfg);

  var first = points[0], last = points[points.length - 1];
  var low = points.reduce(function (a, b) {
    return b.max_disparity < a.max_disparity ? b : a;
  }, points[0]);
  $("drift-note").textContent = yearOf(first.period) + "–" + yearOf(last.period) +
    " · " + points.length + " years";
  $("drift-source").textContent = cfg.sourceLine;
  $("drift-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(DATA.history.calc) + "</code><br><br>" +
    "Under the constituencies as they are drawn today, the widest disparity " +
    "was narrowest in " + yearOf(low.period) + " at " + fmtTimes(low.max_disparity) +
    " and stands at " + fmtTimes(last.max_disparity) + " in " + yearOf(last.period) +
    ". The most diluted constituency was " + escapeHtml(first.worst_served) +
    " in " + yearOf(first.period) + " and " + escapeHtml(last.worst_served) +
    " in " + yearOf(last.period) + "; " + escapeHtml(last.best_served) +
    " has been the least diluted throughout. A year with any prefecture " +
    "missing from the panel is left out rather than compared against a " +
    "different set of areas.</div>";
}

/* ---------- constituency detail ---------- */

var COLS = [
  { key: "name_en", label: "Constituency", num: false },
  { key: "seats", label: "Seats", num: true, dp: 0 },
  { key: "electorate", label: "Electors", num: true, dp: 0 },
  { key: "per_seat", label: "Electors per seat", num: true, dp: 0 },
  { key: "vote_weight", label: "Vote weight", num: true, dp: 2 },
  { key: "disparity", label: "Disparity", num: true, dp: 2, times: true },
  { key: "seat_share_pct", label: "Seat share %", num: true, dp: 2 },
  { key: "electorate_share_pct", label: "Elector share %", num: true, dp: 2 },
  { key: "over_representation_pp", label: "Over-represented pp", num: true, dp: 2, signed: true },
];

function cell(row, col) {
  var v = row[col.key];
  if (!col.num) {
    return '<td class="cell-item">' + escapeHtml(String(v)) +
      (row.merged ? ' <span class="tag-note">Merged</span>' : "") + "</td>";
  }
  if (v === null || v === undefined) {
    return '<td class="num" title="Not published for this constituency">' + MISSING + "</td>";
  }
  var text = col.signed ? fmtSigned(v, col.dp, "") : fmtNum(v, col.dp);
  if (col.times) text += "×";
  // The eye reads "3.13×" and "+0.76"; the sorter needs the bare number.
  return '<td class="num" data-sort="' + v + '">' + text + "</td>";
}

function renderTable() {
  var head = "<thead><tr>" + COLS.map(function (c) {
    return '<th scope="col"' + (c.num ? ' class="num"' : "") + ">" +
      escapeHtml(c.label) + "</th>";
  }).join("") + "</tr></thead>";
  var body = DATA.rows.map(function (r) {
    return "<tr>" + COLS.map(function (c) { return cell(r, c); }).join("") + "</tr>";
  }).join("");
  $("rep-table").innerHTML = '<table class="data tbl-series" data-filter-placeholder="Filter constituencies…">' + head +
    "<tbody>" + body + "</tbody></table>";

  var s = DATA.summary;
  $("table-note").textContent = s.districts + " constituencies · " +
    DATA.base.label + " · " + fmtPeriodLong(period());
  $("table-foot").textContent =
    "Seat shares sum to 100% and over-representation sums to zero across the " +
    "chamber, by construction. " + fmtCount(s.electorate) + " electors on this " +
    "basis across " + s.seats + " seats. Vote weight is 1.00 in " +
    s.best_served.name_en + ", the least diluted constituency, and every other " +
    "figure is the fraction of that vote.";
  $("table-calc").innerHTML = "<summary>Show calculation</summary>" +
    '<div class="calc-body"><code>' + escapeHtml(DATA.calc) + "</code><br><code>" +
    escapeHtml(DATA.share_calc) + "</code></div>";
}

function tableCsv() {
  var lines = csvHeader().map(function (l) { return "# " + l; });
  lines.push(COLS.map(function (c) { return '"' + c.label + '"'; }).join(","));
  DATA.rows.forEach(function (r) {
    lines.push(COLS.map(function (c) {
      var v = r[c.key];
      if (v === null || v === undefined) return "";
      return typeof v === "number" ? v : '"' + String(v).replace(/"/g, '""') + '"';
    }).join(","));
  });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
  a.download = "jdo-vote-weight-constituencies-" + DATA.base.key + "-" +
    period() + ".csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------- provenance ---------- */

function renderProvenance() {
  var rel = DATA.release;
  var t = DATA.seat_table;
  var rows = [
    ["Population source", rel.source_name],
    ["Release", rel.label],
    ["Reference date", fmtPeriodLong(rel.latest_period) + " (register, 1 January)"],
    ["Ingested", fmtStamp(rel.ingested_at)],
    ["Artifact sha256", rel.sha256.slice(0, 24) + "…"],
    ["Long-run panel", DATA.history.label + " (" + DATA.history.indicator + "), " +
      DATA.history.dataset],
    ["Seat complement", t.law],
    ["Seats in force from", fmtPeriodLong(t.in_force_from) + " · " +
      t.seats + " district seats across " + t.districts + " constituencies"],
    ["Seat table checked", fmtPeriodLong(t.checked)],
  ];
  var cites = t.sources.map(function (s) {
    return '<a href="' + escapeHtml(s.url) + '" rel="noopener">' +
      escapeHtml(s.label) + "</a>";
  }).join("<br>");
  $("prov-card").innerHTML =
    '<div class="prov-card">' +
      '<div class="prov-card-head">' +
        '<div class="prov-card-title">Data Source</div>' +
        '<div class="prov-card-id">' + escapeHtml(rel.source_id) + "</div>" +
      "</div>" +
      rows.map(function (r) {
        return '<div class="prov-row"><span class="prov-label">' + escapeHtml(r[0]) +
          '</span><span class="prov-value">' + escapeHtml(String(r[1])) + "</span></div>";
      }).join("") +
      '<p class="prov-sub">' + trustBadge("official") +
      " Counts of residents are the ministry's own, stored and served unchanged. " +
      "The seat complement is not a statistic and carries no vintage: it is the " +
      "figure fixed in law, held as a checked constant and cited below. Electors " +
      "per seat, vote weight, disparity and the shares are calculated on this " +
      "platform and each shows its formula." +
      "</p>" +
      '<p class="prov-sub">Seat table read from:<br>' + cites + "</p>" +
    "</div>";
}

/* ---------- controls ---------- */

function renderControls() {
  var st = urlState();
  var sel = $("base-select");
  sel.innerHTML = DATA.bases.map(function (b) {
    return '<option value="' + escapeHtml(b.key) + '"' +
      (b.key === st.base ? " selected" : "") + ">" + escapeHtml(b.label) +
      (b.estimated ? " (estimated)" : "") + "</option>";
  }).join("");
  sel.onchange = function () {
    setUrlState({ base: sel.value });
    load(sel.value);
  };

  $("rank-png").onclick = function () {
    rankChart.exportPNG("jdo-vote-weight-" + DATA.base.key + "-" + period() + ".png");
  };
  $("rank-csv").onclick = function () {
    rankChart.exportCSV(
      "jdo-vote-weight-ranking-" + DATA.base.key + "-" + period() + ".csv",
      csvHeader());
  };
  $("drift-png").onclick = function () {
    driftChart.exportPNG("jdo-vote-weight-drift-" + period() + ".png");
  };
  $("drift-csv").onclick = function () {
    driftChart.exportCSV("jdo-vote-weight-drift-" + period() + ".csv",
      csvHeader(["Series: widest disparity under the seat map in force today, " +
                 "applied to each year of " + DATA.history.label,
                 "Long-run source: " + DATA.history.credit_line]));
  };
  $("table-csv").onclick = tableCsv;
}

/* ---------- boot ---------- */

function renderAll() {
  renderStale();
  renderHead();
  renderTiles();
  renderControls();
  renderRank();
  renderSensitivity();
  renderDrift();
  renderTable();
  renderProvenance();
}

function load(base) {
  return fetch(ENDPOINT + "?base=" + encodeURIComponent(base))
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (payload) {
      DATA = payload;
      renderAll();
    })
    .catch(function (err) {
      $("page-sub").textContent =
        "This surface could not be loaded (" + err.message + "). The population " +
        "release it is built on may not be published yet.";
      $("tiles").innerHTML = "";
    });
}

(function boot() {
  var p = new URLSearchParams(location.search);
  var base = p.get("base") || "adults18";
  load(base);
  initThemeToggle(function () {
    if (rankChart) rankChart.render();
    if (driftChart) driftChart.render();
  });
})();
