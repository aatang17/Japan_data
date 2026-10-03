/* Research Desk, part three: Send to Plover — reading pages the writer
   subscribes to.

   The desk's page reader fetches from the server, with no login, so a paid
   article (FT, WSJ, Nikkei) comes back as its teaser. Send to Plover is a
   bookmark the writer drags to their bookmarks bar once. On an article they
   can read, clicking it runs ploverClip() in that page: it takes the
   article's text (or the passage selected), and opens /clip.html with the
   text in the address's #fragment, which no request carries to a server.
   clip.html saves it to the writer's sent pages (app/research_clips.py) and
   tells any open desk tab, which shows it in Research › Web Page.

   ploverClip runs on someone else's page, so it is self-contained: no
   helper from this file, nothing loaded from anywhere, no request of its
   own. It is turned into the bookmark by bookmarkletHref().

   Loaded before desk.js; uses its helpers ($, S, api, send, toast …) only
   inside functions. */
"use strict";

var CLIP_CHANNEL = "plover-clips";

/* Runs in the article's page. Keep it ES5 and free of outside names. */
function ploverClip(origin) {
  var d = document, out = [], seen = {}, n = 0, MAX = 60000, cut = false;
  function meta(k) {
    var m = d.querySelector('meta[property="' + k + '"],meta[name="' + k + '"],meta[itemprop="' + k + '"]');
    return m ? (m.getAttribute("content") || "").trim() : "";
  }
  function push(kind, t) {
    t = (t || "").replace(/\s+/g, " ").trim();
    if (!t || seen[t]) return;
    if (n + t.length > MAX) { cut = true; return; }
    seen[t] = 1; n += t.length; out.push({ kind: kind, text: t });
  }
  function ptext(el) {
    var s = 0, ps = el.querySelectorAll("p");
    for (var i = 0; i < ps.length; i++) s += (ps[i].textContent || "").length;
    return s;
  }
  var sel = window.getSelection ? String(window.getSelection()) : "";
  if (sel.replace(/\s+/g, "").length > 40) {
    sel.split(/\n+/).forEach(function (t) { push("p", t); });
  } else {
    var all = ptext(d.body), root = d.body;
    var tries = ['[itemprop="articleBody"]', "#article-body", ".article-body", "article", "main", '[role="main"]'];
    for (var i = 0; i < tries.length && root === d.body; i++) {
      var els = d.querySelectorAll(tries[i]);
      for (var j = 0; j < els.length; j++) {
        var t = ptext(els[j]);
        if (t >= 300 && t >= all * 0.4) { root = els[j]; break; }
      }
    }
    var skip = "nav,footer,aside,form,figure,figcaption,button,[aria-hidden='true'],[hidden]";
    var els2 = root.querySelectorAll("h2,h3,h4,p,li,blockquote");
    for (var k = 0; k < els2.length; k++) {
      var el = els2[k], tag = el.tagName;
      if (el.closest(skip) || !el.getClientRects().length) continue;
      if (tag !== "BLOCKQUOTE" && el.parentElement && el.parentElement.closest("blockquote")) continue;
      if (tag === "LI" && el.querySelector("p")) continue;
      push(tag === "BLOCKQUOTE" ? "quote" : (tag.charAt(0) === "H" ? "h" : "p"), el.textContent);
    }
  }
  /* Sites that keep the date and byline only in their structured data. */
  var ld = {};
  var lds = d.querySelectorAll('script[type="application/ld+json"]');
  for (var q = 0; q < lds.length && !ld.datePublished; q++) {
    try {
      var x = JSON.parse(lds[q].textContent), xs = [].concat(x["@graph"] || x);
      for (var r = 0; r < xs.length; r++) if (xs[r] && xs[r].datePublished) { ld = xs[r]; break; }
    } catch (e) { /* not ours to fix */ }
  }
  var by = [].concat(ld.author || []).map(function (a) { return a && (a.name || a); })
    .filter(function (a) { return typeof a === "string"; }).join(", ");
  var canon = d.querySelector('link[rel="canonical"]'), url = location.href.split("#")[0];
  if (canon && canon.href && canon.href.indexOf(location.protocol + "//" + location.hostname) === 0) url = canon.href;
  var page = {
    url: url,
    title: meta("og:title") || d.title,
    site: meta("og:site_name") || location.hostname,
    published: meta("article:published_time") || meta("datePublished") || ld.datePublished || meta("date") || "",
    author: meta("author") || by || "",
    selection: sel.replace(/\s+/g, "").length > 40,
    cut: cut,
    blocks: out
  };
  window.open(origin + "/clip.html#" + encodeURIComponent(JSON.stringify(page)), "plover-clip",
    "width=520,height=460");
}

function bookmarkletHref() {
  /* Encoded whole: a javascript: address is decoded before it runs, and the
     address parser would otherwise drop the line breaks. */
  return "javascript:" + encodeURIComponent("void((" + ploverClip.toString() + ")(" +
    JSON.stringify(location.origin) + "))");
}

/* ---------------------------------------------------------------- in the desk */

/* The Send to Plover box and the list of sent pages, under Research › Web Page. */
function renderClips() {
  var box = $("#dk-rs-clips");
  if (!box) return;
  box.innerHTML =
    '<div class="dk-clip-how">' +
    '<p class="dk-clip-head">Paid sites: FT, WSJ, Nikkei</p>' +
    '<p class="hint">The reader above sees what a logged-out visitor sees. To read an article you subscribe to, ' +
    "drag this button to your bookmarks bar once:</p>" +
    '<p><a class="dk-clip-btn" id="dk-clip-bm" title="Drag me to your bookmarks bar">Send to Plover</a></p>' +
    '<p class="hint">Then, on the article in your browser, click the bookmark. The page appears here. ' +
    "To send one passage, select it first.</p></div>" +
    '<div class="dk-clip-list" id="dk-clip-list"><p class="muted">Loading your sent pages…</p></div>';
  var bm = $("#dk-clip-bm");
  bm.setAttribute("href", bookmarkletHref());
  bm.addEventListener("click", function (e) {
    e.preventDefault();
    toast("Drag this button to your bookmarks bar, then click it on an article.");
  });
  loadClips();
}

function clipWhen(ts) {
  var d = new Date(ts * 1000);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " +
    d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function loadClips(openId) {
  var list = $("#dk-clip-list");
  if (!list) return;
  api("/research/clips").then(function (r) {
    if (!r.clips.length) {
      list.innerHTML = '<p class="muted">No pages sent yet.</p>';
      return;
    }
    list.innerHTML = '<p class="dk-clip-head">Sent from your browser</p><ul>' + r.clips.map(function (c) {
      return '<li data-clip="' + c.id + '"><button type="button" class="dk-clip-open" data-clip-open="' + c.id + '">' +
        '<span class="dk-clip-title">' + escapeHtml(c.title) + "</span>" +
        '<span class="dk-clip-meta">' + escapeHtml(c.site) + " · " + escapeHtml(clipWhen(c.sent_at)) + "</span></button>" +
        '<button type="button" class="dk-clip-del" data-clip-del="' + c.id + '" aria-label="Delete ' +
        escapeHtml(c.title) + '" title="Delete">Delete</button></li>';
    }).join("") + "</ul>";
    $all("[data-clip-open]", list).forEach(function (b) {
      b.addEventListener("click", function () { openClip(Number(b.getAttribute("data-clip-open"))); });
    });
    $all("[data-clip-del]", list).forEach(function (b) {
      b.addEventListener("click", function () {
        api("/research/clips/" + b.getAttribute("data-clip-del"), { method: "DELETE" }).then(function () {
          if (S.rsPage && S.rsPage.id === Number(b.getAttribute("data-clip-del"))) $("#dk-rs-wres").innerHTML = "";
          loadClips();
        }).catch(function (err) { toast(err.message); });
      });
    });
    if (openId) openClip(openId);
  }).catch(function (err) {
    list.innerHTML = '<p class="bad">Your sent pages could not be loaded: ' + escapeHtml(err.message) + "</p>";
  });
}

function openClip(id) {
  var res = $("#dk-rs-wres");
  res.innerHTML = '<p class="muted">Opening the page…</p>';
  api("/research/clips/" + id).then(showPage).catch(function (err) {
    res.innerHTML = '<p class="bad">' + escapeHtml(err.message) + "</p>";
  });
}

/* clip.html says when a page arrives; show it straight away. */
function listenForClips() {
  if (typeof BroadcastChannel === "undefined") return;
  var ch = new BroadcastChannel(CLIP_CHANNEL);
  ch.onmessage = function (e) {
    var id = e.data && e.data.clip;
    if (!id) return;
    var tab = $('.dk-tab[data-pane="research"]');
    if (tab) tab.click();
    var web = $('[data-rs="web"]');
    if (web) web.click();
    loadClips(id);
    toast("Page received: " + (e.data.title || "from your browser") + ".");
  };
}

listenForClips();
