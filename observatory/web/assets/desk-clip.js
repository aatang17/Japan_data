/* Research Desk, part three: reading pages the writer subscribes to.

   The desk's page reader fetches from the server, with no login, so a paid
   article comes back as its teaser (Nikkei) or not at all (FT and WSJ refuse
   the server). The common way round is the paste box: it appears under the
   reader right then, the writer copies the article in their own browser and
   pastes it, and the server keeps the tidied text against that address
   (POST /clips/paste, app/research_clips.py).

   Send to Plover is the faster way for someone who sends many: a bookmark
   the writer drags to their bookmarks bar once. On an article they
   can read, clicking it runs ploverClip() in that page: it takes the
   article's text (or the passage selected), and opens /clip.html with the
   text in the address's #fragment, which no request carries to a server.
   clip.html saves it to the writer's sent pages (app/research_clips.py) and
   tells any open desk tab, which opens it in a new Research tab.

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

/* Sites whose articles a logged-out reader sees only the start of. */
var PAID_SITES = /(^|\.)(ft\.com|wsj\.com|nikkei\.com|bloomberg\.com|economist\.com|barrons\.com|nytimes\.com)$/i;

function isPaidSite(url) {
  try { return PAID_SITES.test(new URL(url).hostname); } catch (e) { return false; }
}

function siteName(page) {
  if (page.site && !/^www\./.test(page.site) && page.site.indexOf(".") === -1) return page.site;
  try { return new URL(page.url).hostname.replace(/^www\./, ""); } catch (e) { return page.site || "This site"; }
}

/* The keys to name, or null on a phone or tablet, which has none. */
function pasteKeys() {
  var ua = navigator.userAgent || "";
  if (/iPhone|iPad|Android|Mobile/.test(ua) || (/Mac/.test(ua) && navigator.maxTouchPoints > 1)) return null;
  return /Mac/.test(navigator.platform || ua)
    ? ["\u2318A", "\u2318C", "\u2318V"] : ["Ctrl+A", "Ctrl+C", "Ctrl+V"];
}

/* The paste box under the reader. Open when the page is known to be cut
   short; otherwise one button that opens it, for a page that turns out to be. */
function pasteBoxHtml(lead, url, open) {
  var k = pasteKeys();
  return (open ? "" : '<p class="dk-artpaste-more"><button type="button" class="dk-mini dk-artpaste-show">' +
      "Text Cut Off? Paste the Article</button></p>") +
    '<div class="dk-artpaste"' + (open ? "" : " hidden") + ">" +
    (lead ? '<p class="dk-artpaste-lead">' + escapeHtml(lead) + "</p>" : "") +
    '<ol class="dk-artpaste-steps">' +
    '<li><a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer">Open the article</a> in your browser, signed in.</li>' +
    (k ? "<li>Press <kbd>" + k[0] + "</kbd>, then <kbd>" + k[1] + "</kbd>.</li>" +
      "<li>Click the box below and press <kbd>" + k[2] + "</kbd>.</li></ol>"
      : "<li>Select all of the article and copy it.</li><li>Tap the box below and paste.</li></ol>") +
    '<textarea class="dk-artpaste-area" rows="2" placeholder="Paste the article here" aria-label="Paste the article here"></textarea>' +
    '<p class="dk-artpaste-status" role="status" aria-live="polite"></p></div>';
}

/* `root` is the research tab the reader is in: each tab has its own box. */
function wirePasteBox(page, root) {
  var show = $(".dk-artpaste-show", root), area = $(".dk-artpaste-area", root), status = $(".dk-artpaste-status", root);
  if (!area) return;
  if (show) {
    show.addEventListener("click", function () {
      show.parentNode.hidden = true;
      $(".dk-artpaste", root).hidden = false;
      area.focus();
    });
  }
  function say(kind, text) {
    status.className = "dk-artpaste-status " + kind;
    status.textContent = text;
  }
  area.addEventListener("paste", function (e) {
    var cd = e.clipboardData;
    if (!cd) return;
    e.preventDefault();
    var html = cd.getData("text/html") || "", text = cd.getData("text/plain") || "";
    if (!html.trim() && !text.trim()) {
      var k = pasteKeys();
      say("bad", "Nothing was copied yet. On the article, " + (k ? "press " + k[0] + " then " + k[1]
        : "select all and copy") + ", then paste here again.");
      return;
    }
    if (html.length > 10000000) html = "";   // past the server's cap: the plain text still works
    area.disabled = true;
    say("busy", "Reading what you pasted\u2026");
    send("POST", "/research/clips/paste", {
      url: page.url, title: page.title || "", site: page.site || "", published: page.published || "",
      author: page.author || "", html: html, text: text,
    }).then(function (clip) {
      showPage(clip, root);
      toast("Saved your copy of \u201c" + clip.title + "\u201d. Cite it or quote from it here.");
    }).catch(function (err) {
      area.disabled = false;
      area.value = "";
      say("bad", err.message);
    });
  });
}

/* The Send to Plover box and the list of sent pages, on a new research tab. */
function renderClips(box) {
  if (!box) return;
  box.innerHTML =
    '<div class="dk-clip-how">' +
    '<p class="dk-clip-head">Paid sites: FT, WSJ, Nikkei</p>' +
    '<p class="hint">Read the article\u2019s address above. When only the start comes through, a box appears: ' +
    "copy the article in your browser and paste it there. Your copy is kept for citing and quoting, " +
    "and only you can see it.</p>" +
    '<details class="dk-clip-bm"><summary>Send many articles? Use a bookmark instead</summary>' +
    '<p class="hint">Drag this button to your bookmarks bar once:</p>' +
    '<p><a class="dk-clip-btn" title="Drag me to your bookmarks bar">Send to Plover</a></p>' +
    '<p class="hint">Then, on the article in your browser, click the bookmark. The page appears here. ' +
    "To send one passage, select it first.</p></details></div>" +
    '<div class="dk-clip-list"><p class="muted">Loading your saved articles\u2026</p></div>';
  var bm = $(".dk-clip-btn", box);
  bm.setAttribute("href", bookmarkletHref());
  bm.addEventListener("click", function (e) {
    e.preventDefault();
    toast("Drag this button to your bookmarks bar, then click it on an article.");
  });
  loadClips($(".dk-clip-list", box));
}

function clipWhen(ts) {
  var d = new Date(ts * 1000);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " +
    d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function loadClips(list) {
  if (!list) return;
  api("/research/clips").then(function (r) {
    if (!r.clips.length) {
      list.innerHTML = '<p class="muted">No saved articles yet.</p>';
      return;
    }
    list.innerHTML = '<p class="dk-clip-head">Your saved articles</p><ul>' + r.clips.map(function (c) {
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
          loadClips(list);
        }).catch(function (err) { toast(err.message); });
      });
    });
  }).catch(function (err) {
    list.innerHTML = '<p class="bad">Your saved articles could not be loaded: ' + escapeHtml(err.message) + "</p>";
  });
}

function openClip(id) {
  openResearchTab({ kind: "web", clip: id, title: "Saved article" }, true);
}

/* clip.html says when a page arrives; show it straight away. */
function listenForClips() {
  if (typeof BroadcastChannel === "undefined") return;
  var ch = new BroadcastChannel(CLIP_CHANNEL);
  ch.onmessage = function (e) {
    var id = e.data && e.data.clip;
    if (!id) return;
    showPane("research");
    openClip(id);
    toast("Page received: " + (e.data.title || "from your browser") + ".");
  };
}

listenForClips();
