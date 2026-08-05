/* Centralised formatters. Never format a number inline in page code.
   Missing is "—", never 0. Negative uses a true minus (U+2212). */
"use strict";

const MINUS = "−";
const MISSING = "—"; // em dash

/* value -> "1,653.4" with fixed decimals and a true minus */
function fmtNum(v, dp) {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  const s = Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  });
  return (v < 0 ? MINUS : "") + s;
}

/* rate to 1 decimal with unit: "2.7%" */
function fmtRate(v, dp) {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  return fmtNum(v, dp === undefined ? 1 : dp) + "%";
}

/* signed delta: "+0.3 pp" / "−0.2 pp" / "0.0 pp" (zero is unsigned) */
function fmtSigned(v, dp, unit) {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  const d = dp === undefined ? 1 : dp;
  const rounded = Number(v.toFixed(d));
  const body = fmtNum(Math.abs(v), d);
  let sign = "";
  if (rounded > 0) sign = "+";
  else if (rounded < 0) sign = MINUS;
  // '%' binds to the number ("+3.2%"); word units get a space ("+0.2 pp")
  return sign + body + (unit ? (unit === "%" ? unit : " " + unit) : "");
}

/* index level to 1 decimal: "113.6" */
function fmtIndex(v) { return fmtNum(v, 1); }

/* "2026-06-01" -> "2026-06" (tables) */
function fmtPeriod(iso) { return iso ? iso.slice(0, 7) : MISSING; }

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];

/* "2026-06-01" -> "June 2026" (prose) */
function fmtPeriodLong(iso) {
  if (!iso) return MISSING;
  const m = Number(iso.slice(5, 7));
  return MONTHS[m - 1] + " " + iso.slice(0, 4);
}

/* ISO timestamp -> "2026-08-05 12:04 UTC" */
function fmtStamp(iso) {
  if (!iso) return MISSING;
  return iso.slice(0, 16).replace("T", " ") + " UTC";
}

/* raw enum -> Title-Case display label; never render the raw value.
   'derived' carries no label: rates of change are shown with their formula
   ("Show calculation") instead of a badge. */
const TRUST_LABELS = {
  official: "Official Statistic",
  model: "Model Estimate",
};
const TRUST_CLASS = {
  official: "badge-official",
  model: "badge-model",
};

/* returns "" for an unlabelled tier — callers must not pad around this */
function trustBadge(trust) {
  const label = TRUST_LABELS[trust];
  if (!label) return "";
  return '<span class="badge ' + TRUST_CLASS[trust] + '">' + label + "</span>";
}

/* ---- flags on the latest reading ----
   The API sends facts ({id, period, pct, share} / {id, index}); the wording and
   the marker live here. Markers are stable per flag type, so a given glyph means
   the same thing on every row and keeps its meaning when the table is re-sorted;
   the row's own numbers go in the marker tooltip and in the detail panel. */
const NOTE_DEFS = {
  step: {
    marker: "†",
    cols: ["yoy"],  // a statement about the 12-month move only
    label: "One-month step change",
    rule: "A single month accounts for at least 70% of the 12-month move and shifted the " +
          "index by at least 10%. Typical of an administered price, subsidy or tax that " +
          "changes on a set date rather than a move that accumulated over the year.",
    text: function (n) {
      return "A single-month change of " + fmtSigned(n.pct, 1, "%") + " in " +
        fmtPeriodLong(n.period) + " accounts for " + fmtNum(n.share * 100, 0) +
        "% of this 12-month move.";
    },
  },
  low_base: {
    marker: "‡",
    cols: ["yoy", "mom"],  // an unstable base distorts every rate off it
    label: "Index near zero",
    rule: "The index level is below 5.0 (2020 = 100). Percent changes on a base this " +
          "small are arithmetically unstable and are shown for completeness only.",
    text: function (n) {
      return "The index level is " + fmtIndex(n.index) + " (2020 = 100). Percent changes " +
        "on a base this small are arithmetically unstable.";
    },
  },
};

/* markers for one column, always in a fixed-width lane so that a flagged row and
   an unflagged row keep their digits in the same place */
function noteLane(notes, col) {
  const marks = (notes || [])
    .filter(n => NOTE_DEFS[n.id] && NOTE_DEFS[n.id].cols.indexOf(col) !== -1)
    .map(n => {
      const d = NOTE_DEFS[n.id];
      const full = d.label + " — " + d.text(n);
      // the glyph is decorative to a screen reader; the sentence is what carries
      return '<sup class="note-mark" title="' + escapeHtml(full) + '">' +
        '<span aria-hidden="true">' + d.marker + "</span>" +
        '<span class="visually-hidden">' + escapeHtml(full) + "</span></sup>";
    }).join("");
  return '<span class="note-lane">' + marks + "</span>";
}

/* distinct flag types present across rows, in NOTE_DEFS order */
function notesPresent(rows) {
  const seen = {};
  rows.forEach(r => (r.notes || []).forEach(n => { seen[n.id] = true; }));
  return Object.keys(NOTE_DEFS).filter(id => seen[id]);
}

const MEASURE_LABELS = {
  yoy: "Year over Year", mom: "Month over Month",
  ann3m: "3-Month Annualized", index: "Index Level",
};
const MEASURE_SHORT = {
  yoy: "YoY", mom: "MoM", ann3m: "3m Ann.", index: "Index",
};

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ---- theme ---- */

function currentTheme() {
  const forced = document.documentElement.getAttribute("data-theme");
  if (forced) return forced;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function initThemeToggle(onChange) {
  // explicit ?theme= wins (preview links, tests), then the saved preference
  const qp = new URLSearchParams(location.search).get("theme");
  const saved = qp === "dark" || qp === "light" ? qp : localStorage.getItem("obs-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  const btn = document.querySelector(".theme-toggle");
  if (!btn) return;
  const sync = () => { btn.textContent = currentTheme() === "dark" ? "Light Mode" : "Dark Mode"; };
  sync();
  btn.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("obs-theme", next);
    sync();
    if (onChange) onChange(next);
  });
}

/* read a design token's computed value (charts must use this, never hex) */
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
