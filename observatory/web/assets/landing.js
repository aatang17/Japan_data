/* Landing page: the current state of each live product, pulled from the same
   API the product pages use.

   The point of putting live figures on a front door is to prove the pipeline
   is running, so these must never be stubs or last-known values baked into
   the markup. If a product's API cannot be reached, its figures are removed
   rather than faked — the product's description and links stay, and the page
   is silent about numbers it does not have. */
"use strict";

/* One figure in a product row. `note` names the measure's status where it
   matters (as filed, calculated); the row's footer carries the as-of. */
function landingStat(label, value, note) {
  return '<div class="prod-stat">' +
    '<div class="prod-stat-label">' + escapeHtml(label) + "</div>" +
    '<div class="prod-stat-value">' + value + "</div>" +
    (note ? '<div class="prod-stat-note">' + escapeHtml(note) + "</div>" : "") +
    "</div>";
}

function dropStats(statsId, footId) {
  const stats = document.getElementById(statsId);
  const foot = document.getElementById(footId);
  if (stats) stats.remove();
  if (foot) foot.remove();
}

function fillCpi() {
  return fetch("/api/v1/cpi-jp/overview")
    .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(d => {
      const byKey = {};
      d.tiles.forEach(t => { byKey[t.key] = t; });
      const wanted = [
        ["Headline · YoY", byKey.headline_yoy],
        ["Core · YoY", byKey.core_yoy],
        ["Headline · 3m annualized", byKey.headline_ann3m],
      ].filter(pair => pair[1]);
      if (!wanted.length) return dropStats("cpi-stats", "cpi-foot");

      document.getElementById("cpi-stats").innerHTML = wanted.map(
        pair => landingStat(pair[0], fmtRate(pair[1].value, 1))).join("");

      // Rates are calculated here, so they carry their formula rather than a
      // trust badge — the same rule the product pages follow.
      document.getElementById("cpi-foot").innerHTML =
        "Latest month " + escapeHtml(fmtPeriodLong(d.release.latest_period)) +
        " · index levels are official statistics, rates calculated from them" +
        ' (<a href="cpi.html">formula</a>)' +
        (d.stale ? " · <b>this release is behind schedule</b>" : "");
    })
    .catch(() => dropStats("cpi-stats", "cpi-foot"));
}

function fillEquity() {
  return fetch("/api/v1/equity/summary")
    .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(d => {
      // Book values are filed in yen; trillions is the only readable unit at
      // this scale, and the label carries it.
      const tn = d.total_book_value_yen === null || d.total_book_value_yen === undefined
        ? null : d.total_book_value_yen / 1e12;
      document.getElementById("eq-stats").innerHTML = [
        landingStat("Named policy holdings", "¥" + fmtNum(tn, 2) + "tn", "as filed"),
        landingStat("Filers extracted", fmtNum(d.filers, 0), "of ~3,800 eventually"),
        landingStat("Positions cut · added", fmtNum(d.positions_reduced, 0) +
          " · " + fmtNum(d.positions_increased, 0), "year on year, calculated"),
      ].join("");

      const st = d.extraction_status || {};
      const parts = Object.keys(st).sort().map(k => fmtNum(st[k], 0) + " " + k);
      document.getElementById("eq-foot").innerHTML =
        "From " + escapeHtml(fmtNum(d.named_holdings, 0)) +
        " named holdings in annual securities reports" +
        (parts.length ? " · extraction status " + escapeHtml(parts.join(", ")) : "") +
        " · coverage grows as filings are extracted";
    })
    .catch(() => dropStats("eq-stats", "eq-foot"));
}

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
fillEquity();
wireCopy("copy-url", "mcp-url");
