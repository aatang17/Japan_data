/* Peer groups: one measure read across the companies a company trades beside.
   Data: /api/v1/equity/cohorts.

   The question this page answers is "is this number normal for a company like
   this?", so the distribution comes before the league table: a rank of 22 out
   of 31 says nothing until you can see whether the cohort is bunched or
   spread. Every figure is either as filed or calculated by this platform from
   filed inputs — the calculated ones carry their formula rather than a badge,
   and the cohort statistics carry theirs. Missing renders as —, never 0, and a
   company that does not report the measure is listed separately with the
   reason rather than ranked last.

   The URL carries the cohort, the measure, the order and the highlighted
   company, so any view here is a citable link. A custom basket is nothing but
   its codes in that URL; names for baskets live in this browser's own storage
   and never leave it. */
(function () {
  "use strict";

  var API = "/api/v1/equity/cohorts";
  var STORE = "obs.baskets.v1";
  var state = { cohort: "size:core30", metric: "roe_pct", order: "desc", company: "" };
  var catalogue = null, metrics = null, metricByKey = {}, chart = null, current = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) { return escapeHtml(String(s == null ? "" : s)); }

  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) {
        return r.json().then(
          function (b) { throw new Error(b.detail || (url + " -> " + r.status)); },
          function () { throw new Error(url + " -> " + r.status); });
      }
      return r.json();
    });
  }

  // ---- units ---------------------------------------------------------------
  // One precision per unit, applied everywhere the unit appears: the tiles,
  // the axis, the tooltip, the table and the export all read the same.
  function dpFor(unit) {
    if (unit === "×") return 2;
    if (unit === "¥") return 1;
    if (unit === "") return 0;
    return 1;
  }
  function fmtValue(v, unit) {
    if (v === null || v === undefined) return MISSING;
    if (unit === "¥") return "¥" + fmtNum(v / 1e9, 1) + "bn";
    if (unit === "×") return fmtNum(v, 2) + "×";
    if (unit === "%") return fmtNum(v, 1) + "%";
    if (unit === "years") return fmtNum(v, 1);
    return fmtNum(v, 0);
  }
  // A difference between two percentages is percentage points, never percent.
  function fmtGap(v, unit) {
    if (v === null || v === undefined) return MISSING;
    if (unit === "%") return fmtSigned(v, 1, "pp");
    if (unit === "¥") return (v < 0 ? MINUS : "+") + "¥" + fmtNum(Math.abs(v) / 1e9, 1) + "bn";
    return fmtSigned(v, dpFor(unit), unit === "×" ? "×" : "");
  }
  // The chart plots the raw values, so ¥ is plotted in billions to keep the
  // axis readable — the only place a unit is rescaled, and the axis says so.
  function chartScale(unit) { return unit === "¥" ? 1e9 : 1; }
  function chartUnit(unit) {
    if (unit === "¥") return "¥bn";
    if (unit === "years") return " yrs";
    return unit;
  }

  // ---- URL state -----------------------------------------------------------
  function readUrl() {
    var p = new URLSearchParams(location.search);
    if (p.get("cohort")) state.cohort = p.get("cohort");
    if (p.get("metric")) state.metric = p.get("metric");
    if (p.get("order") === "asc") state.order = "asc";
    if (p.get("c")) state.company = p.get("c").trim().toUpperCase();
  }
  function writeUrl() {
    var p = new URLSearchParams();
    p.set("cohort", state.cohort);
    p.set("metric", state.metric);
    if (state.order === "asc") p.set("order", "asc");
    if (state.company) p.set("c", state.company);
    history.replaceState(null, "", location.pathname + "?" + p.toString());
  }

  // ---- saved baskets (this browser only) -----------------------------------
  function loadBaskets() {
    try { return JSON.parse(localStorage.getItem(STORE)) || []; }
    catch (e) { return []; }
  }
  function saveBaskets(list) {
    try { localStorage.setItem(STORE, JSON.stringify(list)); } catch (e) { /* private mode */ }
  }
  function renderBaskets() {
    var wrap = $("b-saved"), list = loadBaskets();
    Array.prototype.slice.call(wrap.querySelectorAll(".chip")).forEach(function (c) { c.remove(); });
    wrap.hidden = list.length === 0;
    list.forEach(function (b) {
      var chip = document.createElement("span");
      chip.className = "chip";
      chip.innerHTML = "<span class='open'>" + esc(b.name) + "</span>" +
        "<span class='muted'>" + b.codes.length + "</span><button type='button' title='Forget this basket'>×</button>";
      chip.querySelector(".open").addEventListener("click", function () {
        $("b-codes").value = b.codes.join(", ");
        state.cohort = "codes:" + b.codes.join(",");
        writeUrl();
        load();
      });
      chip.querySelector("button").addEventListener("click", function () {
        saveBaskets(loadBaskets().filter(function (x) { return x.name !== b.name; }));
        renderBaskets();
      });
      wrap.appendChild(chip);
    });
  }
  function parseCodes(text) {
    return (text || "").split(/[^0-9A-Za-z]+/)
      .map(function (s) { return s.trim().toUpperCase(); })
      .filter(function (s) { return s.length === 4; });
  }

  // ---- pickers -------------------------------------------------------------
  function fillCohorts() {
    var sel = $("p-cohort");
    sel.innerHTML = "";
    catalogue.groups.forEach(function (g) {
      var og = document.createElement("optgroup");
      og.label = g.label + (g.restricted ? " (internal)" : "");
      g.cohorts.forEach(function (c) {
        var o = document.createElement("option");
        o.value = c.spec;
        o.textContent = c.label + "  (" + fmtNum(c.count, 0) + ")";
        og.appendChild(o);
      });
      sel.appendChild(og);
    });
    var og2 = document.createElement("optgroup");
    og2.label = "Your own";
    var o2 = document.createElement("option");
    o2.value = "codes:";
    o2.textContent = "Custom basket…";
    og2.appendChild(o2);
    sel.appendChild(og2);
    sel.value = state.cohort.indexOf("codes:") === 0 ? "codes:" : state.cohort;
  }

  function fillMetrics() {
    var sel = $("p-metric");
    sel.innerHTML = "";
    metrics.families.forEach(function (f) {
      var og = document.createElement("optgroup");
      og.label = f.label;
      f.metrics.forEach(function (m) {
        metricByKey[m.metric] = m;
        var o = document.createElement("option");
        o.value = m.metric;
        o.textContent = m.label + (m.unit ? " (" + m.unit + ")" : "");
        og.appendChild(o);
      });
      sel.appendChild(og);
    });
    sel.value = state.metric;
  }

  function syncBasketLane() {
    var isBasket = state.cohort.indexOf("codes:") === 0;
    $("basket").hidden = !isBasket;
    if (isBasket && !$("b-codes").value) {
      $("b-codes").value = state.cohort.slice("codes:".length).split(",").join(", ");
    }
  }

  // ---- render --------------------------------------------------------------
  function tile(label, value, foot, title) {
    return "<div class='strip-cell'><div class='strip-label' title='" + esc(title || label) + "'>" +
      esc(label) + "</div><div class='strip-value'>" + value + "</div>" +
      "<div class='strip-delta flat'>" + (foot || "&nbsp;") + "</div></div>";
  }

  function renderTiles(d) {
    var unit = d.metric.unit, s = d.distribution, h = d.highlight;
    var iqr = (s.p25 === null || s.p75 === null) ? MISSING
      : fmtValue(s.p25, unit) + " to " + fmtValue(s.p75, unit);
    var cells = [
      tile("Cohort median", fmtValue(s.median, unit),
           d.metric.label + " across " + fmtNum(s.count, 0) + " companies",
           "Median " + d.metric.label + " in this peer group"),
      tile("Middle half", iqr, "25th to 75th percentile",
           "The range the middle half of the peer group falls in"),
      tile("Companies", fmtNum(d.members, 0),
           d.without_value ? fmtNum(d.without_value, 0) + " do not report this" : "all report this",
           "Members of this peer group"),
    ];
    if (h && h.value !== null && h.value !== undefined) {
      cells.push(tile(h.name_en || h.name || h.sec_code,
        fmtValue(h.value, unit),
        "Rank " + fmtNum(h.rank, 0) + " of " + fmtNum(h.of, 0) +
        " · " + fmtGap(h.vs_median, unit) + " vs median",
        "The highlighted company's reading against this peer group"));
    } else if (h) {
      cells.push(tile(h.sec_code, MISSING, esc(h.reason || "no value"),
        "The highlighted company"));
    } else {
      var span = (s.min === null) ? MISSING : fmtValue(s.min, unit) + " to " + fmtValue(s.max, unit);
      cells.push(tile("Full range", span, "lowest to highest in the group",
        "The whole peer group's range"));
    }
    $("tiles").innerHTML = cells.join("");
  }

  // ---- plotted window ------------------------------------------------------
  // A handful of metrics have tails that no equal-width binning survives:
  // operating margin over 222 electrical-machinery makers runs from a
  // four-figure negative to a four-figure positive, and the whole cohort
  // collapses into one bar. The window is the 1st to 99th percentile of the
  // cohort's own values; anything beyond is counted in the end bars and
  // reported in the caption. Nothing is dropped, and a cohort with no tail is
  // left exactly as it is.
  function quantile(sorted, p) {
    if (!sorted.length) return null;
    if (sorted.length === 1) return sorted[0];
    var pos = (sorted.length - 1) * p, lo = Math.floor(pos), hi = Math.min(lo + 1, sorted.length - 1);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }
  function window_(values) {
    var v = values.slice().sort(function (a, b) { return a - b; });
    if (v.length < 20) return { min: null, max: null, clipped: 0 };
    var lo = quantile(v, 0.01), hi = quantile(v, 0.99);
    var span = v[v.length - 1] - v[0], inner = hi - lo;
    // Only clip where it changes the picture: if the tails are within half
    // again of the visible span there is nothing to gain by hiding them.
    if (!(span > 0) || inner <= 0 || span < inner * 1.5) return { min: null, max: null, clipped: 0 };
    var out = v.filter(function (x) { return x < lo || x > hi; }).length;
    return { min: lo, max: hi, clipped: out };
  }

  function renderChart(d) {
    var unit = d.metric.unit, k = chartScale(unit);
    var rows = d.rows.map(function (r) {
      return { sec_code: r.sec_code, name: r.name_en || r.name || r.sec_code, value: r.value / k };
    });
    var s = d.distribution;
    var scaled = (d.values || []).map(function (v) { return v / k; });
    var win = window_(scaled);
    current.plotWindow = win;
    var cfg = {
      // Every member's value drives the bars; `rows` only names them.
      values: scaled,
      min: win.min, max: win.max,
      rows: rows,
      unit: chartUnit(unit),
      dp: unit === "¥" ? 1 : dpFor(unit),
      metricLabel: d.metric.label,
      stats: { p25: s.p25 === null ? null : s.p25 / k,
               median: s.median === null ? null : s.median / k,
               p75: s.p75 === null ? null : s.p75 / k },
      highlight: null,
      trust: d.metric.trust,
      sourceLine: sourceLine(d),
    };
    var h = d.highlight;
    if (h && h.value !== null && h.value !== undefined) {
      cfg.highlight = { name: h.name_en || h.name || h.sec_code,
                        code: h.sec_code, value: h.value / k };
    }
    if (chart) chart.dispose();
    chart = obsChart($("dist-chart"), "dist", cfg);
  }

  function sourceLine(d) {
    return d.cohort.label + " · " + d.metric.label +
      " · " + fmtNum(d.with_value, 0) + " companies · " +
      "Classification: Japan Exchange Group. Measures: company filings on EDINET.";
  }

  function nameCell(r) {
    var main = r.name_en || r.name || r.sec_code;
    return "<div class='cell-name'><a href='company.html?code=" + esc(r.sec_code) + "'>" +
      esc(main) + "</a></div>";
  }

  function renderTable(d) {
    var unit = d.metric.unit;
    var head = "<thead><tr><th>Company</th><th>Code</th><th class='r'>" +
      esc(d.metric.label) + (unit ? " (" + esc(unit === "¥" ? "¥bn" : unit) + ")" : "") +
      "</th><th class='r'>Percentile</th><th class='r'>vs median</th><th>Reference period</th></tr></thead>";
    var body = d.rows.map(function (r) {
      var focus = d.highlight && d.highlight.sec_code === r.sec_code;
      var gap = (d.distribution.median === null) ? null : r.value - d.distribution.median;
      return "<tr class='" + (focus ? "is-focus" : "") + "'>" +
        "<td>" + nameCell(r) + "</td>" +
        "<td class='muted'>" + esc(r.sec_code) + "</td>" +
        "<td class='r'>" + fmtValue(r.value, unit) + "</td>" +
        "<td class='r'>" + fmtNum(r.percentile, 0) + "</td>" +
        "<td class='r'>" + fmtGap(gap, unit) + "</td>" +
        "<td class='muted'>" + esc((r.period_end || MISSING).slice(0, 10)) + "</td></tr>";
    }).join("");
    $("rank-table").innerHTML = head + "<tbody>" + body + "</tbody>";

    $("rank-note").textContent = fmtNum(d.with_value, 0) + " ranked" +
      (d.truncated ? " · showing the first " + d.rows.length : "");
    if (d.without_value) {
      var names = d.no_value.slice(0, 12).map(function (x) { return x.sec_code; }).join(", ");
      $("rank-missing").textContent = fmtNum(d.without_value, 0) +
        " member" + (d.without_value === 1 ? "" : "s") +
        " report no figure for this measure and are left out of the ranking rather than " +
        "counted as zero: " + names + (d.without_value > 12 ? ", …" : "") + ".";
    } else {
      $("rank-missing").textContent = "Every member of this peer group reports this measure.";
    }
  }

  function renderCalc(d) {
    var items = [];
    if (d.metric.formula) {
      items.push(["<b>" + esc(d.metric.label) + "</b> — " + esc(d.metric.formula)]);
    } else {
      items.push(["<b>" + esc(d.metric.label) + "</b> — as filed by the company; not recomputed."]);
    }
    items.push(["<b>Quartiles</b> — " + esc(d.calc.quartiles)]);
    items.push(["<b>Percentile</b> — " + esc(d.calc.percentile)]);
    items.push(["<b>vs median</b> — " + esc(d.calc.vs_median)]);
    $("calc-list").innerHTML = items.map(function (i) { return "<li>" + i[0] + "</li>"; }).join("");
  }

  function render(d) {
    current = d;
    renderTiles(d);
    // renderChart computes the plotted window and stashes it on `d`; the
    // caption below reads it, so the chart must be built first.
    renderChart(d);
    renderTable(d);
    renderCalc(d);
    $("page-asof").textContent = d.cohort.as_of
      ? "Classification as of " + d.cohort.as_of : "Basket · no classification date";
    $("dist-note").textContent = d.cohort.label;
    $("dist-sub").textContent = d.coverage_note + " " + d.as_of_note;
    $("dist-source").textContent = sourceLine(d);
    // The chart's grey rules are unlabelled on purpose (see charts.js); this
    // is where they are read.
    var s2 = d.distribution, u = d.metric.unit;
    var win = d.plotWindow || { clipped: 0 };
    $("dist-legend").textContent = s2.median === null ? "" :
      "Each bar counts companies. Grey rules mark the 25th percentile (" +
      fmtValue(s2.p25, u) + "), the median (" + fmtValue(s2.median, u) +
      ", solid) and the 75th percentile (" + fmtValue(s2.p75, u) + ")." +
      (d.highlight && d.highlight.value !== null && d.highlight.value !== undefined
        ? " The coloured rule and bar are " +
          (d.highlight.name_en || d.highlight.name || d.highlight.sec_code) + "." : "") +
      (win.clipped
        ? " The axis is cut to the 1st–99th percentile so the shape is visible; " +
          fmtNum(win.clipped, 0) + " compan" + (win.clipped === 1 ? "y falls" : "ies fall") +
          " outside it and " + (win.clipped === 1 ? "is" : "are") +
          " counted in the end bars. The table below carries every value in full." : "");
    $("strip-foot").textContent = d.metric.formula
      ? "Calculated by this platform: " + d.metric.formula
      : d.metric.label + " as filed by each company.";
    var restricted = $("restricted-note");
    restricted.hidden = d.cohort.public !== false;
    if (!restricted.hidden) {
      restricted.textContent = "Membership of " + d.cohort.label + " is the index provider's " +
        "copyrighted work. It is held here for internal comparison and is not published or " +
        "redistributed by this platform.";
    }
  }

  function fail(message) {
    $("tiles").innerHTML = "<div class='strip-cell state-error' style='grid-column:1/-1'>" +
      esc(message) + "</div>";
    $("dist-chart").innerHTML = "";
    $("rank-table").innerHTML = "";
    $("rank-missing").textContent = "";
  }

  function load() {
    syncBasketLane();
    if (state.cohort === "codes:" || !state.cohort) {
      fail("Enter at least one securities code to build a basket.");
      return;
    }
    var url = API + "/compare?cohort=" + encodeURIComponent(state.cohort) +
      "&metric=" + encodeURIComponent(state.metric) +
      "&order=" + encodeURIComponent(state.order) +
      "&limit=1000" +
      (state.company ? "&highlight=" + encodeURIComponent(state.company) : "");
    getJSON(url).then(render, function (e) { fail(e.message); });
  }

  // ---- wiring --------------------------------------------------------------
  function bind() {
    $("p-cohort").addEventListener("change", function () {
      state.cohort = this.value === "codes:"
        ? "codes:" + parseCodes($("b-codes").value).join(",") : this.value;
      if (state.cohort === "codes:") state.cohort = "codes:";
      writeUrl(); load();
    });
    $("p-metric").addEventListener("change", function () {
      state.metric = this.value; writeUrl(); load();
    });
    $("p-order").addEventListener("change", function () {
      state.order = this.value; writeUrl(); load();
    });
    var typing = null;
    $("p-company").addEventListener("input", function () {
      var v = this.value.trim().toUpperCase();
      clearTimeout(typing);
      typing = setTimeout(function () {
        state.company = v.length === 4 ? v : "";
        writeUrl(); load();
      }, 350);
    });
    $("b-codes").addEventListener("input", function () {
      var codes = parseCodes(this.value);
      clearTimeout(typing);
      var self = this;
      typing = setTimeout(function () {
        state.cohort = "codes:" + codes.join(",");
        writeUrl();
        if (codes.length) load(); else fail("Enter at least one securities code to build a basket.");
        void self;
      }, 400);
    });
    $("b-save").addEventListener("click", function () {
      var name = $("b-name").value.trim(), codes = parseCodes($("b-codes").value);
      if (!name || !codes.length) return;
      var list = loadBaskets().filter(function (b) { return b.name !== name; });
      list.push({ name: name, codes: codes });
      saveBaskets(list);
      $("b-name").value = "";
      renderBaskets();
    });
    $("dist-png").addEventListener("click", function () {
      if (chart) chart.exportPNG("peer-group-" + state.metric + ".png");
    });
    $("dist-csv").addEventListener("click", function () {
      if (!chart || !current) return;
      var d = current;
      chart.exportCSV("peer-group-" + state.metric + ".csv", [
        "Plover Analytics — peer group comparison",
        "Peer group: " + d.cohort.label + " (" + d.cohort.spec + ")",
        "Classification as of: " + (d.cohort.as_of || "n/a (basket)"),
        "Measure: " + d.metric.label + (d.metric.unit ? " in " + d.metric.unit : ""),
        "Values in the value column are in the measure's own unit" +
          (d.metric.unit === "¥" ? ", divided by 1,000,000,000 (¥bn)" : ""),
        d.metric.formula ? "Formula: " + d.metric.formula
                         : "As filed by each company; not recomputed.",
        "Cohort median: " + d.distribution.median + "; 25th: " + d.distribution.p25 +
          "; 75th: " + d.distribution.p75,
        d.coverage_note,
        d.as_of_note,
        "Classification: Japan Exchange Group, listed issue list.",
        "Measures: company filings on EDINET (Financial Services Agency of Japan).",
      ]);
    });
    initThemeToggle(function () { if (current) renderChart(current); });
  }

  readUrl();
  bind();
  renderBaskets();
  Promise.all([getJSON(API), getJSON(API + "/metrics")]).then(function (r) {
    catalogue = r[0]; metrics = r[1];
    fillCohorts(); fillMetrics(); syncBasketLane();
    load();
  }, function (e) { fail(e.message); });
})();
