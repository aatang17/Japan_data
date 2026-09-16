/* Admin console: ingest health, release history, audit log.

   Structure follows the GSA-platform admin (persistent sidebar driven by one
   nav description, KPI summary cards, outline-only status badges, rows that
   expand into detail) rendered with Plover Analytics tokens and helpers. All data
   comes from /admin/api/*, which requires a signed-in session; the page shell
   itself holds no numbers.

   Statuses are never shown raw — every enum goes through a label map. */
"use strict";

var ROOT = document.getElementById("admin-root");

var ADMIN_NAV = [
  { group: "Operations", pages: [
    { id: "health", label: "Ingest Health", hash: "#health" },
    { id: "vintages", label: "Release History", hash: "#vintages" },
    { id: "traffic", label: "Traffic", hash: "#traffic" },
  ]},
  { group: "Classification", pages: [
    { id: "queue", label: "Classification Queue", hash: "#queue" },
    { id: "parties", label: "Party Profiles", hash: "#parties" },
  ]},
  { group: "System", pages: [
    { id: "audit", label: "Audit Log", hash: "#audit" },
  ]},
];

/* raw enum -> Title-Case label + badge tone; never render the slug */
var RELEASE_STATUS = {
  published: { label: "Published", cls: "badge-ok" },
  superseded: { label: "Superseded", cls: "badge-neutral" },
  rejected: { label: "Rejected", cls: "badge-danger" },
};
var AUDIT_ACTIONS = {
  party_created: { label: "Profile Created", cls: "badge-info" },
  party_updated: { label: "Profile Edited", cls: "badge-info" },
  party_deleted: { label: "Profile Deleted", cls: "badge-warn" },
  party_exported: { label: "Classification Exported", cls: "badge-neutral" },
  login: { label: "Signed In", cls: "badge-ok" },
  logout: { label: "Signed Out", cls: "badge-neutral" },
  login_failed: { label: "Failed Login", cls: "badge-danger" },
  login_locked_out: { label: "Locked Out", cls: "badge-danger" },
  unparseable_entry: { label: "Unreadable Entry", cls: "badge-warn" },
};

function badge(map, key) {
  var d = map[key] || { label: key ? key.replace(/_/g, " ") : MISSING, cls: "badge-neutral" };
  return '<span class="badge ' + d.cls + '">' + escapeHtml(d.label) + "</span>";
}

/* Values across datasets span index points to ¥100mn stocks: group thousands,
   true minus, and ONE precision per table — the widest number of decimals any
   value in the column actually carries (capped at 4), so 127.0 and 129.6
   never sit in the same column as "127" and "129.6". */
function decimalsOf(v) {
  if (v === null || v === undefined) return 0;
  var s = String(v);
  var dot = s.indexOf(".");
  return dot === -1 ? 0 : Math.min(4, s.length - dot - 1);
}

function fmtVal(v, dp) {
  if (v === null || v === undefined) return MISSING;
  return v.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })
    .replace(/-/g, MINUS);
}

/* Age of the ingest heartbeat. Hours up to two days, then days: an operator
   needs "is this today's data?" at a glance, and 51.7 does not answer it. */
function fmtAgo(hours) {
  if (hours === null || hours === undefined) return MISSING;
  if (hours < 1) return "Under 1h";
  if (hours < 48) return Math.round(hours) + "h ago";
  return Math.round(hours / 24) + "d ago";
}

function fmtBytes(b) {
  if (b === null || b === undefined) return MISSING;
  if (b >= 1024 * 1024) return (b / (1024 * 1024)).toFixed(1) + " MB";
  return Math.round(b / 1024).toLocaleString("en-US") + " KB";
}

/* ---------- API ---------- */

function api(path, opts) {
  return fetch("/admin/api" + path, Object.assign({ credentials: "same-origin" }, opts || {}))
    .then(function (r) {
      if (r.status === 401) { renderLogin(""); throw new Error("Signed out"); }
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          throw new Error(b.detail || "The request failed (" + r.status + ")");
        });
      }
      return r.json();
    });
}

function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function loadFailed(what, err) {
  return '<div class="admin-alert"><span class="head">Could not load ' + escapeHtml(what) +
    ".</span> " + escapeHtml(err.message || String(err)) + " Reload the page to try again.</div>";
}

/* ---------- login / disabled ---------- */

function renderDisabled() {
  ROOT.innerHTML =
    '<div class="admin-login-wrap"><div class="admin-login-card">' +
    "<h1>Admin Console</h1>" +
    '<p class="sub">The admin console is switched off on this deployment: no admin ' +
    "password is configured. Set <code>ADMIN_PASSWORD</code> in the server environment " +
    "(or in <code>.env</code> locally) and restart to enable it.</p>" +
    '<a class="btn" href="index.html">Back to Plover Analytics</a>' +
    "</div></div>";
}

function renderLogin(message) {
  ROOT.innerHTML =
    '<div class="admin-login-wrap"><div class="admin-login-card">' +
    "<h1>Admin Console</h1>" +
    '<p class="sub">Plover Analytics — internal operations. Sign in to continue.</p>' +
    '<div id="login-alert"></div>' +
    '<form id="login-form">' +
    '<label for="login-pw">Password</label>' +
    '<input type="password" id="login-pw" autocomplete="current-password" required>' +
    '<button type="submit" class="btn btn-primary" id="login-btn">Sign In</button>' +
    "</form></div></div>";
  if (message) showLoginAlert(message);
  var form = document.getElementById("login-form");
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var btn = document.getElementById("login-btn");
    btn.disabled = true;
    btn.textContent = "Signing in…";
    post("/login", { password: document.getElementById("login-pw").value })
      .then(function () { renderShell(); route(); })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = "Sign In";
        showLoginAlert(err.message);
      });
  });
  document.getElementById("login-pw").focus();
}

function showLoginAlert(message) {
  var box = document.getElementById("login-alert");
  if (box) box.innerHTML = '<div class="login-alert" role="alert">' + escapeHtml(message) + "</div>";
}

/* ---------- shell ---------- */

function renderShell() {
  var nav = ADMIN_NAV.map(function (g) {
    return '<div class="admin-nav-group">' + escapeHtml(g.group) + "</div>" +
      g.pages.map(function (p) {
        return '<a class="admin-nav-item" data-view="' + p.id + '" href="' + p.hash + '">' +
          escapeHtml(p.label) + "</a>";
      }).join("");
  }).join("");

  ROOT.innerHTML =
    '<div class="admin-shell">' +
    '<aside class="admin-sidebar" id="admin-sidebar">' +
    '<div class="admin-side-head"><span class="brand">Plover Analytics ' +
    '<span class="ds">/ Admin</span></span></div>' +
    '<button type="button" class="admin-menu-btn" id="admin-menu-btn">Menu</button>' +
    '<nav class="admin-nav" aria-label="Admin">' + nav + "</nav>" +
    '<div class="admin-side-foot">' +
    '<a class="side-btn" href="index.html">View Site</a>' +
    '<button type="button" class="theme-toggle side-btn">Dark Mode</button>' +
    '<button type="button" class="side-btn" id="sign-out">Sign Out</button>' +
    "</div></aside>" +
    '<main class="admin-main"><div class="admin-container" id="admin-view"></div></main>' +
    "</div>";

  // The traffic chart reads its colours from tokens at build time, so a theme
  // switch has to redraw it.
  initThemeToggle(function () { if (trafficChart) trafficChart.render(); });
  document.getElementById("sign-out").addEventListener("click", function () {
    post("/logout").then(function () { renderLogin("Signed out."); })
      .catch(function () { renderLogin(""); });
  });
  document.getElementById("admin-menu-btn").addEventListener("click", function () {
    var side = document.getElementById("admin-sidebar");
    if (side.hasAttribute("data-menu-open")) side.removeAttribute("data-menu-open");
    else side.setAttribute("data-menu-open", "");
  });
}

function route() {
  var hash = location.hash || "#health";
  var parts = hash.slice(1).split("/");
  var view = parts[0] || "health";
  var arg = parts[1] || null;
  /* #parties/new/<edinet-code> carries the filer to prefill from. */
  var arg2 = parts[2] || null;
  var links = document.querySelectorAll(".admin-nav-item");
  for (var i = 0; i < links.length; i++) {
    if (links[i].getAttribute("data-view") === view) links[i].setAttribute("aria-current", "page");
    else links[i].removeAttribute("aria-current");
  }
  var side = document.getElementById("admin-sidebar");
  if (side) side.removeAttribute("data-menu-open");
  var target = document.getElementById("admin-view");
  if (!target) return;
  disposeTrafficChart();  // the view about to be replaced may own it
  if (view === "vintages") viewVintages(target, arg);
  else if (view === "traffic") viewTraffic(target, arg);
  else if (view === "audit") viewAudit(target);
  else if (view === "queue") viewQueue(target);
  else if (view === "parties") {
    if (arg) viewPartyDetail(target, arg, arg2);
    else viewParties(target);
  } else viewHealth(target);
}

/* ---------- ingest health ---------- */

var HEALTH_BADGES_NOTE = {
  stale: "the newest period on the surface is older than this dataset should ever be",
  orphan: "a file was fetched after the published one and no release came of it",
};

function viewHealth(target) {
  target.innerHTML = '<div class="admin-loading">Loading ingest health…</div>';
  api("/overview").then(function (report) {
    var ds = report.datasets;
    var current = ds.filter(function (d) { return d.status === "ok"; }).length;
    var orphans = ds.filter(function (d) { return d.unpublished_artifact; }).length;
    var rejected = ds.reduce(function (n, d) { return n + (d.releases_rejected || 0); }, 0);
    var vintages = ds.reduce(function (n, d) { return n + (d.vintages || 0); }, 0);

    // refresh_overdue is tri-state: true, false, or null when nothing has
    // stamped a cycle yet. Unknown is not healthy and not a fault — it gets
    // the neutral tone and an em dash, never a reassuring green zero.
    var refreshTone = report.refresh_overdue === true ? "danger"
      : report.refresh_overdue === false ? "ok" : "";

    var kpis =
      kpi(current + " / " + ds.length, "Datasets Current", current === ds.length ? "ok" : "danger") +
      kpi(fmtAgo(report.hours_since_ingest), "Last Ingest", refreshTone) +
      kpi(orphans ? String(orphans) : "All clear", "Unpublished Files", orphans ? "danger" : "ok") +
      kpi(rejected ? String(rejected) : "None", "Rejected Ingests", rejected ? "danger" : "ok") +
      kpi(String(vintages), "Releases Stored", "");

    // The refresh comes first: a pipeline that has stopped is the reason every
    // dataset under it is ageing, so it must not be buried among the symptoms.
    var faults = [];
    if (report.refresh_overdue) {
      faults.push("<strong>Daily refresh</strong> — the ingest last ran " +
        escapeHtml(fmtAgo(report.hours_since_ingest)) + ", past the " +
        escapeHtml(String(report.refresh_max_age_hours)) + "-hour limit");
    }
    ds.filter(function (d) { return d.status === "attention"; }).forEach(function (d) {
      var why = [];
      if (!d.published) why.push("no published release");
      if (d.stale) why.push(HEALTH_BADGES_NOTE.stale);
      if (d.unpublished_artifact) why.push(HEALTH_BADGES_NOTE.orphan);
      faults.push("<strong>" + escapeHtml(d.dataset) + "</strong> — " +
        escapeHtml(why.join("; ")));
    });
    var banner = faults.length
      ? '<div class="admin-alert"><span class="head">Needs attention:</span> ' +
        faults.join(" · ") + "</div>"
      : "";

    var rows = ds.map(function (d) {
      var status;
      if (!d.published) status = '<span class="badge badge-danger">No Release</span>';
      else {
        status = d.stale ? '<span class="badge badge-danger">Stale</span>'
                         : '<span class="badge badge-ok">Current</span>';
        if (d.unpublished_artifact) status += ' <span class="badge badge-warn">Unpublished File</span>';
      }
      return '<tr class="clickable" data-ds="' + escapeHtml(d.dataset) + '">' +
        "<td><strong>" + escapeHtml(d.dataset) + "</strong></td>" +
        "<td>" + status + "</td>" +
        '<td class="num">' + (d.latest_period ? escapeHtml(d.latest_period) : MISSING) + "</td>" +
        '<td class="num">' + (d.published ? d.days_since_latest_period.toLocaleString("en-US") +
          ' <span class="muted">/ ' + d.stale_after_days + "</span>" : MISSING) + "</td>" +
        '<td class="num">' + (d.last_published_at ? fmtStamp(d.last_published_at) : MISSING) + "</td>" +
        '<td class="num">' + (d.series_active !== null && d.series_active !== undefined
          ? d.series_active.toLocaleString("en-US") : MISSING) + "</td>" +
        '<td class="num">' + (d.vintages || 0) + "</td>" +
        '<td class="mono">' + (d.artifact_sha256 ? escapeHtml(d.artifact_sha256.slice(0, 12)) +
          ' <span class="muted">· ' + fmtBytes(d.artifact_bytes) + "</span>" : MISSING) + "</td>" +
        "</tr>";
    }).join("");

    target.innerHTML =
      '<div class="admin-page-head"><h1>Ingest Health</h1><span class="spacer"></span>' +
      '<button type="button" class="btn" id="health-refresh">Refresh</button>' +
      '<p class="admin-page-sub">Whether each dataset is current, and whether an ingest went ' +
      "quiet — a fetched file that published nothing is either a validation failure or a crash. " +
      "Checked " + escapeHtml(fmtStamp(report.checked_at)) + " · last ingest " +
      escapeHtml(fmtStamp(report.last_ingest_at)) + ".</p></div>" +
      '<div class="kpi-row">' + kpis + "</div>" + banner +
      '<div class="admin-section">Datasets <span class="note">age is days since the newest ' +
      "period / the limit before it counts as stale · click a row for its releases</span></div>" +
      '<div class="table-wrap"><table class="data" data-no-enhance>' +
      "<thead><tr><th>Dataset</th><th>Status</th>" +
      '<th class="num">Data Through</th><th class="num">Age, Days</th>' +
      '<th class="num">Last Published (UTC)</th><th class="num">Active Series</th>' +
      '<th class="num">Releases</th><th>Source File</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div>";

    document.getElementById("health-refresh").addEventListener("click", function () {
      viewHealth(target);
    });
    var trs = target.querySelectorAll("tr.clickable");
    for (var i = 0; i < trs.length; i++) {
      trs[i].addEventListener("click", function () {
        location.hash = "#vintages/" + this.getAttribute("data-ds");
      });
    }
  }).catch(function (err) {
    target.innerHTML = loadFailed("the ingest health report", err);
  });
}

function kpi(value, label, tone) {
  return '<div class="kpi"><div class="kpi-value ' + tone + '">' + escapeHtml(value) +
    '</div><div class="kpi-label">' + escapeHtml(label) + "</div></div>";
}

/* ---------- release history ---------- */

function viewVintages(target, slug) {
  target.innerHTML = '<div class="admin-loading">Loading releases…</div>';
  api("/overview").then(function (report) {
    var ds = report.datasets;
    if (!slug || !ds.some(function (d) { return d.dataset === slug; })) {
      slug = ds[0].dataset;
    }
    var cards = ds.map(function (d) {
      return '<button type="button" class="ds-card" data-ds="' + escapeHtml(d.dataset) + '"' +
        (d.dataset === slug ? ' aria-pressed="true"' : ' aria-pressed="false"') + ">" +
        '<div class="t">' + escapeHtml(d.dataset) + "</div>" +
        '<div class="s">' + (d.vintages || 0) + " release" + (d.vintages === 1 ? "" : "s") +
        " · through " + (d.latest_period ? escapeHtml(d.latest_period) : MISSING) + "</div></button>";
    }).join("");

    target.innerHTML =
      '<div class="admin-page-head"><h1>Release History</h1>' +
      '<p class="admin-page-sub">Every accepted ingest is a stored release. A stored release is ' +
      "never edited — a correction arrives as a new release, and this page shows exactly what " +
      "each one introduced, revised, or withdrew.</p></div>" +
      '<div class="ds-cards">' + cards + "</div>" +
      '<div id="release-list"><div class="admin-loading">Loading releases…</div></div>';

    var btns = target.querySelectorAll(".ds-card");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function () {
        location.hash = "#vintages/" + this.getAttribute("data-ds");
      });
    }
    renderReleases(document.getElementById("release-list"), slug);
  }).catch(function (err) {
    target.innerHTML = loadFailed("the dataset list", err);
  });
}

function renderReleases(box, slug) {
  api("/releases/" + encodeURIComponent(slug)).then(function (data) {
    if (!data.releases.length) {
      box.innerHTML = '<p class="table-empty">No releases stored for this dataset yet.</p>';
      return;
    }
    var rows = data.releases.map(function (r) {
      return '<tr class="clickable" data-release="' + r.release_id + '" data-first="' +
        (r.is_first_vintage ? "1" : "0") + '" data-recorded="' + r.recorded + '">' +
        '<td><span class="chev">▸</span> <strong>' + escapeHtml(r.label) + "</strong></td>" +
        "<td>" + badge(RELEASE_STATUS, r.status) + "</td>" +
        '<td class="num">' + fmtStamp(r.ingested_at) + "</td>" +
        '<td class="num">' + r.recorded.toLocaleString("en-US") + "</td>" +
        '<td class="num">' + (r.withdrawn ? r.withdrawn.toLocaleString("en-US") : "0") + "</td>" +
        '<td class="mono">' + escapeHtml(r.sha256.slice(0, 12)) +
        ' <span class="muted">· ' + fmtBytes(r.bytes) + "</span></td>" +
        "</tr>";
    }).join("");

    box.innerHTML =
      '<div class="admin-section">' + escapeHtml(slug) +
      ' <span class="note">newest first · click a release to see what it changed</span></div>' +
      '<div class="table-wrap"><table class="data" data-no-enhance>' +
      "<thead><tr><th>Release</th><th>Status</th>" +
      '<th class="num">Ingested (UTC)</th><th class="num">Values Recorded</th>' +
      '<th class="num">Withdrawn</th><th>Source File</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div>";

    var trs = box.querySelectorAll("tr.clickable");
    for (var i = 0; i < trs.length; i++) {
      trs[i].addEventListener("click", function () { toggleReleaseDetail(this, slug); });
    }
  }).catch(function (err) {
    box.innerHTML = loadFailed("the releases of " + slug, err);
  });
}

function toggleReleaseDetail(tr, slug) {
  var open = tr.nextElementSibling && tr.nextElementSibling.classList.contains("detail-row");
  if (open) {
    tr.parentNode.removeChild(tr.nextElementSibling);
    tr.querySelector(".chev").textContent = "▸";
    return;
  }
  tr.querySelector(".chev").textContent = "▾";
  var detail = document.createElement("tr");
  detail.className = "detail-row";
  var cell = document.createElement("td");
  cell.colSpan = tr.children.length;
  detail.appendChild(cell);
  tr.parentNode.insertBefore(detail, tr.nextElementSibling);

  // The first release of a dataset is its entire history as first recorded —
  // tens of thousands of "new" values with nothing to compare against.
  if (tr.getAttribute("data-first") === "1") {
    cell.innerHTML = '<div class="detail-block"><div class="h">Initial Release</div>' +
      "This release is the dataset’s first recorded release: all " +
      Number(tr.getAttribute("data-recorded")).toLocaleString("en-US") +
      " values are the history as it stood at first ingest. Later releases are " +
      "compared against it.</div>";
    return;
  }

  cell.innerHTML = '<div class="admin-loading">Loading changes…</div>';
  api("/releases/" + encodeURIComponent(slug) + "/" + tr.getAttribute("data-release") + "/changes")
    .then(function (c) { cell.innerHTML = renderChanges(c); })
    .catch(function (err) { cell.innerHTML = loadFailed("this release's changes", err); });
}

function changeTable(rows, withPrior) {
  var SHOW = 20;
  var shown = rows.slice(0, SHOW);
  var dp = shown.reduce(function (d, r) {
    return Math.max(d, decimalsOf(r.value), withPrior ? decimalsOf(r.prior) : 0);
  }, 0);
  var body = shown.map(function (r) {
    return "<tr><td>" + escapeHtml(r.code) + "</td>" +
      '<td class="cell-item"><span class="en">' + escapeHtml(r.name || "") + "</span></td>" +
      '<td class="num">' + escapeHtml(r.period) + "</td>" +
      '<td class="num">' + (withPrior
        ? '<span class="was">' + fmtVal(r.prior, dp) + "</span> → " +
          '<span class="now">' + fmtVal(r.value, dp) + "</span>"
        : '<span class="now">' + fmtVal(r.value, dp) + "</span>") + "</td></tr>";
  }).join("");
  var more = rows.length > SHOW
    ? '<p class="table-empty">…and ' + (rows.length - SHOW).toLocaleString("en-US") +
      " more not shown.</p>" : "";
  return '<div class="table-wrap"><table class="data" data-no-enhance>' +
    "<thead><tr><th>Code</th><th>Item</th>" +
    '<th class="num">Period</th><th class="num">' + (withPrior ? "Was → Now" : "Value") +
    "</th></tr></thead><tbody>" + body + "</tbody></table></div>" + more;
}

function renderChanges(c) {
  var parts = [];
  var rev = c.revisions, add = c.new_values, gone = c.withdrawals;

  parts.push('<div class="detail-block"><div class="h">Revisions — ' +
    rev.count.toLocaleString("en-US") + "</div>" +
    (rev.count
      ? changeTable(rev.rows, true) +
        (rev.truncated ? '<p class="table-empty">List capped at ' + rev.rows.length +
          " rows; the count above is complete.</p>" : "")
      : '<span class="muted">No previously published value was changed.</span>') + "</div>");

  if (add.count) {
    var periods = add.rows.map(function (r) { return r.period; });
    var lo = periods.slice().sort()[0];
    var hi = periods.slice().sort().slice(-1)[0];
    var range = add.truncated
      ? "listed sample runs " + lo + " to " + hi
      : (lo === hi ? "all for " + lo : "covering " + lo + " to " + hi);
    parts.push('<div class="detail-block"><div class="h">New Values — ' +
      add.count.toLocaleString("en-US") + ' <span style="text-transform:none;letter-spacing:0">(' +
      escapeHtml(range) + ")</span></div>" + changeTable(add.rows, false) + "</div>");
  } else {
    parts.push('<div class="detail-block"><div class="h">New Values — 0</div>' +
      '<span class="muted">No new periods or series.</span></div>');
  }

  if (gone.count) {
    parts.push('<div class="detail-block"><div class="h">Withdrawn — ' +
      gone.count.toLocaleString("en-US") + "</div>" + changeTable(gone.rows, true) + "</div>");
  }
  return parts.join("");
}

/* ---------- traffic ---------- */

var TRAFFIC_WINDOWS = [7, 30, 90];

/* The console's only chart. Held at module scope so a theme switch can redraw
   it and a move to another page can dispose it. */
var trafficChart = null;

/* "2026-09-12" -> "12 Sep 2026" */
function fmtDay(iso) {
  if (!iso) return MISSING;
  var month = (MONTHS[Number(String(iso).slice(5, 7)) - 1] || "").slice(0, 3);
  return Number(String(iso).slice(8, 10)) + " " + month + " " + String(iso).slice(0, 4);
}

function fmtCount(v) {
  if (v === null || v === undefined) return MISSING;
  return v.toLocaleString("en-US");
}

/* Seconds as a person reads them. Under a minute keeps its seconds, because
   the difference between 20 and 50 seconds on a page is the whole question. */
function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return MISSING;
  seconds = Math.round(seconds);
  if (seconds < 60) return seconds + "s";
  var mins = Math.floor(seconds / 60);
  if (mins < 60) return mins + "m " + (seconds % 60) + "s";
  return Math.floor(mins / 60) + "h " + (mins % 60) + "m";
}

/* The "right now" panel refreshes itself; the handle lives here so leaving the
   page can stop it. */
var liveTimer = null;
var LIVE_REFRESH_MS = 20000;

function disposeTrafficChart() {
  if (trafficChart) {
    trafficChart.dispose();
    trafficChart = null;
  }
  if (liveTimer) {
    window.clearInterval(liveTimer);
    liveTimer = null;
  }
}

/* Counting stops silently if the log cannot be written, so a quiet day and a
   broken counter look identical until the age of the last request is stated. */
var TRAFFIC_SILENT_HOURS = 36;

function viewTraffic(target, arg) {
  var days = TRAFFIC_WINDOWS.indexOf(Number(arg)) === -1 ? 30 : Number(arg);
  target.innerHTML = '<div class="admin-loading">Loading traffic…</div>';
  api("/visits?days=" + days).then(function (d) {
    target.innerHTML = trafficMarkup(d, days);
    wireTraffic(target, d, days);
  }).catch(function (err) {
    target.innerHTML = loadFailed("the traffic summary", err);
  });
}

/* Readers on the site in the last few minutes, and what they have open.
   Its own endpoint rather than part of the summary: it answers in memory,
   costs nothing, and is the one figure here worth asking for again while the
   page is open. */
function liveMarkup(d) {
  if (!d) return '<p class="table-empty">Live readership is unavailable.</p>';
  var minutes = Math.round((d.window_seconds || 300) / 60);
  var rows = (d.pages || []).filter(function (r) { return r.key; }).map(function (r) {
    return '<tr><td class="mono"><a href="' + escapeHtml(r.key) + '" target="_blank" ' +
      'rel="noopener">' + escapeHtml(r.key) + "</a></td>" +
      '<td class="num">' + fmtCount(r.visitors) + "</td></tr>";
  }).join("");
  var places = (d.countries || []).map(function (r) {
    return escapeHtml(countryName(r.key)) + " " + fmtCount(r.visitors);
  }).join(" · ");

  return '<div class="kpi-row">' +
    kpi(fmtCount(d.visitors), "Reading Now", d.visitors ? "ok" : "") +
    kpi(fmtCount((d.pages || []).length), "Pages Open", "") +
    kpi(fmtCount((d.countries || []).length), "Countries", "") + "</div>" +
    (rows
      ? '<div class="table-wrap"><table class="data" data-no-enhance><thead><tr>' +
        '<th>Page Open Now</th><th class="num">Readers</th></tr></thead><tbody>' +
        rows + "</tbody></table></div>"
      : '<p class="table-empty">Nobody has asked for anything in the last ' +
        minutes + " minutes.</p>") +
    '<p class="source-line">A reader counts as here for ' + minutes + " minutes after " +
    "their last request; an open page reports itself every minute, so somebody sitting " +
    "still on one page stays counted." + (places ? " Now: " + places + "." : "") + "</p>";
}

function refreshLive(target) {
  var box = target.querySelector("#traffic-live");
  if (!box) return;
  api("/visits/live").then(function (d) {
    var still = target.querySelector("#traffic-live");
    if (still) still.innerHTML = liveMarkup(d);
  }).catch(function () {
    var still = target.querySelector("#traffic-live");
    // Silent: the window figures beside it are still good, and a red box
    // every twenty seconds would say the console is broken when it is not.
    if (still) still.innerHTML = '<p class="table-empty">Live readership is ' +
      "unavailable — the figures below are unaffected.</p>";
  });
}

function trafficMarkup(d, days) {
  var seg = '<div class="seg" role="group" aria-label="Window" id="traffic-seg">' +
    TRAFFIC_WINDOWS.map(function (w) {
      return '<button type="button" data-days="' + w + '"' +
        (w === days ? ' aria-pressed="true"' : "") + ">" + w + "D</button>";
    }).join("") + "</div>";

  var head =
    '<div class="admin-page-head"><h1>Traffic</h1><span class="spacer"></span>' + seg +
    '<button type="button" class="btn" id="traffic-refresh">Refresh</button>' +
    '<p class="admin-page-sub">Readership counted by the server itself, so readers on ' +
    "networks that block analytics scripts are counted too. No addresses are stored; the " +
    "only cookie is the one a reader accepts, and it holds a random number and the day it " +
    "was issued. " + escapeHtml(fmtDay(d.from)) + " to " + escapeHtml(fmtDay(d.to)) +
    (d.last_event ? " · last request " + escapeHtml(fmtStamp(d.last_event)) : "") +
    ".</p></div>";

  var hoursSilent = d.last_event
    ? (Date.now() - Date.parse(d.last_event)) / 3600000 : null;
  var banner = "";
  if (hoursSilent !== null && hoursSilent > TRAFFIC_SILENT_HOURS) {
    banner = '<div class="admin-alert"><span class="head">Counting may have stopped:</span> ' +
      "the last request recorded was " + escapeHtml(fmtAgo(hoursSilent)) +
      ". Either nothing reached the site, or the visit log on the data volume cannot be " +
      "written — the server log reports the write failure if that is the cause.</div>";
  }

  // "Visits", never "unique visitors": the identifier rotates daily, so this
  // is the sum of each day's visitors, not a headcount of people.
  // People is the strict figure — a script ran, the network is placed and is
  // not a data centre — and sits beside Visits so the gap between the two is
  // the first thing read off the row.
  var confirmed = d.confirmed || {};
  var kpis =
    kpi(fmtCount(d.visitors), "Visits", "") +
    kpi(fmtCount(confirmed.people), "People", "") +
    kpi(fmtCount(d.browser_visits), "Browser Visits", "") +
    kpi(fmtCount(d.pageviews), "Page Views", "") +
    kpi(fmtCount(d.api_calls + d.mcp_calls), "API Requests", "") +
    kpi(fmtCount(d.bot_hits), "Automated Hits", "");

  var chart = d.counting_since
    ? '<div class="chart-panel">' +
      '<div class="controls"><span class="spacer"></span>' +
      '<button type="button" class="btn" id="traffic-png">Download PNG</button>' +
      '<button type="button" class="btn" id="traffic-csv">Download CSV</button></div>' +
      '<div class="chart" id="traffic-chart"></div>' +
      '<p class="source-line">Counted by the Plover Analytics server from its own ' +
      "request log. Days before counting began on this deployment are shown as gaps, " +
      "not as zero.</p>" + trafficCalc(d) + "</div>"
    : '<p class="table-empty">No requests recorded yet. Counting begins the moment this ' +
      "build is deployed, and the window fills in from that day forward.</p>" + trafficCalc(d);

  return head +
    '<div class="admin-section">Right Now <span class="note">from the server\u2019s ' +
    "memory, refreshed every 20 seconds</span></div>" +
    '<div id="traffic-live"><p class="admin-loading">Loading live readership…</p></div>' +
    '<div class="admin-section">This Window <span class="note">' +
    escapeHtml(fmtDay(d.from)) + " to " + escapeHtml(fmtDay(d.to)) + "</span></div>" +
    '<div class="kpi-row">' + kpis + "</div>" + peopleNote(d) + banner +
    '<div class="admin-section">Daily Readership <span class="note">unique visitors and ' +
    "page views per day</span></div>" + chart +
    trafficTime(d) + trafficPeople(d) +
    '<div class="admin-section">Most-Read Pages <span class="note">page views in this ' +
    "window</span></div>" +
    trafficTable(d.top_pages, "Page",
      { link: true, dwell: true, empty: "No page views recorded in this window." }) +
    '<div class="admin-section">How Readers Arrived <span class="note">only the sending ' +
    "site is recorded, never the page a reader came from</span></div>" +
    trafficArrivals(d) + trafficDirect(d) + trafficAI(d) + trafficPlaces(d);
}

/* What each AI fetcher was doing. Three different facts, so three labels:
   nobody read the page when it was taken for training, and somebody was asking
   about it when it was fetched on request. */
var AI_PURPOSE = {
  asked: { label: "Someone asked about this page", cls: "badge-ok" },
  search: { label: "Building an index that can cite us", cls: "badge-info" },
  training: { label: "Taking the text to train on", cls: "badge-neutral" },
};

/* Assistants that fetched pages, and readers who arrived from an assistant's
   answer. Given its own section because it answers a question nothing else
   here can: is anything out there answering questions about this site. */
function trafficAI(d) {
  var rows = d.ai_agents || [];
  var referred = d.ai_referrals || { views: 0, visitors: 0 };
  var note = referred.views
    ? fmtCount(referred.views) + " page view" + (referred.views === 1 ? "" : "s") +
      " arrived from an assistant\u2019s answer"
    : "no reader has arrived from an assistant\u2019s answer yet";
  var body = rows.length
    ? '<div class="table-wrap"><table class="data">' +
      "<thead><tr><th>Assistant</th><th>What it was doing</th>" +
      '<th class="num">Requests</th><th class="num">Visits</th>' +
      "<th>Most-requested page</th><th>Last seen</th></tr></thead><tbody>" +
      rows.map(function (r) {
        var p = AI_PURPOSE[r.purpose] ||
          { label: r.purpose || MISSING, cls: "badge-neutral" };
        return "<tr><td>" + escapeHtml(r.key) + "</td>" +
          '<td><span class="badge ' + p.cls + '">' + escapeHtml(p.label) + "</span></td>" +
          '<td class="num">' + fmtCount(r.views) + "</td>" +
          '<td class="num">' + fmtCount(r.visitors) + "</td>" +
          '<td class="mono">' + (r.top_page ? escapeHtml(r.top_page) : MISSING) + "</td>" +
          '<td class="num">' + (r.last ? escapeHtml(fmtStamp(r.last)) : MISSING) +
          "</td></tr>";
      }).join("") + "</tbody></table></div>"
    : '<p class="table-empty">No assistant has fetched a page in this window. ' +
      "They are identified by the name they send, so one that sends none is " +
      "counted as an ordinary crawler instead.</p>";
  return '<div class="admin-section">AI Assistants ' +
    '<span class="note">' + escapeHtml(note) + "</span></div>" + body;
}

/* What the People figure is made of, so a small number can be read: how many
   visits ran the page's script, how many were placed, how many were data
   centres. A line under the row it qualifies, not a panel. */
function peopleNote(d) {
  var c = d.confirmed;
  if (!c || !d.visitors) return "";
  return '<p class="admin-page-sub">Of ' + fmtCount(d.visitors) + " visits, " +
    fmtCount(c.scripted) + " reported a reading time, " + fmtCount(c.placed) +
    " were placed on a network, and " + fmtCount(c.hosting) +
    " came from a data centre. <strong>People</strong> counts the visits that reported a " +
    "time from a placed network that is not a data centre — see Show calculation.</p>";
}

/* A share of a total, where a real but tiny share must not read as zero. */
function share(part, total) {
  if (!total) return MISSING;
  var pct = (part || 0) / total * 100;
  if (pct > 0 && pct < 1) return "<1%";
  return Math.round(pct) + "%";
}

/* How long a page was open, and how long a visit ran. Medians, not averages:
   one tab left open over a weekend would carry an average by itself. */
function trafficTime(d) {
  var dwell = d.dwell || {};
  var sessions = d.sessions || {};
  var bounce = sessions.samples ? share(sessions.single_page, sessions.samples) : MISSING;
  var note = fmtCount(dwell.samples) + " page" + (dwell.samples === 1 ? "" : "s") +
    " reported a reading time · " + fmtCount(sessions.samples) + " visit" +
    (sessions.samples === 1 ? "" : "s") + " reconstructed from the request log";
  return '<div class="admin-section">How Long Readers Stayed ' +
    '<span class="note">' + escapeHtml(note) + "</span></div>" +
    '<div class="kpi-row">' +
    kpi(fmtDuration(dwell.median_seconds), "Median Time on Page", "") +
    kpi(fmtDuration(sessions.median_seconds), "Median Visit Length", "") +
    kpi(sessions.pages_median === null || sessions.pages_median === undefined
      ? MISSING : String(sessions.pages_median), "Pages per Visit (Median)", "") +
    kpi(bounce, "Left After One Page", "") +
    "</div>";
}

/* Readers carrying a cookie: the only population that can be followed from one
   day to the next, and how much of the readership it covers. */
function trafficPeople(d) {
  var people = d.people || {};
  var consent = d.consent || {};
  var answered = (consent.granted || 0) + (consent.denied || 0) + (consent.unanswered || 0);
  // Counts first, share after: with a long log behind it a real handful of
  // consented reads rounds to 0% and reads as "nobody", which is not the same
  // thing as "two people".
  var note = fmtCount(consent.granted || 0) + " of " + fmtCount(answered) +
    " page views (" + share(consent.granted, answered) + ") came from a reader who " +
    "accepted the cookie, " + fmtCount(consent.denied || 0) + " (" +
    share(consent.denied, answered) + ") from one who declined";
  return '<div class="admin-section">Returning Readers ' +
    '<span class="note">' + escapeHtml(note) + "</span></div>" +
    '<div class="kpi-row">' +
    kpi(fmtCount(people.known), "Readers With a Cookie", "") +
    kpi(fmtCount(people.returning), "Known Before This Window", "") +
    kpi(fmtCount(people.new), "First Seen in This Window", "") +
    kpi(fmtCount(people.repeat), "Read on More Than One Day", "") +
    kpi(people.days_median === null || people.days_median === undefined
      ? MISSING : String(people.days_median), "Days Read (Median)", "") +
    "</div>" +
    (people.known
      ? ""
      : '<p class="table-empty">No reader in this window is carrying a cookie yet, so ' +
        "none can be told apart from one day to the next. Every other figure on this " +
        "page covers the whole readership and is unaffected.</p>");
}

/* ISO country code -> "Japan". Built into the browser, so no country table
   ships with the page; the bare code stands in where it is unavailable. */
var REGION_NAMES = (function () {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" });
  } catch (e) {
    return null;
  }
})();

function countryName(code) {
  if (!code) return MISSING;
  try {
    return (REGION_NAMES && REGION_NAMES.of(code)) || code;
  } catch (e) {
    return code;
  }
}

function trafficTable(rows, label, opts) {
  opts = opts || {};
  if (!rows || !rows.length) {
    return '<p class="table-empty">' + escapeHtml(opts.empty || "Nothing recorded.") + "</p>";
  }
  var body = rows.map(function (r) {
    // A referring host or network name is text someone else chose: shown as
    // text, and only our own paths are ever turned into links.
    var name = opts.link
      ? '<a href="' + escapeHtml(r.key) + '" target="_blank" rel="noopener">' +
        escapeHtml(r.key) + "</a>"
      : escapeHtml(opts.label ? opts.label(r.key) : r.key);
    if (r.hosting) {
      name += ' <span class="badge badge-neutral" title="A cloud, hosting or CDN ' +
        'network: its visits are never counted as people">Data Centre</span>';
    }
    return "<tr><td" + (opts.plain ? "" : ' class="mono"') + ">" + name + "</td>" +
      '<td class="num">' + fmtCount(r.views) + "</td>" +
      '<td class="num">' + fmtCount(r.visitors) + "</td>" +
      (opts.browser
        ? '<td class="num">' + fmtCount(r.browser_visits) + "</td>"
        : "") +
      (opts.people
        ? '<td class="num">' + fmtCount(r.people) + "</td>"
        : "") +
      (opts.dwell
        ? '<td class="num"' +
          (r.dwell_samples
            ? ' title="' + fmtCount(r.dwell_samples) + ' reading' +
              (r.dwell_samples === 1 ? "" : "s") + ' measured"'
            : ' title="No reading time was reported for this page"') + ">" +
          fmtDuration(r.dwell_median) + "</td>"
        : "") + "</tr>";
  }).join("");
  return '<div class="table-wrap"><table class="data">' +
    "<thead><tr><th>" + escapeHtml(label) + '</th><th class="num">' +
    escapeHtml(opts.viewsLabel || "Page Views") + '</th>' +
    '<th class="num">Visits</th>' +
    (opts.browser ? '<th class="num">Browser Visits</th>' : "") +
    (opts.people ? '<th class="num">People</th>' : "") +
    (opts.dwell ? '<th class="num">Median Time on Page</th>' : "") +
    "</tr></thead><tbody>" + body + "</tbody></table></div>";
}

/* Referring sites and direct arrivals in one table, so the sources account for
   every page read. Without the direct row an empty table reads as broken
   detection rather than "nobody followed a link". */
function trafficArrivals(d) {
  var rows = (d.top_referrers || []).map(function (r) {
    return { key: r.key, views: r.views, visitors: r.visitors, people: r.people,
             ai: r.ai, direct: false };
  });
  var direct = d.direct || { views: 0, visitors: 0 };
  if (direct.views) {
    rows.push({ key: "Direct — no referring link", views: direct.views,
                visitors: direct.visitors, people: direct.people, direct: true });
  }
  if (!rows.length) {
    return '<p class="table-empty">No page reads in this window.</p>';
  }
  rows.sort(function (a, b) { return b.views - a.views; });
  var total = rows.reduce(function (n, r) { return n + r.views; }, 0);
  var body = rows.map(function (r) {
    var share = total ? Math.round((r.views / total) * 100) : 0;
    var name = r.direct
      ? "<td><strong>" + escapeHtml(r.key) + "</strong></td>"
      : '<td class="mono">' + escapeHtml(r.key) +
        (r.ai ? ' <span class="badge badge-ok" title="A reader who followed a ' +
          'citation out of an assistant\u2019s answer">AI Answer</span>' : "") + "</td>";
    return "<tr>" + name +
      '<td class="num">' + fmtCount(r.views) + "</td>" +
      '<td class="num">' + share + "%</td>" +
      '<td class="num">' + fmtCount(r.visitors) + "</td>" +
      '<td class="num">' + fmtCount(r.people) + "</td></tr>";
  }).join("");
  return '<div class="table-wrap"><table class="data">' +
    '<thead><tr><th>Source</th><th class="num">Page Views</th>' +
    '<th class="num">Share</th><th class="num">Visits</th>' +
    '<th class="num">People</th></tr></thead><tbody>' +
    body + "</tbody></table></div>";
}

/* A direct arrival carries no referrer by definition, so the network it came
   from and the page it opened are the only things that can stand in for one. */
function trafficDirect(d) {
  if (!d.direct || !d.direct.views) return "";
  return '<div class="admin-section">Direct Arrivals by Network ' +
    '<span class="note">the closest thing to a source a direct arrival has' +
    "</span></div>" +
    trafficTable(d.direct_networks, "Network",
      { plain: true, people: true,
        empty: "No direct arrival could be attributed to a network." }) +
    '<div class="admin-section">Pages Opened Directly ' +
    '<span class="note">opened with no referring link, so typed, bookmarked or ' +
    "followed from a mail or messaging app</span></div>" +
    trafficTable(d.direct_pages, "Page",
      { link: true, empty: "No page recorded for direct arrivals." });
}

/* Country and network operator. Both are derived from the address while the
   request is in flight; neither is stored, and neither is more than an
   indication — see the caveats under "Show calculation". */
function trafficPlaces(d) {
  var geo = d.geoip || {};
  if (!geo.loaded) {
    return '<div class="admin-section">Requests by Country</div>' +
      '<p class="table-empty">Location tables are not loaded' +
      (geo.error ? ", so nothing can be placed yet. The server reported: " +
        escapeHtml(geo.error) : " yet. They are fetched once a month and read in " +
        "the background after the site comes up, so this fills in a few seconds " +
        "after a restart.") + "</p>";
  }

  var placed = (d.located_hits || 0) + (d.unlocated_hits || 0);
  var share = placed ? Math.round((d.located_hits / placed) * 100) : 0;
  var coverage = fmtCount(d.located_hits) + " of " + fmtCount(placed) +
    " counted requests placed (" + share + "%)";

  return '<div class="admin-section">Requests by Country ' +
    '<span class="note">' + escapeHtml(coverage) + "</span></div>" +
    trafficTable(d.top_countries, "Country",
      { plain: true, label: countryName, viewsLabel: "Requests", browser: true,
        people: true, empty: "No request in this window could be placed." }) +
    '<div class="admin-section">Requests by Network Operator ' +
    '<span class="note">the network a request came from, which is not the same ' +
    "as who the reader works for</span></div>" +
    trafficTable(d.top_networks, "Network",
      { plain: true, viewsLabel: "Requests", browser: true, people: true,
        empty: "No request in this window could be attributed to a network." }) +
    '<p class="source-line">Location and network from ' +
    '<a href="https://db-ip.com" target="_blank" rel="noopener">IP Geolocation by ' +
    "DB-IP</a>, " + escapeHtml(geo.edition || "") + " edition, " +
    fmtCount(geo.ranges) + " address ranges.</p>";
}

function trafficCalc(d) {
  return '<details class="calc"><summary>Show calculation</summary><div class="calc-body">' +
    "<p>A <strong>visitor</strong> is one address-and-browser combination on one UTC day, " +
    "identified by a salted one-way hash. The salt stays on the data volume, so a day’s " +
    "visitors can be counted without being identified and cannot be matched across days.</p>" +
    "<p>Because that identifier deliberately changes every day, a <strong>visit</strong> is " +
    "one visitor on one day, and the figure for a window is the sum of its days — not a " +
    "count of people. Someone who reads on ten days is ten visits.</p>" +
    "<p>A reader who accepts the banner is counted differently: they are given a cookie " +
    "holding a random number and the day it was issued, and their events are keyed on a " +
    "hash of it instead of on the daily one. That is what makes <strong>returning " +
    "readers</strong> answerable, and it is the only thing the cookie is for — it holds " +
    "nothing about the reader, and no address is stored for them either. " +
    "<strong>Known before this window</strong> counts readers whose cookie was issued " +
    "before the window opened; <strong>first seen in this window</strong> accepted inside " +
    "it. Clearing cookies makes a reader new again, and a reader who declines, or who " +
    "never answers, is counted only by the daily identity.</p>" +
    "<p><strong>Reading now</strong> is counted in the server's memory, not from the log: " +
    "visitors who have asked for something in the last five minutes. An open page reports " +
    "itself once a minute so that a reader sitting on one page does not vanish, which " +
    "means anything without scripts — a terminal, a blocked browser — drops out of this " +
    "figure after five quiet minutes while still being counted everywhere else. Nothing " +
    "about it is stored, so it cannot be asked about yesterday and a restart empties it.</p>" +
    "<p><strong>Time on page</strong> is reported by the page itself when it is closed or " +
    "hidden: the seconds it was actually visible, so a tab in the background does not " +
    "accrue time. Anything over an hour is recorded as an hour — that page was left open, " +
    "not read. A page closed within a second of opening, or opened without scripts, " +
    "reports nothing and is not in the median. <strong>Visit length</strong> is separate " +
    "and needs no script: the span of one visitor's requests, ended by half an hour of " +
    "silence, counting page reads and the chart data those pages fetched. A visit of one " +
    "page has no span to measure, so it is reported as <strong>left after one page</strong> " +
    "rather than averaged in as a very short visit.</p>" +
    "<p>A <strong>page view</strong> is a successful page request. Styles, scripts, images, " +
    "the admin console itself and the internal cache warm-up are not counted; a page request " +
    "that returned an error is recorded but is not counted as a page view. " +
    "<strong>API requests</strong> covers both the public API and connector traffic — of " +
    "them, " + fmtCount(d.api_in_page) + " were this site's own pages fetching the data " +
    "for a chart and " + fmtCount(d.api_external) + " came from outside it. Only the " +
    "second is somebody using the API. Requests recorded before this split existed are " +
    "in neither figure.</p>" +
    "<p>A <strong>source</strong> is the site that linked a reader here. Arrivals with no " +
    "referring link are counted as direct rather than dropped: a typed address, a bookmark, " +
    "and a link opened from a mail or messaging app all send nothing, and so do scripts. " +
    "A reader moving between our own pages is not a new arrival and is not counted again.</p>" +
    "<p><strong>Browser visits</strong> counts visits that also asked for the styles, " +
    "images and scripts a page needs before it can be shown. A browser displaying the " +
    "page to somebody has to fetch them; a script taking the text and leaving does not. " +
    "It is much better evidence than the browser name, which anything can copy.</p>" +
    "<p>It still is not proof that a person read anything. A scraper can drive a real " +
    "browser, and a page can be opened in a tab nobody looks at. Knowing whether someone " +
    "actually read a page would take a script running in the browser watching them, which " +
    "this product deliberately does not do. Counted once per visitor per day, and the " +
    "asset requests themselves are never counted as traffic or stored.</p>" +
    "<p><strong>People</strong> is the strict figure, and the one to quote: a visit that " +
    "passes three tests at once. Its page reported a reading time, which only the script " +
    "in the page can send, so a real browser rendered it. Its address was placed on a " +
    "network. And that network is not a cloud, host or CDN — Amazon, Google, Microsoft, " +
    "DigitalOcean, OVH, Hetzner, Tencent, Cloudflare and the like, marked " +
    "<span class=\"badge badge-neutral\">Data Centre</span> in the network table. Each " +
    "test alone is weak; a scraper rarely passes all three. It is deliberately an " +
    "undercount: a reader on a phone using iCloud Private Relay leaves through Cloudflare " +
    "or Akamai and is not counted, and a page closed within a second reports no time. " +
    "The three parts are shown beside the figure so a zero can be read — no reading " +
    "times, nothing placed, or everything from a data centre.</p>" +
    "<p><strong>AI assistants</strong> are counted inside automated hits, never as " +
    "readers, but are listed separately because the three things they do are not the " +
    "same fact. <em>Taking the text to train on</em> means no person was at the other " +
    "end. <em>Building an index</em> means one may arrive later. <em>Someone asked " +
    "about this page</em> means a person was asking that assistant about it at that " +
    "moment — they read the answer, not the page, so it is still not a visit. " +
    "Each is identified by the name the fetcher sends, which anything can copy, and " +
    "one that sends no name is counted as an ordinary crawler. The figure beside the " +
    "table is a different thing and is a person: page reads whose referrer was an " +
    "assistant, meaning a reader followed a citation here out of an answer.</p>" +
    "<p><strong>Automated hits</strong> — crawlers, uptime monitors, the platform " +
    "healthcheck and anything sending no browser identification — are counted separately " +
    "and excluded from every other figure here.</p>" +
    "<p>These are estimates, not exact headcounts. A whole office behind one address on the " +
    "same browser version counts as one visitor, while one person reading on a laptop and a " +
    "phone counts as two.</p>" +
    "<p><strong>Country and network</strong> are looked up from the address while the request " +
    "is being handled, and only the result is kept — the address is still never written down. " +
    "Read the network as an indication, never as proof: a corporate VPN, a home connection " +
    "and a phone all resolve to whoever runs that network, so a reader at a bank shows as the " +
    "bank only when they browse from its own network. Cloud and CDN addresses resolve to the " +
    "provider, and to wherever that address is registered rather than where the reader sat — " +
    "which is why a Cloudflare address can read as Australia.</p>" +
    '<p class="muted">Visit log: ' + escapeHtml(String(d.log_files)) + " file" +
    (d.log_files === 1 ? "" : "s") + ", " + escapeHtml(fmtBytes(d.log_bytes)) +
    " on the data volume · " + escapeHtml(fmtCount(d.lines_read)) + " records read" +
    (d.counting_since ? " · counting since " + escapeHtml(fmtDay(d.counting_since)) : "") +
    (d.unreadable_lines
      ? " · " + escapeHtml(fmtCount(d.unreadable_lines)) + " unreadable records skipped" : "") +
    (d.truncated ? " · capped at the most recent records" : "") + "</p></div></details>";
}

function trafficChartCfg(d) {
  // With only a day or two recorded, every reading is an isolated point: a
  // line between neighbours that do not exist draws nothing at all.
  var known = d.daily.filter(function (r) { return r.visitors !== null; }).length;
  return {
    series: [
      { name: "Visitors", slot: 1,
        points: d.daily.map(function (r) { return [r.date, r.visitors]; }) },
      { name: "Page Views", slot: 2,
        points: d.daily.map(function (r) { return [r.date, r.pageviews]; }) },
      { name: "People", slot: 3,
        points: d.daily.map(function (r) { return [r.date, r.people]; }) },
    ],
    dp: 0,
    yAxisDp: 0,
    yAxisMinInterval: 1,  // requests are whole things; no half-visitor gridlines
    showPoints: known <= 14,
    yAxisName: "Per Day",
    isoPeriods: true,
    trust: "derived",
    sourceLine: "Plover Analytics — counted by the server from its own request log, " +
      d.from + " to " + d.to + ". Not an official statistic.",
  };
}

function wireTraffic(target, d, days) {
  document.getElementById("traffic-refresh").addEventListener("click", function () {
    viewTraffic(target, days);
  });
  refreshLive(target);
  if (liveTimer) window.clearInterval(liveTimer);
  liveTimer = window.setInterval(function () {
    // The console can be left open for a day; polling a page nobody is looking
    // at would add the watcher to the count it is watching.
    if (document.visibilityState !== "hidden") refreshLive(target);
  }, LIVE_REFRESH_MS);
  var seg = document.getElementById("traffic-seg");
  var btns = seg ? seg.querySelectorAll("button") : [];
  for (var i = 0; i < btns.length; i++) {
    btns[i].addEventListener("click", function () {
      location.hash = "#traffic/" + this.getAttribute("data-days");
    });
  }

  var box = document.getElementById("traffic-chart");
  if (!box) return;
  if (trafficChart) {
    trafficChart.dispose();
    trafficChart = null;
  }
  trafficChart = obsChart(box, "line", trafficChartCfg(d));
  var stem = "observatory-traffic-" + d.from + "-to-" + d.to;
  document.getElementById("traffic-png").addEventListener("click", function () {
    trafficChart.exportPNG(stem + ".png");
  });
  document.getElementById("traffic-csv").addEventListener("click", function () {
    trafficChart.exportCSV(stem + ".csv", [
      "Plover Analytics — internal traffic",
      "Counted by the server from its own request log. Not an official statistic.",
      "Window: " + d.from + " to " + d.to,
      "Visitors = distinct address-and-browser hashes on that UTC day",
      "The hash rotates daily by design, so days cannot be summed into people",
      "People = visitors whose page reported a reading time (a script ran in a browser),",
      "placed on a network that is not a cloud, host or CDN; the strict reading, so an",
      "undercount: readers behind iCloud Private Relay leave through a CDN and are excluded",
      "Page views = successful page requests; assets and the admin console excluded",
      "Automated hits (crawlers, monitors, healthchecks) excluded from both series",
      "An empty cell is a day before counting began, which is not the same as zero",
      "Time on page is reported by the page when hidden or closed; visit length is the",
      "span of one visitor's requests, ended by 30 minutes of silence",
      "Returning readers are those carrying an accepted cookie; the rest cannot be",
      "followed across days by design",
      "Country and network: IP Geolocation by DB-IP (https://db-ip.com), CC BY 4.0",
    ]);
  });
}

/* ---------- audit log ---------- */

function viewAudit(target) {
  target.innerHTML = '<div class="admin-loading">Loading the audit log…</div>';
  api("/audit?limit=200").then(function (data) {
    var entries = data.entries;
    var rows = entries.map(function (e) {
      return "<tr>" +
        '<td class="num">' + fmtStamp(e.at) + "</td>" +
        "<td>" + badge(AUDIT_ACTIONS, e.action) + "</td>" +
        "<td>" + escapeHtml(e.detail || "") + "</td>" +
        '<td class="mono">' + escapeHtml(e.ip || MISSING) + "</td></tr>";
    }).join("");
    target.innerHTML =
      '<div class="admin-page-head"><h1>Audit Log</h1>' +
      '<p class="admin-page-sub">Every sign-in and administrative action, newest first. The log ' +
      "is an append-only file on the data volume; nothing here can be edited from this " +
      "console.</p></div>" +
      (entries.length
        ? '<div class="table-wrap"><table class="data" data-no-enhance>' +
          '<thead><tr><th class="num">When (UTC)</th><th>Action</th><th>Detail</th>' +
          "<th>Address</th></tr></thead><tbody>" + rows + "</tbody></table></div>" +
          (entries.length === 200
            ? '<p class="table-empty">Showing the most recent 200 entries.</p>' : "")
        : '<p class="table-empty">No admin activity recorded yet.</p>');
  }).catch(function (err) {
    target.innerHTML = loadFailed("the audit log", err);
  });
}

/* ---------- boot ---------- */

window.addEventListener("hashchange", function () {
  if (document.getElementById("admin-view")) route();
});

initThemeToggle();
api("/session").then(function (s) {
  if (!s.enabled) renderDisabled();
  else if (!s.authenticated) renderLogin("");
  else { renderShell(); route(); }
}).catch(function () {
  renderLogin("");
});
