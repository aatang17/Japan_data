/* Equities overview: one live reading and an as-of per dataset, pulled from
   the same summary endpoints the product pages use.

   The readings prove the pipeline is running, so they are never stubs or
   values baked into the markup. A dataset whose API cannot be reached shows
   an em dash — missing, never faked and never zero. */
"use strict";

function getJSON(url) {
  return fetch(url).then(r => (r.ok ? r.json() : Promise.reject(new Error(url + " " + r.status))));
}
function setReading(id, value, note) {
  document.getElementById(id).innerHTML =
    escapeHtml(value) + (note ? ' <span class="reading-note">' + escapeHtml(note) + "</span>" : "");
}
function setAsOf(id, text) { document.getElementById(id).textContent = text; }
function rowFailed(rid) {
  document.getElementById("r-" + rid).textContent = MISSING;
  document.getElementById("a-" + rid).textContent = MISSING;
}
function dayLong(iso) { return Number(iso.slice(8, 10)) + " " + fmtPeriodLong(iso); }
function tn(yen) { return "¥" + fmtNum(yen / 1e12, 2) + "tn"; }

getJSON("/api/v1/equity/summary").then(d => {
  setReading("r-hold", tn(d.total_book_value_yen), "held at book, as filed");
  setAsOf("a-hold", "FY to " + fmtPeriodLong(d.latest_period_end));
}).catch(() => rowFailed("hold"));

getJSON("/api/v1/equity/ownership/summary").then(d => {
  setReading("r-own", fmtNum(d.companies, 0), "companies covered");
  setAsOf("a-own", "FY to " + fmtPeriodLong(d.latest_period_end));
}).catch(() => rowFailed("own"));

getJSON("/api/v1/equity/stakes/summary").then(d => {
  setReading("r-stk", fmtNum(d.filings, 0), "filings parsed");
  setAsOf("a-stk", "filed to " + dayLong(d.latest_filed));
}).catch(() => rowFailed("stk"));

getJSON("/api/v1/equity/governance/summary?listed=true").then(d => {
  setReading("r-gov", fmtNum(d.companies, 0), "listed companies");
  setAsOf("a-gov", "FY to " + fmtPeriodLong(d.latest_period_end));
}).catch(() => rowFailed("gov"));

getJSON("/api/v1/equity/agm/summary").then(d => {
  setReading("r-agm", fmtNum(d.meetings, 0), "meetings, as filed");
  setAsOf("a-agm", "to " + dayLong(d.latest_meeting));
}).catch(() => rowFailed("agm"));

getJSON("/api/v1/equity/buyback/summary").then(d => {
  setReading("r-bb", tn(d.authorised_yen), "authorised, as filed");
  setAsOf("a-bb", "filed to " + dayLong(d.last_submitted));
}).catch(() => rowFailed("bb"));

getJSON("/api/v1/equity/financials/summary").then(d => {
  const t = d.totals;
  setReading("r-fin", fmtNum(t.companies, 0) + " companies", fmtNum(t.facts, 0) + " tagged values, as filed");
  setAsOf("a-fin", t.latest_filed ? "filed to " + dayLong(t.latest_filed) : MISSING);
}).catch(() => rowFailed("fin"));

getJSON("/api/v1/equity/facilities/summary").then(d => {
  const s = d.summary || d;
  setReading("r-fac", tn(s.land_book_yen), "land at book, as filed");
  setAsOf("a-fac", "FY to " + fmtPeriodLong(s.last_period_end));
}).catch(() => rowFailed("fac"));

// No summary endpoint yet: count the links the list returns, and say so
// when it is capped rather than pretend the cap is the total.
getJSON("/api/v1/equity/segments/customers?limit=1000").then(d => {
  const e = d.edges || [];
  if (!e.length) throw new Error("no rows");
  const filers = new Set(e.map(x => x.sec_code)).size;
  const latest = e.reduce((m, x) => (x.period_end > m ? x.period_end : m), "");
  setReading("r-cus", (e.length >= 1000 ? "1,000+" : fmtNum(e.length, 0)) + " links",
    "named customer to filer, " + fmtNum(filers, 0) + (e.length >= 1000 ? "+" : "") + " filers, as filed");
  setAsOf("a-cus", latest ? "FY to " + fmtPeriodLong(latest) : "latest filing each");
}).catch(() => rowFailed("cus"));

initThemeToggle();
