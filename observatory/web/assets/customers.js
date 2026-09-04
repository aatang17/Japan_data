/* Customer concentration. The question this screen answers:
   "Which Japanese companies depend on which buyers, and how badly?"

   Japanese listed companies must name any customer worth 10% or more of
   revenue and state the amount. One /concentration payload carries the whole
   disclosed graph; every number on this page is either that filed amount or a
   ratio of two filed amounts, and the ratio carries its formula.

   The one rule this page will not break: customer names are shown exactly as
   each filer wrote them and are never merged. Toyota appears as both
   「トヨタ自動車(株)」 and 「トヨタ自動車株式会社」 because two filers wrote it two
   ways, and silently combining them would invent a disclosure nobody made.
   The search matches text, so the page tells the reader to try more than one
   spelling rather than guessing on their behalf. */
"use strict";

const API = "/api/v1/equity/segments/concentration";

let C = null;                 // the payload
let EDGES = [];               // flattened filer × customer rows

const SUGGEST = ["Samsung", "Toyota", "トヨタ", "Apple", "TSMC", "キオクシア", "NTT", "SK Hynix"];

function $(id) { return document.getElementById(id); }
function bn(v) { return v === null || v === undefined ? MISSING : fmtNum(v / 1e9, 1); }
function pct(v, dp) { return v === null || v === undefined ? MISSING : fmtNum(v, dp === undefined ? 1 : dp); }
function nameOf(f) { return f.name_en || f.name_ja || f.sec_code || f.edinet_code; }

function calcBlock(el, lines) {
  const n = $(el);
  if (!n) return;
  n.style.display = "";
  n.innerHTML = "<summary>Show calculation</summary><div class='calc-body'>" +
    lines.map(l => "<p>" + escapeHtml(l) + "</p>").join("") + "</div>";
}

function urlState() {
  const p = new URLSearchParams(location.search);
  return {
    q: p.get("q") || "",
    theme: p.get("theme") || "",
    reach: p.get("reach") === "value" ? "value" : "suppliers",
    min: p.get("min") || "25",
    rev: p.get("rev") || "0",
    buyers: p.get("buyers") === "end" ? "end" : "all",
  };
}

function setUrlState(next) {
  const s = Object.assign(urlState(), next);
  const p = new URLSearchParams();
  if (s.q) p.set("q", s.q);
  if (s.theme) p.set("theme", s.theme);
  if (s.reach !== "suppliers") p.set("reach", s.reach);
  if (s.min !== "25") p.set("min", s.min);
  if (s.rev !== "0") p.set("rev", s.rev);
  if (s.buyers !== "all") p.set("buyers", s.buyers);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function csvDownload(name, headerLines, cols, rows) {
  const lines = headerLines.map(l => "# " + l);
  lines.push(cols.join(","));
  rows.forEach(r => lines.push(r.map(v => {
    v = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }).join(",")));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function csvHeader(what) {
  return [
    "Japan Data Observatory — " + what,
    C.credit_line + " Annual securities reports, segment information note (主要な顧客ごとの情報).",
    "Latest filing per company; current fiscal year only. " + C.coverage.filers_naming_a_customer +
      " companies name " + C.coverage.relationships + " customer relationships.",
    "Amounts and customer names are exactly as filed. " + C.calc,
    C.note,
  ];
}


/* A customer as the reader should see it: the English name where one could be
   looked up, the filed name underneath, and a link to the buyer's own page
   when the buyer files its own annual report. The filed name is never
   replaced — it is the identity, and two spellings stay two rows. */
function customerCell(c) {
  const filed = escapeHtml(c.customer_name);
  const en = c.customer_name_en;
  const link = c.customer_sec_code
    ? '<a href="company.html?code=' + escapeHtml(c.customer_sec_code) + '">' +
      escapeHtml(en || c.customer_name) + "</a>"
    : escapeHtml(en || c.customer_name);
  if (!en) return '<div class="cell-item"><div class="en">' + link + "</div></div>";
  return '<div class="cell-item"><div class="en">' + link + "</div>" +
    '<div class="ja">' + filed + "</div></div>";
}

function customerLabel(c) { return c.customer_name_en || c.customer_name; }

/* ---- header and tiles ---- */

function renderHeader() {
  const periods = C.filers.map(f => f.period_end).filter(Boolean).sort();
  $("header-asof").textContent = periods.length
    ? "Filings to " + fmtPeriodLong(periods[periods.length - 1]) : "";
  $("page-asof").textContent = C.coverage.relationships + " disclosed relationships";
  if (C.credit_line) $("credit-line").textContent = C.credit_line;
}

function tile(label, value, sub, title) {
  return '<div class="strip-cell">' +
    '<div class="strip-label" title="' + escapeHtml(title || label) + '">' + escapeHtml(label) + "</div>" +
    '<div class="strip-value num">' + value + "</div>" +
    '<div class="strip-delta flat">' + escapeHtml(sub || "") + "</div></div>";
}

function renderTiles() {
  const withShare = C.filers.filter(f => f.named_share_pct !== null);
  const over50 = withShare.filter(f => f.named_share_pct >= 50).length;
  const top = withShare[0];
  const withPct = EDGES.filter(e => e.share_pct !== null && e.share_pct !== undefined);
  const biggest = withPct.slice().sort((a, b) => b.value_yen - a.value_yen)[0];
  const noRevenue = C.filers.filter(f => f.named_share_pct === null).length;
  const mostSuppliers = C.customers.slice().sort((a, b) => b.suppliers - a.suppliers)[0];

  $("tiles").innerHTML =
    tile("Companies Naming a Customer", fmtNum(C.coverage.filers_naming_a_customer, 0),
         C.coverage.relationships + " relationships disclosed",
         "Listed companies whose latest filing names at least one customer at or above 10% of revenue") +
    tile("More Than Half Their Revenue", fmtNum(over50, 0),
         "from customers they had to name",
         "Companies whose named customers together account for 50% or more of revenue") +
    tile("Most Dependent", top ? escapeHtml(nameOf(top)) : MISSING,
         top ? pct(top.named_share_pct) + "% of revenue from " + top.customer_count + " customer(s)" : "",
         "The company with the highest combined dependence on named customers") +
    tile("Most Named Buyer", mostSuppliers ? escapeHtml(customerLabel(mostSuppliers)) : MISSING,
         mostSuppliers ? mostSuppliers.suppliers + " Japanese suppliers · ¥" + bn(mostSuppliers.total_yen) + "bn" : "",
         "The customer named by the most listed Japanese companies");

  $("strip-foot").textContent =
    "Latest filing per company, current fiscal year. The largest relationship whose share can be " +
    "computed is " + (biggest ? nameOf(biggest.filer) + " → " +
      customerLabel(biggest) + " at ¥" + bn(biggest.value_yen) + "bn, " +
      pct(biggest.share_pct) + "% of that supplier's revenue" : "—") +
    ". " + fmtNum(noRevenue, 0) + " companies name a customer but have no consolidated revenue " +
    "figure extracted, so their share is blank rather than assumed.";
  calcBlock("strip-calc", [C.calc, C.note]);
}

/* ---- buyer lookup ---- */

function renderSuggest() {
  $("buyer-suggest").innerHTML = '<span class="band-toggles-label">Try</span>' +
    SUGGEST.map(s => '<label><input type="radio" name="sugg" value="' + escapeHtml(s) + '"> ' +
      escapeHtml(s) + "</label>").join("");
  $("buyer-suggest").onchange = e => {
    if (!e.target.matches("input")) return;
    $("buyer-search").value = e.target.value;
    setUrlState({ q: e.target.value });
    renderBuyer();
  };
}

function renderThemes() {
  const st = urlState();
  const themes = (C.themes || []).filter(t => t.customers > 0);
  $("theme-picker").innerHTML = '<span class="band-toggles-label">Or a theme</span>' +
    themes.map(t => '<label><input type="radio" name="theme" value="' + escapeHtml(t.key) + '"' +
      (st.theme === t.key ? " checked" : "") + "> " + escapeHtml(THEME_LABEL[t.key] || t.key) +
      ' <span style="color:var(--obs-text-muted)">' + t.suppliers + "</span></label>").join("") +
    '<span class="band-toggles-note">themes come from the curated company list</span>';
  $("theme-picker").onchange = e => {
    if (!e.target.matches("input")) return;
    $("buyer-search").value = "";
    setUrlState({ theme: e.target.value, q: "" });
    renderBuyer();
  };
}

const THEME_LABEL = {
  memory: "Memory makers", semiconductor: "Semiconductors", semicap: "Chipmaking equipment",
  wafer: "Wafers", materials: "Chip materials", government: "Government",
  distributor: "Distributors", trading: "Trading houses", telecom: "Telecom",
};

function renderBuyer() {
  const st = urlState();
  const q = st.q.trim().toLowerCase();
  const theme = st.theme;
  const hits = theme
    ? EDGES.filter(e => (e.customer_tags || []).indexOf(theme) !== -1)
    : (q ? EDGES.filter(e =>
        e.customer_name.toLowerCase().indexOf(q) !== -1 ||
        (e.customer_name_en || "").toLowerCase().indexOf(q) !== -1) : []);
  hits.sort((a, b) => (b.share_pct || 0) - (a.share_pct || 0));
  $("buyer-count").textContent = (q || theme) ? hits.length + " supplier" + (hits.length === 1 ? "" : "s") : "";
  $("buyer-note").textContent = theme ? (THEME_LABEL[theme] || theme) : (q ? '"' + q + '"' : "");

  if (!q && !theme) {
    $("buyer-table").innerHTML = '<p class="table-foot" style="padding:18px">Type a buyer\'s name above, pick a suggestion, or choose a theme.</p>';
    $("buyer-foot").textContent = "";
    return;
  }
  if (!hits.length) {
    $("buyer-table").innerHTML = '<p class="table-foot" style="padding:18px">No filer names a customer matching that text. Names are as written by each filer — try a different spelling, or the Japanese form.</p>';
    $("buyer-foot").textContent = "";
    return;
  }
  const spellings = [];
  hits.forEach(h => { if (spellings.indexOf(h.customer_name) === -1) spellings.push(h.customer_name); });
  const total = hits.reduce((s, h) => s + h.value_yen, 0);

  $("buyer-table").innerHTML = '<table class="data"><thead><tr>' +
    "<th>Supplier</th><th>Industry</th><th>Customer</th>" +
    '<th class="num">Revenue from them (¥bn)</th><th class="num">Share of supplier revenue (%)</th>' +
    "<th>Segment</th><th>Fiscal year to</th></tr></thead><tbody>" +
    hits.map(h =>
      "<tr><td>" + (h.filer.sec_code
        ? '<a href="company.html?code=' + escapeHtml(h.filer.sec_code) + '">' + escapeHtml(nameOf(h.filer)) + "</a>"
        : escapeHtml(nameOf(h.filer))) +
        (h.filer.sec_code ? ' <span style="color:var(--obs-text-muted)">' + escapeHtml(h.filer.sec_code) + "</span>" : "") + "</td>" +
      "<td>" + escapeHtml(h.filer.industry || "") + "</td>" +
      "<td>" + customerCell(h) + "</td>" +
      '<td class="num">' + bn(h.value_yen) + "</td>" +
      '<td class="num" data-sort="' + (h.share_pct || 0) + '">' + pct(h.share_pct) + "</td>" +
      "<td>" + escapeHtml(h.segment_label || "") + "</td>" +
      "<td>" + escapeHtml(h.filer.period_end || "") + "</td></tr>").join("") +
    "</tbody></table>";

  if (theme) {
    const buyers = [];
    hits.forEach(h => { if (buyers.indexOf(h.customer_name) === -1) buyers.push(h.customer_name); });
    $("buyer-foot").textContent =
      "¥" + bn(total) + "bn of disclosed revenue across " + hits.length + " supplier relationships " +
      "and " + buyers.length + " buyers tagged \u201c" + (THEME_LABEL[theme] || theme) + "\u201d in the " +
      "curated company list. The theme is the platform's own classification, not a disclosure: a " +
      "company is tagged only where its own filings describe that business. Only relationships " +
      "that crossed a supplier's 10% threshold appear at all.";
    calcBlock("buyer-calc", [C.calc, C.note, C.name_note]);
    wireBuyerCsv(hits, "theme-" + theme);
    return;
  }
  $("buyer-foot").textContent =
    "¥" + bn(total) + "bn of disclosed revenue across " + hits.length + " supplier" +
    (hits.length === 1 ? "" : "s") + ", matching " + spellings.length + " spelling" +
    (spellings.length === 1 ? "" : "s") + " as filed: " + spellings.join(" · ") +
    ". This is only what crossed each supplier's 10% threshold — a buyer's real Japanese " +
    "supply base is larger than any list built this way.";
  calcBlock("buyer-calc", [C.calc, C.note, C.name_note]);

  wireBuyerCsv(hits, q);
}

function wireBuyerCsv(hits, label) {
  const cur = $("buyer-csv");
  cur.onclick = e => {
    e.preventDefault();
    csvDownload("customers-" + String(label).replace(/[^a-z0-9]+/gi, "-") + ".csv",
      csvHeader('Suppliers naming a customer matching "' + label + '"'),
      ["sec_code", "supplier", "industry", "customer_as_filed", "customer_name_en",
       "english_name_source", "revenue_from_customer_yen",
       "share_of_supplier_revenue_pct", "segment", "fiscal_year_end"],
      hits.map(h => [h.filer.sec_code, nameOf(h.filer), h.filer.industry, h.customer_name,
        h.customer_name_en, h.name_source,
        h.value_yen, h.share_pct === null ? "" : h.share_pct.toFixed(2),
        h.segment_label, h.filer.period_end]));
  };
}

/* ---- buyers by reach ---- */

function renderReach() {
  const by = urlState().reach;
  const rows = C.customers.slice().sort((a, b) =>
    by === "value" ? b.total_yen - a.total_yen : (b.suppliers - a.suppliers) || (b.total_yen - a.total_yen));
  const top = rows.slice(0, 40);
  $("reach-note").textContent = C.coverage.distinct_customer_names + " distinct names";
  $("reach-table").innerHTML = '<table class="data"><thead><tr>' +
    "<th>Customer</th>" +
    '<th class="num">Japanese suppliers</th><th class="num">Combined disclosed revenue (¥bn)</th>' +
    '<th class="num">Largest single dependence (%)</th></tr></thead><tbody>' +
    top.map(c => "<tr><td>" + customerCell(c) + "</td>" +
      '<td class="num">' + fmtNum(c.suppliers, 0) + "</td>" +
      '<td class="num">' + bn(c.total_yen) + "</td>" +
      '<td class="num">' + pct(c.max_share_pct) + "</td></tr>").join("") +
    "</tbody></table>";
  $("reach-foot").textContent =
    "English names are shown where one could be looked up — " +
    fmtNum(C.coverage.names_with_english, 0) + " of " +
    fmtNum(C.coverage.distinct_customer_names, 0) + " names, plus " +
    fmtNum(C.coverage.names_already_latin, 0) + " already in Latin script; the remaining " +
    fmtNum(C.coverage.names_without_english, 0) + " have no published English name and are " +
    "shown as filed rather than translated. Top 40 of " +
    C.coverage.distinct_customer_names + " names. Two spellings of the same buyer " +
    "are two rows — Toyota appears twice because two filers wrote it differently, and merging " +
    "them here would state a total no filer disclosed.";
  $("reach-csv").onclick = e => {
    e.preventDefault();
    csvDownload("customers-by-reach.csv", csvHeader("Buyers ranked by Japanese suppliers"),
      ["customer_as_filed", "customer_name_en", "english_name_source", "customer_sec_code",
       "japanese_suppliers", "combined_disclosed_revenue_yen", "largest_single_dependence_pct"],
      rows.map(c => [c.customer_name, c.customer_name_en, c.name_source, c.customer_sec_code,
        c.suppliers, c.total_yen, c.max_share_pct === null ? "" : c.max_share_pct.toFixed(2)]));
  };
}

/* ---- most dependent suppliers ---- */

/* A buyer that resells. Excluding these answers a different question —
   dependence on end demand rather than on a route to market — so it is a
   filter the reader turns on, never the default, and the classification is
   the platform's own (company_labels.py), never the filer's. */
function isIntermediary(c) {
  const t = c.customer_tags || [];
  return t.indexOf("distributor") >= 0 || t.indexOf("trading") >= 0;
}

/* The filers ranked under the current filters. When intermediaries are
   excluded the dependence is recomputed over the customers that remain, so
   the column always states the sum of what is actually listed beside it. */
function dependenceRows() {
  const st = urlState();
  const min = Number(st.min), minRev = Number(st.rev) * 1e9, endOnly = st.buyers === "end";
  const out = [];
  C.filers.forEach(f => {
    if ((f.revenue_yen || 0) < minRev) return;
    const custs = endOnly ? f.customers.filter(c => !isIntermediary(c)) : f.customers;
    if (!custs.length) return;
    const named = custs.reduce((a, c) => a + c.value_yen, 0);
    const share = f.revenue_yen ? named / f.revenue_yen * 100 : null;
    if ((share || 0) < min) return;
    out.push(Object.assign({}, f, {
      shown_customers: custs, shown_named_yen: named, shown_share_pct: share,
      dropped: f.customers.length - custs.length }));
  });
  out.sort((a, b) => (b.shown_share_pct || 0) - (a.shown_share_pct || 0));
  return out;
}

function renderDependence() {
  const st = urlState();
  const min = Number(st.min), endOnly = st.buyers === "end";
  const rows = dependenceRows();
  const CAP = 60;
  const shown = rows.slice(0, CAP);
  $("dep-count").textContent = rows.length + " companies" +
    (rows.length > CAP ? " · showing the top " + CAP : "");
  $("dep-note").textContent = [
    min ? "at or above " + min + "%" : "",
    Number(st.rev) ? "revenue " + fmtNum(Number(st.rev), 0) + " ¥bn or more" : "",
    endOnly ? "end customers only" : "",
  ].filter(Boolean).join(" · ");
  $("dep-table").innerHTML = '<table class="data tbl-roomy"><thead><tr>' +
    "<th>Company</th><th>Industry</th>" +
    '<th class="num">Revenue (¥bn)</th><th class="num">Named customers</th>' +
    '<th class="num">Combined dependence (%)</th><th>Who</th></tr></thead><tbody>' +
    shown.map(f => {
      const who = f.shown_customers.slice()
        .sort((a, b) => b.value_yen - a.value_yen)
        .map(c => escapeHtml(customerLabel(c)) + " " +
          '<span style="color:var(--obs-text-muted)">' + pct(c.share_pct) + "%</span>" +
          (isIntermediary(c) ? ' <span class="tag-note">resells</span>' : "")).join(" · ");
      return "<tr><td>" + (f.sec_code
          ? '<a href="company.html?code=' + escapeHtml(f.sec_code) + '">' + escapeHtml(nameOf(f)) + "</a>"
          : escapeHtml(nameOf(f))) +
          (f.sec_code ? ' <span style="color:var(--obs-text-muted)">' + escapeHtml(f.sec_code) + "</span>" : "") + "</td>" +
        "<td>" + escapeHtml(f.industry || "") + "</td>" +
        '<td class="num">' + bn(f.revenue_yen) + "</td>" +
        '<td class="num">' + fmtNum(f.shown_customers.length, 0) + "</td>" +
        '<td class="num" data-sort="' + (f.shown_share_pct || 0) + '">' + pct(f.shown_share_pct) + "</td>" +
        "<td>" + who + "</td></tr>";
    }).join("") + "</tbody></table>";
  const classified = C.customers.filter(isIntermediary).length;
  $("dep-foot").textContent =
    (rows.length > CAP ? "Showing the " + CAP + " most dependent of " + rows.length +
      " companies at these filters; the CSV carries all of them. " : "") +
    "Combined dependence is the sum of every customer counted here, as a share of the company's " +
    "own revenue. It cannot exceed 100%: a filing where it did was a parsing fault and is now " +
    "gated. A company naming nobody is absent, which means nothing crossed the 10% threshold — " +
    "not that its revenue is spread thin." +
    (endOnly
      ? " Buyers classified as wholesalers or trading companies are excluded and the dependence " +
        "is recomputed over the customers that remain, so a company whose only named buyer " +
        "resells drops out of the list entirely. That classification is the platform's, not the " +
        "filer's: " + fmtNum(classified, 0) + " of " +
        fmtNum(C.coverage.distinct_customer_names, 0) + " buyer names as filed are classified " +
        "this way, so a smaller intermediary the list does not yet name is still counted as an " +
        "end customer."
      : " A buyer marked “resells” is one the platform classifies as a wholesaler or trading " +
        "company — the supplier's dependence on it is a route to market, not exposure to that " +
        "buyer's own end demand. Switch to End Customers Only to rank without them.");
  calcBlock("dep-calc", [
    endOnly
      ? "combined dependence = Σ revenue from each named customer not classified as a wholesaler " +
        "or trading company / consolidated revenue × 100, on the latest filing per company."
      : C.calc,
    C.note,
    "Wholesaler and trading-company classification is the platform's own, applied at serve time " +
    "to the buyer name as filed, and it changes which rows are counted — never a filed amount.",
  ]);
  $("dep-csv").onclick = e => {
    e.preventDefault();
    const flat = [];
    rows.forEach(f => f.shown_customers.forEach(c => flat.push([f.sec_code, nameOf(f), f.industry,
      f.revenue_yen, c.customer_name, c.customer_name_en,
      isIntermediary(c) ? "wholesaler or trading company" : "not classified", c.value_yen,
      c.share_pct === null ? "" : c.share_pct.toFixed(2),
      f.shown_share_pct === null ? "" : f.shown_share_pct.toFixed(2),
      c.segment_label, c.source, f.period_end])));
    csvDownload("customer-dependence.csv",
      csvHeader("Supplier dependence on named customers").concat([
        "Filters: minimum dependence " + (min || 0) + "%, minimum revenue " +
          fmtNum(Number(st.rev), 0) + " bn yen, " +
          (endOnly ? "buyers classified as wholesalers or trading companies excluded and the "
                   + "combined dependence recomputed over the customers that remain"
                   : "all named buyers counted") + ".",
        "buyer_classification is the platform's own, applied to the name as filed; every amount "
        + "in this file is as filed.",
      ].concat(endOnly ? ["combined_dependence_pct here = SUM(revenue from each named customer "
        + "not classified as a wholesaler or trading company) / consolidated revenue x 100, "
        + "which supersedes the combined-dependence formula above."] : [])),
      ["sec_code", "company", "industry", "consolidated_revenue_yen", "customer_as_filed",
       "customer_name_en", "buyer_classification", "revenue_from_customer_yen",
       "share_of_revenue_pct", "combined_dependence_pct", "segment", "disclosed_as",
       "fiscal_year_end"], flat);
  };
}

/* ---- provenance ---- */

function renderProvenance() {
  const periods = C.filers.map(f => f.period_end).filter(Boolean).sort();
  $("prov-card").innerHTML =
    '<div class="prov-card"><div class="prov-card-head">' +
      '<div class="prov-card-title">Data Source</div>' +
      '<div class="prov-card-id">EDINET · 有価証券報告書</div></div>' +
    '<div class="prov-grid">' +
      '<div class="prov-field full"><div class="prov-label">Official source</div>' +
        '<div class="prov-value">Annual securities reports, segment information note — 主要な顧客ごとの情報</div>' +
        '<div class="prov-sub">' + escapeHtml(C.credit_line) + " Disclosure is required of any customer " +
        "at or above 10% of consolidated revenue.</div></div>" +
      '<div class="prov-field"><div class="prov-label">Coverage</div>' +
        '<div class="prov-value num">' + fmtNum(C.coverage.filers_naming_a_customer, 0) + " companies</div>" +
        '<div class="prov-sub">' + fmtNum(C.coverage.relationships, 0) + " relationships · " +
        fmtNum(C.coverage.distinct_customer_names, 0) + " distinct names as filed</div></div>" +
      '<div class="prov-field"><div class="prov-label">Filings</div>' +
        '<div class="prov-value">' + (periods.length ? escapeHtml(periods[0]) + " – " + escapeHtml(periods[periods.length - 1]) : MISSING) + "</div>" +
        '<div class="prov-sub">Latest filing per company, current fiscal year only</div></div>' +
      '<div class="prov-field full"><div class="prov-label">English names</div>' +
        '<div class="prov-value">' + fmtNum(C.coverage.names_with_english, 0) + " looked up · " +
        fmtNum(C.coverage.names_already_latin, 0) + " already Latin · " +
        fmtNum(C.coverage.names_without_english, 0) + " none available</div>" +
        '<div class="prov-sub">' + escapeHtml(C.name_note) + "</div></div>" +
      '<div class="prov-field full"><div class="prov-label">Known limitation</div>' +
        '<div class="prov-value">' + escapeHtml(C.note) + "</div></div>" +
    "</div></div>";
}

/* ---- load ---- */

function renderAll() {
  EDGES = [];
  C.filers.forEach(f => f.customers.forEach(c => EDGES.push({
    filer: f, customer_name: c.customer_name, customer_name_en: c.customer_name_en,
    customer_sec_code: c.customer_sec_code, name_source: c.name_source,
    customer_group: c.customer_group, customer_tags: c.customer_tags,
    value_yen: c.value_yen, share_pct: c.share_pct,
    segment_label: c.segment_label, source: c.source })));
  renderHeader();
  renderTiles();
  renderSuggest();
  renderThemes();
  renderBuyer();
  renderReach();
  renderDependence();
  renderProvenance();
}

(function init() {
  initThemeToggle();
  const st = urlState();
  $("buyer-search").value = st.q;
  $("min-share").value = st.min;
  $("min-rev").value = st.rev;
  Array.prototype.forEach.call($("buyers-seg").querySelectorAll("button"), x =>
    x.setAttribute("aria-pressed", x.getAttribute("data-buyers") === st.buyers ? "true" : "false"));
  let t = null;
  $("buyer-search").addEventListener("input", e => {
    clearTimeout(t);
    t = setTimeout(() => {
      setUrlState({ q: e.target.value, theme: "" });
      const r = document.querySelector('#theme-picker input:checked');
      if (r) r.checked = false;
      renderBuyer();
    }, 180);
  });
  $("reach-seg").addEventListener("click", e => {
    const b = e.target.closest("button");
    if (!b) return;
    setUrlState({ reach: b.getAttribute("data-reach") });
    Array.prototype.forEach.call($("reach-seg").querySelectorAll("button"), x =>
      x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    renderReach();
  });
  $("min-share").addEventListener("change", e => {
    setUrlState({ min: e.target.value });
    renderDependence();
  });
  $("min-rev").addEventListener("change", e => {
    setUrlState({ rev: e.target.value });
    renderDependence();
  });
  $("buyers-seg").addEventListener("click", e => {
    const b = e.target.closest("button");
    if (!b) return;
    setUrlState({ buyers: b.getAttribute("data-buyers") });
    Array.prototype.forEach.call($("buyers-seg").querySelectorAll("button"), x =>
      x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    renderDependence();
  });
  fetch(API).then(r => {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(d => {
    C = d;
    Array.prototype.forEach.call($("reach-seg").querySelectorAll("button"), x =>
      x.setAttribute("aria-pressed", x.getAttribute("data-reach") === st.reach ? "true" : "false"));
    renderAll();
  }).catch(err => {
    $("stale-banner").innerHTML = '<div class="banner" role="alert">This page could not load its data (' +
      escapeHtml(err.message) + "). Nothing here is showing a stale number in the meantime.</div>";
  });
})();
