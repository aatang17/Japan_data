/* Research Desk: article tabs.

   A row of tabs under the top bar, one per article the writer has open, so
   they can work on several at once — start the AI drafting one, write
   another, check a third — without going back to the article list. "+ Open
   Article" at the right starts a new article or opens an existing one.

   Switching saves the draft first, then opens the other article in this
   window (each tab is a link, so Cmd/Ctrl-click opens it in a browser tab
   instead). The list of open tabs is kept in this browser and follows the
   writer across browser tabs. A tab whose AI run is still working says so,
   and says when it has finished.

   Loaded before desk.js; uses its helpers ($, S, api, send, saveNow …) only
   inside functions, which run after both files have loaded. */
"use strict";

var AT = { key: "dk-article-tabs", tabs: [], known: null, menuOpen: false, ai: {}, poll: null, MAX: 12 };

function atLoad() {
  try {
    var v = JSON.parse(localStorage.getItem(AT.key) || "[]");
    return Array.isArray(v) ? v.filter(function (t) { return t && typeof t.id === "number" && t.id > 0; }) : [];
  } catch (e) { return []; }
}

function atSave() {
  try { localStorage.setItem(AT.key, JSON.stringify(AT.tabs.slice(0, AT.MAX))); } catch (e) { /* not remembered */ }
}

function atTitle(t) { return (t || "").replace(/\s+/g, " ").trim() || "Untitled"; }

/* The tab of the article on screen is always there. */
function atEnsureCurrent() {
  var title = atTitle($("#dk-title") ? $("#dk-title").value : S.article.draft.title);
  var cur = AT.tabs.filter(function (t) { return t.id === ID; })[0];
  if (cur) cur.title = title;
  else AT.tabs.push({ id: ID, title: title });
  if (AT.tabs.length > AT.MAX) {
    // the oldest other tab makes room
    var drop = AT.tabs.filter(function (t) { return t.id !== ID; })[0];
    AT.tabs = AT.tabs.filter(function (t) { return t !== drop; });
  }
}

function initArticleTabs() {
  AT.tabs = atLoad();
  atEnsureCurrent();
  atSave();
  drawArticleTabs();
  var title = $("#dk-title");
  var timer = null;
  title.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { AT.tabs = atLoad(); atEnsureCurrent(); atSave(); drawArticleTabs(); }, 400);
  });
  // another browser tab opened or closed an article
  window.addEventListener("storage", function (e) {
    if (e.key !== AT.key) return;
    AT.tabs = atLoad();
    atEnsureCurrent();
    drawArticleTabs();
  });
  document.addEventListener("mousedown", function (e) {
    if (AT.menuOpen && !e.target.closest(".dk-at-menu") && !e.target.closest(".dk-at-plus")) atMenu(false);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && AT.menuOpen) atMenu(false); });
  // titles change and articles get deleted elsewhere: refresh both once
  atFetchList().then(function () {
    AT.tabs = AT.tabs.filter(function (t) { return t.id === ID || AT.known[t.id]; });
    AT.tabs.forEach(function (t) { if (t.id !== ID) t.title = atTitle(AT.known[t.id].title); });
    atSave();
    drawArticleTabs();
  }).catch(function () { /* the tabs still work from what this browser remembers */ });
  atWatchAI();
}

function atFetchList() {
  return api("/research/articles").then(function (r) {
    AT.known = {};
    AT.list = r.articles.slice().sort(function (a, b) { return (b.updated_at || "").localeCompare(a.updated_at || ""); });
    AT.list.forEach(function (a) { AT.known[a.id] = a; });
    return AT.list;
  });
}

/* The row of tabs is redrawn as tabs change; the + button and its menu are
   built once, so a redraw never wipes what the writer is typing in it. */
function drawArticleTabs() {
  var box = $("#dk-atabs");
  if (!box) return;
  if (!$(".dk-at-row", box)) {
    box.innerHTML = '<div class="dk-at-row" role="tablist" aria-label="Open articles"></div>' +
      '<div class="dk-at-plusbox"><button type="button" class="dk-at-plus" aria-haspopup="dialog" aria-expanded="false" ' +
      'title="Start a new article or open another one">+ Open Article</button>' +
      '<div class="dk-at-menu" role="dialog" aria-label="Open an article" hidden></div></div>';
    $(".dk-at-plus", box).addEventListener("click", function () { atMenu(!AT.menuOpen); });
  }
  var row = $(".dk-at-row", box);
  row.innerHTML = AT.tabs.map(function (t) {
      var on = t.id === ID;
      var ai = AT.ai[t.id];
      return '<div class="dk-at' + (on ? " on" : "") + '">' +
        '<a class="dk-at-b" role="tab" aria-selected="' + on + '" href="desk.html?id=' + t.id + '" data-at="' + t.id +
        '" title="' + escapeHtml(t.title) + '"><span class="dk-at-t">' + escapeHtml(t.title) + "</span>" +
        (ai === "running" ? '<span class="dk-at-ai">AI working</span>' : ai === "done" ? '<span class="dk-at-ai done">AI done</span>' : "") +
        "</a>" +
        '<button type="button" class="dk-at-x" data-atx="' + t.id + '" aria-label="Close ' + escapeHtml(t.title) +
        '" title="Close this tab (the article is kept)">×</button></div>';
  }).join("");
  $all("[data-at]", row).forEach(function (a) {
    a.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;   // a browser tab of its own
      e.preventDefault();
      atSwitch(Number(a.getAttribute("data-at")));
    });
  });
  $all("[data-atx]", row).forEach(function (b) {
    b.addEventListener("click", function () { atClose(Number(b.getAttribute("data-atx"))); });
  });
}

/* Leave this article for another, its last changes saved first. */
function atSwitch(id, then) {
  if (id === ID) { if (then) then(); return; }
  setStatus("saving");
  saveNow().then(function () {
    if (S.seq !== S.savedSeq) {
      toast("Your latest changes are not saved yet, so this article stays open. Try again in a moment.");
      return;
    }
    location.href = "desk.html?id=" + id;
  });
}

function atClose(id) {
  var i = AT.tabs.map(function (t) { return t.id; }).indexOf(id);
  if (i < 0) return;
  AT.tabs.splice(i, 1);
  atSave();
  if (id !== ID) { drawArticleTabs(); return; }
  // closing the article on screen opens its neighbour, or the article list
  var next = AT.tabs[i] || AT.tabs[i - 1];
  saveNow().then(function () {
    if (S.seq !== S.savedSeq) {
      AT.tabs.splice(i, 0, { id: ID, title: atTitle($("#dk-title").value) });
      atSave();
      drawArticleTabs();
      toast("Your latest changes are not saved yet, so the tab stays open. Try again in a moment.");
      return;
    }
    var go = function () { location.href = next ? "desk.html?id=" + next.id : listUrl(); };
    // a new article closed before anything was written in it is not kept
    if (atEmpty() && !S.article.published_version) {
      api("/research/articles/" + ID, { method: "DELETE" }).then(go, go);
    } else go();
  });
}

function atEmpty() {
  var d = serialize();
  return !d.title && !d.dek && !d.summary && !(d.notes || []).length && !d.plan &&
    d.blocks.every(function (b) { return (b.type === "p" || b.type === "heading") && !textOf(b.html || b.text || "").trim(); });
}

function atMenu(open) {
  AT.menuOpen = open;
  var m = $(".dk-at-menu");
  var b = $(".dk-at-plus");
  if (!m) return;
  m.hidden = !open;
  b.setAttribute("aria-expanded", String(open));
  if (open) atDrawMenu();
}

function atDrawMenu() {
  var m = $(".dk-at-menu");
  m.innerHTML =
    '<button type="button" class="btn btn-primary dk-at-new">New Article</button>' +
    '<label class="dk-at-find"><span>Or open one</span>' +
    '<input type="search" class="dk-at-q" placeholder="Filter by title" aria-label="Filter your articles by title"></label>' +
    '<ul class="dk-at-list"><li class="muted">Loading your articles…</li></ul>';
  var q = $(".dk-at-q", m);
  var list = $(".dk-at-list", m);
  function fill() {
    var words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    var rows = (AT.list || []).filter(function (a) {
      var t = (a.title || "untitled").toLowerCase();
      return words.every(function (w) { return t.indexOf(w) !== -1; });
    });
    var open = {};
    AT.tabs.forEach(function (t) { open[t.id] = true; });
    list.innerHTML = rows.length ? rows.slice(0, 60).map(function (a) {
      return '<li><button type="button" data-atopen="' + a.id + '"><span class="dk-at-lt">' + escapeHtml(atTitle(a.title)) + "</span>" +
        '<span class="dk-at-lm">' + (open[a.id] ? "Open" : a.status === "published" ? "Published" : a.status === "withdrawn" ? "Withdrawn" : "Draft") +
        "</span></button></li>";
    }).join("") : '<li class="muted">' + (AT.list && AT.list.length ? "No article has that in its title." : "No articles yet.") + "</li>";
    $all("[data-atopen]", list).forEach(function (b) {
      b.addEventListener("click", function () {
        var id = Number(b.getAttribute("data-atopen"));
        var a = AT.known[id];
        if (!AT.tabs.some(function (t) { return t.id === id; })) AT.tabs.push({ id: id, title: atTitle(a && a.title) });
        atSave();
        atMenu(false);
        drawArticleTabs();
        atSwitch(id);
      });
    });
  }
  q.addEventListener("input", fill);
  q.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { var first = $("[data-atopen]", list); if (first) first.click(); }
  });
  $(".dk-at-new", m).addEventListener("click", function (e) {
    var btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Starting a new article…";
    var body = S.article && S.article.publication_id ? { publication_id: S.article.publication_id } : {};
    send("POST", "/research/articles", body).then(function (a) {
      AT.tabs.push({ id: a.id, title: "Untitled" });
      atSave();
      atMenu(false);
      atSwitch(a.id);
    }).catch(function (err) {
      btn.disabled = false;
      btn.textContent = "New Article";
      toast(err.message);
    });
  });
  (AT.list ? Promise.resolve() : atFetchList()).then(fill).catch(function (err) {
    list.innerHTML = '<li class="bad">Your articles could not be loaded: ' + escapeHtml(err.message) + "</li>";
  });
  q.focus();
}

/* An AI run started on another open article: say while it works, and when
   it is done, on that article's tab. */
function atWatchAI() {
  clearTimeout(AT.poll);
  var others = AT.tabs.filter(function (t) { return t.id !== ID && AT.ai[t.id] !== "done"; });
  var checks = others.map(function (t) {
    var job = null;
    try { job = localStorage.getItem("dk-ai-job-" + t.id); } catch (e) { job = null; }
    if (!job) return Promise.resolve();
    return api("/research/ai/jobs/" + job).then(function (j) {
      var was = AT.ai[t.id];
      if (j.status === "running") AT.ai[t.id] = "running";
      else if (was === "running") AT.ai[t.id] = "done";
    }).catch(function () { /* the run is gone (server restart): nothing to show */ });
  });
  Promise.all(checks).then(function () {
    drawArticleTabs();
    var any = Object.keys(AT.ai).some(function (k) { return AT.ai[k] === "running"; });
    if (any) AT.poll = setTimeout(atWatchAI, 10000);
  });
}
