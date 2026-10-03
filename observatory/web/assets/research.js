/* PloverResearch article pages, and the chart drawing the research desk
   shares with them.

   On an article page every chart is drawn from the data embedded in the page
   (#rs-data): the numbers as they stood on the version's publication date,
   frozen when it was published. Nothing here asks the API for live data, so
   a chart can never drift away from the text written about it. The desk
   (desk.js) calls the same researchChart.cfg() on live data while writing,
   so the preview and the published chart are drawn by one function. */
"use strict";

var researchChart = (function () {
  var MEASURE_CAPTION = {
    yoy: "% change on a year earlier",
    mom: "% change on the previous month",
    ann3m: "% three-month change, annualised",
  };

  function caption(snap) {
    return MEASURE_CAPTION[snap.measure] || snap.unit || "";
  }

  function sourceLine(snap) {
    var rel = snap.release || {};
    var parts = [snap.credit || "", rel.source_name || "",
                 rel.label ? "Release " + rel.label : "",
                 snap.as_of ? "Data as of " + snap.as_of : "Live data",
                 snap.trust === "official" ? "Values as published" : ""];
    return parts.filter(function (p) { return p && p.trim(); })
      .map(function (p) { return p.trim().replace(/\.$/, ""); }).join(" · ") + ".";
  }

  /* obsChart "line" config from a block and its observations response. */
  function cfg(block, snap) {
    var pct = snap.measure && snap.measure !== "index";
    return {
      series: snap.series.map(function (s, i) {
        return { name: s.name_en || s.code, slot: i + 1, points: s.points };
      }),
      unit: pct ? "%" : snap.unit,
      unitSuffix: pct ? "" : (snap.unit && snap.unit !== "index" ? snap.unit : ""),
      yAxisName: caption(snap),
      trust: null,   // research pages carry no trust badge; the source line says it
      sourceLine: (block.title ? block.title + " — " : "") + sourceLine(snap),
      isoPeriods: snap.frequency === "daily",
      dp: pct ? 1 : undefined,
    };
  }

  function draw(el, block, snap) {
    return obsChart(el, "line", cfg(block, snap));
  }

  /* A chart copied from a Plover page: the page's own kind and config, so it
     is drawn exactly as the page drew it. Rankings and distributions get the
     height their rows need. */
  function drawSnapshot(el, entry, fixedHeight) {
    var c = entry.cfg || {};
    var rows = (c.rows || c.items || []).length;
    if (!fixedHeight && (entry.kind === "rank" || entry.kind === "bar") && rows) {
      el.style.height = Math.max(320, Math.min(1400, rows * 24 + 80)) + "px";
    }
    var copy = JSON.parse(JSON.stringify(c));
    copy.trust = null;
    copy.sourceLine = (entry.title ? entry.title + " \u2014 " : "") + (entry.source || c.sourceLine || "");
    return obsChart(el, entry.kind, copy);
  }

  /* A thumbnail: the same chart with its axes, legend and tooltip taken away,
     so a list of notes reads as a row of small pictures of the data. */
  function strip(el) {
    var inst = window.echarts && echarts.getInstanceByDom(el);
    if (!inst) return;
    var o = inst.getOption();
    inst.setOption({
      animation: false,
      legend: (o.legend || []).map(function () { return { show: false }; }),
      tooltip: { show: false },
      grid: (o.grid || [{}]).map(function () { return { left: 4, right: 4, top: 8, bottom: 4, containLabel: false }; }),
      xAxis: (o.xAxis || []).map(function () { return { show: false }; }),
      yAxis: (o.yAxis || []).map(function () { return { show: false }; }),
      graphic: [],
      series: (o.series || []).map(function () {
        return { markPoint: { data: [] }, label: { show: false }, emphasis: { disabled: true } };
      }),
    });
  }

  return { cfg: cfg, draw: draw, drawSnapshot: drawSnapshot, strip: strip, sourceLine: sourceLine, caption: caption };
})();

(function articlePage() {
  // The desk loads this file for researchChart only; it owns its own toggle.
  if (!document.querySelector("main.rs-wrap")) return;
  var holder = document.getElementById("rs-data");
  // The theme toggle lives in the shared header on every research page,
  // including the list, which carries no chart data.
  var charts = {};
  var thumbs = [];
  initThemeToggle(function () {
    Object.keys(charts).forEach(function (k) { charts[k].render(); });
    thumbs.forEach(researchChart.strip);
  });
  if (!holder) return;
  var data;
  try { data = JSON.parse(holder.textContent); } catch (e) { return; }

  // Homepage and "More from" figures: the lead story's chart, Chart of the
  // Week and the thumbnails, each drawn from its article's frozen data.
  Object.keys(data.figures || {}).forEach(function (key) {
    var entry = data.figures[key];
    var el = document.querySelector('.rh-plot[data-fig="' + key + '"]');
    if (!el || !entry) return;
    var thumb = el.classList.contains("rh-plot-card");
    charts["fig:" + key] = entry.kind ? researchChart.drawSnapshot(el, entry, thumb)
      : researchChart.draw(el, entry.block, entry.snap);
    if (thumb) { thumbs.push(el); researchChart.strip(el); }
  });
  homeFilters();

  Object.keys(data.charts || {}).forEach(function (id) {
    var entry = data.charts[id];
    var el = document.querySelector('.rs-plot[data-chart="' + id + '"]');
    if (!el) return;
    charts[id] = entry.kind ? researchChart.drawSnapshot(el, entry) : researchChart.draw(el, entry.block, entry.snap);
  });

  // Download CSV for a chart copied from a Plover page: its own data, with
  // the page, the source and the capture date in the header.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-csv]");
    if (!btn) return;
    var id = btn.getAttribute("data-csv");
    var entry = data.charts[id];
    if (!charts[id] || !entry) return;
    var n = btn.closest("figure") ? btn.closest("figure").id : "chart";
    charts[id].exportCSV((data.slug || "plover-research") + "-v" + data.version + "-" + n + ".csv", [
      "PloverResearch — " + (entry.title || ""),
      entry.source || "",
      "Copied from " + location.origin + entry.url,
      "Blank cells are missing values, never zero.",
    ]);
  });

  // Download PNG: the export menu (size, copy, download) every chart on the
  // platform uses, light theme and source line included.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-png]");
    if (!btn) return;
    var id = btn.getAttribute("data-png");
    if (!charts[id]) return;
    var n = btn.closest("figure") ? btn.closest("figure").id : "chart";
    charts[id].exportPNG((data.slug || "plover-research") + "-v" + data.version + "-" + n + ".png");
  });

  // In-page links (footnotes): the page sets <base href="/"> so the shared
  // header's relative links work, which would send "#fn-1" to the home page.
  document.addEventListener("click", function (e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a) return;
    var target = document.getElementById(a.getAttribute("href").slice(1));
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ block: "center" });
    history.replaceState(null, "", location.pathname + a.getAttribute("href"));
    target.classList.add("rs-flash");
    setTimeout(function () { target.classList.remove("rs-flash"); }, 1200);
  });

  /* Market tabs on the homepage cards. The choice is kept in the address
     (?market=jp) so a filtered view can be shared. */
  function homeFilters() {
    var list = document.getElementById("rh-list");
    if (!list || !document.querySelector(".rh-tabs")) return;
    var market = new URLSearchParams(location.search).get("market") || "";
    function apply() {
      var shown = 0;
      Array.prototype.forEach.call(list.querySelectorAll(".rh-card"), function (card) {
        card.hidden = !!market && card.getAttribute("data-market") !== market;
        if (!card.hidden) shown++;
      });
      document.getElementById("rh-none").hidden = shown > 0;
      Array.prototype.forEach.call(document.querySelectorAll(".rh-tabs [data-market]"), function (b) {
        b.setAttribute("aria-pressed", String(b.getAttribute("data-market") === market));
      });
      var q = new URLSearchParams(location.search);
      if (market) q.set("market", market); else q.delete("market");
      var qs = q.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
      window.dispatchEvent(new Event("resize"));   // cards that were hidden
    }
    document.addEventListener("click", function (e) {
      var m = e.target.closest(".rh-tabs [data-market]");
      if (m) { market = m.getAttribute("data-market"); apply(); }
      else if (e.target.id === "rh-clear") { market = ""; apply(); }
    });
    apply();
  }

  var link = document.getElementById("rs-copy-link");
  if (link) {
    link.addEventListener("click", function () {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(link.getAttribute("data-url")).then(function () {
        link.classList.add("done");
        link.setAttribute("title", "Link copied");
        setTimeout(function () { link.classList.remove("done"); link.setAttribute("title", "Copy link"); }, 1600);
      });
    });
  }
  var printBtn = document.getElementById("rs-print");
  if (printBtn) printBtn.addEventListener("click", function () { window.print(); });

  var copy = document.getElementById("rs-cite-copy");
  if (copy) {
    copy.addEventListener("click", function () {
      var text = document.getElementById("rs-cite").textContent;
      var done = function () { copy.textContent = "Copied"; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () {});
      }
    });
  }
})();
