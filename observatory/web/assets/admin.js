/* Admin console: ingest health, vintage browser, audit log.

   Structure follows the GSA-platform admin (persistent sidebar driven by one
   nav description, KPI summary cards, outline-only status badges, rows that
   expand into detail) rendered with Observatory tokens and helpers. All data
   comes from /admin/api/*, which requires a signed-in session; the page shell
   itself holds no numbers.

   Statuses are never shown raw — every enum goes through a label map. */
"use strict";

var ROOT = document.getElementById("admin-root");

var ADMIN_NAV = [
  { group: "Operations", pages: [
    { id: "health", label: "Ingest Health", hash: "#health" },
    { id: "vintages", label: "Vintage Browser", hash: "#vintages" },
  ]},
  { group: "Curation", pages: [
    { id: "queue", label: "Curation Queue", hash: "#queue" },
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
  party_exported: { label: "Curation Exported", cls: "badge-neutral" },
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
    '<a class="btn" href="index.html">Back to the Observatory</a>' +
    "</div></div>";
}

function renderLogin(message) {
  ROOT.innerHTML =
    '<div class="admin-login-wrap"><div class="admin-login-card">' +
    "<h1>Admin Console</h1>" +
    '<p class="sub">Japan Data Observatory — internal operations. Sign in to continue.</p>' +
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
    '<div class="admin-side-head"><span class="brand">Japan Data Observatory ' +
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

  initThemeToggle();
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
  if (view === "vintages") viewVintages(target, arg);
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
      kpi(String(vintages), "Vintages Stored", "");

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
      "period / the limit before it counts as stale · click a row for its vintages</span></div>" +
      '<div class="table-wrap"><table class="data" data-no-enhance>' +
      "<thead><tr><th>Dataset</th><th>Status</th>" +
      '<th class="num">Data Through</th><th class="num">Age, Days</th>' +
      '<th class="num">Last Published (UTC)</th><th class="num">Active Series</th>' +
      '<th class="num">Vintages</th><th>Source File</th></tr></thead>' +
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

/* ---------- vintage browser ---------- */

function viewVintages(target, slug) {
  target.innerHTML = '<div class="admin-loading">Loading vintages…</div>';
  api("/overview").then(function (report) {
    var ds = report.datasets;
    if (!slug || !ds.some(function (d) { return d.dataset === slug; })) {
      slug = ds[0].dataset;
    }
    var cards = ds.map(function (d) {
      return '<button type="button" class="ds-card" data-ds="' + escapeHtml(d.dataset) + '"' +
        (d.dataset === slug ? ' aria-pressed="true"' : ' aria-pressed="false"') + ">" +
        '<div class="t">' + escapeHtml(d.dataset) + "</div>" +
        '<div class="s">' + (d.vintages || 0) + " vintage" + (d.vintages === 1 ? "" : "s") +
        " · through " + (d.latest_period ? escapeHtml(d.latest_period) : MISSING) + "</div></button>";
    }).join("");

    target.innerHTML =
      '<div class="admin-page-head"><h1>Vintage Browser</h1>' +
      '<p class="admin-page-sub">Every accepted ingest is a stored release. A stored release is ' +
      "never edited — a correction arrives as a new vintage, and this page shows exactly what " +
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

  // The first vintage of a dataset is its entire history as first recorded —
  // tens of thousands of "new" values with nothing to compare against.
  if (tr.getAttribute("data-first") === "1") {
    cell.innerHTML = '<div class="detail-block"><div class="h">Initial Vintage</div>' +
      "This release is the dataset’s first recorded vintage: all " +
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
