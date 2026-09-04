/* Financials: a company's own five-year record of key indicators and its
   statements line by line, exactly as tagged in the annual securities report.
   Data: /api/v1/equity/financials/*.

   Every value is official as filed. The page derives exactly one thing — the
   change column on a statement (current − prior) — and says so under "Show
   calculation". Ratios the taxonomy stores as fractions arrive from the API in
   percent and the calc note says so. Missing renders as —, never 0. */
(function () {
  "use strict";

  var API = "/api/v1/equity/financials";
  var state = { code: null, basis: "consolidated", st: "bs", fy: "", chart: "revenue_profit",
                metric: "revenue" };
  var company = null;      // /company payload
  var statement = null;    // /statements payload
  var screenData = null;
  var kiChart = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) { return escapeHtml(String(s == null ? "" : s)); }

  /* ¥ at a stated scale. Statements print in ¥ millions (the filer's own
     convention, 百万円); the record and tiles in ¥bn. Unit always attached. */
  function yenMn(v) { return v == null ? MISSING : fmtNum(v / 1e6, 0); }
  function yenBn(v, dp) {
    if (v == null) return MISSING;
    return "¥" + fmtNum(v / 1e9, dp == null ? 1 : dp) + "bn";
  }
  function yenUnit(v) { return v == null ? MISSING : "¥" + fmtNum(v, 2); }
  function pct(v) { return v == null ? MISSING : fmtRate(v, 1); }
  function count(v) { return v == null ? MISSING : fmtNum(v, 0); }
  function times(v) { return v == null ? MISSING : fmtNum(v, 1) + "×"; }
  function fyLabel(iso) { return iso ? "FY" + iso.slice(0, 4) + " (" + iso.slice(0, 7) + ")" : MISSING; }
  function fyShort(iso) { return iso ? iso.slice(0, 7) : MISSING; }

  /* One formatter per standardised field; the unit lives in the row label. */
  var FIELD_FMT = {
    revenue: yenMn, operating_income: yenMn, ordinary_income: yenMn, pretax_income: yenMn,
    profit: yenMn, comprehensive_income: yenMn, net_assets: yenMn, total_assets: yenMn,
    cf_operating: yenMn, cf_investing: yenMn, cf_financing: yenMn, cash: yenMn,
    capital_stock: yenMn, bps: yenUnit, eps: yenUnit, eps_diluted: yenUnit, dps: yenUnit,
    dps_interim: yenUnit, equity_ratio_pct: pct, roe_pct: pct, payout_ratio_pct: pct,
    per: times, issued_shares: count, employees: count,
  };
  var FIELD_UNIT_LABEL = {
    yen: "¥ mn", "%": "%", x: "×", shares: "shares", people: "people",
  };
  function unitLabel(f) {
    if (f.field === "bps" || f.field === "eps" || f.field === "eps_diluted" ||
        f.field === "dps" || f.field === "dps_interim") return "¥";
    return FIELD_UNIT_LABEL[f.unit] || f.unit;
  }

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

  function errorInto(id, e) {
    $(id).innerHTML = "<span class='state-error'>Data unavailable — " + esc(e.message) +
      ". The last good state is unaffected.</span>";
  }

  function nameCell(en, ja, href) {
    var main = en || ja || MISSING;
    var sub = en && ja ? "<span class='sub'>" + esc(ja) + "</span>" : "";
    return "<div class='cell-name'><a href='" + href + "'>" + esc(main) + "</a>" + sub + "</div>";
  }

  function edinetLink(docId) {
    return "<a class='mono' href='https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?" +
      esc(docId) + "' target='_blank' rel='noopener'>" + esc(docId) + "</a>";
  }

  // ---- market view ---------------------------------------------------------
  function renderStrip(d) {
    var t = d.totals;
    var years = d.years.map(function (y) { return y.year; });
    $("stat-strip").innerHTML = "<div class='strip-grid'>" +
      tile("Companies", count(t.companies), "", "with an accepted annual report") +
      tile("Filings", count(d.status.reduce(function (a, s) { return a + s.n; }, 0)), "",
           d.status.map(function (s) { return count(s.n) + " " + s.status; }).join(" · ")) +
      tile("Fiscal years", years.length ? years[years.length - 1] + "–" + years[0] : MISSING, "",
           "filing period ends; each filing restates five years") +
      tile("Tagged values", count(t.facts), "", count(t.elements) + " distinct line items") +
      tile("Accounting standards", d.accounting_standards.length ? String(d.accounting_standards.length) : MISSING, "",
           d.accounting_standards.map(function (s) { return (s.accounting_standard || "untagged") + " " + count(s.n); }).join(" · ")) +
      "</div><p class='strip-foot'>Latest filing archived " + esc(t.latest_filed || MISSING) +
      " · Official statistics as filed on EDINET.</p>";
  }
  function tile(label, value, unit, foot) {
    return "<div class='strip-cell'><div class='strip-label'>" + esc(label) + "</div>" +
      "<div class='strip-value'>" + value + (unit ? " <span class='unit'>" + esc(unit) + "</span>" : "") +
      "</div><div class='strip-foot'>" + esc(foot) + "</div></div>";
  }

  var SCREEN_FMT = {
    revenue: yenBn, profit: yenBn, total_assets: yenBn, net_assets: yenBn, cf_operating: yenBn,
    cash: yenBn, roe_pct: pct, equity_ratio_pct: pct, payout_ratio_pct: pct, employees: count,
  };

  function renderScreen(d) {
    screenData = d;
    var fmt = SCREEN_FMT[d.metric] || yenBn;
    var extra = ["revenue", "profit", "roe_pct", "equity_ratio_pct"].indexOf(d.metric) < 0;
    $("screen-count").textContent = count(d.companies_ranked) + " companies ranked · latest filing each";
    $("screen-meta").innerHTML = "<b>" + esc(d.metric_label) + "</b>, one filing per company (its " +
      "latest accepted annual report), consolidated where the filer reports one, parent-only " +
      "otherwise. Official statistics as filed.";
    $("screen-table").innerHTML =
      "<thead><tr><th class=r>#</th><th>Company</th><th>Standard</th><th>Basis</th>" +
      (extra ? "<th class=r>" + esc(d.metric_label) + "</th>" : "") + "<th class=r>Revenue (¥bn)</th>" +
      "<th class=r>Profit (¥bn)</th><th class=r>ROE (%)</th><th class=r>Equity ratio (%)</th>" +
      "<th class=r>FY end</th></tr></thead><tbody>" +
      d.rows.map(function (r) {
        var v = r.values;
        return "<tr><td class=r>" + r.rank + "</td><td>" +
          nameCell(r.filer_name_en, r.filer_name, "financials.html?c=" + esc(r.sec_code)) +
          "</td><td>" + esc(r.accounting_standard || MISSING) +
          "</td><td>" + (r.basis === "parent" ? "Parent" : "Consolidated") +
          "</td>" + (extra ? "<td class=r data-sort='" + (r.metric_value == null ? "" : r.metric_value) + "'>" + fmt(r.metric_value) + "</td>" : "") +
          "<td class=r data-sort='" + (v.revenue == null ? "" : v.revenue) + "'>" + yenBn(v.revenue) +
          "</td><td class=r data-sort='" + (v.profit == null ? "" : v.profit) + "'>" + yenBn(v.profit) +
          "</td><td class=r>" + pct(v.roe_pct) +
          "</td><td class=r>" + pct(v.equity_ratio_pct) +
          "</td><td class=r>" + esc(fyShort(r.period_end)) + "</td></tr>";
      }).join("") + "</tbody>";
    $("screen-formula").textContent = "Ratios are the filer's own, printed in percent " +
      "(the taxonomy stores 10.1% as 0.101). Yen values are exact as tagged; ¥bn here is display rounding.";
  }

  function loadScreen() {
    syncUrl();
    getJSON(API + "/screen?metric=" + encodeURIComponent(state.metric) + "&limit=100")
      .then(renderScreen).catch(function (e) { errorInto("screen-meta", e); });
  }

  function runSearch(q) {
    if (!q) { $("search-results").innerHTML = ""; return; }
    getJSON(API + "/companies?q=" + encodeURIComponent(q)).then(function (d) {
      if (!d.companies.length) {
        $("search-results").innerHTML = "<p class='sec-note'>No company with an accepted " +
          "financial filing matches that.</p>";
        return;
      }
      $("search-results").innerHTML =
        "<div class='table-wrap'><table class='tbl-fin' data-no-enhance><thead><tr><th>Company</th>" +
        "<th>Sector</th><th class=r>Filings</th><th class=r>Latest FY end</th></tr></thead><tbody>" +
        d.companies.map(function (c) {
          return "<tr><td>" + nameCell(c.name_en, c.name, "financials.html?c=" + esc(c.sec_code)) +
            "</td><td>" + esc(c.industry || MISSING) + "</td><td class=r>" + count(c.filings) +
            "</td><td class=r>" + esc(fyShort(c.period_end)) + "</td></tr>";
        }).join("") + "</tbody></table></div>";
    }).catch(function (e) { errorInto("search-results", e); });
  }

  function initMarket() {
    var p = new URLSearchParams(location.search);
    if (p.get("screen")) state.metric = p.get("screen");
    getJSON(API + "/summary").then(renderStrip).catch(function (e) { errorInto("stat-strip", e); });
    getJSON(API + "/screen/metrics").then(function (d) {
      $("screen-select").innerHTML = d.metrics.map(function (m) {
        return "<option value='" + esc(m.metric) + "'" +
          (m.metric === state.metric ? " selected" : "") + ">" + esc(m.label) + "</option>";
      }).join("");
      loadScreen();
    }).catch(function (e) { errorInto("screen-meta", e); });
    $("screen-select").addEventListener("change", function () {
      state.metric = this.value; loadScreen();
    });
    $("screen-csv").addEventListener("click", function () {
      if (!screenData) return;
      csvDownload("financials-screen-" + state.metric + ".csv", [
        "Japan Data Observatory — financials screen: " + screenData.metric_label,
        "One filing per company (latest accepted annual securities report); consolidated where filed, parent-only otherwise",
        "trust: official (as filed) · source: EDINET, Financial Services Agency of Japan",
        "yen values exact as tagged; *_pct ratios = filed fraction × 100",
      ], ["rank", "sec_code", "filer_name", "filer_name_en", "accounting_standard", "basis",
          "period_end", "doc_id", "revenue_yen", "profit_yen", "total_assets_yen", "net_assets_yen",
          "roe_pct", "equity_ratio_pct", "payout_ratio_pct", "cf_operating_yen", "cash_yen", "employees"],
        screenData.rows.map(function (r) {
          var v = r.values;
          return [r.rank, r.sec_code, r.filer_name, r.filer_name_en, r.accounting_standard, r.basis,
                  r.period_end, r.doc_id, v.revenue, v.profit, v.total_assets, v.net_assets,
                  v.roe_pct, v.equity_ratio_pct, v.payout_ratio_pct, v.cf_operating, v.cash, v.employees];
        }));
    });
    var timer = null;
    $("q").addEventListener("input", function () {
      var q = this.value.trim();
      clearTimeout(timer);
      timer = setTimeout(function () { runSearch(q); }, 180);
    });
  }

  // ---- company view --------------------------------------------------------
  function syncUrl() {
    var p = new URLSearchParams();
    if (state.code) {
      p.set("c", state.code);
      if (state.basis !== "consolidated") p.set("basis", state.basis);
      if (state.st !== "bs") p.set("st", state.st);
      if (state.fy) p.set("fy", state.fy);
      if (state.chart !== "revenue_profit") p.set("chart", state.chart);
    } else if (state.metric !== "revenue") {
      p.set("screen", state.metric);
    }
    var qs = p.toString();
    history.replaceState(null, "", "financials.html" + (qs ? "?" + qs : ""));
  }

  function panelRows() {
    if (!company) return [];
    return company.panel.filter(function (r) { return r.basis === state.basis; });
  }

  function renderHeader(d) {
    var lf = d.latest_filing;
    $("co-name").textContent = d.filer_name_en || d.filer_name || d.sec_code;
    $("co-code").textContent = d.sec_code;
    $("co-industry").textContent = d.industry || "";
    if (d.filer_name_en && d.filer_name) {
      $("co-name-ja").textContent = d.filer_name;
      $("co-name-ja").hidden = false;
    }
    $("co-filing").innerHTML = "Latest annual report: fiscal year ended <b>" + esc(lf.period_end) +
      "</b>, filed " + esc(lf.filed_date) + " · " + esc(d.accounting_standard || "standard not tagged") +
      (d.consolidated === false ? " · parent-only filer" : "") +
      " · EDINET " + edinetLink(lf.doc_id) + " · SHA-256 <span class='mono'>" +
      esc((lf.sha256 || "").slice(0, 12)) + "…</span>" +
      " · " + count(d.filings.length) + (d.filings.length === 1 ? " filing" : " filings") + " held";
    if (lf.status !== "clean") {
      $("co-flag").innerHTML = "<b>This filing is marked " + esc(lf.status) + ":</b> " + esc(lf.detail || "");
      $("co-flag").hidden = false;
    }
  }

  function renderFacts() {
    var rows = panelRows();
    if (!rows.length) { $("co-facts").innerHTML = ""; return; }
    var cur = rows[rows.length - 1];
    var v = cur.values;
    var q = "FY" + cur.fiscal_year_end.slice(0, 4) + " · " +
      (state.basis === "parent" ? "parent only" : "consolidated") + " · as filed";
    function fact(label, value, unit) {
      return "<div><dt>" + esc(label) + "</dt><dd>" + value +
        (unit ? " <span class='unit'>" + esc(unit) + "</span>" : "") +
        "<span class='qual'>" + esc(q) + "</span></dd></div>";
    }
    $("co-facts").innerHTML =
      fact("Revenue", yenBn(v.revenue)) +
      fact("Profit to owners", yenBn(v.profit)) +
      fact("Return on equity", pct(v.roe_pct)) +
      fact("Equity ratio", pct(v.equity_ratio_pct)) +
      fact("Dividend per share", yenUnit(v.dps)) +
      fact("Operating cash flow", yenBn(v.cf_operating));
  }

  function renderPanel() {
    var rows = panelRows();
    $("ki-note").textContent = rows.length ? rows.length + " fiscal years · " +
      (state.basis === "parent" ? "parent only" : "consolidated") : "no summary rows on this basis";
    if (!rows.length) {
      $("ki-table").innerHTML = "";
      $("ki-source").textContent = "";
      return;
    }
    var head = "<thead><tr><th>Indicator</th>" + rows.map(function (r) {
      return "<th class=r>" + esc(fyLabel(r.fiscal_year_end)) + "</th>";
    }).join("") + "</tr></thead>";
    var body = company.fields.map(function (f) {
      var present = rows.some(function (r) { return r.values[f.field] != null; });
      if (!present) return "";
      var fmt = FIELD_FMT[f.field] || yenMn;
      var el = rows.map(function (r) { return r.elements[f.field]; }).filter(Boolean)[0] || "";
      return "<tr><td class='lbl' title='" + esc(el ? "XBRL element: " + el : "") + "'>" + esc(f.label) +
        " <span class='unit'>(" + esc(unitLabel(f)) + ")</span></td>" + rows.map(function (r) {
          return "<td class=r>" + fmt(r.values[f.field]) + "</td>";
        }).join("") + "</tr>";
    }).join("");
    var src = "<tr><td class='lbl'>Filing</td>" + rows.map(function (r) {
      return "<td class='r src'>" + edinetLink(r.source.doc_id) + "<span class='sub'>filed " +
        esc(r.source.filed_date) + (r.source.year_offset ? " · restated " + r.source.year_offset + "y" : "") +
        "</span></td>";
    }).join("") + "</tr>";
    $("ki-table").innerHTML = head + "<tbody>" + body + src + "</tbody>";
    $("ki-calc").innerHTML = "<b>Nothing is recomputed.</b> " + esc(company.calc.percent_fields) +
      " " + esc(company.calc.panel) + " " + esc(company.calc.fiscal_year_end) +
      (rows.some(function (r) { return r.revenue_source === "first_line"; })
        ? " " + esc(company.calc.revenue_fallback) : "");
    drawChart();
  }

  var CHARTS = {
    revenue_profit: { kind: "cols", fields: [["revenue", "Revenue"], ["profit", "Profit to owners"]],
                      scale: 1e9, unit: "¥bn", dp: 1 },
    returns: { kind: "line", fields: [["roe_pct", "Return on equity"], ["equity_ratio_pct", "Equity ratio"]],
               scale: 1, unit: "%", dp: 1 },
    cf: { kind: "cols", fields: [["cf_operating", "Operating"], ["cf_investing", "Investing"],
                                 ["cf_financing", "Financing"]], scale: 1e9, unit: "¥bn", dp: 1 },
    dividends: { kind: "line", fields: [["dps", "Dividend per share (¥)"], ["payout_ratio_pct", "Payout ratio (%)"]],
                 scale: 1, unit: "", dp: 1 },
  };

  function drawChart() {
    var rows = panelRows();
    var spec = CHARTS[state.chart];
    var el = $("ki-chart");
    if (kiChart) { kiChart.dispose(); kiChart = null; }
    if (!rows.length) { el.innerHTML = ""; return; }
    var cats = rows.map(function (r) { return "FY" + r.fiscal_year_end.slice(0, 4); });
    var anyNeg = false;
    var series = spec.fields.map(function (f, i) {
      var pts = rows.map(function (r) {
        var v = r.values[f[0]];
        if (v != null && v < 0) anyNeg = true;
        return v == null ? null : v / spec.scale;
      });
      return { name: f[1], slot: i + 1, points: pts };
    });
    var anyValue = series.some(function (s) { return s.points.some(function (v) { return v != null; }); });
    if (!anyValue) {
      el.innerHTML = "<p class='state-empty'>No " + esc(spec.fields.map(function (f) { return f[1].toLowerCase(); }).join(" / ")) +
        " figures in the filer's summary on the " + (state.basis === "parent" ? "parent-only" : "consolidated") +
        " basis. A consolidated filer's parent-only summary usually omits cash flows.</p>";
      $("ki-source").textContent = "";
      return;
    }
    var source = "Source: 有価証券報告書 via EDINET (FSA) · " +
      (company.filer_name_en || company.filer_name) + " · " +
      (state.basis === "parent" ? "parent only" : "consolidated") + " · Official statistics as filed";
    var cfg;
    // A column chart must keep a zero baseline; a negative value (a loss, a
    // cash outflow) would be clipped by it, so those series draw as lines.
    if (spec.kind === "cols" && !anyNeg) {
      cfg = { categories: cats, series: series, unitSuffix: spec.unit, dp: spec.dp,
              yAxisName: spec.unit, trust: "official", sourceLine: source };
      kiChart = obsChart(el, "cols", cfg);
    } else {
      cfg = { xType: "category", unit: spec.unit === "%" ? "%" : "", dp: spec.dp,
              yAxisName: spec.unit, trust: "official", sourceLine: source,
              series: series.map(function (s) {
                return { name: s.name, points: s.points.map(function (v, i) { return [cats[i], v]; }) };
              }) };
      kiChart = obsChart(el, "line", cfg);
    }
    $("ki-source").textContent = source;
  }

  function panelCsv() {
    var rows = panelRows();
    if (!rows.length) return;
    var fields = company.fields;
    csvDownload("financials-" + state.code + "-key-indicators-" + state.basis + ".csv", [
      "Japan Data Observatory — key indicators as filed (主要な経営指標等の推移): " +
        (company.filer_name_en || company.filer_name) + " (" + state.code + ")",
      "basis: " + state.basis + " · trust: official (as filed) · source: EDINET, Financial Services Agency of Japan",
      "yen values exact as tagged; *_pct = filed fraction × 100; per-share values in yen; per = filer's own PER at year end",
      "each fiscal year from the latest accepted filing covering it (doc_id, filed_date on the row)",
    ], ["fiscal_year_end", "basis", "doc_id", "filed_date", "year_offset"].concat(
         fields.map(function (f) { return f.field; })),
      rows.map(function (r) {
        return [r.fiscal_year_end, r.basis, r.source.doc_id, r.source.filed_date, r.source.year_offset]
          .concat(fields.map(function (f) { return r.values[f.field]; }));
      }));
  }

  // ---- calculated ratios ---------------------------------------------------
  var METRIC_FMT = { "%": pct, "×": times2, "¥": yenBn };
  function times2(v) { return v == null ? MISSING : fmtNum(v, 2) + "×"; }

  function renderMetrics(d) {
    var m = d.metrics;
    var filed = { roe_pct: d.filed.roe_pct, equity_ratio_pct: d.filed.equity_ratio_pct };
    var chk = { roe_pct: d.checks.roe_vs_filed_pp, equity_ratio_pct: d.checks.equity_ratio_vs_filed_pp };
    $("dr-note").textContent = "FY ended " + d.period_end + " · " +
      (d.basis === "parent" ? "parent only" : "consolidated") + " · derived";
    $("dr-table").innerHTML = "<thead><tr><th>Ratio</th><th class=r>This platform</th>" +
      "<th class=r>Filer's own</th><th class=r>Difference</th></tr></thead><tbody>" +
      d.metric_defs.map(function (def) {
        var f = METRIC_FMT[def.unit] || pct;
        var own = filed[def.metric];
        var diff = chk[def.metric];
        var withheld = d.checks[def.metric.replace(/_pct$/, "").replace(/_x$/, "") + "_withheld"] ||
          (def.metric === "roe_pct" ? d.checks.roe_withheld : null) ||
          (def.metric === "dividend_yield_implied_pct" ? d.checks.dividend_yield_withheld : null);
        var shown = m[def.metric] == null && withheld
          ? "<span class='flag' title='" + esc(withheld) + "'>not shown</span>"
          : f(m[def.metric]);
        return "<tr><td class='lbl' title='" + esc(def.formula) + "'>" + esc(def.label) +
          " <span class='unit'>(" + esc(def.unit) + ")</span></td>" +
          "<td class=r>" + shown + "</td>" +
          "<td class=r>" + (own == null ? MISSING : f(own)) + "</td>" +
          "<td class=r>" + (diff == null ? MISSING : fmtSigned(diff, 2, "pp")) + "</td></tr>";
      }).join("") + "</tbody>";
    var inputs = Object.keys(d.inputs).map(function (k) {
      var i = d.inputs[k];
      var v = i.value;
      var shown = Math.abs(v) >= 1e6 ? "¥" + fmtNum(v / 1e6, 0) + "mn" : fmtNum(v, 2);
      return "<li><b>" + esc(k) + "</b> = " + shown + " <span class='unit'>(" + esc(i.element) +
        ", FY" + (i.year_offset === 0 ? "" : i.year_offset) + ")</span></li>";
    }).join("");
    var withheldAll = Object.keys(d.checks).filter(function (k) { return /_withheld$/.test(k); });
    $("dr-flags").innerHTML = withheldAll.length
      ? "<b>Not calculated for this company:</b> " + withheldAll.map(function (k) {
          return esc(d.checks[k]); }).join(" · ")
      : "";
    $("dr-flags").hidden = !withheldAll.length;
    $("dr-calc").innerHTML = "<ul class='calc-list'>" + d.metric_defs.map(function (def) {
      return "<li><b>" + esc(def.label) + "</b> — " + esc(def.formula) + "</li>";
    }).join("") + "<li><b>Equity attributable to owners</b> — " + esc(d.calc.equity_owners_yen) + "</li></ul>" +
      "<p class='sec-note' style='margin-top:8px'><b>Inputs used</b> (value, XBRL element, fiscal year):</p>" +
      "<ul class='calc-list'>" + inputs + "</ul>";
  }

  function loadMetrics() {
    getJSON(API + "/metrics/" + encodeURIComponent(state.code)).then(renderMetrics).catch(function (e) {
      $("dr-table").innerHTML = "";
      $("dr-note").textContent = "";
      $("dr-calc").innerHTML = "<span class='state-error'>Ratios unavailable — " + esc(e.message) + "</span>";
    });
  }

  // ---- statements ----------------------------------------------------------
  var stReq = 0;
  function loadStatement() {
    syncUrl();
    var url = API + "/statements/" + encodeURIComponent(state.code) + "?statement=" + state.st +
      "&basis=" + state.basis + (state.fy ? "&year=" + state.fy : "");
    // Two controls clicked in quick succession fire two fetches; only the
    // latest may render, or a slower earlier response overwrites the newer.
    var mine = ++stReq;
    getJSON(url).then(function (d) { if (mine === stReq) renderStatement(d); }).catch(function (e) {
      if (mine !== stReq) return;
      statement = null;
      $("st-table").innerHTML = "";
      $("st-meta").innerHTML = e.message.indexOf("404") > -1
        ? "<span class='state-empty'>This filing carries no " +
          (state.basis === "parent" ? "parent-only " : "consolidated ") + esc(STATEMENT_LABEL[state.st]) +
          ". A parent-only filer has no consolidated set; a filer that prepares consolidated " +
          "statements usually omits a parent cash flow statement.</span>"
        : "<span class='state-error'>Data unavailable — " + esc(e.message) + "</span>";
      $("st-note").textContent = "";
    });
  }

  var STATEMENT_LABEL = { bs: "balance sheet", pl: "income statement",
                          ci: "statement of comprehensive income", cf: "cash flow statement",
                          ss: "statement of changes in equity" };

  function renderStatement(d) {
    statement = d;
    var n = d.lines.filter(function (l) { return !l.is_heading; }).length;
    $("st-note").textContent = n + " lines · " + (d.basis === "parent" ? "parent only" : "consolidated") +
      " · FY ended " + d.period_end;
    $("st-meta").innerHTML = "<b>" + esc(d.statement_name) + "</b>, " +
      (d.basis === "parent" ? "parent only" : "consolidated") + ", from the annual report for the " +
      "fiscal year ended " + esc(d.period_end) + " (filed " + esc(d.filed_date) + ", EDINET " +
      edinetLink(d.doc_id) + "). Every line in the filer's own order; values in ¥ millions, exact " +
      "as tagged. <b>Official statistics</b> as filed.";
    var isBs = d.statement === "bs";
    var curHead = isBs ? esc(d.period_end) : "FY to " + esc(d.period_end);
    var priHead = isBs ? esc(d.prior_period_end) : "FY to " + esc(d.prior_period_end);
    var perShare = function (l) { return l.unit === "JPYPerShares"; };
    $("st-table").innerHTML =
      "<thead><tr><th>Line item</th><th class=r>" + curHead + " (¥ mn)</th><th class=r>" +
      priHead + " (¥ mn)</th><th class=r>Change (¥ mn)</th><th class=r>Change (%)</th></tr></thead><tbody>" +
      d.lines.map(function (l) {
        var cls = l.is_heading ? "heading" : (l.is_total ? "total" : "");
        var lbl = "<td class='lbl' data-depth='" + Math.min(l.depth, 4) + "' title='XBRL element: " + esc(l.element) + "'>" + esc(l.label_en) +
          (l.label_en_source === "derived" ? "<span class='pill' title='English label derived from the XBRL element name; the Japanese label is the filer&#39;s own'>derived</span>" : "") +
          (l.negated ? "<span class='pill' title='The filer prints this line with its sign reversed'>sign reversed</span>" : "") +
          (l.label_ja ? "<span class='ja'>" + esc(l.label_ja) + "</span>" : "") + "</td>";
        if (l.is_heading) return "<tr class='heading'>" + lbl + "<td></td><td></td><td></td><td></td></tr>";
        var f = perShare(l) ? yenUnit : (l.unit === "pure" || l.unit === "shares" ? count : yenMn);
        var chg = (l.current != null && l.prior != null) ? l.current - l.prior : null;
        var chgPct = (chg != null && l.prior) ? chg / Math.abs(l.prior) * 100 : null;
        return "<tr class='" + cls + "'>" + lbl +
          "<td class=r>" + f(l.current) + "</td><td class=r>" + f(l.prior) + "</td>" +
          "<td class=r>" + (chg == null ? MISSING : (perShare(l) ? fmtSigned(chg, 2) : fmtSigned(chg / 1e6, 0))) + "</td>" +
          "<td class=r>" + (chgPct == null ? MISSING : fmtSigned(chgPct, 1, "%")) + "</td></tr>";
      }).join("") + "</tbody>";
    $("st-calc").innerHTML = "<b>Derived here, and only here:</b> change = current − prior on the " +
      "tagged values; change (%) = change ÷ |prior| × 100, shown as — where the prior value is " +
      "missing or zero. " + esc(d.calc.note);
    var derived = d.lines.filter(function (l) { return l.label_en_source === "derived"; }).length;
    $("st-labels").innerHTML = "<b>Labels.</b> Japanese labels are the filer's own. " +
      (derived ? count(derived) + " of " + count(d.lines.length) + " English labels on this statement " +
        "are derived from the XBRL element name (marked <i>derived</i>); the rest are the filer's own." :
        "Every English label on this statement is the filer's own.");
    // filing selector
    var sel = $("fy-select");
    if (sel.options.length !== d.available_years.length) {
      sel.innerHTML = d.available_years.map(function (y) {
        return "<option value='" + esc(y) + "'>FY ending " + esc(y) + "</option>";
      }).join("");
    }
    sel.value = String(new Date(d.period_end).getFullYear());
  }

  function statementCsv() {
    if (!statement) return;
    var d = statement;
    csvDownload("financials-" + state.code + "-" + d.statement + "-" + d.basis + "-" + d.period_end + ".csv", [
      "Japan Data Observatory — " + d.statement_name + " as filed: " +
        (d.filer_name_en || d.filer_name) + " (" + state.code + ")",
      "basis: " + d.basis + " · fiscal year ended " + d.period_end + " · prior column " + d.prior_period_end +
        " · filed " + d.filed_date + " · EDINET " + d.doc_id + " · SHA-256 " + d.sha256,
      "trust: official (as filed) · source: EDINET, Financial Services Agency of Japan · values in yen exactly as tagged",
      "change_yen = current − prior (derived on this platform); negated = filer prints the line with its sign reversed",
    ], ["ord", "depth", "element", "label_ja", "label_en", "label_en_source", "is_heading", "is_total",
        "negated", "unit", "current", "prior", "change"],
      d.lines.map(function (l) {
        var chg = (l.current != null && l.prior != null) ? l.current - l.prior : null;
        return [l.ord, l.depth, l.element, l.label_ja, l.label_en, l.label_en_source, l.is_heading,
                l.is_total, l.negated, l.unit, l.current, l.prior, chg];
      }));
  }

  function setSeg(id, attr, value) {
    Array.prototype.forEach.call($(id).querySelectorAll("button"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute(attr) === value ? "true" : "false");
    });
  }

  function initCompany(code) {
    state.code = code;
    var p = new URLSearchParams(location.search);
    if (p.get("basis") === "parent") state.basis = "parent";
    if (p.get("st") && STATEMENT_LABEL[p.get("st")]) state.st = p.get("st");
    if (p.get("fy")) state.fy = p.get("fy");
    if (p.get("chart") && CHARTS[p.get("chart")]) state.chart = p.get("chart");
    setSeg("basis-seg", "data-basis", state.basis);
    setSeg("st-seg", "data-st", state.st);
    $("chart-select").value = state.chart;

    $("basis-seg").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      state.basis = b.getAttribute("data-basis");
      setSeg("basis-seg", "data-basis", state.basis);
      renderFacts(); renderPanel(); loadStatement();
    });
    $("st-seg").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      state.st = b.getAttribute("data-st");
      setSeg("st-seg", "data-st", state.st);
      loadStatement();
    });
    $("fy-select").addEventListener("change", function () { state.fy = this.value; loadStatement(); });
    $("chart-select").addEventListener("change", function () { state.chart = this.value; syncUrl(); drawChart(); });
    $("ki-csv").addEventListener("click", panelCsv);
    $("ki-png").addEventListener("click", function () {
      if (kiChart) kiChart.exportPNG("financials-" + state.code + "-" + state.chart + ".png");
    });
    $("st-csv").addEventListener("click", statementCsv);

    getJSON(API + "/company/" + encodeURIComponent(code)).then(function (d) {
      company = d;
      renderHeader(d);
      // A filer with no consolidated statements is read on its only basis.
      if (d.consolidated === false && state.basis === "consolidated") {
        state.basis = "parent"; setSeg("basis-seg", "data-basis", "parent");
      }
      renderFacts(); renderPanel(); loadStatement(); loadMetrics();
    }).catch(function (e) {
      $("co-name").textContent = code;
      $("co-filing").textContent = e.message.indexOf("404") > -1
        ? "No accepted financial filing for this company in the archive held here."
        : "Data unavailable — " + e.message + ". The last good state is unaffected.";
    });
  }

  // ---- boot ----------------------------------------------------------------
  initThemeToggle(function () { if (company) drawChart(); });
  var code = new URLSearchParams(location.search).get("c");
  if (code) {
    $("market-view").hidden = true;
    $("company-view").hidden = false;
    initCompany(code);
  } else {
    initMarket();
  }
})();
