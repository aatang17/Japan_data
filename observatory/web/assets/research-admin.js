/* Admin console: the PloverResearch article list. Opening an article goes to
   the editor (desk.html), which has a screen of its own. */
"use strict";

var ARTICLE_STATUS = {
  draft: { label: "Draft", cls: "badge-neutral" },
  published: { label: "Published", cls: "badge-ok" },
  withdrawn: { label: "Withdrawn", cls: "badge-warn" },
};

function articleStatus(a) {
  var html = badge(ARTICLE_STATUS, a.status);
  if (a.status === "published") {
    html += ' <span class="badge badge-neutral">Version ' + a.published_version + "</span>";
    if (a.unpublished_changes) html += ' <span class="badge badge-info">Unpublished Changes</span>';
  }
  return html;
}

function backupLine(b) {
  if (!b || !b.last_run) {
    return "Backups: none yet. The first runs ten minutes after the server starts, then daily.";
  }
  var when = fmtStamp(b.last_run) + " UTC";
  if (!b.ok) return "Backups: the last attempt (" + when + ") failed. " + (b.error || "");
  var off = b.offsite && b.offsite.configured
    ? "copied to the object store"
    : "kept on the server only; the object store is not configured";
  return "Backups: last run " + when + ", " + off + ".";
}

/* Delete is one click with a few seconds to undo it, not a confirm step: the
   row goes at once and the draft is deleted on the server when the Undo bar
   times out, or straight away if the page is left before then. */
var UNDO_MS = 8000;
var HANDOFF_KEY = "plover-delete-draft";
var PENDING = null;   // {id, title, timer}

function $title(tr) {
  var a = tr && tr.querySelector(".art-title");
  return a ? a.textContent : "Untitled";
}

function rowOf(target, id) { return target.querySelector('tr[data-open="' + id + '"]'); }

function setCount(target) {
  var n = target.querySelectorAll("tr[data-open]:not([hidden])").length;
  var c = target.querySelector(".admin-section .note");
  if (c) c.textContent = n;
}

function sendDelete(p, keepalive) {
  return api("/research/articles/" + p.id, keepalive ? { method: "DELETE", keepalive: true } : { method: "DELETE" });
}

function deleteLater(target, id, title) {
  if (PENDING) finishDelete(target);
  var tr = rowOf(target, id);
  if (tr) tr.hidden = true;
  setCount(target);
  PENDING = { id: id, title: title || "Untitled" };
  PENDING.timer = setTimeout(function () { finishDelete(target); }, UNDO_MS);
  showUndo(target);
}

function showUndo(target) {
  var box = target.querySelector("#art-alert");
  if (!box || !PENDING) return;
  box.innerHTML = '<div class="undo-bar" role="status">Deleted “' + escapeHtml(PENDING.title) + '”. ' +
    '<button type="button" class="btn" id="art-undo">Undo</button></div>';
  box.querySelector("#art-undo").addEventListener("click", function () {
    var p = PENDING;
    if (!p) return;
    clearTimeout(p.timer);
    PENDING = null;
    var tr = rowOf(target, p.id);
    if (tr) tr.hidden = false;
    setCount(target);
    box.innerHTML = "";
  });
}

function finishDelete(target) {
  var p = PENDING;
  if (!p) return;
  clearTimeout(p.timer);
  PENDING = null;
  var box = target.querySelector("#art-alert");
  sendDelete(p).then(function () {
    var tr = rowOf(target, p.id);
    if (tr) tr.parentNode.removeChild(tr);
    if (box && box.querySelector(".undo-bar")) box.innerHTML = "";
  }).catch(function (err) {
    var tr = rowOf(target, p.id);
    if (tr) tr.hidden = false;
    setCount(target);
    if (box) box.innerHTML = '<div class="login-alert" role="alert">Could not delete “' + escapeHtml(p.title) +
      "”: " + escapeHtml(err.message) + "</div>";
  });
}

// leaving the page ends the undo window: the delete still goes through
window.addEventListener("pagehide", function () {
  var p = PENDING;
  if (!p) return;
  clearTimeout(p.timer);
  PENDING = null;
  sendDelete(p, true).catch(function () {});
});

function viewArticles(target) {
  target.innerHTML = '<div class="admin-loading">Loading articles…</div>';
  api("/research/articles").then(function (data) {
    var rows = data.articles.map(function (a) {
      var addr = a.slug ? "/research/" + a.slug : MISSING;
      return '<tr class="clickable" data-open="' + a.id + '">' +
        '<td class="art-title"><a href="desk.html?id=' + a.id + '">' + escapeHtml(a.title || "Untitled") + "</a></td>" +
        "<td>" + articleStatus(a) + "</td>" +
        '<td class="num">' + fmtStamp(a.updated_at) + "</td>" +
        "<td>" + escapeHtml(a.updated_by || MISSING) + "</td>" +
        '<td class="mono">' + (a.status === "published"
          ? '<a href="' + escapeHtml(addr) + '" target="_blank" rel="noopener">' + escapeHtml(addr) + "</a>"
          : escapeHtml(addr)) + "</td>" +
        '<td class="art-acts"><a class="btn" href="desk.html?id=' + a.id + '">Edit</a>' +
        // the server refuses to delete anything ever published: withdraw it in the editor
        (a.published_version ? "" :
          '<button type="button" class="btn btn-danger" data-del="' + a.id + '">Delete</button>') +
        "</td></tr>";
    }).join("");
    var b = data.backup || {};
    target.innerHTML =
      '<div class="admin-page-head"><h1>Articles</h1><span class="spacer"></span>' +
      '<button type="button" class="btn" id="art-import">Import Markdown</button>' +
      '<button type="button" class="btn btn-primary" id="art-new">New Article</button>' +
      '<input type="file" id="art-file" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden>' +
      '<p class="admin-page-sub">PloverResearch notes. Drafts are visible only here; publishing ' +
      "puts a version on the site at /research.</p></div>" +
      '<div id="art-alert"></div>' +
      '<div class="admin-section">All Articles <span class="note">' + data.articles.length + "</span></div>" +
      (data.articles.length
        ? '<div class="table-wrap"><table class="data art-table" data-no-enhance><thead><tr>' +
          '<th>Title</th><th>Status</th><th class="num">Last Edited (UTC)</th><th>By</th>' +
          "<th>Address</th><th aria-label=\"Actions\"></th></tr></thead><tbody>" + rows + "</tbody></table></div>"
        : '<p class="table-empty">No articles yet. Start one, or import a Markdown draft.</p>') +
      '<p class="backup-line' + (b.last_run && !b.ok ? " bad" : "") + '">' +
      escapeHtml(backupLine(b)) +
      ' <button type="button" class="linkish" id="art-backup">Back Up Now</button></p>';

    var alertBox = document.getElementById("art-alert");
    function fail(err) {
      alertBox.innerHTML = '<div class="login-alert" role="alert">' + escapeHtml(err.message) + "</div>";
    }
    document.getElementById("art-new").addEventListener("click", function () {
      post("/research/articles").then(function (a) {
        location.href = "desk.html?id=" + a.id;
      }).catch(fail);
    });
    var file = document.getElementById("art-file");
    document.getElementById("art-import").addEventListener("click", function () { file.click(); });
    file.addEventListener("change", function () {
      var f = file.files[0];
      if (!f) return;
      f.text().then(function (text) {
        return post("/research/import", { markdown: text });
      }).then(function (a) {
        location.href = "desk.html?id=" + a.id;
      }).catch(fail);
    });
    document.getElementById("art-backup").addEventListener("click", function (e) {
      e.target.disabled = true;
      e.target.textContent = "Backing up…";
      post("/research/backup").then(function () { viewArticles(target); }).catch(fail);
    });
    var dels = target.querySelectorAll("button[data-del]");
    for (var d = 0; d < dels.length; d++) {
      dels[d].addEventListener("click", function () {
        var tr = this.closest("tr");
        deleteLater(target, Number(this.getAttribute("data-del")), $title(tr));
      });
    }
    // the editor's Delete Draft comes back here to offer the same Undo
    var handed = null;
    try { handed = JSON.parse(sessionStorage.getItem(HANDOFF_KEY) || "null"); sessionStorage.removeItem(HANDOFF_KEY); }
    catch (e) { handed = null; }
    if (handed && handed.id) deleteLater(target, handed.id, handed.title);
    else if (PENDING) {
      var tr = rowOf(target, PENDING.id);
      if (tr) tr.hidden = true;
      setCount(target);
      showUndo(target);
    }
    var trs = target.querySelectorAll("tr[data-open]");
    for (var i = 0; i < trs.length; i++) {
      trs[i].addEventListener("click", function (e) {
        if (e.target.closest("a, button")) return;
        location.href = "desk.html?id=" + this.getAttribute("data-open");
      });
    }
  }).catch(function (err) {
    target.innerHTML = loadFailed("the articles", err);
  });
}
