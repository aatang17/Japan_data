/* Landing page: one live reading and an as-of per dataset, pulled from the
   same API the product pages use.

   The point of putting live figures on the front door is to prove the
   pipeline is running, so these must never be stubs or last-known values
   baked into the markup. If a dataset's API cannot be reached, its cells show
   an em dash — missing, never faked and never zero. */
"use strict";

function getJSON(url) {
  return fetch(url).then(r => (r.ok ? r.json() : Promise.reject(new Error(url + " " + r.status))));
}

/* value + quiet qualifier in the reading column; as-of in its own column */
function setReading(id, value, note) {
  document.getElementById(id).innerHTML =
    escapeHtml(value) + (note ? ' <span class="reading-note">' + escapeHtml(note) + "</span>" : "");
}

function setAsOf(id, text, stale) {
  document.getElementById(id).innerHTML =
    escapeHtml(text) + (stale ? " · <b>behind schedule</b>" : "");
}

function rowFailed(rid, aid) {
  document.getElementById(rid).textContent = MISSING;
  document.getElementById(aid).textContent = MISSING;
}

function dayLong(iso) {   // "2026-08-27" -> "27 August 2026"
  return Number(iso.slice(8, 10)) + " " + fmtPeriodLong(iso);
}

/* ---- macro ---- */

function fillCpi() {
  return getJSON("/api/v1/cpi-jp/overview").then(d => {
    const t = d.tiles.find(x => x.key === "headline_yoy");
    setReading("r-cpi", fmtRate(t.value, 1), "headline YoY, calculated");
    setAsOf("a-cpi", fmtPeriodLong(d.release.latest_period), d.stale);
    setAsOf("a-explorer", fmtPeriodLong(d.release.latest_period), d.stale);
  }).catch(() => { rowFailed("r-cpi", "a-cpi"); document.getElementById("a-explorer").textContent = MISSING; });
}

function fillBoj() {
  return getJSON("/api/v1/boj-assets/overview").then(d => {
    const h = d.tiles.find(x => x.key === "holdings");
    setReading("r-boj", "¥" + fmtNum(h.value / 10000, 1) + "tn", "JGB holdings, as published");
    setAsOf("a-boj", fmtPeriodLong(d.release.latest_period), d.stale);
  }).catch(() => rowFailed("r-boj", "a-boj"));
}

function fillRates() {
  // a short recent window: two months back always contains a business day
  const from = new Date();
  from.setMonth(from.getMonth() - 2);
  const start = from.getFullYear() + "-" + String(from.getMonth() + 1).padStart(2, "0");
  return getJSON("/api/v1/jgb-yields/observations?series=10Y&measure=index&start=" + start)
    .then(d => {
      const pts = d.series[0].points;
      let v = null;
      for (let i = pts.length - 1; i >= 0; i--) {
        if (pts[i][1] !== null) { v = pts[i][1]; break; }
      }
      if (v === null) throw new Error("no yield");
      setReading("r-rates", fmtRate(v, 3), "10-year yield, as published");
      setAsOf("a-rates", dayLong(d.release.latest_period), d.stale);
    }).catch(() => rowFailed("r-rates", "a-rates"));
}

function fillSemis() {
  // The headline the page itself leads with: what Japan shipped in chips last
  // month, summed across every partner.
  return getJSON("/api/v1/trade-semis/trade").then(d => {
    const totals = d.world["exp.70323050"];
    let last = -1;
    for (let i = totals.length - 1; i >= 0; i--) {
      if (totals[i] !== null && totals[i] !== undefined) { last = i; break; }
    }
    if (last < 0) throw new Error("no value");
    setReading("r-semis", "\u00a5" + fmtNum(totals[last] / 1e6, 0) + "bn",
               "integrated circuits exported");
    setAsOf("a-semis", fmtPeriodLong(d.periods[last]), d.stale);
  }).catch(() => rowFailed("r-semis", "a-semis"));
}

function fillInbound() {
  return getJSON("/api/v1/jnto-visitors/arrivals").then(d => {
    const totals = d.values.total;
    let last = -1;
    for (let i = totals.length - 1; i >= 0; i--) {
      if (totals[i] !== null && totals[i] !== undefined) { last = i; break; }
    }
    setReading("r-inbound", fmtNum(totals[last] / 1e6, 2) + "mn", "visitors in the month");
    setAsOf("a-inbound", fmtPeriodLong(d.periods[last]), d.stale);
  }).catch(() => rowFailed("r-inbound", "a-inbound"));
}

function fillPop() {
  return getJSON("/api/v1/population-jp/prefectures").then(d => {
    const col = d.values[(d.national || "00") + ".all.population"];
    const v = col[col.length - 1];
    setReading("r-pop", fmtNum(v / 1e6, 2) + "mn", "registered residents");
    setAsOf("a-pop", "1 January " + d.periods[d.periods.length - 1].slice(0, 4), d.stale);
  }).catch(() => rowFailed("r-pop", "a-pop"));
}

/* ---- equities ---- */

function fillHoldings() {
  return getJSON("/api/v1/equity/summary").then(d => {
    setReading("r-hold", "¥" + fmtNum(d.total_book_value_yen / 1e12, 2) + "tn",
      "held at book, as filed");
    setAsOf("a-hold", "FY to " + fmtPeriodLong(d.latest_period_end));
  }).catch(() => rowFailed("r-hold", "a-hold"));
}

function fillOwnership() {
  return getJSON("/api/v1/equity/ownership/summary").then(d => {
    setReading("r-own", fmtNum(d.companies, 0), "companies covered");
    setAsOf("a-own", "FY to " + fmtPeriodLong(d.latest_period_end));
  }).catch(() => rowFailed("r-own", "a-own"));
}

function fillStakes() {
  return getJSON("/api/v1/equity/stakes/summary").then(d => {
    setReading("r-stk", fmtNum(d.filings, 0), "filings parsed");
    setAsOf("a-stk", "filed to " + dayLong(d.latest_filed));
  }).catch(() => rowFailed("r-stk", "a-stk"));
}

function fillGovernance() {
  return getJSON("/api/v1/equity/governance/summary?listed=true").then(d => {
    setReading("r-gov", fmtNum(d.companies, 0), "listed companies");
    setAsOf("a-gov", "FY to " + fmtPeriodLong(d.latest_period_end));
  }).catch(() => rowFailed("r-gov", "a-gov"));
}

function fillBuyback() {
  return getJSON("/api/v1/equity/buyback/summary").then(d => {
    setReading("r-bb", "¥" + fmtNum(d.authorised_yen / 1e12, 2) + "tn",
      "authorised, as filed");
    setAsOf("a-bb", "filed to " + dayLong(d.last_submitted));
  }).catch(() => rowFailed("r-bb", "a-bb"));
}

function fillFacilities() {
  return getJSON("/api/v1/equity/facilities/summary").then(d => {
    const s = d.summary || d;
    setReading("r-fac", "¥" + fmtNum(s.land_book_yen / 1e12, 2) + "tn",
      "land at book, as filed");
    setAsOf("a-fac", "FY to " + fmtPeriodLong(s.last_period_end));
  }).catch(() => rowFailed("r-fac", "a-fac"));
}

function fillFinancials() {
  return getJSON("/api/v1/equity/financials/summary").then(d => {
    const t = d.totals;
    setReading("r-fin", fmtNum(t.companies, 0) + " companies",
      fmtNum(t.facts, 0) + " tagged values, as filed");
    setAsOf("a-fin", t.latest_filed ? "filed to " + dayLong(t.latest_filed) : "—");
  }).catch(() => rowFailed("r-fin", "a-fin"));
}

/* ---- MCP url copy ---- */

function wireCopy(btnId, textId) {
  const btn = document.getElementById(btnId);
  const source = document.getElementById(textId);
  if (!btn || !source) return;
  const text = source.textContent;
  btn.addEventListener("click", () => {
    const done = () => {
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = "Copy"; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done);
    } else {
      const range = document.createRange();
      range.selectNodeContents(source);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.execCommand("copy");
      sel.removeAllRanges();
      done();
    }
  });
}

fillCpi();
fillBoj();
fillRates();
fillInbound();
fillSemis();
fillPop();
fillHoldings();
fillOwnership();
fillStakes();
fillGovernance();
fillBuyback();
fillFacilities();
fillFinancials();
wireCopy("copy-url", "mcp-url");
