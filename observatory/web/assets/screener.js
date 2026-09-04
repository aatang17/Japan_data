/* Screener: platform-calculated ratios over every company's latest annual
   report, filtered and ranked. Data: /api/v1/equity/financials/screener.

   Every number here is DERIVED — computed on the platform from filed inputs —
   so it carries no badge and its formula is on the page. The filer's own ROE
   sits beside ours in every row. Missing renders as —, never 0. The URL
   carries every filter and the sort, so any screen is citable. */
(function () {
  "use strict";

  var API = "/api/v1/equity/financials";
  var COLS = [
    ["roe_pct", "ROE (%)", pct], ["roa_pct", "ROA (%)", pct],
    ["operating_margin_pct", "Op. margin (%)", pct], ["net_margin_pct", "Net margin (%)", pct],
    ["equity_ratio_pct", "Equity ratio (%)", pct], ["revenue_growth_pct", "Rev. growth (%)", pct],
    ["cash_conversion_x", "Cash conv. (×)", times], ["fcf_margin_pct", "FCF margin (%)", pct],
    ["cash_to_assets_pct", "Cash/assets (%)", pct], ["pbr_implied_x", "PBR impl. (×)", times],
    ["dividend_yield_implied_pct", "Yield impl. (%)", pct],
  ];
  var SIZE_LABEL = { revenue_yen: "Revenue (¥bn)", profit_yen: "Profit (¥bn)",
    total_assets_yen: "Total assets (¥bn)", equity_owners_yen: "Equity (¥bn)",
    cf_operating_yen: "Operating CF (¥bn)" };
  var FILTER_IDS = { industry: "f-industry", standard: "f-standard", min_revenue_yen: "f-min-rev",
    min_assets_yen: "f-min-assets", roe_min: "f-roe-min", roa_min: "f-roa-min",
    operating_margin_min: "f-opm-min", equity_ratio_min: "f-eqr-min", equity_ratio_max: "f-eqr-max",
    revenue_growth_min: "f-growth-min", pbr_implied_max: "f-pbr-max",
    dividend_yield_min: "f-yield-min", cash_to_assets_min: "f-cash-min" };
  var YEN_BN = { min_revenue_yen: true, min_assets_yen: true };   // page shows ¥bn, API wants yen

  var FLAG_LABEL = { negative_equity: "negative equity",
                     negative_equity_prior_year: "negative equity a year ago" };
  var state = { sort: "roe_pct", order: "desc" };
  var options = null;
  var data = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) { return escapeHtml(String(s == null ? "" : s)); }
  function pct(v) { return v == null ? MISSING : fmtRate(v, 1); }
  function times(v) { return v == null ? MISSING : fmtNum(v, 2) + "×"; }
  function yenBn(v) { return v == null ? MISSING : "¥" + fmtNum(v / 1e9, 1) + "bn"; }
  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) return r.json().then(function (b) { throw new Error(b.detail || (url + " -> " + r.status)); },
        function () { throw new Error(url + " -> " + r.status); });
      return r.json();
    });
  }
  function nameCell(en, ja, href) {
    var main = en || ja || MISSING;
    var sub = en && ja ? "<span class='sub'>" + esc(ja) + "</span>" : "";
    return "<div class='cell-name'><a href='" + href + "'>" + esc(main) + "</a>" + sub + "</div>";
  }

  // ---- URL state -----------------------------------------------------------
  function readUrl() {
    var p = new URLSearchParams(location.search);
    if (p.get("sort")) state.sort = p.get("sort");
    if (p.get("order") === "asc") state.order = "asc";
    Object.keys(FILTER_IDS).forEach(function (k) {
      var v = p.get(k);
      if (v != null) $(FILTER_IDS[k]).value = YEN_BN[k] ? String(Number(v) / 1e9) : v;
    });
    $("f-sort").value = state.sort;
    $("f-order").value = state.order;
  }
  function filterParams() {
    var q = new URLSearchParams();
    q.set("sort", state.sort);
    if (state.order === "asc") q.set("order", "asc");
    Object.keys(FILTER_IDS).forEach(function (k) {
      var v = $(FILTER_IDS[k]).value.trim();
      if (v === "") return;
      q.set(k, YEN_BN[k] ? String(Number(v) * 1e9) : v);
    });
    return q;
  }
  function syncUrl(q) {
    var s = q.toString();
    history.replaceState(null, "", "screener.html" + (s ? "?" + s : ""));
  }

  // ---- render ---------------------------------------------------------------
  function render(d) {
    data = d;
    var sortIsSize = !!SIZE_LABEL[d.sort];
    // The ranked column leads the metric columns so it is never off-screen.
    var cols = COLS.slice().sort(function (a, b) {
      return (b[0] === d.sort ? 1 : 0) - (a[0] === d.sort ? 1 : 0);
    });
    var sortLabel = sortIsSize ? SIZE_LABEL[d.sort]
      : (options.metrics.find(function (m) { return m.metric === d.sort; }) || {}).label || d.sort;
    $("res-count").textContent = fmtNum(d.ranked, 0) + " of " + fmtNum(d.universe, 0) + " companies · ranked by " + sortLabel;
    var filt = Object.keys(d.filters).filter(function (k) { return d.filters[k] != null; }).length;
    $("res-meta").innerHTML = "<b>" + fmtNum(d.matched, 0) + " companies</b> match " +
      (filt ? filt + (filt === 1 ? " filter" : " filters") : "no filters") + "; " +
      fmtNum(d.excluded_missing_sort, 0) + " of them have no " + esc(sortLabel) +
      " and are left out of the ranking. One filing per company, its latest accepted annual report; " +
      "consolidated where the filer reports one. Showing " + fmtNum(d.rows.length, 0) +
      (d.rows.length < d.ranked ? " of " + fmtNum(d.ranked, 0) : "") + ".";

    var head = "<thead><tr><th class=r>#</th><th>Company</th><th>Industry</th><th class=r>Revenue (¥bn)</th>" +
      (sortIsSize && d.sort !== "revenue_yen" ? "<th class='r sorted'>" + esc(SIZE_LABEL[d.sort]) + "</th>" : "") +
      cols.map(function (c) {
        var on = c[0] === d.sort;
        return "<th class='r sortable" + (on ? " sorted" : "") + "' data-sort='" + c[0] + "' title='Rank by this column'>" +
          esc(c[1]) + (on ? (d.order === "asc" ? " ▲" : " ▼") : "") + "</th>";
      }).join("") + "<th class=r title=\"The filer's own ROE from its five-year summary, and ours minus it\">Filer's ROE</th>" +
      "<th class=r>FY end</th></tr></thead>";
    var body = d.rows.map(function (r) {
      var m = r.metrics;
      var chk = r.checks.roe_vs_filed_pp;
      var filed = r.filed.roe_pct == null ? MISSING : fmtRate(r.filed.roe_pct, 1) +
        (chk == null ? "" : " <span class='chk" + (Math.abs(chk) > 1 ? " off" : "") + "'>" + fmtSigned(chk, 1, "pp") + "</span>");
      return "<tr><td class=r>" + r.rank + "</td><td>" +
        nameCell(r.filer_name_en, r.filer_name, "financials.html?c=" + esc(r.sec_code)) +
        "</td><td>" + esc(r.industry_en || r.industry || MISSING) +
        "</td><td class=r>" + yenBn(r.size.revenue_yen) + "</td>" +
        (sortIsSize && d.sort !== "revenue_yen" ? "<td class='r sorted'>" + yenBn(r.size[d.sort]) + "</td>" : "") +
        cols.map(function (c) {
          // A ratio withheld because its base is unusable shows the reason, not
          // a bare dash: negative equity is the finding, not a missing number.
          var body = c[2](m[c[0]]);
          if (m[c[0]] == null && c[0] === "roe_pct" && r.flags && r.flags.length) {
            body = "<span class='flag' title='" + esc(r.checks.roe_withheld || "") + "'>" +
              esc(FLAG_LABEL[r.flags[0]] || r.flags[0]) + "</span>";
          }
          return "<td class='r" + (c[0] === d.sort ? " sorted" : "") + "'>" + body + "</td>";
        }).join("") +
        "<td class=r>" + filed + "</td><td class=r>" + esc(r.period_end.slice(0, 7)) + "</td></tr>";
    }).join("");
    $("res-table").innerHTML = head + "<tbody>" + body + "</tbody>";
    Array.prototype.forEach.call($("res-table").querySelectorAll("th.sortable"), function (th) {
      th.addEventListener("click", function () {
        var k = th.getAttribute("data-sort");
        if (state.sort === k) state.order = state.order === "desc" ? "asc" : "desc";
        else { state.sort = k; state.order = "desc"; }
        $("f-sort").value = state.sort; $("f-order").value = state.order;
        load();
      });
    });
    $("res-formula").textContent = "Every column is calculated on this platform from the filed " +
      "statements; the formulas are listed under Show calculation. ROE and ROA use average opening " +
      "and closing balances. \"Implied\" uses the price implied by the filer's own year-end PER. " +
      "A difference over 1 pp between our ROE and the filer's is marked.";
    $("calc-list").innerHTML = options.metrics.map(function (m) {
      return "<li><b>" + esc(m.label) + "</b> — " + esc(m.formula) + "</li>";
    }).join("") + "<li><b>Equity attributable to owners</b> — " + esc(d.calc.equity_owners_yen) + "</li>";
  }

  function load() {
    var q = filterParams();
    syncUrl(q);
    q.set("limit", "200");
    $("res-count").textContent = "loading…";
    getJSON(API + "/screener?" + q.toString()).then(render).catch(function (e) {
      $("res-meta").innerHTML = "<span class='state-error'>" + esc(e.message) + "</span>";
      $("res-count").textContent = "";
    });
  }

  function csv() {
    if (!data) return;
    var cols = ["rank", "sec_code", "filer_name", "filer_name_en", "industry", "industry_en",
      "accounting_standard", "basis", "period_end", "doc_id", "revenue_yen", "profit_yen",
      "total_assets_yen", "equity_owners_yen", "cf_operating_yen"]
      .concat(options.metrics.map(function (m) { return m.metric; }))
      .concat(["roe_filed_pct", "roe_vs_filed_pp", "equity_ratio_filed_pct"]);
    var header = [
      "Japan Data Observatory — screener, ranked by " + data.sort + " (" + data.order + ")",
      "filters: " + JSON.stringify(data.filters),
      "trust: derived — every ratio calculated on this platform from filed inputs; size fields in yen as filed",
    ].concat(options.metrics.map(function (m) { return m.metric + " = " + m.formula; }))
      .concat(["equity_owners_yen = " + data.calc.equity_owners_yen,
               "source of inputs: EDINET, Financial Services Agency of Japan"]);
    var lines = header.map(function (l) { return "# " + l; });
    lines.push(cols.join(","));
    data.rows.forEach(function (r) {
      var row = [r.rank, r.sec_code, r.filer_name, r.filer_name_en, r.industry, r.industry_en,
        r.accounting_standard, r.basis, r.period_end, r.doc_id, r.size.revenue_yen, r.size.profit_yen,
        r.size.total_assets_yen, r.size.equity_owners_yen, r.size.cf_operating_yen]
        .concat(options.metrics.map(function (m) { return r.metrics[m.metric]; }))
        .concat([r.filed.roe_pct, r.checks.roe_vs_filed_pp, r.filed.equity_ratio_pct]);
      lines.push(row.map(function (v) {
        v = v == null ? "" : String(v);
        return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
      }).join(","));
    });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" }));
    a.download = "screener-" + data.sort + ".csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---- boot ------------------------------------------------------------------
  initThemeToggle();
  getJSON(API + "/screener/options").then(function (o) {
    options = o;
    $("f-sort").innerHTML = o.metrics.map(function (m) {
      return "<option value='" + esc(m.metric) + "'>" + esc(m.label) + " (" + esc(m.unit) + ")</option>";
    }).join("") + o.size_fields.map(function (f) {
      return "<option value='" + esc(f) + "'>" + esc(SIZE_LABEL[f] || f) + "</option>";
    }).join("");
    $("f-industry").innerHTML += o.industries.map(function (i) {
      return "<option value='" + esc(i.industry) + "'>" + esc(i.industry_en || i.industry) +
        " (" + fmtNum(i.companies, 0) + ")</option>";
    }).join("");
    $("f-standard").innerHTML += o.standards.map(function (s) {
      return "<option value='" + esc(s.standard) + "'>" + esc(s.standard) + " (" + fmtNum(s.companies, 0) + ")</option>";
    }).join("");
    readUrl();
    load();
  }).catch(function (e) {
    $("res-meta").innerHTML = "<span class='state-error'>" + esc(e.message) + "</span>";
  });
  $("filters").addEventListener("submit", function (e) {
    e.preventDefault();
    state.sort = $("f-sort").value; state.order = $("f-order").value;
    load();
  });
  $("f-reset").addEventListener("click", function () {
    Object.keys(FILTER_IDS).forEach(function (k) { $(FILTER_IDS[k]).value = ""; });
    state.sort = "roe_pct"; state.order = "desc";
    $("f-sort").value = state.sort; $("f-order").value = state.order;
    load();
  });
  $("res-csv").addEventListener("click", csv);
})();
