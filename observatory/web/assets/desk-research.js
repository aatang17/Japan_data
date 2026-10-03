/* Research Desk, part two: charts copied from Plover pages, and the research
   panel (Plover data and the web).

   Copying a chart
     Every chart a Plover page draws goes through charts.js, which keeps a
     list of them with the config — data included — each is drawn from. The
     desk opens the page in an invisible frame (same site, light theme), waits
     for its charts to settle, and reads that list. The writer picks one; its
     kind and config are stored in the article and drawn by the same code, so
     it looks exactly as on the page, frozen on the day it was copied. A chart
     a page draws some other way (a map, the yield curve) comes across as an
     image. An agent working over MCP can only name the page; the desk copies
     those charts when a person opens the draft.

   Research panel
     Plover data: search series and companies, insert a chart, insert a
     latest value with a footnote saying where it came from, or copy a chart
     from a company's pages. Web page: read a page by its address as text,
     cite it as a footnote or quote from it. Searching the web is left to the
     writer's own Claude or Codex over /mcp/research.

   Loaded before desk.js; uses its helpers ($, S, api, send, insertBlock …)
   only inside functions, which run after both files have loaded. */
"use strict";

var SITE_HOSTS = ["ploveranalytics.com", "www.ploveranalytics.com"];

/* A Plover page address as "/page.html?query", or "" — the same rule the
   server applies (research_doc.page_path). */
function pagePath(url) {
  url = (url || "").trim();
  if (!url) return "";
  var m = /^https?:\/\/([^/]+)(\/.*)?$/i.exec(url);
  if (m) {
    var host = m[1].toLowerCase().split(":")[0];
    if (SITE_HOSTS.indexOf(host) === -1 && host !== "localhost" && host !== "127.0.0.1" &&
        host !== location.hostname) return "";
    url = m[2] || "/";
  }
  url = url.split("#")[0];
  if (url === "" || url === "/") url = "/index.html";
  return /^\/(?!admin|desk)[A-Za-z0-9_\-]+\.html(\?[^\s<>"#]*)?$/.test(url) ? url : "";
}

function chartIndexOf(url) {
  var m = /#chart-(\d+)$/.exec(url || "");
  return m ? Number(m[1]) : 0;
}

function todayIso() { return new Date().toISOString().slice(0, 10); }

function dateLong(iso) {
  if (!iso) return "";
  var d = new Date(iso.slice(0, 10) + "T00:00:00Z");
  return d.getUTCDate() + " " + d.toLocaleString("en-GB", { month: "long", timeZone: "UTC" }) +
    " " + d.getUTCFullYear();
}

/* ---------------------------------------------------------------- the block */

function snapshotHeight(model) {
  var c = model.cfg || {};
  var rows = (c.rows || c.items || []).length;
  if ((model.kind === "rank" || model.kind === "bar") && rows) {
    return Math.max(320, Math.min(1400, rows * 24 + 80));
  }
  return 320;
}

function renderSnapshotBlock(c, b) {
  var head = '<div class="dk-fig-label dk-chart-label"></div>' +
    '<input type="text" class="dk-chart-title" data-f="title" maxlength="200" placeholder="Chart title">';
  if (!b.url) {
    c.innerHTML = head +
      '<div class="dk-snap-ask"><label class="dk-flabel" for="snap-' + b.id + '">Plover page</label>' +
      '<div class="dk-snap-row"><input type="text" id="snap-' + b.id + '" data-snap="url" ' +
      'placeholder="Paste a page address, e.g. https://ploveranalytics.com/financials.html?c=7203">' +
      '<button type="button" class="dk-mini" data-snap="capture">Copy Chart</button></div>' +
      '<p class="dk-snap-status" hidden></p></div>';
  } else if (!b.cfg) {
    c.innerHTML = head +
      '<div class="dk-snap-ask"><p>Waiting to copy ' + (b.chart ? "chart " + b.chart : "a chart") +
      ' from <a href="' + escapeHtml(b.url) + '" target="_blank" rel="noopener">' +
      escapeHtml(b.url) + "</a>.</p>" +
      '<div class="dk-snap-row"><button type="button" class="dk-mini" data-snap="capture">Copy Now</button>' +
      '<button type="button" class="dk-mini" data-snap="clear">Use Another Page</button></div>' +
      '<p class="dk-snap-status" hidden></p></div>';
  } else {
    c.innerHTML = head +
      '<p class="dk-snap-meta">From <a href="' + escapeHtml(b.url) + '" target="_blank" rel="noopener">' +
      escapeHtml(b.page_title || b.url) + "</a> · copied " + escapeHtml(dateLong(b.captured_at)) +
      ' · <button type="button" class="linkish" data-snap="capture">Copy Again</button>' +
      ' · <button type="button" class="linkish" data-snap="choose">Choose Another Chart</button></p>' +
      '<div class="dk-chart-plot" style="height:' + snapshotHeight(b) + 'px"></div>' +
      '<p class="source-line">' + escapeHtml(b.source || "") + "</p>" +
      (b.calc ? '<details class="calc"><summary>Show calculation</summary><div class="calc-body">' +
        escapeHtml(b.calc) + "</div></details>" : "") +
      '<p class="dk-snap-status" hidden></p>' +
      '<div class="dk-fig-fields"><label class="wide"><span>Note under the chart <span class="muted">optional</span></span>' +
      '<input type="text" data-f="note" maxlength="400"></label></div>';
    var noteIn = $('[data-f="note"]', c);
    if (noteIn) noteIn.value = b.note || "";
    setTimeout(function () { drawSnapshotIn(c, b); }, 0);
  }
  $('[data-f="title"]', c).value = b.title || "";
}

function drawSnapshotIn(c, b) {
  var plot = $(".dk-chart-plot", c);
  if (!plot || !b.cfg) return;
  disposeChart(b.id);
  S.charts[b.id] = researchChart.drawSnapshot(plot, { kind: b.kind, cfg: b.cfg, title: b.title, source: b.source });
}

function snapStatus(blockEl, text, bad) {
  var st = $(".dk-snap-status", blockEl);
  if (!st) return;
  st.hidden = !text;
  st.className = "dk-snap-status" + (bad ? " bad" : "");
  st.textContent = text || "";
}

function snapClick(blockEl, model, t) {
  var act = t.getAttribute("data-snap");
  if (!act) return false;
  if (act === "capture" || act === "choose") {
    if (!model.url) {
      var input = $('[data-snap="url"]', blockEl);
      var path = pagePath(input ? input.value : "");
      if (!path) { snapStatus(blockEl, "Paste the address of a Plover page (ploveranalytics.com/…).", true); return true; }
      model.url = path;
      model.chart = chartIndexOf(input.value);
    }
    copyChart(blockEl, model, act === "choose");
    return true;
  }
  if (act === "clear") {
    Object.assign(model, { url: "", chart: 0, cfg: null, kind: "" });
    renderSnapshotBlock(blockEl.querySelector(".dk-content"), model);
    updateCounts();
    changed();
    return true;
  }
  return false;
}

/* ---------------------------------------------------------------- capture */

var captureQueue = Promise.resolve();

/* One page at a time: a second capture waits for the first frame to close. */
function capturePage(path) {
  var job = captureQueue.then(function () { return captureNow(path); });
  captureQueue = job.catch(function () {});
  return job;
}

function captureNow(path) {
  return new Promise(function (resolve, reject) {
    var frame = document.createElement("iframe");
    frame.setAttribute("aria-hidden", "true");
    frame.tabIndex = -1;
    frame.className = "dk-capture-frame";
    frame.src = path + (path.indexOf("?") === -1 ? "?" : "&") + "theme=light";
    var started = Date.now();
    var last = -1;
    var stable = 0;
    var done = false;
    var timer = null;
    function finish(err) {
      if (done) return;
      done = true;
      clearInterval(timer);
      var out = null;
      if (!err) {
        try { out = collectCharts(frame); } catch (e) { err = new Error("The page's charts could not be read."); }
      }
      frame.parentNode && frame.parentNode.removeChild(frame);
      if (err) reject(err); else resolve(out);
    }
    timer = setInterval(function () {
      var w;
      try {
        w = frame.contentWindow;
        if (!w || !w.document || w.document.readyState === "loading") return;
        if (w.document.title === "" && Date.now() - started < 3000) return;
      } catch (e) { finish(new Error("That page could not be opened here.")); return; }
      try { w.scrollTo(0, w.document.body.scrollHeight); } catch (e) { /* ignore */ }
      var n = liveCharts(w).length + rawCharts(w, liveCharts(w)).length;
      if (n === last && n > 0) stable++; else { stable = 0; last = n; }
      if (stable >= 4) finish();
      else if (n === 0 && Date.now() - started > 12000) {
        // A page that has drawn nothing in 12 seconds shows no chart at this
        // address; waiting the full 25 only makes the writer wait to be told.
        finish(new Error("That page shows no chart at this address. If it charts one company " +
                         "at a time, open it, choose the company, and copy from that address."));
      } else if (Date.now() - started > 25000) {
        finish();
      }
    }, 500);
    document.body.appendChild(frame);
  });
}

function liveCharts(w) {
  var d = w.document;
  var byEl = new Map();
  (w.__obsCharts || []).forEach(function (x) {
    if (d.contains(x.el) && x.el.querySelector("canvas")) byEl.set(x.el, x);
  });
  return Array.from(byEl.values());
}

function rawCharts(w, live) {
  if (!w.echarts) return [];
  var taken = new Set(live.map(function (x) { return x.el; }));
  return Array.prototype.slice.call(w.document.querySelectorAll("[_echarts_instance_]")).filter(function (el) {
    return !taken.has(el) && el.offsetWidth >= 200 && w.echarts.getInstanceByDom(el);
  });
}

function cleanText(node) {
  var copy = node.cloneNode(true);
  Array.prototype.forEach.call(copy.querySelectorAll(".h2-note, .badge, button"), function (x) { x.remove(); });
  return (copy.textContent || "").replace(/\s+/g, " ").trim().slice(0, 200);
}

function titleNear(el) {
  var sel = "h1, h2, h3, h4, .chart-title, .panel-title, figcaption, .card-title, .section-title";
  var n = el;
  for (var depth = 0; n && depth < 8; depth++) {
    var p = n.previousElementSibling;
    while (p) {
      if (p.matches(sel)) return cleanText(p);
      var q = p.querySelectorAll(sel);
      if (q.length) return cleanText(q[q.length - 1]);
      p = p.previousElementSibling;
    }
    n = n.parentElement;
  }
  return "";
}

function textNear(el, sel) {
  var n = el.parentElement;
  for (var depth = 0; n && depth < 6; depth++) {
    var hits = Array.prototype.slice.call(n.querySelectorAll(sel)).filter(function (h) {
      return el.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING;
    });
    if (hits.length) {
      // the page's own download links (JSON, Markdown, CSV) are not part of the source
      var copy = hits[0].cloneNode(true);
      Array.prototype.forEach.call(copy.querySelectorAll('a[href*="/api/"], a[href$=".md"], a[href*=".md?"], a[download], button'),
        function (a) { a.remove(); });
      return (copy.textContent || "").replace(/\s+/g, " ").replace(/(\s*\u00b7\s*)+\.?\s*$/, "")
        .replace(/(\s*\u00b7\s*){2,}/g, " \u00b7 ").trim().slice(0, 1000);
    }
    n = n.parentElement;
  }
  return "";
}

function collectCharts(frame) {
  var w = frame.contentWindow;
  var d = w.document;
  var live = liveCharts(w);
  var found = [];
  live.forEach(function (x) {
    var cfg;
    try { cfg = JSON.parse(JSON.stringify(x.cfg)); } catch (e) { return; }
    found.push({ el: x.el, kind: x.kind, cfg: cfg, title: titleNear(x.el),
                 source: textNear(x.el, ".source-line") || cfg.sourceLine || "",
                 calc: textNear(x.el, "details.calc .calc-body") });
  });
  rawCharts(w, live).forEach(function (el) {
    var url;
    try {
      url = w.echarts.getInstanceByDom(el).getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
    } catch (e) { return; }
    found.push({ el: el, image: url, title: titleNear(el), source: textNear(el, ".source-line"),
                 width: el.offsetWidth * 2, height: el.offsetHeight * 2 });
  });
  found.sort(function (a, b) {
    return a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
  });
  found.forEach(function (f) { delete f.el; });
  return { page_title: (d.title || "").replace(/\s*[·|]\s*Plover Analytics\s*$/, ""), candidates: found };
}

var KIND_LABEL = { line: "Line chart", stack: "Stacked bars", cols: "Bars", dist: "Distribution",
                   rank: "Ranking", bar: "Bars" };

/* The picker: every chart the page drew, drawn small, newest choice first. */
function pickChart(found, wanted) {
  return new Promise(function (resolve) {
    var dlg = $("#dk-capture");
    var body = $("#dk-capture-body");
    var minis = [];
    // one picker at a time: an earlier one still open is cancelled, never
    // answered with this one's choice
    if (dlg.open) dlg.close();
    body.innerHTML = "<h2>Choose a Chart</h2>" +
      '<p class="hint">From ' + escapeHtml(found.page_title || "the page") + ". " +
      found.candidates.length + (found.candidates.length === 1 ? " chart" : " charts") + " found.</p>" +
      '<ol class="dk-pick">' + found.candidates.map(function (cnd, i) {
        var names = cnd.cfg && cnd.cfg.series ? cnd.cfg.series.slice(0, 3).map(function (s) { return s.name; }).join(", ") : "";
        return '<li' + (wanted === i + 1 ? ' class="wanted"' : "") + '><div class="dk-pick-prev" data-i="' + i + '">' +
          (cnd.image ? '<img alt="" src="' + cnd.image + '">' : "") + "</div>" +
          '<div class="dk-pick-txt"><strong>' + (i + 1) + ". " + escapeHtml(cnd.title || "Untitled chart") + "</strong>" +
          '<span class="muted">' + escapeHtml(cnd.image ? "Image" : (KIND_LABEL[cnd.kind] || cnd.kind)) +
          (names ? " · " + escapeHtml(names) : "") + "</span></div>" +
          '<button type="button" class="btn" data-pick="' + i + '">Use This Chart</button></li>';
      }).join("") + "</ol>" +
      '<div class="dk-dlg-acts"><button type="button" class="btn" data-close>Cancel</button></div>';
    dlg.showModal();
    found.candidates.forEach(function (cnd, i) {
      if (cnd.image) return;
      var box = $('.dk-pick-prev[data-i="' + i + '"]', body);
      try {
        var cfg = JSON.parse(JSON.stringify(cnd.cfg));
        cfg.legendFloor = 9999;
        minis.push(obsChart(box, cnd.kind, cfg));
        var inst = echarts.getInstanceByDom(box);
        if (inst) inst.setOption({ legend: { show: false } });
      } catch (e) { box.textContent = "Preview unavailable"; }
    });
    function close(choice) {
      minis.forEach(function (m) { m.dispose(); });
      dlg.removeEventListener("close", onClose);
      if (dlg.open) dlg.close();
      resolve(choice);
    }
    function onClose() { close(null); }
    dlg.addEventListener("close", onClose);
    $all("[data-pick]", body).forEach(function (b) {
      b.addEventListener("click", function () { close(Number(b.getAttribute("data-pick"))); });
    });
  });
}

function dataUrlBlob(url) {
  var bin = atob(url.split(",")[1]);
  var buf = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new Blob([buf], { type: "image/png" });
}

/* Copy a chart into a snapshot block: open the page, choose (or take the
   one asked for), store it. `choose` forces the picker. */
function copyChart(blockEl, model, choose, quiet) {
  snapStatus(blockEl, "Opening " + model.url + " and reading its charts…");
  return capturePage(model.url).then(function (found) {
    if (!document.contains(blockEl)) return false;
    var n = found.candidates.length;
    var pick = null;
    if (!choose && model.chart && model.chart <= n) pick = model.chart - 1;
    else if (!choose && n === 1) pick = 0;
    if (pick === null) {
      if (quiet) { snapStatus(blockEl, n + " charts on that page: choose one.", false); return false; }
      return pickChart(found, model.chart).then(function (i) {
        if (i === null) { snapStatus(blockEl, ""); return false; }
        return applyCapture(blockEl, model, found, i);
      });
    }
    return applyCapture(blockEl, model, found, pick);
  }).catch(function (err) {
    snapStatus(blockEl, err.message, true);
    return false;
  });
}

function applyCapture(blockEl, model, found, i) {
  var cnd = found.candidates[i];
  if (cnd.image) {
    // a chart the page draws without charts.js: kept as an image of it
    return fetch("/admin/api/research/media", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "image/png", "X-File-Name": "plover-chart.png" },
      body: dataUrlBlob(cnd.image),
    }).then(function (r) {
      return r.json().then(function (b) { if (!r.ok) throw new Error(b.detail || "Upload failed"); return b; });
    }).then(function (info) {
      var title = model.title || cnd.title;
      replaceBlock(blockEl, { id: model.id, type: "image", media: info.media, ext: info.ext,
        width: info.width, height: info.height, caption: title, alt: title,
        source: cnd.source || ("Plover Analytics, " + (found.page_title || model.url)), link: model.url });
      return true;
    });
  }
  Object.assign(model, {
    kind: cnd.kind, cfg: cnd.cfg, page_title: found.page_title, source: cnd.source, calc: cnd.calc,
    captured_at: todayIso(), chart: i + 1, title: model.title || cnd.title,
  });
  renderSnapshotBlock(blockEl.querySelector(".dk-content"), model);
  updateCounts();
  changed();
  return Promise.resolve(true);
}

/* Charts an agent named over MCP: copy them as soon as the draft opens. */
function capturePending() {
  var pending = $all('.dk-block[data-type="snapshot"]', blocksEl()).filter(function (el) {
    var m = S.models[el.getAttribute("data-id")];
    return m && m.url && !m.cfg;
  });
  if (!pending.length) return;
  toast("Copying " + pending.length + (pending.length === 1 ? " chart" : " charts") + " from Plover pages…");
  var copied = 0;
  pending.reduce(function (p, el) {
    return p.then(function () {
      return copyChart(el, S.models[el.getAttribute("data-id")], false, true).then(function (ok) { if (ok) copied++; });
    });
  }, Promise.resolve()).then(function () {
    if (copied) toast("Copied " + copied + (copied === 1 ? " chart" : " charts") + " from Plover pages.");
  });
}

/* A Plover page address pasted on its own line becomes a copied chart. */
function pasteAsChart(blockEl, model, target, text) {
  var raw = (text || "").trim();
  if (/\s/.test(raw) || model.type !== "p" || !isEmpty(target)) return false;
  var path = pagePath(raw);
  if (!path) return false;
  var el = replaceBlock(blockEl, { type: "snapshot", url: path, chart: chartIndexOf(raw), title: "", note: "" });
  copyChart(el, S.models[el.getAttribute("data-id")], false);
  return true;
}

/* ---------------------------------------------------------------- caret memory */

/* The panel takes focus away from the draft; remember where the writer was,
   so a value, citation or quote lands there. */
function rememberCaret() {
  var s = window.getSelection();
  if (!s.rangeCount) return;
  var node = s.anchorNode;
  var el = node && (node.nodeType === 1 ? node : node.parentNode);
  var ed = el && el.closest ? el.closest("#dk-blocks [contenteditable=true]") : null;
  if (!ed) return;
  S.lastRange = s.getRangeAt(0).cloneRange();
  S.lastBlock = blockOf(ed);
}

function restoreCaret() {
  var r = S.lastRange;
  var ok = r && document.contains(r.startContainer);
  var ed;
  if (ok) {
    var n = r.startContainer.nodeType === 1 ? r.startContainer : r.startContainer.parentNode;
    ed = n.closest("[contenteditable=true]");
  }
  if (!ed) {
    var texts = $all('.dk-block[data-type="p"] [contenteditable=true]', blocksEl());
    ed = texts[texts.length - 1];
    if (!ed) {
      var p = insertBlock({ type: "p", html: "" }, blocksEl().lastElementChild, false);
      ed = p.querySelector("[contenteditable=true]");
    }
    r = document.createRange();
    r.selectNodeContents(ed);
    r.collapse(false);
  }
  ed.focus();
  var s = window.getSelection();
  s.removeAllRanges();
  s.addRange(r);
  return ed;
}

function insertAtCaret(html) {
  restoreCaret();
  document.execCommand("insertHTML", false, html);
  rememberCaret();
  changed();
}

function insertAfterCaretBlock(b) {
  var after = S.lastBlock && document.contains(S.lastBlock) ? S.lastBlock : blocksEl().lastElementChild;
  var el = insertBlock(b, after, false);
  S.lastBlock = el;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  el.classList.add("dk-flash");
  setTimeout(function () { el.classList.remove("dk-flash"); }, 900);
  return el;
}

/* ---------------------------------------------------------------- research panel */

function renderResearchPane() {
  var box = $("#dk-pane-research");
  if (box.getAttribute("data-ready")) return;
  box.setAttribute("data-ready", "1");
  box.innerHTML =
    '<div class="dk-seg" role="tablist">' +
    '<button type="button" role="tab" aria-selected="true" data-rs="data">Plover Data</button>' +
    '<button type="button" role="tab" aria-selected="false" data-rs="web">Web Page</button></div>' +
    '<div id="dk-rs-data">' +
    '<form class="dk-rs-form" id="dk-rs-dform"><input type="search" id="dk-rs-dq" placeholder="Series, company or topic, e.g. core CPI, 7203, CEO pay" aria-label="Search Plover data">' +
    '<button type="submit" class="dk-mini">Search</button></form>' +
    '<div id="dk-rs-dres" class="dk-rs-res"><p class="hint">Find a series to chart or quote, or a company or topic whose charts to copy. ' +
    'A value is inserted where your cursor was, with a footnote naming its source and date.</p></div></div>' +
    '<div id="dk-rs-web" hidden>' +
    '<p class="hint">Paste a page address to read it here, then cite it as a footnote or quote from it. ' +
    "To search the web, ask your own Claude or Codex: connected to the desk, it searches and writes " +
    "into the draft.</p>" +
    '<form class="dk-rs-form" id="dk-rs-rform"><input type="url" id="dk-rs-url" placeholder="https://\u2026" aria-label="Page address">' +
    '<button type="submit" class="dk-mini">Read</button></form>' +
    '<div id="dk-rs-wres" class="dk-rs-res"></div>' +
    '<div id="dk-rs-clips"></div></div>';

  $all("[data-rs]", box).forEach(function (b) {
    b.addEventListener("click", function () {
      $all("[data-rs]", box).forEach(function (x) { x.setAttribute("aria-selected", String(x === b)); });
      $("#dk-rs-data").hidden = b.getAttribute("data-rs") !== "data";
      $("#dk-rs-web").hidden = b.getAttribute("data-rs") !== "web";
    });
  });
  $("#dk-rs-dform").addEventListener("submit", function (e) { e.preventDefault(); dataSearch($("#dk-rs-dq").value); });
  $("#dk-rs-rform").addEventListener("submit", function (e) { e.preventDefault(); webRead($("#dk-rs-url").value); });
  renderClips();
}

/* ---- Plover data ---- */

function dataSearch(q) {
  var res = $("#dk-rs-dres");
  if (!q.trim()) return;
  res.innerHTML = '<p class="muted">Searching…</p>';
  api("/research/data/search?q=" + encodeURIComponent(q)).then(function (r) {
    var pages = r.pages || [];
    if (!r.series.length && !r.companies.length && !pages.length) {
      res.innerHTML = '<p class="muted">Nothing matches. Try a shorter name, or a series code.</p>';
      return;
    }
    S.rsData = r;
    // a search for a company (its code, or the start of its name) lists companies first
    var ql = q.trim().toLowerCase();
    var firstCo = r.companies.some(function (c) {
      return String(c.code).toLowerCase() === ql || (c.name || "").toLowerCase().indexOf(ql) === 0;
    });
    var seriesHtml =
      (r.series.length ? '<p class="dk-rs-h">Series</p><ul class="dk-rs-list">' + r.series.map(function (s, i) {
        return '<li><span class="dk-rs-name" title="' + escapeHtml(s.dataset_name + " · " + s.code) + '">' +
          escapeHtml(s.name) + ' <span class="mono muted">' + escapeHtml(s.dataset) + "</span></span>" +
          '<span class="dk-rs-acts"><button type="button" class="dk-mini" data-schart="' + i + '">Insert Chart</button>' +
          '<button type="button" class="dk-mini" data-svalue="' + i + '">Insert Value</button></span></li>';
      }).join("") + "</ul>" : "");
    var companyHtml =
      (r.companies.length ? '<p class="dk-rs-h">Companies</p><ul class="dk-rs-list">' + r.companies.map(function (c, i) {
        return '<li><span class="dk-rs-name" title="' + escapeHtml(c.name_ja || "") + '">' + escapeHtml(c.name) +
          ' <span class="mono muted">' + escapeHtml(c.code) + "</span></span>" +
          '<span class="dk-rs-acts"><select data-cpage="' + i + '" aria-label="Page">' + c.pages.map(function (p) {
            return '<option value="' + escapeHtml(p.url) + '">' + escapeHtml(p.label) + "</option>";
          }).join("") + '</select><button type="button" class="dk-mini" data-ccopy="' + i + '">Copy a Chart</button>' +
          '<button type="button" class="dk-mini" data-copen="' + i + '">Open</button></span></li>';
      }).join("") + "</ul>" : "");
    // pages about the topic ("CEO compensation"): copy one of their charts
    var pageHtml =
      (pages.length ? '<p class="dk-rs-h">Pages</p><ul class="dk-rs-list">' + pages.map(function (pg, i) {
        return '<li><span class="dk-rs-name" title="' + escapeHtml(pg.description) + '">' + escapeHtml(pg.title) +
          ' <span class="mono muted">' + escapeHtml(pg.url.replace(/^\//, "")) + "</span></span>" +
          '<span class="dk-rs-acts"><button type="button" class="dk-mini" data-pcopy="' + i + '">Copy a Chart</button>' +
          '<button type="button" class="dk-mini" data-popen="' + i + '">Open</button></span></li>';
      }).join("") + "</ul>" : "");
    res.innerHTML = (firstCo ? companyHtml + seriesHtml : seriesHtml + companyHtml) + pageHtml;
    $all("[data-pcopy]", res).forEach(function (b) {
      b.addEventListener("click", function () { copyFromSearch(pages[Number(b.getAttribute("data-pcopy"))].url); });
    });
    $all("[data-popen]", res).forEach(function (b) {
      b.addEventListener("click", function () {
        window.open(pages[Number(b.getAttribute("data-popen"))].url, "_blank", "noopener");
      });
    });
    $all("[data-schart]", res).forEach(function (b) {
      b.addEventListener("click", function () {
        var s = r.series[Number(b.getAttribute("data-schart"))];
        insertAfterCaretBlock({ type: "chart", dataset: s.dataset, series: [s.code], measure: "index",
                                start: "", end: "", title: s.name, note: "" });
        toast("Chart inserted. Pick the measure and dates in its Data settings.");
      });
    });
    $all("[data-svalue]", res).forEach(function (b) {
      b.addEventListener("click", function () { insertValue(r.series[Number(b.getAttribute("data-svalue"))], b); });
    });
    $all("[data-ccopy]", res).forEach(function (b) {
      b.addEventListener("click", function () {
        copyFromSearch($('[data-cpage="' + b.getAttribute("data-ccopy") + '"]', res).value);
      });
    });
    $all("[data-copen]", res).forEach(function (b) {
      b.addEventListener("click", function () {
        window.open($('[data-cpage="' + b.getAttribute("data-copen") + '"]', res).value, "_blank", "noopener");
      });
    });
  }).catch(function (err) { res.innerHTML = '<p class="bad">' + escapeHtml(err.message) + "</p>"; });
}

/* Copy a chart from a page found in the search. The chart block goes in at
   once, so the writer sees where it will land; if no chart comes of it (the
   page has none, or the writer cancels the choice) the block is taken out
   again and the reason shown, so nothing half-made is left in the draft. */
function copyFromSearch(url) {
  var el = insertAfterCaretBlock({ type: "snapshot", url: url, chart: 0, title: "", note: "" });
  // a page with one chart gives it straight away; with several, the writer chooses
  copyChart(el, S.models[el.getAttribute("data-id")], false).then(function (ok) {
    if (ok || !document.contains(el)) return;
    var st = el.querySelector(".dk-snap-status");
    var why = st && st.classList.contains("bad") ? st.textContent : "";
    removeBlock(el);
    toast(why ? why + " Nothing was added." : "No chart chosen. Nothing was added.");
  });
}

/* Thousands grouped, every published decimal kept, true minus. */
function grouped(v) {
  var parts = String(Math.abs(v)).split(".");
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (v < 0 ? "\u2212" : "") + parts.join(".");
}

/* The latest published value, exactly as published, with a footnote that
   names the series, the period, the release and the day it was read. */
function insertValue(s, btn) {
  btn.disabled = true;
  fetch("/api/v1/" + encodeURIComponent(s.dataset) + "/observations?series=" + encodeURIComponent(s.code) + "&measure=index")
    .then(function (r) { return r.json().then(function (b) { if (!r.ok) throw new Error(b.detail || "Could not read the value"); return b; }); })
    .then(function (body) {
      var pts = body.series[0].points.filter(function (p) { return p[1] !== null; });
      if (!pts.length) throw new Error("This series has no published value.");
      var last = pts[pts.length - 1];
      var unit = body.unit && body.unit !== "index" ? body.unit : "";
      var period = last[0].length > 10 ? last[0].slice(0, 10) : (body.release && body.release.frequency === "daily" ? last[0] : last[0].slice(0, 7));
      var shown = grouped(last[1]) + (unit === "%" ? "%" : (unit ? " " + unit : ""));
      var rel = body.release || {};
      var note = s.name + " (" + s.dataset_name + ", series " + s.code + "), " + period + ": " + shown +
        (body.trust === "official" ? ", as published" : "") + ". " +
        (rel.source_name ? rel.source_name + (rel.label ? ", release " + rel.label : "") + ". " : "") +
        "Read from Plover Analytics on " + dateLong(todayIso()) + ".";
      insertAtCaret(escapeHtml(shown) + noteSup(note));
      toast("Inserted " + shown + " with its footnote.");
    })
    .catch(function (err) { toast(err.message); })
    .then(function () { btn.disabled = false; });
}

/* ---- the web ---- */

function citation(page) {
  var when = page.published && /^\d{4}-\d{2}-\d{2}/.test(page.published) ? ", " + dateLong(page.published) : "";
  // A page sent from the writer's browser was read on the day it was sent.
  var read = page.sent_at ? new Date(page.sent_at * 1000).toISOString().slice(0, 10) : todayIso();
  return (page.author ? page.author + ", " : "") + (page.title || page.url) + ". " +
    (page.site ? page.site + when + ". " : "") + page.url + " (accessed " + dateLong(read) + ").";
}

function citePage(page) {
  insertAtCaret(noteSup(citation(page)));
  toast("Footnote added where your cursor was.");
}

function webRead(url) {
  var res = $("#dk-rs-wres");
  if (!(url || "").trim()) return;
  res.innerHTML = '<p class="muted">Reading the page…</p>';
  send("POST", "/research/web/read", { url: url.trim() }).then(showPage)
    .catch(function (err) { res.innerHTML = '<p class="bad">' + escapeHtml(err.message) + "</p>"; });
}

/* A page in the reader: one read by address, or one sent from the writer's
   browser (desk-clip.js). */
function showPage(page) {
  var res = $("#dk-rs-wres");
  var chars = (page.blocks || []).reduce(function (n, b) { return n + b.text.length; }, 0);
  S.rsPage = page;
  res.innerHTML =
    '<div class="dk-reader">' +
    '<p class="dk-reader-src"><a href="' + escapeHtml(page.url) + '" target="_blank" rel="noopener noreferrer">' +
    escapeHtml(page.site || page.url) + "</a>" + (page.published ? " · " + escapeHtml(dateLong(page.published) || page.published) : "") + "</p>" +
    '<p class="dk-reader-title">' + escapeHtml(page.title || page.url) + "</p>" +
    (page.sent ? '<p class="dk-reader-sent">Sent from your browser on ' + escapeHtml(dateLong(new Date(page.sent_at * 1000).toISOString())) +
      (page.selection ? ": the passage you selected" : "") + ".</p>"
      : (!page.pdf && chars < 1500 ? '<p class="dk-reader-sent">Only a short part of this page came through. If the site needs a ' +
        "subscription, open the article in your browser and use Send to Plover, below.</p>" : "")) +
    '<div class="dk-reader-acts"><button type="button" class="dk-mini" id="dk-rd-cite">Cite This Page</button>' +
    '<button type="button" class="dk-mini" id="dk-rd-quote">Quote Selection</button></div>' +
    '<div class="dk-reader-text" id="dk-reader-text">' +
    (page.pdf ? '<p>This is a PDF. Open it to read it; citing it works from here.</p>'
      : page.blocks.map(function (b) {
        return b.kind === "h" ? "<p><strong>" + escapeHtml(b.text) + "</strong></p>"
          : (b.kind === "quote" ? "<blockquote>" + escapeHtml(b.text) + "</blockquote>" : "<p>" + escapeHtml(b.text) + "</p>");
      }).join("") || "<p>No readable text was found on this page.</p>") +
    "</div></div>";
  $("#dk-rd-cite").addEventListener("click", function () { citePage(page); });
  $("#dk-rd-quote").addEventListener("click", function () {
    var s = window.getSelection();
    var text = s && s.rangeCount && $("#dk-reader-text").contains(s.anchorNode) ? s.toString().replace(/\s+/g, " ").trim() : "";
    if (!text) { toast("Select the passage to quote in the page text first."); return; }
    insertAfterCaretBlock({ type: "quote", html: escapeHtml(text) + noteSup(citation(page)) });
    toast("Quotation added with its footnote.");
  });
}
