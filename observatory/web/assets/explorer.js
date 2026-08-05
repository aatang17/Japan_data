/* Item Explorer. The question this screen answers:
   "How is the price of <this item> moving?" — search, scan, click for detail.
   All control state (q, sort, selected series) lives in the URL. */
"use strict";

const DEFAULT_DATASET = "cpi-jp";
// per-dataset copy; everything else is driven by the API payload
const DATASET_UI = {
  "cpi-jp": {
    sub: "The published category aggregates of the national CPI (middle-class indices), " +
         "searchable in English and Japanese. Click a row for its full history and provenance.",
    placeholder: "Search items — electricity, 電気代, rent, 0001 …",
    csvName: "japan-cpi-categories.csv",
  },
  "cpi-jp-items": {
    sub: "All national CPI series at full item depth — individual goods and services, " +
         "searchable in English and Japanese. Click a row for its full history and provenance.",
    placeholder: "Search items — rice, 米類, electricity, mobile phone …",
    csvName: "japan-cpi-detailed-items.csv",
  },
};

function currentDataset() { return urlState().dataset; }
function apiBase() { return "/api/v1/" + currentDataset(); }

let ALL = null;        // /series payload
let detailChart = null;

const COLS = [
  { key: "code", label: "Code", num: false },
  { key: "name_en", label: "Item", num: false },
  { key: "weight", label: "Weight / 10,000", num: true, dp: 0 },
  { key: "index", label: "Index (2020 = 100)", num: true, dp: 1 },
  { key: "yoy", label: "YoY (%)", num: true, dp: 1, lane: true },
  { key: "mom", label: "MoM (%)", num: true, dp: 1, lane: true },
  { key: "spark", label: "5Y Index Trend", num: false, nosort: true },
  { key: "as_of", label: "As Of", num: false },
];

function urlState() {
  const p = new URLSearchParams(location.search);
  const ds = p.get("dataset");
  return {
    dataset: ds && DATASET_UI[ds] ? ds : DEFAULT_DATASET,
    q: p.get("q") || "",
    sort: p.get("sort") || "weight",
    dir: p.get("dir") || "desc",
    series: p.get("series") || "",
    measure: p.get("measure") || "yoy",
  };
}

function setUrlState(next) {
  const cur = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (cur.dataset !== DEFAULT_DATASET) p.set("dataset", cur.dataset);
  if (cur.q) p.set("q", cur.q);
  if (cur.sort !== "weight" || cur.dir !== "desc") { p.set("sort", cur.sort); p.set("dir", cur.dir); }
  if (cur.series) p.set("series", cur.series);
  if (cur.measure !== "yoy") p.set("measure", cur.measure);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function filtered() {
  const q = urlState().q.trim().toLowerCase();
  let rows = ALL.series;
  if (q) {
    rows = rows.filter(s =>
      s.name_en.toLowerCase().includes(q) ||
      (s.name_ja || "").toLowerCase().includes(q) ||
      s.code === q);
  }
  const { sort, dir } = urlState();
  const mul = dir === "asc" ? 1 : -1;
  rows = rows.slice().sort((a, b) => {
    const av = a[sort], bv = b[sort];
    // missing values sort last in BOTH directions
    const aMiss = av === null || av === undefined;
    const bMiss = bv === null || bv === undefined;
    if (aMiss && bMiss) return 0;
    if (aMiss) return 1;
    if (bMiss) return -1;
    if (typeof av === "string") return mul * av.localeCompare(bv);
    return mul * (av - bv);
  });
  return rows;
}

function renderTable() {
  const rows = filtered();
  const { sort, dir, q } = urlState();

  document.getElementById("row-count").textContent =
    fmtNum(rows.length, 0) + " of " + fmtNum(ALL.series.length, 0) + " series";
  document.getElementById("filter-note").textContent =
    q ? "· filtered by “" + q + "”" : "";

  const head = COLS.map(c => {
    // has-lane keeps the header flush with digits that sit left of a marker lane
    const cls = (c.num ? "num " : "") + (c.lane ? "has-lane " : "") +
      (c.nosort ? "" : "sortable");
    const arrow = c.key === sort ? '<span class="arrow">' + (dir === "asc" ? "▲" : "▼") + "</span>" : "";
    return '<th scope="col" class="' + cls + '" data-key="' + c.key + '"' +
      (c.key === sort ? ' aria-sort="' + (dir === "asc" ? "ascending" : "descending") + '"' : "") +
      ">" + c.label + arrow + "</th>";
  }).join("");

  const latest = ALL.release.latest_period.slice(0, 7);
  const body = rows.map(s => {
    const discontinued = s.discontinued
      ? ' <span class="badge badge-stale" title="No value for the latest reference month">Ends ' +
        fmtPeriod(s.as_of) + "</span>"
      : "";
    return '<tr class="clickable" data-code="' + s.code + '" tabindex="0" ' +
      'aria-label="Open detail for ' + escapeHtml(s.name_en) + '">' +
      '<td class="num muted">' + s.code + "</td>" +
      '<td class="cell-item"><div class="en">' + escapeHtml(s.name_en) + discontinued +
        '</div><div class="ja">' + escapeHtml(s.name_ja || "") + "</div></td>" +
      '<td class="num">' + fmtNum(s.weight, 0) + "</td>" +
      '<td class="num">' + fmtIndex(s.index) + "</td>" +
      '<td class="num">' + (s.yoy === null ? MISSING : fmtSigned(s.yoy, 1)) +
        noteLane(s.notes, "yoy") + "</td>" +
      '<td class="num">' + (s.mom === null ? MISSING : fmtSigned(s.mom, 1)) +
        noteLane(s.notes, "mom") + "</td>" +
      "<td>" + sparkSVG(s.spark) + "</td>" +
      '<td class="muted num">' + fmtPeriod(s.as_of) + "</td>" +
      "</tr>";
  }).join("");

  document.getElementById("table-wrap").innerHTML =
    rows.length === 0
      ? '<div class="state-empty">No items match “' + escapeHtml(q) +
        "”. Try the Japanese name (電気代), the English name (electricity), or clear the search.</div>"
      : '<table class="data"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table>";

  renderTableNotes(rows);

  document.querySelectorAll("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      const cur = urlState();
      const nextDir = cur.sort === key && cur.dir === "desc" ? "asc" : "desc";
      setUrlState({ sort: key, dir: nextDir });
      renderTable();
    });
  });

  document.querySelectorAll("tr.clickable").forEach(tr => {
    const open = () => { setUrlState({ series: tr.dataset.code }); renderDetail(); };
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
  });
}

/* Footnotes under the table, listing only the flags the visible rows actually
   carry — an explanation for a marker nobody can see is noise. */
function renderTableNotes(rows) {
  const slot = document.getElementById("table-notes");
  const ids = notesPresent(rows);
  if (ids.length === 0) { slot.innerHTML = ""; return; }
  slot.innerHTML = ids.map(id => {
    const d = NOTE_DEFS[id];
    return '<p><sup class="note-mark">' + d.marker + "</sup> <b>" + d.label +
      "</b> — " + d.rule + "</p>";
  }).join("") +
    "<p class=\"note-calc\">Flags are calculated here from published index values; " +
    "they are not published by the agency. Hover a marker for that row's month and size. " +
    '<a href="methodology.html#flags">How these are computed</a></p>';
}

function sourceLine(rel, trust) {
  const label = TRUST_LABELS[trust];
  return "Source: Statistics Bureau of Japan · " + rel.source_id +
    " · 2020 = 100 · Data through " + fmtPeriod(rel.latest_period) +
    " · Retrieved " + fmtStamp(rel.retrieved_at) +
    (label ? " · " + label : "");
}

async function renderDetail() {
  const { series: code, measure } = urlState();
  const slot = document.getElementById("detail-slot");
  if (!code) { slot.innerHTML = ""; return; }
  const meta = ALL.series.find(s => s.code === code);
  if (!meta) { slot.innerHTML = ""; return; }

  slot.innerHTML = '<div class="detail">' +
    '<div class="detail-head"><h2>' + escapeHtml(meta.name_en) + "</h2>" +
    '<span class="ja">' + escapeHtml(meta.name_ja || "") + "</span>" +
    '<span class="muted num" style="font-size:12px">Code ' + meta.code + "</span>" +
    '<button type="button" class="btn detail-close" id="detail-close">Close</button></div>' +
    '<p class="detail-meta num">Weight ' + fmtNum(meta.weight, 0) + " / 10,000 · Latest index " +
    fmtIndex(meta.index) + " (" + fmtPeriod(meta.as_of) + ") · YoY " +
    (meta.yoy === null ? MISSING : fmtSigned(meta.yoy, 1, "%")) + " · MoM " +
    (meta.mom === null ? MISSING : fmtSigned(meta.mom, 1, "%")) + "</p>" +
    (meta.notes || []).map(n => {
      const d = NOTE_DEFS[n.id];
      return d ? '<p class="detail-note"><sup class="note-mark">' + d.marker + "</sup> <b>" +
        d.label + "</b> — " + escapeHtml(d.text(n)) + "</p>" : "";
    }).join("") +
    '<div class="controls">' +
    '<label for="detail-measure">Measure</label>' +
    '<select id="detail-measure">' +
    '<option value="yoy">Year over Year (%)</option>' +
    '<option value="mom">Month over Month (%)</option>' +
    '<option value="ann3m">3-Month Annualized (%)</option>' +
    '<option value="index">Index Level (2020 = 100)</option>' +
    "</select>" +
    '<span class="spacer"></span>' +
    '<button type="button" class="btn" id="detail-png">Download PNG</button>' +
    '<button type="button" class="btn" id="detail-csv">Download CSV</button>' +
    "</div>" +
    '<div class="chart" id="detail-chart"><div class="skeleton" style="width:100%;height:100%"></div></div>' +
    '<p class="source-line" id="detail-source"></p>' +
    '<details class="calc" id="detail-calc"></details>' +
    "</div>";

  document.getElementById("detail-close").addEventListener("click", () => {
    setUrlState({ series: "" });
    if (detailChart) { detailChart.dispose(); detailChart = null; }
    slot.innerHTML = "";
  });
  const sel = document.getElementById("detail-measure");
  sel.value = measure;
  sel.addEventListener("change", () => { setUrlState({ measure: sel.value }); renderDetail(); });

  let data;
  try {
    const r = await fetch(apiBase() + "/observations?series=" + code + "&measure=" + measure);
    if (!r.ok) throw new Error("observations " + r.status);
    data = await r.json();
  } catch (err) {
    document.getElementById("detail-chart").innerHTML =
      '<div class="state-error">This series failed to load. Retry, and check that the data service is running.' +
      "<details><summary>See details</summary><pre>" + escapeHtml(String(err)) + "</pre></details></div>";
    return;
  }

  const cfg = {
    series: [{ name: meta.name_en, slot: 1, points: data.series[0].points }],
    unit: data.unit,
    yAxisName: measure === "index" ? "Index (2020 = 100)" : "%",
    trust: data.trust,
    sourceLine: sourceLine(ALL.release, data.trust),
  };
  const el = document.getElementById("detail-chart");
  el.innerHTML = "";
  if (detailChart) detailChart.dispose();
  detailChart = obsChart(el, "line", cfg);

  document.getElementById("detail-source").textContent = sourceLine(ALL.release, data.trust);
  const calcEl = document.getElementById("detail-calc");
  if (data.trust === "derived") {
    calcEl.innerHTML = "<summary>Show calculation</summary>" +
      '<div class="calc-body"><code>' + escapeHtml(data.calc) + "</code><br>" +
      "Inputs: official index values, release “" + escapeHtml(ALL.release.label) +
      "” (sha256 " + ALL.release.sha256.slice(0, 12) + "…).</div>";
  } else {
    calcEl.innerHTML = "";
  }

  document.getElementById("detail-png").onclick = () =>
    detailChart.exportPNG("japan-cpi-" + code + "-" + measure + ".png");
  document.getElementById("detail-csv").onclick = () =>
    detailChart.exportCSV("japan-cpi-" + code + "-" + measure + ".csv", [
      "Japan CPI — " + meta.name_en + " (" + (meta.name_ja || "") + ") — " + MEASURE_LABELS[measure],
      TRUST_LABELS[data.trust] ? "Trust: " + TRUST_LABELS[data.trust]
        : "Trust: calculated from official index values (formula below)",
      "Calculation: " + data.calc,
      "Source: Statistics Bureau of Japan via e-Stat, " + ALL.release.source_id,
      "Vintage: " + ALL.release.label + " (2020 = 100)",
      "Retrieved: " + fmtStamp(ALL.release.retrieved_at),
      "Permalink: " + location.href,
    ]);
}

function exportFilteredCSV() {
  const rows = filtered();
  const rel = ALL.release;
  const header = [
    "Japan CPI — Item Explorer export (filtered rows)",
    "Columns: code, name_en, name_ja, weight_per_10000, index (official), yoy_pct, mom_pct, as_of, flags",
    "Trust: index = Official Statistic; yoy/mom and flags are calculated here — (index[t]/index[t-n] - 1) x 100 from published index values",
    "Flags: step = one month is at least 70% of the 12-month move and shifted the index at least 10%; low_base = index level below 5.0, so percent changes are unstable",
    "Source: Statistics Bureau of Japan via e-Stat, " + rel.source_id,
    "Vintage: " + rel.label + " (2020 = 100)",
    "Retrieved: " + fmtStamp(rel.retrieved_at),
    "Permalink: " + location.href,
  ].map(l => "# " + l).join("\n");
  let csv = header + "\ncode,name_en,name_ja,weight_per_10000,index,yoy_pct,mom_pct,as_of,flags\n";
  rows.forEach(s => {
    const flags = (s.notes || [])
      .filter(n => NOTE_DEFS[n.id])
      .map(n => n.id + ": " + NOTE_DEFS[n.id].text(n))
      .join(" ");
    csv += [
      s.code,
      '"' + s.name_en.replace(/"/g, '""') + '"',
      '"' + (s.name_ja || "").replace(/"/g, '""') + '"',
      s.weight ?? "",
      s.index ?? "",
      s.yoy === null ? "" : s.yoy.toFixed(4),
      s.mom === null ? "" : s.mom.toFixed(4),
      fmtPeriod(s.as_of),
      '"' + flags.replace(/"/g, '""') + '"',
    ].join(",") + "\n";
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = DATASET_UI[currentDataset()].csvName;
  a.click();
  URL.revokeObjectURL(a.href);
}

function syncDatasetUI() {
  const ds = currentDataset();
  const ui = DATASET_UI[ds];
  document.getElementById("page-sub").textContent = ui.sub;
  document.getElementById("q").placeholder = ui.placeholder;
  document.querySelectorAll("#dataset-seg button").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.dataset === ds)));
}

async function loadData() {
  syncDatasetUI();
  document.getElementById("table-wrap").innerHTML =
    '<div class="skeleton" style="height:400px"></div>';
  try {
    const r = await fetch(apiBase() + "/series");
    if (!r.ok) throw new Error("series " + r.status + " " + (await r.text()).slice(0, 300));
    ALL = await r.json();
  } catch (err) {
    document.getElementById("table-wrap").innerHTML =
      '<div class="state-error">The item list failed to load. The data service may not be running — ' +
      "start it and reload this page.<details><summary>See details</summary><pre>" +
      escapeHtml(String(err)) + "</pre></details></div>";
    return false;
  }
  document.getElementById("header-asof").textContent =
    "Data through " + fmtPeriod(ALL.release.latest_period);
  return true;
}

async function init() {
  initThemeToggle(() => { if (urlState().series) renderDetail(); });

  const q = document.getElementById("q");
  q.value = urlState().q;
  let t = null;
  q.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => { setUrlState({ q: q.value }); renderTable(); }, 150);
  });

  document.getElementById("export-csv").addEventListener("click", exportFilteredCSV);

  document.querySelectorAll("#dataset-seg button").forEach(b => {
    b.addEventListener("click", async () => {
      if (b.dataset.dataset === currentDataset()) return;
      // series codes are table-specific; drop any open detail on switch
      setUrlState({ dataset: b.dataset.dataset, series: "" });
      if (detailChart) { detailChart.dispose(); detailChart = null; }
      document.getElementById("detail-slot").innerHTML = "";
      if (await loadData()) renderTable();
    });
  });

  if (!(await loadData())) return;
  renderTable();
  renderDetail();
}

init();
