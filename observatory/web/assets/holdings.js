/* Cross-shareholdings page: sector unwind view + per-company both-directions view.
   Data: /api/v1/equity/*. Book values official-as-filed; deltas derived client-side
   and labelled as calculated. Missing renders as —, never 0. */
(function () {
  "use strict";

  var MINUS = "−";
  var chart = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) { return escapeHtml(String(s == null ? "" : s)); }

  function yenBn(v, dp) {
    if (v == null) return MISSING;
    return fmtNum(v / 1e9, dp == null ? 1 : dp);
  }
  function signedBn(v) {
    if (v == null) return MISSING;
    var s = v < 0 ? MINUS : "+";
    return s + fmtNum(Math.abs(v) / 1e9, 1);
  }
  function shares(v) { return v == null ? MISSING : fmtNum(v, 0); }
  function mutual(rec) {
    if (!rec) return MISSING;
    if (rec.indexOf("有") === 0) return "Mutual";      // 有
    if (rec.indexOf("無") === 0) return "—";      // 無 -> em dash
    return MISSING;
  }
  function periodShort(iso) { return iso ? String(iso).slice(0, 7) : MISSING; }

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

  // ---- sector view ---------------------------------------------------------
  function renderStrip(s) {
    // Year-ends are staggered and delisted filers stop filing, so the reference
    // period is a range, not a single FY. Say so rather than name one year.
    var asof = s.earliest_period_end && s.latest_period_end
      ? "FY ends " + periodShort(s.earliest_period_end) + " – " + periodShort(s.latest_period_end)
      : "latest filing per company";
    $("stat-strip").innerHTML =
      '<div class="strip-grid">' +
      cell("Named policy holdings", "¥" + fmtNum(s.total_book_value_yen / 1e12, 2) + '<span class="unit"> tn</span>',
           s.named_holdings.toLocaleString() + " named holdings · " + asof) +
      cell("Positions cut vs added", fmtNum(s.positions_reduced, 0) + '<span class="unit"> · </span>' + fmtNum(s.positions_increased, 0),
           "reduced · increased, year on year (calculated)") +
      cell("Mutual holdings", fmtNum(s.reciprocal_pairs, 0),
           "of " + s.named_holdings.toLocaleString() + " — issuer holds the filer’s shares too (as filed)") +
      cell("Coverage", fmtNum(s.filers, 0) + '<span class="unit"> filers</span>',
           (s.extraction_status.clean || 0) + " clean · " + (s.extraction_status.partial || 0) + " partial · " +
           (s.extraction_status.failed || 0) + " failed — status disclosed per filing") +
      "</div>";
    function cell(label, value, foot) {
      return '<div class="strip-cell"><div class="strip-label">' + label +
        '</div><div class="strip-value num">' + value +
        '</div><div class="strip-foot">' + foot + "</div></div>";
    }
  }

  function renderChart(filers) {
    // The honest unwind measure is positions cut vs added: book values are
    // fair-valued, so a rising market inflates Δ value even mid-unwind.
    var top = filers.filter(function (f) { return (f.reduced || 0) + (f.increased || 0) > 0; })
      .sort(function (a, b) { return (b.reduced + b.increased) - (a.reduced + a.increased); })
      .slice(0, 14)
      .sort(function (a, b) { return (a.reduced - a.increased) - (b.reduced - b.increased); })
      .reverse();

    var el = $("unwind-chart");
    chart = echarts.init(el, null, { renderer: "canvas" });
    var neg = cssVar("--obs-diverge-neg") || "#2f6f8f";
    var pos = cssVar("--obs-diverge-pos") || "#b3703a";
    // at phone widths the outside bar labels collide with category names;
    // the tooltip still carries exact values
    var showLabels = el.clientWidth >= 560;
    var opt = {
      animation: false,
      grid: { left: 8, right: 56, top: 28, bottom: 24, containLabel: true },
      legend: {
        top: 0, right: 0, itemWidth: 10, itemHeight: 10, icon: "rect",
        textStyle: { color: cssVar("--obs-text-muted"), fontSize: 11.5 }
      },
      xAxis: {
        type: "value", name: "positions", nameLocation: "end", nameGap: 8,
        // headroom so the outside labels of the longest bars never touch the edges
        min: -Math.ceil(Math.max.apply(null, top.map(function (f) { return f.reduced; })) * 1.18),
        max: Math.ceil(Math.max.apply(null, top.map(function (f) { return f.increased; })) * 1.3),
        axisLabel: {
          color: cssVar("--obs-text-muted"),
          formatter: function (v) { return fmtNum(Math.abs(v), 0); }
        },
        splitLine: { lineStyle: { color: cssVar("--obs-grid") } },
        axisLine: { show: false }, nameTextStyle: { color: cssVar("--obs-text-muted") }
      },
      yAxis: {
        type: "category",
        data: top.map(function (f) { return f.name.replace(/株式会社/g, "").trim(); }),
        axisLabel: { color: cssVar("--obs-ink"), fontSize: 11.5, width: 190, overflow: "truncate" },
        axisTick: { show: false }, axisLine: { show: false }
      },
      tooltip: {
        trigger: "axis", axisPointer: { type: "shadow" },
        formatter: function (ps) {
          var f = top[ps[0].dataIndex];
          return esc(f.name) + " (" + esc(f.sec_code) + ")<br>" +
            "Positions cut: <b>" + fmtNum(f.reduced, 0) + "</b> · added: <b>" +
            fmtNum(f.increased, 0) + "</b><br>" +
            "<span style='opacity:.75'>share counts vs prior FY, as filed; " +
            "additions can include stock splits</span>";
        }
      },
      series: [
        { name: "Cut", type: "bar", stack: "s", barMaxWidth: 14,
          itemStyle: { color: neg },
          data: top.map(function (f) { return -f.reduced; }),
          label: { show: showLabels, position: "left", fontSize: 11,
                   color: cssVar("--obs-text-muted"),
                   formatter: function (p) { return fmtNum(Math.abs(p.value), 0); } } },
        { name: "Added", type: "bar", stack: "s", barMaxWidth: 14,
          itemStyle: { color: pos },
          data: top.map(function (f) { return f.increased; }),
          label: { show: showLabels, position: "right", fontSize: 11,
                   color: cssVar("--obs-text-muted"),
                   formatter: function (p) { return fmtNum(p.value, 0); } } }
      ]
    };
    chart.setOption(opt);
    window.addEventListener("resize", function () { chart && chart.resize(); });
  }

  function renderUnwindTable(filers) {
    var head = "<thead><tr>" +
      "<th>Filer</th><th class=r>Code</th><th class=r>FY end</th>" +
      "<th class=r>Named holdings</th><th class=r>Book value (¥bn)</th>" +
      "<th class=r>Prior (¥bn)</th><th class=r>Δ (¥bn)</th>" +
      "<th class=r>Cut</th><th class=r>Added</th></tr></thead>";
    var body = filers.map(function (f) {
      var d = (f.book_value_yen != null && f.prior_book_value_yen != null)
        ? f.book_value_yen - f.prior_book_value_yen : null;
      return "<tr><td><a href='holdings.html?c=" + esc(f.sec_code) + "'>" + esc(f.name) + "</a></td>" +
        "<td class='r mono'>" + esc(f.sec_code) + "</td>" +
        "<td class=r>" + periodShort(f.period_end) + "</td>" +
        "<td class=r>" + fmtNum(f.named_holdings, 0) + "</td>" +
        "<td class=r>" + yenBn(f.book_value_yen) + "</td>" +
        "<td class=r>" + yenBn(f.prior_book_value_yen) + "</td>" +
        "<td class=r>" + (d == null ? MISSING : signedBn(d)) + "</td>" +
        "<td class=r>" + fmtNum(f.reduced, 0) + "</td>" +
        "<td class=r>" + fmtNum(f.increased, 0) + "</td></tr>";
    }).join("");
    $("unwind-table").innerHTML = head + "<tbody>" + body + "</tbody>";
    $("unwind-count").textContent = filers.length + " filers";
  }

  function loadSector() {
    Promise.all([getJSON("/api/v1/equity/summary"), getJSON("/api/v1/equity/unwind")])
      .then(function (rs) {
        var summary = rs[0], unwind = rs[1];
        renderStrip(summary);
        renderChart(unwind.filers);
        renderUnwindTable(unwind.filers);
        $("chart-asof").textContent = "named positions cut vs added, YoY · calculated";
        $("chart-source").textContent =
          "Source: annual securities reports via EDINET (FSA). Book values as filed; Δ calculated.";
        $("header-asof").textContent = "Each company's latest filing · through " +
          periodShort(summary.latest_period_end);
        $("unwind-csv").onclick = function () {
          csvDownload("cross-shareholdings-unwind.csv",
            ["Cross-shareholdings — unwind by filer",
             "Source: EDINET annual securities reports; each company on its latest filing; book values official as filed",
             "Delta = current minus prior FY named book value (calculated)",
             "Retrieved: " + new Date().toISOString().slice(0, 10),
             "Missing values are empty, never 0"],
            ["filer", "sec_code", "fy_end", "named_holdings", "book_value_yen",
             "prior_book_value_yen", "delta_yen_calculated", "reduced", "increased"],
            unwind.filers.map(function (f) {
              var d = (f.book_value_yen != null && f.prior_book_value_yen != null)
                ? f.book_value_yen - f.prior_book_value_yen : null;
              return [f.name, f.sec_code, f.period_end, f.named_holdings,
                      f.book_value_yen, f.prior_book_value_yen, d, f.reduced, f.increased];
            }));
        };
        $("chart-png").onclick = function () {
          if (!chart) return;
          var url = chart.getDataURL({ pixelRatio: 2, backgroundColor: cssVar("--obs-surface") || "#fff" });
          var a = document.createElement("a");
          a.href = url; a.download = "cross-shareholdings-unwind.png"; a.click();
        };
      })
      .catch(function (e) {
        $("stat-strip").innerHTML = "<p class='table-meta'>Data unavailable — " +
          esc(e.message) + ". The last good state is unaffected; try reloading.</p>";
      });
  }

  // ---- company view --------------------------------------------------------
  function holdingsRows(holdings) {
    var out = [];
    holdings.forEach(function (h, i) {
      var d = (h.shares != null && h.prior_shares != null) ? h.shares - h.prior_shares : null;
      var name = h.held_sec_code
        ? "<a href='holdings.html?c=" + esc(h.held_sec_code) + "'>" + esc(h.held_name_raw) + "</a>"
        : esc(h.held_name_raw);
      out.push("<tr><td>" + name +
        (h.match_status === "foreign" ? " <span class='h2-note'>overseas</span>" : "") + "</td>" +
        "<td class=r>" + shares(h.shares) + "</td>" +
        "<td class=r>" + shares(h.prior_shares) + "</td>" +
        "<td class=r>" + (d == null ? MISSING : (d === 0 ? "0" : (d < 0 ? MINUS : "+") + fmtNum(Math.abs(d), 0))) + "</td>" +
        "<td class=r>" + yenBn(h.book_value_yen) + "</td>" +
        "<td class=r>" + yenBn(h.prior_book_value_yen) + "</td>" +
        "<td class=r>" + mutual(h.reciprocal) + "</td>" +
        "<td>" + (h.purpose_ja
          ? "<button type=button class=purpose-toggle data-i=" + i + ">Stated purpose</button>"
          : MISSING) + "</td></tr>");
      if (h.purpose_ja) {
        out.push("<tr class=purpose-row hidden data-for=" + i + "><td colspan=8>" +
          "<b>Stated reason for holding (as filed):</b> " + esc(h.purpose_ja) + "</td></tr>");
      }
    });
    return out.join("");
  }

  function loadCompany(code) {
    getJSON("/api/v1/equity/company/" + encodeURIComponent(code)).then(function (d) {
      $("sector-view").hidden = true;
      $("company-view").hidden = false;
      var name = (d.entity && d.entity.name_ja) ||
                 (d.filing && d.filing.filer_name) ||
                 (d.holders[0] && d.holders[0].holder_name) || code;
      document.title = name + " · Cross-Shareholdings · Observatory";
      $("co-name").textContent = name;
      $("co-code").textContent = code;
      $("co-industry").textContent = (d.entity && d.entity.industry) || "";
      $("header-asof").textContent = d.filing
        ? "FY end " + periodShort(d.filing.period_end)
        : "No extracted filing";

      if (d.filing) {
        $("co-filing").innerHTML = "Filing: <span class=mono>" + esc(d.filing.doc_id) +
          "</span> · FY end " + periodShort(d.filing.period_end) +
          " · filed " + esc(d.filing.filed_date) +
          " · archived SHA-256 <span class=mono>" +
          (d.filing.sha256 ? esc(String(d.filing.sha256).slice(0, 12)) + "…" : MISSING) + "</span>" +
          (d.filing.status !== "clean"
            ? " · <b>extraction status: " + esc(d.filing.status) + "</b> (disclosed, see methodology)"
            : "") +
          " · Official statistic — figures exactly as filed";
      } else {
        $("co-filing").textContent =
          "No extracted filing for this company (it may not disclose named policy holdings, " +
          "or its next fiscal year is not yet filed) — " +
          "the holders view below is still complete for covered filers.";
      }

      if (d.holdings.length) {
        $("holdings-sec").hidden = false;
        $("holdings-count").textContent = d.holdings.length + " named holdings";
        $("holdings-table").innerHTML = "<thead><tr>" +
          "<th>Held company</th><th class=r>Shares</th><th class=r>Prior shares</th>" +
          "<th class=r title='Share counts as filed — a 2×/3×/5× jump with an unchanged position is usually a stock split, not a purchase'>Δ shares*</th>" +
          "<th class=r>Book value (¥bn)</th>" +
          "<th class=r>Prior (¥bn)</th><th class=r>Mutual</th><th>Purpose</th>" +
          "</tr></thead><tbody>" + holdingsRows(d.holdings) + "</tbody>" +
          "<tfoot><tr><td colspan=8 style='font-size:12px;color:var(--obs-text-muted)'>" +
          "* Δ shares compares the two as-filed columns; filings are not adjusted for stock " +
          "splits, so a round multiple usually indicates a split rather than a purchase.</td></tr></tfoot>";
        $("holdings-table").addEventListener("click", function (e) {
          var b = e.target.closest(".purpose-toggle");
          if (!b) return;
          var row = document.querySelector(".purpose-row[data-for='" + b.dataset.i + "']");
          if (row) row.hidden = !row.hidden;
        });
        $("holdings-csv").onclick = function () {
          csvDownload("holdings-" + code + ".csv",
            ["Policy shareholdings of " + name + " (" + code + ")",
             "Source: EDINET filing " + d.filing.doc_id + ", archived SHA-256 " + d.filing.sha256,
             "Official statistics as filed; delta columns calculated",
             "Missing values are empty, never 0"],
            ["held_company", "held_sec_code", "match_status", "shares", "prior_shares",
             "book_value_yen", "prior_book_value_yen", "reciprocal_as_filed", "purpose_ja"],
            d.holdings.map(function (h) {
              return [h.held_name_raw, h.held_sec_code, h.match_status, h.shares, h.prior_shares,
                      h.book_value_yen, h.prior_book_value_yen, h.reciprocal, h.purpose_ja];
            }));
        };
      } else { $("holdings-sec").hidden = true; }

      if (d.holders.length) {
        $("holders-sec").hidden = false;
        $("holders-count").textContent = d.holders.length + " disclosed holders";
        $("holders-table").innerHTML = "<thead><tr>" +
          "<th>Holder</th><th class=r>Code</th><th class=r>FY end</th>" +
          "<th class=r>Shares</th><th class=r>Book value (¥bn)</th>" +
          "<th class=r>Prior (¥bn)</th><th class=r>Mutual</th></tr></thead><tbody>" +
          d.holders.map(function (h) {
            return "<tr><td><a href='holdings.html?c=" + esc(h.holder_sec_code) + "'>" +
              esc(h.holder_name) + "</a></td>" +
              "<td class='r mono'>" + esc(h.holder_sec_code) + "</td>" +
              "<td class=r>" + periodShort(h.period_end) + "</td>" +
              "<td class=r>" + shares(h.shares) + "</td>" +
              "<td class=r>" + yenBn(h.book_value_yen) + "</td>" +
              "<td class=r>" + yenBn(h.prior_book_value_yen) + "</td>" +
              "<td class=r>" + mutual(h.reciprocal) + "</td></tr>";
          }).join("") + "</tbody>";
        $("holders-csv").onclick = function () {
          csvDownload("holders-of-" + code + ".csv",
            ["Policy holders of " + name + " (" + code + ")",
             "Source: each holder's EDINET annual securities report (doc ids in column)",
             "Official statistics as filed",
             "Coverage: filers that disclose named policy holdings — not the full shareholder register"],
            ["holder", "holder_sec_code", "doc_id", "fy_end", "shares",
             "book_value_yen", "prior_book_value_yen", "reciprocal_as_filed"],
            d.holders.map(function (h) {
              return [h.holder_name, h.holder_sec_code, h.doc_id, h.period_end,
                      h.shares, h.book_value_yen, h.prior_book_value_yen, h.reciprocal];
            }));
        };
      } else { $("holders-sec").hidden = true; }
    }).catch(function () {
      $("sector-view").hidden = true;
      $("company-view").hidden = false;
      $("co-name").textContent = "No data for " + code;
      $("co-filing").textContent =
        "No covered filing and no covered holder names this securities code. " +
        "Coverage is filers that disclose named policy holdings; see the filer list.";
    });
  }

  // ---- search --------------------------------------------------------------
  function initSearch() {
    var t = null;
    $("q").addEventListener("input", function () {
      clearTimeout(t);
      var q = this.value.trim();
      if (!q) { $("search-results").innerHTML = ""; return; }
      t = setTimeout(function () {
        getJSON("/api/v1/equity/companies?q=" + encodeURIComponent(q)).then(function (d) {
          $("search-results").innerHTML = d.companies.length
            ? "<div class='table-wrap' style='margin-top:8px'><table class='tbl-hold'><tbody>" +
              d.companies.map(function (c) {
                return "<tr><td><a href='holdings.html?c=" + esc(c.sec_code) + "'>" + esc(c.name) +
                  "</a></td><td class='r mono'>" + esc(c.sec_code) + "</td>" +
                  "<td class=r>" + (c.holdings_count ? fmtNum(c.holdings_count, 0) + " holdings" : "") + "</td>" +
                  "<td class=r>" + (c.held_by_count ? "held by " + fmtNum(c.held_by_count, 0) : "") + "</td></tr>";
              }).join("") + "</tbody></table></div>"
            : "<p class='table-meta'>No covered company matches “" + esc(q) + "”.</p>";
        });
      }, 200);
    });
  }

  // ---- boot ----------------------------------------------------------------
  initThemeToggle(function () { if (chart) { location.reload(); } });
  var code = new URLSearchParams(location.search).get("c");
  if (code) { loadCompany(code); } else { loadSector(); initSearch(); }
})();
