/* Home page: the front door of the platform.

   Everything numeric on this page is fetched from the same API the product
   pages use when the page loads — the ticker, the coverage numbers, the
   trace across the hero, the four assistant scenarios, the API response
   sample and the featured chart. Nothing is baked into the markup, so the
   page cannot show a number the platform would not serve. A source that
   cannot be reached leaves its slot empty or its scenario out of the
   rotation; it never shows a stale or invented value.

   The assistant block is a demonstration of the MCP path, not a live model
   call: the questions are fixed, the tool names are the MCP server's real
   ones, and the answers are composed here from the API's own numbers. */
"use strict";

const API = "/api/v1";
const CHARTS = [];   // obsChart handles, re-rendered on theme change
const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function getJSON(url) {
  return fetch(url).then(r => (r.ok ? r.json() : Promise.reject(new Error(url + " " + r.status))));
}
function $(id) { return document.getElementById(id); }
function lastValue(points) {
  for (let i = points.length - 1; i >= 0; i--) {
    const v = Array.isArray(points[i]) ? points[i][1] : points[i];
    if (v !== null && v !== undefined) return { v: v, i: i };
  }
  return null;
}
function monthsAgo(iso, n) {   // "2026-07" -> n months earlier, "YYYY-MM"
  const y = Number(iso.slice(0, 4)), m = Number(iso.slice(5, 7)) - 1 - n;
  const d = new Date(Date.UTC(y, m, 1));
  return d.getUTCFullYear() + "-" + String(d.getUTCMonth() + 1).padStart(2, "0");
}
function dayLong(iso) { return Number(iso.slice(8, 10)) + " " + fmtPeriodLong(iso); }
function bn(yen, dp) { return fmtNum(yen / 1e9, dp === undefined ? 0 : dp); }

/* Filers state their English name in capitals with a corporate suffix;
   a chart label wants "Denso", not "DENSO CORPORATION". */
function shortName(s) {
  let n = String(s || "")
    .replace(/\s*(CORPORATION|CORP\.?|CO\.,\s?LTD\.?|CO\.,LTD\.|COMPANY LIMITED|LIMITED|LTD\.?|HOLDINGS,?\s?INC\.?|GROUP,?\s?INC\.?|,?\s?INC\.?|K\.K\.)\s*$/i, "")
    .replace(/\s*(HOLDINGS|GROUP)\s*$/i, "")
    .trim();
  n = n.replace(/^THE\s+/i, "").replace(/[\s,]+$/, "");
  if (n === n.toUpperCase()) n = n.toLowerCase().replace(/(^|[\s\-&(])([a-z])/g, (m, a, b) => a + b.toUpperCase());
  return n.replace(/\bOf\b/g, "of").replace(/\bAnd\b/g, "and");
}

/* ---------- theme ---------- */
initThemeToggle(() => CHARTS.forEach(h => h.render()));

/* ---------- ticker ---------- */

function tickerItem(label, value, note) {
  return '<span class="home-tick"><span class="home-tick-label">' + escapeHtml(label) +
    '</span><span class="home-tick-value num">' + escapeHtml(value) + "</span>" +
    (note ? '<span class="home-tick-note num">' + escapeHtml(note) + "</span>" : "") + "</span>";
}

function fillTicker() {
  const from = new Date(); from.setMonth(from.getMonth() - 2);
  const start = from.getFullYear() + "-" + String(from.getMonth() + 1).padStart(2, "0");
  const jobs = [
    getJSON(API + "/cpi-jp/overview").then(d => {
      const t = d.tiles.find(x => x.key === "headline_yoy");
      return ["CPI headline", fmtRate(t.value, 1), "YoY · " + fmtPeriodLong(d.release.latest_period)];
    }),
    getJSON(API + "/jgb-yields/observations?series=10Y&measure=index&start=" + start).then(d => {
      const l = lastValue(d.series[0].points);
      return ["10-year JGB", fmtRate(l.v, 3), dayLong(d.series[0].points[l.i][0])];
    }),
    getJSON(API + "/boj-assets/overview").then(d => {
      const h = d.tiles.find(x => x.key === "holdings");
      return ["BOJ JGB holdings", "¥" + fmtNum(h.value / 10000, 1) + "tn", fmtPeriodLong(d.release.latest_period)];
    }),
    getJSON(API + "/jnto-visitors/arrivals").then(d => {
      const l = lastValue(d.values.total);
      return ["Visitor arrivals", fmtNum(l.v / 1e6, 2) + "mn", fmtPeriodLong(d.periods[l.i])];
    }),
    getJSON(API + "/rice-prices-jp/overview").then(d => {
      const t = d.tiles.find(x => x.key === "all_brands");
      return ["Rice contract price", "¥" + fmtNum(t.value, 0), "per 60kg · " + fmtPeriodLong(d.release.latest_period)];
    }),
    getJSON(API + "/equity/summary").then(d =>
      ["Cross-shareholdings", "¥" + fmtNum(d.total_book_value_yen / 1e12, 2) + "tn", "at book"]),
    getJSON(API + "/equity/buyback/summary").then(d =>
      ["Buybacks authorised", "¥" + fmtNum(d.authorised_yen / 1e12, 2) + "tn", "to " + dayLong(d.last_submitted)]),
    getJSON(API + "/equity/stakes/summary").then(d =>
      ["5% filings", fmtNum(d.filings, 0), "parsed"]),
    getJSON(API + "/population-jp/prefectures").then(d => {
      const col = d.values[(d.national || "00") + ".all.population"];
      return ["Population", fmtNum(col[col.length - 1] / 1e6, 2) + "mn", "1 Jan " + d.periods[d.periods.length - 1].slice(0, 4)];
    }),
  ];
  return Promise.allSettled(jobs).then(rs => {
    const items = rs.filter(r => r.status === "fulfilled").map(r => tickerItem.apply(null, r.value));
    if (!items.length) { $("ticker").parentNode.hidden = true; return; }
    // The strip scrolls by half its width, so the list is laid twice.
    $("ticker").innerHTML = items.join("") + items.join("");
  });
}

/* ---------- hero: status line and the CPI trace ---------- */

function fillHeroStatus() {
  return getJSON(API + "/catalog/health").then(h => {
    const stale = (h.datasets || []).filter(d => d.stale).map(d => d.dataset);
    const when = h.last_ingest_at ? dayLong(h.last_ingest_at.slice(0, 10)) : null;
    $("hero-status").innerHTML = '<span class="live-dot' + (stale.length ? " is-stale" : "") + '"></span>' +
      (when ? "Updated " + escapeHtml(when) + " · " : "") +
      (stale.length ? escapeHtml(stale.length + (stale.length === 1 ? " source" : " sources") + " behind schedule")
                    : "all sources on schedule");
    return h;
  }).catch(() => { $("hero-status").innerHTML = '<span class="live-dot"></span>Live from the primary sources'; });
}

function fillHeroTrace() {
  return getJSON(API + "/cpi-jp/overview").then(ov => {
    const start = monthsAgo(ov.release.latest_period.slice(0, 7), 120);
    return getJSON(API + "/cpi-jp/observations?series=0001&measure=yoy&start=" + start).then(obs => {
      const pts = obs.series[0].points.map(p => p[1]);
      const vals = pts.filter(v => v !== null);
      if (vals.length < 2) return;
      const min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
      const x0 = 760, x1 = 1400, y0 = 150, y1 = 380;
      let d = "";
      pts.forEach((v, i) => {
        if (v === null) { d += " "; return; }   // a gap stays a gap
        const x = x0 + (i / (pts.length - 1)) * (x1 - x0);
        const y = y1 - ((v - min) / (max - min || 1)) * (y1 - y0);
        d += (d.endsWith(" ") || !d ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1);
      });
      const path = $("hero-trace-path");
      path.setAttribute("d", d);
      path.setAttribute("pathLength", "1");
      path.classList.add("is-drawn");
      const first = obs.series[0].points[0][0].slice(0, 4);
      $("hero-legend").textContent = "Headline CPI, % YoY, " + first + " to " +
        ov.release.latest_period.slice(0, 4) + " · Statistics Bureau of Japan";
      $("hero-legend").hidden = false;
    });
  }).catch(() => {});
}

/* ---------- coverage numbers ---------- */

function countUp(el, target, format) {
  if (REDUCED) { el.textContent = format(target); return; }
  const t0 = performance.now(), dur = 1800;
  const step = now => {
    const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = format(Math.round(target * e));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

const SECTION_OF = {   // dataset slug -> entry point; anything else is Macro
  "jnto-visitors": "tourism", "accommodation-jp": "tourism",
  "rice-prices-jp": "agri", "rice-inventory-jp": "agri", "agri-prices": "agri",
  "ja-statistics": "agri", "rice-cost-jp": "agri",
  "trade-semis": "trade", "trade-inputs": "trade", "trade-autos": "trade",
  "trade-energy": "trade", "trade-machinery": "trade", "trade-pharma": "trade",
  "trade-food": "trade",
  "population-jp": "demo", "population-jp-history": "demo", "population-jp-municipal": "demo",
};

function fillNumbers(health) {
  const n = v => fmtNum(v, 0);
  const jobs = [
    Promise.resolve(health && health.datasets ? health.datasets.length : null),
    getJSON(API + "/equity/governance/summary?listed=true").then(d => d.companies),
    getJSON(API + "/equity/stakes/summary").then(d => d.filings),
    getJSON(API + "/catalog/datasets").then(d => {
      const list = Array.isArray(d) ? d : (d.datasets || []);
      const agencies = new Set(list.map(x => x.agency));
      const by = { macro: 0, tourism: 0, agri: 0, trade: 0, demo: 0 };
      list.forEach(x => { by[SECTION_OF[x.slug] || "macro"]++; });
      // A count of zero means this server has none of the section yet; the
      // entry keeps its span line rather than advertising an empty section.
      const label = (n, since) => (n ? n + " datasets · " : "") + since;
      $("e-macro").textContent = label(by.macro, "from 1970");
      $("e-tourism").textContent = label(by.tourism, "from 2003");
      $("e-agri").textContent = label(by.agri, "from 1957");
      $("e-trade").textContent = label(by.trade, "from 2001");
      $("e-demo").textContent = label(by.demo, "from 1975");
      return agencies.size + 1;   // plus company filings via EDINET
    }),
  ];
  return Promise.allSettled(jobs).then(rs => {
    const ids = ["n-datasets", "n-companies", "n-filings", "n-sources"];
    rs.forEach((r, i) => {
      if (r.status === "fulfilled" && r.value !== null) countUp($(ids[i]), r.value, n);
      if (i === 1 && r.status === "fulfilled") $("e-equities").textContent = n(r.value) + " companies · as filed";
    });
  });
}

/* ---------- the assistant ---------- */

const MONO = "asst-mono";

/* Each scenario loads its own data and returns what the sequence needs:
   the question, the tool rows, the answer, the trust line, the result
   pane's title and tiles, and a draw() that renders chart or table into
   the result body. A scenario whose data cannot be loaded is left out. */
const SCENARIOS = [
  // 1 · cross-shareholdings: ten largest reductions, ranked bars
  () => getJSON(API + "/equity/unwind").then(d => {
    const rows = d.filers.filter(f => f.prior_book_value_yen && f.book_value_yen !== null);
    const fy = rows.reduce((m, f) => (f.period_end > m ? f.period_end : m), "").slice(0, 4);
    const inFy = rows.filter(f => f.period_end.slice(0, 4) === fy);
    const top = inFy.map(f => ({ code: f.sec_code, name: shortName(f.name_en || f.name),
      chg: f.book_value_yen - f.prior_book_value_yen,
      pct: 100 * (f.book_value_yen - f.prior_book_value_yen) / f.prior_book_value_yen, reduced: f.reduced }))
      .sort((a, b) => a.chg - b.chg).slice(0, 10);
    if (top.length < 3) throw new Error("unwind: too few rows");
    const t = top, fyLabel = "fiscal year to " + fmtPeriodLong(fy + "-03");
    const line = x => "<b>" + escapeHtml(x.name) + "</b> (<span class=\"num\">−¥" + bn(Math.abs(x.chg)) +
      "bn, " + fmtSigned(x.pct, 1) + "%</span>)";
    return {
      q: "Which companies cut their cross-shareholdings the most in the " + fyLabel + "? Chart the ten largest reductions.",
      tools: [["get_unwind_ranking", "", fmtNum(inFy.length, 0) + " filers · FY" + fy + " · official"],
              ["get_company_holdings", "sec_code: " + t[0].code, t[0].name + " · " + t[0].reduced + " positions reduced"]],
      answer: "The largest reductions were " + line(t[0]) + ", " + line(t[1]) + " and " + line(t[2]) +
        ". The ten largest are charted on the right.",
      trust: "official", note: "carrying amount at fiscal year end, as filed",
      title: "Cross-Shareholdings — Largest Reductions", asof: "FY" + fy,
      tiles: [["Largest reduction", "−¥" + bn(Math.abs(t[0].chg)), "bn", t[0].name + ", as filed"],
              ["Ten largest combined", "−¥" + bn(Math.abs(t.reduce((a, x) => a + x.chg, 0))), "bn", "calculated"],
              ["Filers ranked", fmtNum(inFy.length, 0), "", "annual reports, FY" + fy]],
      source: "Source: annual securities reports via EDINET · carrying amount as filed",
      open: "holdings.html", kind: "chart",
      draw: el => obsChart(el, "rank", {
        items: t.map(x => ({ name: x.name, value: Math.abs(x.chg) / 1e9,
          sub: fmtSigned(x.pct, 1) + "% · " + x.reduced + " positions reduced" })),
        unit: "", dp: 0, valueLabel: "Reduction, ¥bn",
        xAxisName: "Reduction in carrying amount, ¥bn, FY" + fy + " vs prior year",
        trust: "derived", sourceLine: "Source: annual securities reports via EDINET",
      }),
    };
  }),
  // 2 · inflation: headline against food, ten years, two lines
  () => getJSON(API + "/cpi-jp/overview").then(ov => {
    const start = monthsAgo(ov.release.latest_period.slice(0, 7), 120);
    return getJSON(API + "/cpi-jp/observations?series=0001,0002&measure=yoy&start=" + start).then(obs => {
      const H = obs.series.find(s => s.code === "0001"), F = obs.series.find(s => s.code === "0002");
      const h = lastValue(H.points), f = lastValue(F.points);
      let peak = null;
      F.points.forEach(p => { if (p[1] !== null && (!peak || p[1] > peak[1])) peak = p; });
      const when = fmtPeriodLong(ov.release.latest_period);
      return {
        q: "Chart headline inflation against food inflation over the last ten years. Where are they now?",
        tools: [["search_series", "\"headline, food\"", "2 series matched"],
                ["get_series_values", "cpi-jp, 0001,0002, yoy", H.points.length + " months · calculated from official index"]],
        answer: "Headline CPI was <b class=\"num\">" + fmtNum(h.v, 1) + "%</b> year over year in " + escapeHtml(when) +
          " and food <b class=\"num\">" + fmtNum(f.v, 1) + "%</b>. Food peaked at <span class=\"num\">" +
          fmtNum(peak[1], 1) + "%</span> in " + escapeHtml(fmtPeriodLong(peak[0])) + ".",
        trust: "derived", note: "",
        title: "Consumer Price Index — Headline and Food", asof: "Data through " + when,
        tiles: [["Headline · YoY", fmtNum(h.v, 1), "%", "calculated"], ["Food · YoY", fmtNum(f.v, 1), "%", "calculated"],
                ["Food peak", fmtNum(peak[1], 1), "%", fmtPeriodLong(peak[0])]],
        source: "Source: Statistics Bureau of Japan via e-Stat · index levels official, YoY calculated from them",
        open: "cpi.html", kind: "chart",
        draw: el => obsChart(el, "line", {
          series: [{ name: "Headline CPI", slot: 1, points: H.points }, { name: "Food", slot: 2, points: F.points }],
          unit: "%", yAxisName: "% YoY", trust: obs.trust,
          sourceLine: "Source: Statistics Bureau of Japan via e-Stat · YoY calculated from published index levels",
        }),
      };
    });
  }),
  // 3 · officer pay: the eight highest-paid named officers, a table
  () => getJSON(API + "/equity/governance/named?limit=8&listed=true").then(d => {
    const P = d.rows.map(r => ({ name: r.name_en, co: shortName(r.filer_name_en || r.filer_name),
      pay: r.consolidated_pay_yen / 1e9, board: r.on_board_at_filing }));
    if (P.length < 3) throw new Error("named: too few rows");
    const who = x => "<b>" + escapeHtml(x.name) + "</b> of " + escapeHtml(x.co);
    return {
      q: "Who were the highest-paid executives in the latest annual reports? Give me a table of the top " + P.length + ".",
      tools: [["get_top_paid_officers", "limit: " + P.length, P.length + " rows · latest filing each · official"]],
      answer: who(P[0]) + " at <b class=\"num\">¥" + fmtNum(P[0].pay, 1) + "bn</b>, then " + who(P[1]) +
        " at <span class=\"num\">¥" + fmtNum(P[1].pay, 1) + "bn</span> and " + who(P[2]) + " at <span class=\"num\">¥" +
        fmtNum(P[2].pay, 1) + "bn</span>. Consolidated pay, including group companies. The table is on the right.",
      trust: "official", note: "consolidated remuneration, as filed",
      title: "Highest-Paid Named Officers", asof: "Latest annual reports",
      tiles: [["Highest", "¥" + fmtNum(P[0].pay, 1), "bn", P[0].name + ", as filed"],
              ["Top " + P.length + " combined", "¥" + fmtNum(P.reduce((a, x) => a + x.pay, 0), 1), "bn", "calculated"],
              ["Disclosure trigger", "¥100", "m", "mandatory named pay"]],
      source: "Source: annual securities reports via EDINET · consolidated remuneration as filed",
      open: "governance.html", kind: "table",
      draw: el => {
        el.classList.add("is-table");
        el.innerHTML = '<div class="table-wrap"><table class="data" data-no-enhance><thead><tr>' +
          "<th>Name</th><th>Company</th><th class=\"num\">Pay, ¥bn</th><th>On board</th></tr></thead><tbody>" +
          P.map((x, i) => '<tr class="asst-row" style="--i:' + i + '"><td><b>' + escapeHtml(x.name) + "</b></td><td>" +
            escapeHtml(x.co) + '</td><td class="num">' + fmtNum(x.pay, 2) + "</td><td>" + (x.board ? "Yes" : "No") + "</td></tr>").join("") +
          "</tbody></table></div>";
        return null;
      },
    };
  }),
  // 4 · yield curve: today against a year ago, two lines by tenor
  () => getJSON(API + "/jgb-yields/curve").then(d => {
    const dates = d.dates, iNow = dates.length - 1, now = dates[iNow];
    const target = (Number(now.slice(0, 4)) - 1) + now.slice(4);
    let iAgo = iNow; while (iAgo > 0 && dates[iAgo] > target) iAgo--;
    const codes = d.maturities.map(m => m.code);
    const curve = i => codes.map(c => [c, d.values[c][i]]);
    const nowC = curve(iNow), agoC = curve(iAgo);
    const at = (c, code) => { const p = c.find(x => x[0] === code); return p ? p[1] : null; };
    const y10 = at(nowC, "10Y"), y10a = at(agoC, "10Y"), y2 = at(nowC, "2Y"), y2a = at(agoC, "2Y");
    if (y10 === null || y10a === null) throw new Error("curve: missing 10Y");
    return {
      q: "Draw today's JGB yield curve against the same day a year ago.",
      tools: [["get_yield_curve", "", codes.length + " tenors · " + dayLong(now) + " · official"],
              ["get_yield_curve", "date: " + dates[iAgo], codes.length + " tenors · " + dayLong(dates[iAgo]) + " · official"]],
      answer: "The 10-year yield is <b class=\"num\">" + fmtNum(y10, 3) + "%</b> against <span class=\"num\">" + fmtNum(y10a, 3) +
        "%</span> a year ago, " + (y10 >= y10a ? "up" : "down") + " <span class=\"num\">" + fmtNum(Math.abs(y10 - y10a), 2) +
        " pp</span>. The 2s10s spread " + ((y10 - y2) >= (y10a - y2a) ? "widened" : "narrowed") + " to <span class=\"num\">" +
        fmtSigned(y10 - y2, 3) + " pp</span> from <span class=\"num\">" + fmtSigned(y10a - y2a, 3) + " pp</span>. The whole curve is on the right.",
      trust: "official", note: "constant-maturity yields, as published",
      title: "JGB Yield Curve — " + dayLong(now) + " vs " + dayLong(dates[iAgo]), asof: "Ministry of Finance",
      tiles: [["10-year", fmtNum(y10, 3), "%", "as published"], ["Change · 1 year", fmtSigned(y10 - y10a, 2), "pp", "calculated"],
              ["2s10s spread", fmtSigned(y10 - y2, 3), "pp", "calculated"]],
      source: "Source: Ministry of Finance · constant-maturity yields as published",
      open: "rates.html?d=" + now, kind: "chart",
      draw: el => obsChart(el, "line", {
        xType: "category",
        series: [{ name: dayLong(now), slot: 1, points: nowC }, { name: dayLong(dates[iAgo]), slot: 5, points: agoC }],
        unit: "%", dp: 3, yAxisName: "% per year", trust: "official",
        sourceLine: "Source: Ministry of Finance · constant-maturity yields as published",
      }),
    };
  }),
];

function scenarioHtml(k, S, total) {
  const words = S.q.split(" ").map((w, i) => '<span class="w" style="--i:' + i + '">' + escapeHtml(w) + "</span>").join(" ");
  const tool = (n, t) => '<div class="asst-tool t' + n + '"><span class="asst-chk c' + n + '">' +
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3 3 7-7"/></svg></span>' +
    '<span class="' + MONO + '">' + escapeHtml(t[0]) + '<span class="muted">(' + escapeHtml(t[1]) + ")</span></span>" +
    '<span class="asst-tool-out c' + n + '">' + escapeHtml(t[2]) + "</span></div>";
  const trust = S.trust === "official"
    ? '<span class="badge badge-official">Official Statistic</span>' + (S.note ? '<span class="muted">' + escapeHtml(S.note) + "</span>" : "")
    : '<span class="muted">Calculated from official index levels · <a href="methodology.html">formula</a></span>';
  const tiles = S.tiles.map(r => '<div class="ov-reading"><div class="ov-reading-label">' + escapeHtml(r[0]) +
    '</div><div class="ov-reading-value">' + escapeHtml(r[1]) + (r[2] ? '<span class="unit">' + escapeHtml(r[2]) + "</span>" : "") +
    '</div><div class="ov-reading-note">' + escapeHtml(r[3]) + "</div></div>").join("");
  return '<div class="asst-scn" data-k="' + k + '">' +
    '<div class="asst-chat">' +
      '<div class="asst-head"><span>Investment Assistant · Japan Data Observatory over MCP</span><span class="muted num"><span class="live-dot"></span>live · ' + (k + 1) + " of " + total + "</span></div>" +
      '<div class="asst-q-row"><div class="asst-q">' + words + '<span class="asst-cur"></span></div></div>' +
      '<div class="asst-status"><span>Querying Japan Data Observatory</span><span class="asst-dots"><i></i><i></i><i></i></span></div>' +
      '<div class="asst-tools">' + S.tools.map((t, i) => tool(i + 1, t)).join("") + "</div>" +
      '<div class="asst-ans"><div class="asst-who">Assistant</div><div class="asst-text">' + S.answer + '</div><div class="asst-trust">' + trust + "</div></div>" +
      '<div class="asst-foot muted">Every tool call is shown to the reader. The assistant has no other route to the numbers.</div>' +
    "</div>" +
    '<div class="asst-result">' +
      '<div class="asst-ph"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">' +
        (S.kind === "table" ? '<path d="M4 6h16M4 12h16M4 18h16M9 6v12M15 6v12"/>' : '<path d="M3 20h18M5 16l4-5 4 3 6-8"/>') +
        "</svg><span>Result appears when the answer is ready</span></div>" +
      '<div class="ov-head"><span class="ov-title">' + escapeHtml(S.title) + '</span><span class="ov-asof asst-cap">' + escapeHtml(S.asof) + "</span></div>" +
      '<div class="ov-readings asst-tiles">' + tiles + "</div>" +
      '<div class="asst-body asst-cap" data-body></div>' +
      '<div class="ov-foot asst-cap"><p class="source-line">' + escapeHtml(S.source) + '</p><span class="ov-dls"><a class="ov-dl" href="' +
        escapeHtml(S.open) + '">Open</a> <a class="ov-dl" href="#" data-png>Download PNG</a> <a class="ov-dl" href="#" data-csv>Download CSV</a></span></div>' +
    "</div></div>";
}

/* The 20-second sequence: words type in, tools run, answer lands, result
   draws. Class names are added on a timer; app.css does the motion. */
const TIMELINE = [[600, "s-type"], [3600, "s-status"], [4400, "s-tool1"], [5000, "s-chk1"],
                  [5400, "s-tool2"], [6000, "s-chk2"], [6900, "s-answer"], [19100, "s-out"]];
const PERIOD = 20000;

function runAssistant(scenarios) {
  const root = $("asst");
  root.innerHTML = scenarios.map((S, k) => scenarioHtml(k, S, scenarios.length)).join("");
  const els = Array.prototype.slice.call(root.querySelectorAll(".asst-scn"));
  const drawn = {};
  let timers = [], k = 0;

  function draw(i) {
    if (drawn[i]) return;
    const body = els[i].querySelector("[data-body]");
    const S = scenarios[i];
    const handle = S.draw(body);
    drawn[i] = true;
    if (handle) {
      CHARTS.push(handle);
      const png = els[i].querySelector("[data-png]"), csv = els[i].querySelector("[data-csv]");
      png.addEventListener("click", e => { e.preventDefault(); handle.exportPNG("japan-data-observatory-" + (i + 1) + ".png"); });
      csv.addEventListener("click", e => { e.preventDefault(); handle.exportCSV("japan-data-observatory-" + (i + 1) + ".csv",
        ["Japan Data Observatory — " + S.title, S.source, "retrieved: " + new Date().toISOString(), "permalink: " + location.origin + "/" + S.open]); });
    } else {
      els[i].querySelector("[data-png]").remove();
      els[i].querySelector("[data-csv]").remove();
    }
  }

  function show(i) {
    timers.forEach(clearTimeout); timers = [];
    els.forEach((el, j) => { el.className = "asst-scn" + (j === i ? " is-active" : ""); });
    if (REDUCED) {
      TIMELINE.slice(0, -1).forEach(t => els[i].classList.add(t[1]));
      draw(i);
      return;
    }
    TIMELINE.forEach(t => timers.push(setTimeout(() => {
      els[i].classList.add(t[1]);
      if (t[1] === "s-answer") draw(i);
    }, t[0])));
  }

  show(0);
  if (scenarios.length > 1) setInterval(() => { k = (k + 1) % scenarios.length; show(k); }, PERIOD);
}

function fillAssistant() {
  return Promise.allSettled(SCENARIOS.map(f => f())).then(rs => {
    const ok = rs.filter(r => r.status === "fulfilled").map(r => r.value);
    if (!ok.length) { $("asst").innerHTML = '<p class="muted">The assistant demonstration is unavailable right now.</p>'; return; }
    runAssistant(ok);
  });
}

/* ---------- API response sample ---------- */

function fillApiSample() {
  // The vintage in the example must be one that exists: the platform's own
  // first release of the dataset, read from the releases list.
  return getJSON(API + "/cpi-jp/releases").then(r => {
    const rel = (r.releases || r).filter(x => x.status === "published")
      .sort((a, b) => (a.ingested_at < b.ingested_at ? -1 : 1))[0];
    const asOf = rel.ingested_at.slice(0, 10);
    $("api-request").textContent = "GET /api/v1/cpi-jp/observations\n    ?series=0001&measure=yoy\n    &start=2016-01\n    &as_of=" + asOf + "        ";
    $("api-request-note").textContent = "# the release in force on that date";
    return getJSON(API + "/cpi-jp/observations?series=0001&measure=yoy&start=2016-01&as_of=" + asOf);
  }).then(d => {
    // Hand-laid, not JSON.stringify: the points stay on one line and the
    // formula is not allowed to push the block off the page.
    const s = d.series && d.series[0];
    const pts = s ? s.points.slice(0, 2).map(p => "[" + JSON.stringify(p[0].slice(0, 7)) + ", " +
      (p[1] === null ? "null" : Number(p[1]).toFixed(2)) + "]").join(", ") + ", …" : "";
    const calc = String(d.calc || "").length > 58 ? String(d.calc).slice(0, 55) + "…" : d.calc;
    $("api-response").textContent =
      "{\n" +
      '  "release": { "latest_period": ' + JSON.stringify(d.release.latest_period.slice(0, 7)) + ",\n" +
      '               "source_id": ' + JSON.stringify(d.release.source_id) + ",\n" +
      '               "retrieved_at": ' + JSON.stringify(String(d.release.retrieved_at).slice(0, 19) + "Z") + " },\n" +
      '  "trust": ' + JSON.stringify(d.trust) + ",\n" +
      '  "calc": ' + JSON.stringify(calc) + ",\n" +
      (s ? '  "series": [{ "code": ' + JSON.stringify(s.code) + ",\n               \"points\": [" + pts + "] }]\n" : "") +
      "}";
  }).catch(() => {
    $("api-response").textContent = "// the API could not be reached from this page";
    $("api-response-note").textContent = "";
  });
}

/* ---------- the research letter ---------- */

/* Posts are listed here until the letter has a feed the platform can read.
   Each entry: [date, title, url]. An empty list hides the column. */
const LETTER_URL = "";
const POSTS = [];

function fillLetter() {
  const posts = $("posts");
  if (POSTS.length) {
    posts.innerHTML = POSTS.map(p => '<div class="home-post"><div class="home-post-date num">' + escapeHtml(p[0]) +
      '</div><a class="home-post-title" href="' + escapeHtml(p[2]) + '">' + escapeHtml(p[1]) + "</a></div>").join("") +
      (LETTER_URL ? '<div class="home-post-more"><a href="' + escapeHtml(LETTER_URL) + '">Subscribe</a></div>' : "");
  } else {
    posts.remove();
    document.querySelector(".home-letter").classList.add("is-single");
  }
  if (LETTER_URL) { $("post-link").href = LETTER_URL; $("post-link").hidden = false; }

  // The featured chart: the BOJ's JGB holdings, with the peak marked.
  return getJSON(API + "/boj-assets/overview").then(ov => {
    const h = ov.tiles.find(x => x.key === "holdings"), p = ov.tiles.find(x => x.key === "from_peak");
    const head = ov.main_series.find(m => m.role === "headline");
    const tn = v => (v === null || v === undefined ? null : v / 10000);
    return getJSON(API + "/boj-assets/observations?series=" + head.code + "&measure=index").then(obs => {
      const points = obs.series[0].points.map(pt => [pt[0], tn(pt[1])]);
      const peakPt = points.find(pt => pt[0] === p.peak_period);
      $("post-kicker").textContent = "Featured · " + fmtPeriodLong(ov.release.latest_period);
      $("post-title").textContent = "The Bank of Japan is ¥" + fmtNum((peakPt ? peakPt[1] : 0) - tn(h.value), 0) +
        "tn below its peak. Who absorbed it?";
      const el = $("post-chart"); el.innerHTML = "";
      const source = "Source: Bank of Japan · holdings as published, shown in ¥tn (exact ÷10,000)";
      CHARTS.push(obsChart(el, "line", {
        series: [{ name: "BOJ JGB holdings", slot: 1, points: points }],
        unit: "index", dp: 1, yAxisName: "¥tn", trust: "official", sourceLine: source,
        annotations: peakPt ? [{ x: peakPt[0], y: peakPt[1], text: "Peak ¥" + fmtNum(peakPt[1], 0) + "tn" }] : [],
      }));
      $("post-source").textContent = source;
    });
  }).catch(() => { document.querySelector(".home-featured").hidden = true; });
}

/* ---------- go ---------- */

fillTicker();
fillHeroTrace();
fillHeroStatus().then(fillNumbers);
fillAssistant();
fillApiSample();
fillLetter();
