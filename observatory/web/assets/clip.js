/* clip.html: where Send to Plover lands.

   The bookmark (ploverClip in desk-clip.js) opens this page with the
   article's text in the #fragment. The fragment is read once and removed
   from the address straight away, so the text does not stay in the
   browser's history; it never reached the server in the first place. The
   page then saves it to the writer's sent pages and tells any open desk
   tab, which shows it in Research › Web Page. */
"use strict";

(function () {
  var box = document.getElementById("clip-status");
  var page = null;

  function show(kind, html) {
    box.className = "clip-status " + kind;
    box.innerHTML = html;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function words(p) {
    var n = 0;
    p.blocks.forEach(function (b) { n += b.text.split(/\s+/).filter(Boolean).length; });
    return n;
  }

  function retryButton() {
    return '<p><button type="button" class="btn" id="clip-retry">Try Again</button></p>';
  }

  function wireRetry() {
    var b = document.getElementById("clip-retry");
    if (b) b.addEventListener("click", save);
  }

  function save() {
    show("busy", "<p>Sending <strong>" + esc(page.title || page.url) + "</strong> to Plover…</p>");
    fetch("/admin/api/research/clips", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(page),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (r.status === 401) {
          show("bad", "<p>You are not signed in to Plover in this browser.</p>" +
            '<p><a href="/admin.html" target="_blank" rel="noopener">Sign in</a> in a new tab, then come back and click Try Again.</p>' +
            retryButton());
          wireRetry();
          return;
        }
        if (!r.ok) {
          show("bad", "<p>" + esc(body.detail || "Plover could not save the page (" + r.status + ").") + "</p>" + retryButton());
          wireRetry();
          return;
        }
        if (typeof BroadcastChannel !== "undefined") {
          try { new BroadcastChannel("plover-clips").postMessage({ clip: body.id, title: body.title }); } catch (e) { /* no open desk */ }
        }
        show("ok", "<p><strong>Sent.</strong> " + esc(body.title) + "</p>" +
          "<p>" + words(body).toLocaleString("en-GB") + " words" + (body.selection ? ", the passage you selected" : "") +
          (page.cut ? ". The article was long: the first part was sent" : "") + ".</p>" +
          "<p>It is in the editor under Research › Web Page, in every draft. An open draft shows it now.</p>" +
          '<p><button type="button" class="btn" id="clip-close">Close</button></p>');
        document.getElementById("clip-close").addEventListener("click", function () { window.close(); });
      });
    }).catch(function () {
      show("bad", "<p>Plover could not be reached. Check your connection.</p>" + retryButton());
      wireRetry();
    });
  }

  var raw = location.hash.slice(1);
  if (raw) history.replaceState(null, "", location.pathname);
  try { page = raw ? JSON.parse(decodeURIComponent(raw)) : null; } catch (e) { page = null; }
  if (!page || !page.url) {
    show("bad", "<p>Nothing arrived. This window opens when you click the Send to Plover bookmark on an article.</p>" +
      '<p>To get the bookmark, open any draft in the <a href="/admin.html#articles">editor</a>: Research › Web Page.</p>');
    return;
  }
  if (!page.blocks || !page.blocks.length) {
    show("bad", "<p>No article text was found on that page.</p>" +
      "<p>Open the article itself, not a list of headlines. If the page still shows nothing, select the passage you want and click the bookmark again.</p>");
    return;
  }
  save();
})();
