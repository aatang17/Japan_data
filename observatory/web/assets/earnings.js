/* Earnings releases (決算短信, TDnet): progress against each company's own
   forecast, the newest releases and the disclosure wire (market view), and one
   company's results, forecast, dividends and release history (company view).
   Data: /api/v1/equity/earnings/*. Amounts, per-share figures and year-on-year
   changes are official exactly as the company tagged them; progress, which
   release is current, and the fiscal period are calculated and say so.
   Results are cumulative from the start of the fiscal year. A result and a
   forecast never share a column. Missing renders as —, never 0. */
(function () {
  "use strict";

  var prState = { period: "q1", line: "operating_income", order: "desc" };
  var wiState = { kind: "forecast-revision" };
  var coverage = null;

  var PERIOD_LABEL = { q1: "Q1", q2: "Q2", q3: "Q3", "full-year": "Full year" };
  var PERIOD_SPAN = { q1: "3 months", q2: "6 months, cumulative", q3: "9 months, cumulative",
                      "full-year": "12 months" };
  var LINE_LABEL = { revenue: "Revenue", operating_income: "Operating income",
                     ordinary_income: "Ordinary income", profit: "Profit" };
  var KIND_LABEL = {
    "earnings": "Earnings", "forecast-revision": "Forecast revision",
    "dividend-forecast": "Dividend forecast", "dividend": "Dividend", "buyback": "Buyback",
    "treasury-shares": "Treasury shares", "tender-offer": "Tender offer",
    "share-split": "Share split", "stock-options": "Stock options",
    "third-party-allotment": "Third-party allotment", "shareholder-perk": "Shareholder perk",
    "personnel": "Personnel", "change": "Change notice", "presentation": "Presentation",
    "correction": "Correction", "other": "Other",
  };
  var BASIS_LABEL = { consolidated: "Consolidated", parent: "Non-consolidated" };
  var NATURE_LABEL = { result: "Paid", forecast: "Forecast",
                       "forecast-upper": "Forecast, upper", "forecast-lower": "Forecast, lower" };
  var FY_LABEL = { prior: "Prior fiscal year", current: "Current fiscal year",
                   next: "Next fiscal year" };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return escapeHtml(String(s == null ? "" : s)); }
  function count(v) { return v == null ? MISSING : fmtNum(v, 0); }
  function day(iso) { return iso ? String(iso) : MISSING; }
  // Yen amounts are shown in ¥ million, the unit the releases themselves print.
  function mn(v) { return v == null ? MISSING : fmtNum(v / 1e6, 0); }
  function yen(v, dp) { return v == null ? MISSING : fmtNum(v, dp == null ? 2 : dp); }
  // A growth rate is a percentage OF a level, so it is %, signed, not pp.
  function chg(v) { return v == null ? MISSING : fmtSigned(v, 1, "%"); }
  function prog(v) { return v == null ? MISSING : fmtNum(v, 1); }
  function fiscal(fp) { return fp ? "FY to " + fp : MISSING; }
  function stamp(d, t) { return esc(day(d)) + (t ? " " + esc(t) : ""); }

  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(url + " -> " + r.status);
      return r.json();
    });
  }

  function csvDownload(name, headerLines, cols, rows) {
    var lines = headerLines.map(function (l) { return "# " + l; });
    lines.push(cols.join(","));
    rows.forEach(function (r) {
      lines.push(r.map(function (v) {
        v = v == null ? "" : String(v);
        return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
      }).join(","));
    });
    var blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // Every export carries where the numbers came from, which are published and
  // which are calculated, and how deep the archive runs.
  function csvHeader(calc, extra) {
    var head = [
      "Plover Analytics — earnings releases (決算短信), TDnet, Tokyo Stock Exchange",
      "Source: the Summary of each company's 決算短信 as disclosed on TDnet",
      "Official as published: amounts in yen, per-share figures, yoy_pct_published " +
        "(the company's own year-on-year percentage), forecasts and their bounds",
      "Results are cumulative from the start of the fiscal year (q2 = 6 months, q3 = 9 months)",
      "Calculated: progress_pct = " + (calc ? calc.progress_pct : ""),
      "Calculated: is_current = " + (calc ? calc.is_current : ""),
      "Calculated: fiscal_period = " + (calc ? calc.fiscal_period : ""),
      "Missing is empty, never 0. A forecast the company did not give is empty.",
    ];
    if (coverage) {
      head.push("Archive: " + coverage.days_covered + " disclosure days, " +
                coverage.first_day + " to " + coverage.last_day +
                "; TDnet deletes disclosures after about a month");
    }
    head.push("Retrieved: " + new Date().toISOString());
    return head.concat(extra || []);
  }

  function nameCell(en, ja, href) {
    var primary = en || ja || MISSING;
    var link = href ? "<a href='" + href + "'>" + esc(primary) + "</a>" : esc(primary);
    return "<div class='cell-item'><div class='en'>" + link + "</div></div>";
  }

  function errorInto(id, e) {
    $(id).innerHTML = "<p class='sec-note'>Data unavailable — " + esc(e.message) +
      ". The last good state is unaffected; try reloading.</p>";
  }

  function pressed(group, attr, value) {
    Array.prototype.forEach.call(group.querySelectorAll("button"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute(attr) === value ? "true" : "false");
    });
  }

  // ---- coverage ------------------------------------------------------------
  // The depth of the archive is the completeness of everything on this page,
  // so it is stated at the top — and it goes loud when the wire stops arriving.
  function renderCoverage(el, c) {
    coverage = c;
    var last = c.last_day;
    var behind = last ? Math.round((Date.now() - Date.parse(last + "T00:00:00Z")) / 86400000) : null;
    var stale = behind == null || behind > 7;
    el.className = "coverage-bar" + (stale ? " is-stale" : "");
    el.innerHTML =
      (stale
        ? "<b>The wire has not advanced since " + esc(day(last)) + "</b> (" +
          count(behind) + " days). Everything below is the record as it stood then. "
        : "") +
      "This record holds <b>" + count(c.days_covered) + " disclosure days</b>, " +
      esc(day(c.first_day)) + " to " + esc(day(c.last_day)) + ", and " +
      count(c.disclosures) + " disclosures. TDnet keeps each one public for about a month and " +
      "then deletes it — there is no archive, no API and no second source, so " +
      "<b>nothing before " + esc(day(c.first_day)) + " can be recovered.</b>";
  }

  // ---- market view ---------------------------------------------------------
  function renderStrip(d) {
    var r = d.releases;
    renderCoverage($("coverage"), d.coverage);
    var top = d.by_period[0] || {};
    $("stat-strip").innerHTML =
      '<div class="strip-grid cols-4">' +
      cell("Releases held", count(r.releases) + '<span class="unit"> releases</span>',
           count(r.current_releases) + " are the newest for their period; the rest were " +
           "re-issued or corrected (calculated)") +
      cell("Companies", count(r.companies) + '<span class="unit"> companies</span>',
           "With at least one release read, " + day(r.first_filed_date) + " to " +
           day(r.last_filed_date)) +
      cell("Largest reporting group", count(top.current_releases) +
           '<span class="unit"> releases</span>',
           top.fiscal_period ? PERIOD_LABEL[top.period] + " of the fiscal year to " +
           esc(top.fiscal_period) : "") +
      cell("Archive depth", count(d.coverage.days_covered) + '<span class="unit"> days</span>',
           day(d.coverage.first_day) + " to " + day(d.coverage.last_day) +
           " — as published on TDnet") +
      "</div>";
    function cell(label, value, foot) {
      return '<div class="strip-cell"><div class="strip-label">' + label +
        '</div><div class="strip-value num">' + value +
        '</div><div class="strip-foot">' + foot + "</div></div>";
    }
  }

  function releaseTag(r) {
    return esc(PERIOD_LABEL[r.period] || r.period) + " · " + esc(fiscal(r.fiscal_period));
  }

  function renderProgress(d) {
    var rows = d.companies, line = d.line;
    $("pr-count").textContent = rows.length + " companies";
    $("pr-meta").innerHTML =
      "<b>" + esc(LINE_LABEL[line]) + "</b> for the " + esc(PERIOD_SPAN[d.period]) +
      " reported, against the company's own full-year forecast from the same release. " +
      "Companies are ranked within one reporting period only. Result and forecast are " +
      "<b>official</b> as published; progress is calculated. A company with no forecast, a " +
      "range, or a forecast at or below zero is not ranked.";
    $("pr-table").innerHTML =
      "<thead><tr><th>Company</th><th>Release</th>" +
      "<th class=r>Result (¥ mn)</th><th class=r>Full-year forecast (¥ mn)</th>" +
      "<th class=r>Progress (%)</th><th class=r>Result YoY, as published</th>" +
      "<th>Disclosed</th></tr></thead><tbody>" +
      rows.map(function (c) {
        return "<tr><td>" + nameCell(c.name_en, c.name, "earnings.html?c=" + esc(c.sec_code)) +
          "</td><td class=nowrap>" + releaseTag(c) +
          "</td><td class=r>" + mn(c[line]) +
          "</td><td class=r>" + mn(c[line + "_forecast"]) +
          "</td><td class=r data-sort='" + (c.sort_value == null ? "" : c.sort_value) + "'>" +
          prog(c.sort_value) +
          "</td><td class='r nowrap'>" + chg(c[line + "_yoy_pct_published"]) +
          "</td><td class=nowrap>" + stamp(c.filed_date) + "</td></tr>";
      }).join("") + "</tbody>";
    $("pr-formula").innerHTML = "<b>Progress (%)</b> = " + esc(d.calc.progress_pct) + ". " +
      esc(d.progress_note);
    $("pr-csv").onclick = function () {
      csvDownload("tdnet-earnings-progress.csv",
        csvHeader(d.calc, ["Ranked by: progress of " + line + ", period " + d.period +
                           ", order " + d.order]),
        ["sec_code", "name", "name_en", "fiscal_period", "period", "basis", line + "_element",
         line, line + "_forecast", "progress_pct", line + "_yoy_pct_published",
         "filed_date", "doc_key"],
        rows.map(function (c) {
          return [c.sec_code, c.name, c.name_en, c.fiscal_period, c.period, c.basis,
                  c[line + "_element"], c[line], c[line + "_forecast"], c.sort_value,
                  c[line + "_yoy_pct_published"], c.filed_date, c.doc_key];
        }));
    };
  }

  function renderRecent(d) {
    var rows = d.releases;
    $("re-count").textContent = rows.length + " newest";
    $("re-table").innerHTML =
      "<thead><tr><th>Company</th><th>Release</th>" +
      "<th class=r>Revenue (¥ mn)</th><th class=r>YoY</th>" +
      "<th class=r>Operating income (¥ mn)</th><th class=r>YoY</th>" +
      "<th class=r>Profit (¥ mn)</th><th class=r>YoY</th>" +
      "<th class=r>Op. income progress (%)</th><th>Disclosed</th></tr></thead><tbody>" +
      rows.map(function (c) {
        return "<tr><td>" + nameCell(c.name_en, c.name, "earnings.html?c=" + esc(c.sec_code)) +
          "</td><td class=nowrap>" + releaseTag(c) +
          "</td><td class=r>" + mn(c.revenue) +
          "</td><td class='r nowrap'>" + chg(c.revenue_yoy_pct_published) +
          "</td><td class=r>" + mn(c.operating_income) +
          "</td><td class='r nowrap'>" + chg(c.operating_income_yoy_pct_published) +
          "</td><td class=r>" + mn(c.profit) +
          "</td><td class='r nowrap'>" + chg(c.profit_yoy_pct_published) +
          "</td><td class=r>" + prog(c.operating_income_progress_pct) +
          "</td><td class=nowrap>" + stamp(c.filed_date, c.filed_time) + "</td></tr>";
      }).join("") + "</tbody>";
    $("re-csv").onclick = function () {
      var cols = ["sec_code", "name", "name_en", "fiscal_period", "period", "basis",
                  "revenue_element", "revenue", "revenue_yoy_pct_published",
                  "operating_income_element", "operating_income",
                  "operating_income_yoy_pct_published", "operating_income_forecast",
                  "operating_income_progress_pct", "profit_element", "profit",
                  "profit_yoy_pct_published", "eps", "filed_date", "filed_time", "doc_key"];
      csvDownload("tdnet-earnings-recent.csv", csvHeader(d.calc), cols,
        rows.map(function (c) { return cols.map(function (k) { return c[k]; }); }));
    };
  }

  function renderWire(d) {
    var rows = d.disclosures;
    $("wi-count").textContent = rows.length + " newest";
    $("wi-meta").textContent = d.wire_note;
    $("wi-table").innerHTML =
      "<thead><tr><th>Disclosed</th><th>Company</th><th>Headline</th><th>Kind</th>" +
      "</tr></thead><tbody>" +
      rows.map(function (w) {
        return "<tr><td class=nowrap>" + stamp(w.filed_date, w.filed_time) +
          "</td><td>" + nameCell(null, w.name, w.sec_code
            ? "earnings.html?c=" + esc(w.sec_code) : null) +
          "</td><td><div class='cell-item headline'>" + esc(w.title) + "</div>" +
          "</td><td class=nowrap>" + esc(KIND_LABEL[w.kind] || w.kind) + "</td></tr>";
      }).join("") + "</tbody>";
    $("wi-csv").onclick = function () {
      csvDownload("tdnet-wire.csv",
        csvHeader(d.calc, ["Kind is read from the headline, for filtering only: " +
                           (wiState.kind || "everything")]),
        ["filed_date", "filed_time", "sec_code", "name", "exchange", "kind", "title", "pdf_name"],
        rows.map(function (w) {
          return [w.filed_date, w.filed_time, w.sec_code, w.name, w.exchange, w.kind,
                  w.title, w.pdf_name];
        }));
    };
  }

  function loadProgress() {
    getJSON("/api/v1/equity/earnings/screen?sort=progress&limit=50&period=" + prState.period +
            "&line=" + prState.line + "&order=" + prState.order)
      .then(renderProgress).catch(function (e) { errorInto("pr-meta", e); });
  }

  function loadWire() {
    getJSON("/api/v1/equity/earnings/wire?limit=50&kind=" + encodeURIComponent(wiState.kind))
      .then(renderWire).catch(function (e) { errorInto("wi-meta", e); });
  }

  // The URL carries the whole view, so any ranking on this page can be cited.
  function syncUrl() {
    var p = new URLSearchParams();
    if (prState.period !== "q1") p.set("period", prState.period);
    if (prState.line !== "operating_income") p.set("line", prState.line);
    if (prState.order !== "desc") p.set("order", prState.order);
    if (wiState.kind !== "forecast-revision") p.set("kind", wiState.kind || "all");
    history.replaceState(null, "", "earnings.html" + (p.toString() ? "?" + p.toString() : ""));
  }

  function runSearch(q) {
    if (!q) { $("search-results").innerHTML = ""; return; }
    getJSON("/api/v1/equity/earnings/companies?limit=12&q=" + encodeURIComponent(q))
      .then(function (d) {
        if (!d.companies.length) {
          $("search-results").innerHTML = "<p class='sec-note'>No earnings release from a " +
            "company matching “" + esc(q) + "” is in the archive, which begins on " +
            esc(coverage ? coverage.first_day : "10 July 2026") + ".</p>";
          return;
        }
        $("search-results").innerHTML =
          "<div class='table-wrap'><table class='tbl-stk' data-no-enhance><thead><tr>" +
          "<th>Company</th><th>Latest release</th><th class=r>Releases held</th>" +
          "<th>Disclosed</th></tr></thead><tbody>" +
          d.companies.map(function (c) {
            return "<tr><td>" + nameCell(c.name_en, c.name, "earnings.html?c=" + esc(c.sec_code)) +
              "</td><td class=nowrap>" +
              releaseTag({ period: c.latest_period, fiscal_period: c.latest_fiscal_period }) +
              "</td><td class=r>" + count(c.releases) +
              "</td><td class=nowrap>" + esc(day(c.last_filed_date)) + "</td></tr>";
          }).join("") + "</tbody></table></div>";
      })
      .catch(function (e) { errorInto("search-results", e); });
  }

  // ---- company view --------------------------------------------------------
  function fact(label, value, unit, qual) {
    return "<div><dt>" + label + "</dt><dd>" + value +
      (unit ? "<span class='unit'> " + unit + "</span>" : "") +
      (qual ? "<span class='qual'>" + qual + "</span>" : "") + "</dd></div>";
  }

  function byLine(rows) {
    var out = {};
    rows.forEach(function (r) { out[r.line] = r; });
    return out;
  }

  function amount(row, v) { return row.line === "eps" ? yen(v) : mn(v); }

  function renderCompany(d) {
    var rel = d.release, res = byLine(d.results), fc = byLine(d.forecast);
    document.title = (d.name_en || d.name) + " · Earnings Releases · Plover Analytics";
    $("c-name").textContent = d.name_en || d.name;
    $("c-code").textContent = d.sec_code;
    if (d.name_en && d.name) { $("c-name-ja").textContent = d.name; $("c-name-ja").hidden = false; }
    coverage = d.coverage;

    var flags = [];
    if (!rel.is_current) flags.push("replaced by a later release");
    if (rel.is_correction) flags.push("correction");
    if (rel.review_completed) flags.push("re-issued after the auditor's review");
    $("c-meta").innerHTML = esc(rel.title) + " · disclosed " + stamp(rel.filed_date, rel.filed_time) +
      " · " + esc(BASIS_LABEL[d.basis] || "basis not stated") +
      (flags.length ? " · <b>" + esc(flags.join(", ")) + "</b>" : "") +
      " · SHA-256 " + esc((rel.sha256 || "").slice(0, 12)) + "…";

    var span = PERIOD_SPAN[rel.period] || "";
    function headline(line, label) {
      var r = res[line];
      return fact(label, r ? mn(r.value) : MISSING, "¥ mn",
        r ? chg(r.yoy_pct_published) + " on the prior year, as published · " + esc(span)
          : "Not reported in this release");
    }
    var op = fc.operating_income;
    $("c-facts").innerHTML =
      headline("revenue", "Revenue") + headline("operating_income", "Operating income") +
      headline("profit", "Profit attributable to owners") +
      (rel.period === "full-year" ? "" :
        fact("Operating income progress", op ? prog(op.progress_pct) : MISSING, "%",
          op && op.progress_pct != null
            ? "Of the company's " + mn(op.forecast) + " ¥ mn full-year forecast (calculated)"
            : "No single positive forecast to measure against"));

    $("c-res-note").textContent = (PERIOD_LABEL[rel.period] || "") + " · " + fiscal(rel.fiscal_period);
    $("c-res-meta").innerHTML = "<b>Official</b>, exactly as the company tagged them. " +
      esc(d.cumulative_note) + " Amounts in ¥ million; per-share figures in yen.";
    $("c-res-table").innerHTML =
      "<thead><tr><th>Line</th><th class=r>This period</th><th class=r>Same period, prior year</th>" +
      "<th class=r>YoY, as published</th></tr></thead><tbody>" +
      d.results.map(function (r) {
        return "<tr><td title='XBRL element: " + esc(r.element) + "'>" + esc(r.label) +
          " <span class='unit'>(" + (r.line === "eps" ? "¥" : "¥ mn") + ")</span></td><td class=r>" +
          amount(r, r.value) + "</td><td class=r>" + amount(r, r.prior_value) +
          "</td><td class='r nowrap'>" + chg(r.yoy_pct_published) + "</td></tr>";
      }).join("") +
      ["total_assets", "net_assets", "owners_equity"].map(function (k) {
        var p = d.position[k];
        if (!p) return "";
        var label = { total_assets: "Total assets", net_assets: "Net assets",
                      owners_equity: "Owners' equity" }[k];
        return "<tr><td title='XBRL element: " + esc(p.element) + " · at period end'>" + label +
          " <span class='unit'>(¥ mn)</span></td><td class=r>" + mn(p.value) +
          "</td><td class=r>" + MISSING + "</td><td class=r>" + MISSING + "</td></tr>";
      }).join("") + "</tbody>";

    $("c-fc-note").textContent = d.forecast_for ? "For " + d.forecast_for : "";
    if (!d.forecast.length) {
      $("c-fc-meta").textContent = "This release carries no company forecast. Nothing is filled in.";
      $("c-fc-table").innerHTML = "";
      $("c-formula").textContent = "";
    } else {
      $("c-fc-meta").innerHTML = esc(d.forecast_note);
      $("c-fc-table").innerHTML =
        "<thead><tr><th>Line</th><th class=r>Forecast</th><th class=r>Lower bound</th>" +
        "<th class=r>Upper bound</th><th class=r>YoY, as published</th>" +
        "<th class=r>Progress (%)</th></tr></thead><tbody>" +
        d.forecast.map(function (r) {
          return "<tr><td title='XBRL element: " + esc(r.element) + "'>" + esc(r.label) +
            " <span class='unit'>(" + (r.line === "eps" ? "¥" : "¥ mn") + ")</span></td><td class=r>" +
            amount(r, r.forecast) + "</td><td class=r>" + amount(r, r.forecast_lower) +
            "</td><td class=r>" + amount(r, r.forecast_upper) +
            "</td><td class='r nowrap'>" + chg(r.yoy_pct_published) +
            "</td><td class=r>" + prog(r.progress_pct) + "</td></tr>";
        }).join("") + "</tbody>";
      $("c-formula").innerHTML = "<b>Progress (%)</b> = " + esc(d.calc.progress_pct) + ". " +
        esc(d.progress_note);
    }

    // Dividends: one row per fiscal year and nature, the sub-periods across.
    var groups = {}, order = [];
    d.dividends_per_share.forEach(function (x) {
      var key = x.fiscal_year + "|" + x.nature;
      if (!groups[key]) { groups[key] = { fy: x.fiscal_year, nature: x.nature }; order.push(key); }
      groups[key][x.sub_period] = x.value;
    });
    $("c-div-table").innerHTML = order.length
      ? "<thead><tr><th>Fiscal year</th><th>Status</th><th class=r>Q1 (yen)</th>" +
        "<th class=r>Q2 (yen)</th><th class=r>Q3 (yen)</th><th class=r>Year-end (yen)</th>" +
        "<th class=r>Annual (yen)</th></tr></thead><tbody>" +
        order.map(function (k) {
          var g = groups[k];
          return "<tr><td>" + esc(FY_LABEL[g.fy] || g.fy) + "</td><td>" +
            esc(NATURE_LABEL[g.nature] || g.nature) + "</td>" +
            ["q1", "q2", "q3", "year-end", "annual"].map(function (s) {
              return "<td class=r>" + yen(g[s]) + "</td>";
            }).join("") + "</tr>";
        }).join("") + "</tbody>"
      : "<tbody><tr><td>This release tags no dividend per share.</td></tr></tbody>";

    $("c-rel-count").textContent = d.releases.length === 1 ? "1 release"
      : d.releases.length + " releases";
    $("c-rel-table").innerHTML =
      "<thead><tr><th>Disclosed</th><th>Release</th><th>Headline</th><th>Status</th>" +
      "</tr></thead><tbody>" +
      d.releases.map(function (r) {
        var status = r.is_current ? "Current" : "Replaced";
        if (r.is_correction) status += " · correction";
        if (r.review_completed) status += " · after review";
        return "<tr" + (r.is_current ? "" : " class='is-replaced'") + "><td class=nowrap>" +
          stamp(r.filed_date, r.filed_time) + "</td><td class=nowrap>" + releaseTag(r) +
          "</td><td><div class='cell-item headline'><a href='earnings.html?c=" +
          esc(d.sec_code) + "&doc=" + esc(r.doc_key) + "'>" + esc(r.title) + "</a></div>" +
          "</td><td class=nowrap>" + esc(status) + "</td></tr>";
      }).join("") + "</tbody>";

    var wire = d.wire || [];
    $("c-wire-count").textContent = wire.length + " newest";
    $("c-wire-table").innerHTML =
      "<thead><tr><th>Disclosed</th><th>Headline</th><th>Kind</th></tr></thead><tbody>" +
      wire.map(function (w) {
        return "<tr><td class=nowrap>" + stamp(w.filed_date, w.filed_time) +
          "</td><td><div class='cell-item headline'>" + esc(w.title) + "</div></td>" +
          "<td class=nowrap>" + esc(KIND_LABEL[w.kind] || w.kind) + "</td></tr>";
      }).join("") + "</tbody>";

    $("c-csv").onclick = function () {
      csvDownload("tdnet-earnings-" + d.sec_code + "-" + rel.doc_key + ".csv",
        csvHeader(d.calc, [
          "Company: " + d.sec_code + " " + (d.name_en || d.name),
          "Release: " + rel.title + " (doc_key " + rel.doc_key + "), disclosed " +
            rel.filed_date + " " + (rel.filed_time || ""),
          "SHA-256 of the archived package: " + rel.sha256,
          "Every fact the Summary tagged, as tagged; value in the unit column's unit " +
            "(Pure = a fraction: 0.104 is the 10.4% the release prints)"]),
        ["element", "period", "nature", "basis", "sub_period", "unit", "value"],
        d.facts.map(function (f) {
          return [f.element, f.period, f.nature, f.basis, f.sub_period, f.unit, f.value];
        }));
    };
  }

  function initMarket() {
    var p = new URLSearchParams(location.search);
    if (p.get("period")) prState.period = p.get("period");
    if (p.get("line")) prState.line = p.get("line");
    if (p.get("order")) prState.order = p.get("order");
    if (p.get("kind")) wiState.kind = p.get("kind") === "all" ? "" : p.get("kind");
    pressed($("pr-period"), "data-period", prState.period);
    pressed($("pr-line"), "data-line", prState.line);
    pressed($("pr-order"), "data-order", prState.order);
    pressed($("wi-seg"), "data-kind", wiState.kind);

    getJSON("/api/v1/equity/earnings/summary")
      .then(renderStrip).catch(function (e) { errorInto("stat-strip", e); });
    loadProgress();
    getJSON("/api/v1/equity/earnings/recent?limit=50")
      .then(renderRecent).catch(function (e) { errorInto("re-table", e); });
    loadWire();

    [["pr-period", "data-period", "period"], ["pr-line", "data-line", "line"],
     ["pr-order", "data-order", "order"]].forEach(function (g) {
      $(g[0]).addEventListener("click", function (ev) {
        var b = ev.target.closest("button");
        if (!b) return;
        prState[g[2]] = b.getAttribute(g[1]);
        pressed(this, g[1], prState[g[2]]);
        syncUrl();
        loadProgress();
      });
    });
    $("wi-seg").addEventListener("click", function (ev) {
      var b = ev.target.closest("button");
      if (!b) return;
      wiState.kind = b.getAttribute("data-kind");
      pressed(this, "data-kind", wiState.kind);
      syncUrl();
      loadWire();
    });
    var timer = null;
    $("q").addEventListener("input", function () {
      var v = this.value.trim();
      clearTimeout(timer);
      timer = setTimeout(function () { runSearch(v); }, 180);
    });
  }

  initThemeToggle(function () {});

  var params = new URLSearchParams(location.search);
  var code = params.get("c");
  if (code) {
    $("market-view").hidden = true;
    $("company-view").hidden = false;
    getJSON("/api/v1/equity/earnings/company/" + encodeURIComponent(code) +
            (params.get("doc") ? "?doc_key=" + encodeURIComponent(params.get("doc")) : ""))
      .then(renderCompany)
      .catch(function (e) {
        $("c-name").textContent = code;
        $("c-meta").textContent = e.message.indexOf("404") > -1
          ? "No earnings release from this company is in the archive, which begins on " +
            "10 July 2026. TDnet deletes disclosures after about a month, so an earlier " +
            "release cannot be recovered."
          : "Data unavailable — " + e.message + ". The last good state is unaffected.";
      });
  } else {
    initMarket();
  }
})();
