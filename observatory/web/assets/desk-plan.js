/* Research Desk, part four: from plan to draft.

   How a note gets written here, in the order people actually write:

   Plan      The AI (skill "Plan") or the writer puts a plan in the page: the
             question, the expected answer, an outline. A bar above it says
             it is a plan, not the article, with one button: Start Writing.
   Start     Start Writing moves the plan out of the page into Research ›
             Plan, and lays the draft out from the outline: one section
             heading per point, an empty paragraph to write in, a reminder
             of the point the section must make ("To show"), and a box for
             the chart the plan promised. Undo puts everything back.
   Research  Research tabs (desk-research.js) fill the planned charts, and
             notes collect numbers and quotations with their sources.
   Write     Each reminder stays until the writer presses Done; a planned
             chart is filled from Plover data, by the AI's suggestion, or by
             pasting a screenshot of another publisher's chart, which the AI
             rebuilds from the public data behind it.
   Check     The Check tab lists what is left from the plan (with Go To),
             numbers without a footnote, whether the title still matches what
             the draft found, and how far the draft has come against the plan.

   Loaded before desk.js; uses its helpers ($, S, api, send, insertBlock …)
   only inside functions, which run after both files have loaded. */
"use strict";

/* ---------------------------------------------------------------- reminders */

function renderPlaceholder(c, b) {
  if (b.role === "chart") {
    c.innerHTML =
      '<div class="dk-ph dk-ph-chart" tabindex="0" aria-label="Planned chart: ' + escapeHtml(b.text) + '">' +
      '<p class="dk-ph-k">Planned Chart</p><p class="dk-ph-t"></p>' +
      '<div class="dk-ph-acts">' +
      '<button type="button" class="dk-mini" data-ph="find">Find in Plover Data</button>' +
      '<button type="button" class="dk-mini" data-ph="suggest">Suggest a Chart</button>' +
      '<button type="button" class="dk-mini" data-ph="shot">Paste a Screenshot</button>' +
      '<button type="button" class="linkish" data-ph="done">Remove</button></div>' +
      '<p class="dk-ph-hint">Have another publisher’s chart (FT, Nikkei, a broker)? Click this box and paste a ' +
      "screenshot, or drop the image here: it is rebuilt from the public data behind it.</p>" +
      '<p class="dk-ph-status" role="status" aria-live="polite" hidden></p>' +
      '<input type="file" accept="image/png,image/jpeg,image/webp" hidden data-ph="file"></div>';
  } else {
    c.innerHTML =
      '<div class="dk-ph dk-ph-text"><span class="dk-ph-k">To Show</span><span class="dk-ph-t"></span>' +
      '<button type="button" class="dk-mini" data-ph="done" title="The section makes this point: remove the reminder">Done</button></div>';
  }
  $(".dk-ph-t", c).textContent = b.text || "";
}

function placeholderClick(blockEl, model, t) {
  var act = t.closest("[data-ph]");
  act = act && act.getAttribute("data-ph");
  if (act === "done") {
    pushUndo("reminder");
    var next = blockEl.nextElementSibling || blockEl.previousElementSibling;
    removeBlock(blockEl);
    if (next) focusBlock(next, false);
    toast(model.role === "chart" ? "Planned chart removed." : "Reminder removed.", true);
  } else if (act === "find") {
    openResearchTab({ kind: "data", q: searchWords(model.text), title: searchWords(model.text), slot: model.id });
  } else if (act === "suggest") {
    suggestChart(model.id);
  } else if (act === "shot") {
    pasteFromClipboard(blockEl, model);
  } else if (!act) {
    var box = t.closest(".dk-ph-chart");
    if (box) box.focus();
  }
}

/* The chart reminders in the draft, in order: [{id, text}]. */
function plannedCharts() {
  return $all('.dk-block[data-type="placeholder"]', blocksEl()).map(function (el) {
    return S.models[el.getAttribute("data-id")];
  }).filter(function (m) { return m && m.role === "chart"; }).map(function (m) { return { id: m.id, text: m.text }; });
}

function headingAbove(el) {
  var p = el.previousElementSibling;
  while (p) {
    var m = S.models[p.getAttribute("data-id")];
    if (m && m.type === "heading") return readBlock(p).text;
    p = p.previousElementSibling;
  }
  return "";
}

/* Ask the writer's AI for charts for one planned chart; each comes back as a
   button that puts it in place of the reminder. */
function suggestChart(slotId) {
  var el = slotEl(slotId);
  if (!el) { toast("That planned chart is no longer in the draft."); return; }
  var m = S.models[slotId];
  var h = headingAbove(el);
  aiRunFor("Suggest charts for one planned chart only: the line “[[Chart: " + m.text + "]]”" +
    (h ? " under the heading “" + h + "”" : "") + ". Read the section and the plan, find the data " +
    "(Plover first), and propose up to three charts that make the section's point, each checked against " +
    "the data. Offer each with offer_next_step: label “Use: <three or four words>”, no skill, " +
    "instruction “Replace the line [[Chart: " + m.text + "]] with this chart line, changing nothing " +
    "else: <the exact chart line>”.", "Find Charts");
}

/* ---------------------------------------------------------------- screenshots */

function phStatus(blockEl, text, bad) {
  var st = $(".dk-ph-status", blockEl);
  if (!st) return;
  st.hidden = !text;
  st.className = "dk-ph-status" + (bad ? " bad" : "");
  st.textContent = text || "";
}

/* Paste a Screenshot: read an image straight off the clipboard where the
   browser allows it; otherwise choose a file. */
function pasteFromClipboard(blockEl, model) {
  var pick = function () { $('[data-ph="file"]', blockEl).click(); };
  if (!navigator.clipboard || !navigator.clipboard.read) { pick(); return; }
  navigator.clipboard.read().then(function (items) {
    for (var i = 0; i < items.length; i++) {
      var type = items[i].types.filter(function (x) { return /^image\//.test(x); })[0];
      if (type) {
        return items[i].getType(type).then(function (blob) {
          rebuildFromPicture(blockEl, model, new File([blob], "screenshot." + type.split("/")[1], { type: type }));
        });
      }
    }
    phStatus(blockEl, "There is no picture on your clipboard. Take a screenshot (on a Mac, Cmd+Ctrl+Shift+4), " +
      "then press Paste a Screenshot again — or choose an image file.", true);
    pick();
  }).catch(pick);
}

function uploadPicture(file) {
  return fetch("/admin/api/research/media", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": file.type || "application/octet-stream", "X-File-Name": file.name || "screenshot.png" },
    body: file,
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (body) {
      if (!r.ok) throw new Error(body.detail || "The upload failed (" + r.status + ")");
      return body;
    });
  });
}

/* A screenshot dropped or pasted on a planned chart: upload it, then have the
   AI rebuild the chart from the public data and put it in the reminder's
   place. The picture itself never goes in the article. */
function rebuildFromPicture(blockEl, model, file) {
  if (!/^image\/(png|jpeg|webp)$/.test(file.type || "")) {
    phStatus(blockEl, "That is not a PNG, JPEG or WebP image.", true);
    return;
  }
  phStatus(blockEl, "Uploading the screenshot…");
  uploadPicture(file).then(function (info) {
    phStatus(blockEl, "Screenshot received. The AI is finding the data behind it — follow it in the AI tab.");
    var h = headingAbove(blockEl);
    aiRunFor("Rebuild the chart in the attached screenshot and put it in place of the line “[[Chart: " +
      model.text + "]]”" + (h ? " under the heading “" + h + "”" : "") +
      ", changing nothing else in the draft.", "", info.media + "." + info.ext, function () {
        phStatus(blockEl, "The rebuild did not start. See the AI tab for why.", true);
      });
  }).catch(function (err) { phStatus(blockEl, err.message, true); });
}

/* The same for an image already in the draft (a screenshot pasted into the
   text becomes an image block): replace it with the rebuilt chart. */
function rebuildImage(blockEl, model, btn) {
  if (!model.media) return;
  btn.disabled = true;
  aiRunFor("Rebuild the chart in the attached screenshot and put it in place of the image " +
    "/research/media/" + model.media + "." + model.ext + " (that image line goes: the rebuilt chart replaces it), " +
    "changing nothing else in the draft.", "", model.media + "." + model.ext, function () { btn.disabled = false; });
}

/* Cmd+V on a focused planned chart. */
function placeholderPaste(e) {
  var box = document.activeElement && document.activeElement.closest && document.activeElement.closest(".dk-ph-chart");
  if (!box || !e.clipboardData) return;
  var file = Array.prototype.slice.call(e.clipboardData.files || []).filter(function (f) { return /^image\//.test(f.type); })[0];
  e.preventDefault();
  e.stopPropagation();
  var blockEl = blockOf(box);
  if (!file) {
    phStatus(blockEl, "Only a picture can be pasted here: take a screenshot of the chart (on a Mac, Cmd+Ctrl+Shift+4) and paste again.", true);
    return;
  }
  rebuildFromPicture(blockEl, S.models[blockEl.getAttribute("data-id")], file);
}

/* An image file dropped on a planned chart. */
function placeholderDrop(e) {
  var box = e.target.closest && e.target.closest(".dk-ph-chart");
  if (!box) return false;
  var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (!file) return false;
  e.preventDefault();
  box.classList.remove("over");
  var blockEl = blockOf(box);
  rebuildFromPicture(blockEl, S.models[blockEl.getAttribute("data-id")], file);
  return true;
}

/* ---------------------------------------------------------------- start writing */

function hasPlanHeading(blocks) {
  return blocks.some(function (b) { return b.type === "heading" && /^plan$/i.test((b.text || "").trim()); });
}

/* The bar above (and below) a plan that is still in the page. */
function planBar() {
  var top = $("#dk-planbar");
  var end = $("#dk-planbar-end");
  if (!top) return;
  var heads = $all('.dk-block[data-type="h2"], .dk-block[data-type="h3"]', blocksEl()).map(readBlock);
  var show = !S.plan && hasPlanHeading(heads);
  [top, end].forEach(function (bar, i) {
    if (!show) { bar.hidden = true; bar.innerHTML = ""; return; }
    if (!bar.hidden && bar.innerHTML) return;
    bar.hidden = false;
    bar.innerHTML = '<div class="dk-planbar-t"><strong>' + (i ? "Happy with the plan?" : "This is the plan, not the article yet.") +
      "</strong><span>" + (i ? "It is kept beside your draft, and you can still change it while you write."
        : "Read it and change anything. Start Writing turns the outline into your sections and keeps the plan beside the draft.") +
      '</span></div><button type="button" class="btn btn-primary" data-startwriting="1">Start Writing</button>';
    $("[data-startwriting]", bar).addEventListener("click", startWriting);
  });
}

function blockText(b) {
  if (b.type === "heading") return b.text || "";
  if (b.type === "list") return b.items.map(textOf).join(" ");
  return textOf(b.html || "");
}

/* The outline's points: [{heading, claim, chart}]. The list after a heading
   (or bold line) called "Outline"; failing that, the first numbered list. */
function parseOutline(blocks) {
  var list = null;
  for (var i = 0; i < blocks.length && !list; i++) {
    var b = blocks[i];
    var isOutline = (b.type === "heading" || b.type === "p") && /^\s*outline\s*:?\s*$/i.test(blockText(b));
    if (isOutline) {
      for (var j = i + 1; j < blocks.length; j++) {
        if (blocks[j].type === "list") { list = blocks[j]; break; }
        if (blocks[j].type === "heading") break;
      }
    }
  }
  if (!list) list = blocks.filter(function (b) { return b.type === "list" && b.style === "number"; })[0];
  if (!list) return [];
  return list.items.map(outlineItem).filter(function (x) { return x.heading; });
}

function outlineItem(html) {
  var div = document.createElement("div");
  div.innerHTML = cleanInline(html);
  var chart = "";
  $all("em", div).forEach(function (em) {
    var t = em.textContent.replace(/\s+/g, " ").trim();
    if (!chart && /^(chart|figure|table)\b/i.test(t)) {
      chart = t.replace(/^(chart|figure)\s*\d*\s*[:—–-]?\s*/i, "").replace(/([a-z0-9)])\.$/, "$1").trim();
      chart = chart.charAt(0).toUpperCase() + chart.slice(1);
      em.parentNode.removeChild(em);
    }
  });
  var heading = "";
  var strong = div.querySelector("strong");
  var first = div.firstChild;
  while (first && first.nodeType === 3 && !first.textContent.trim()) first = first.nextSibling;
  if (strong && strong === first) {
    heading = strong.textContent.replace(/\s+/g, " ").trim();
    strong.parentNode.removeChild(strong);
  }
  var text = div.textContent.replace(/\s+/g, " ").trim();
  if (!heading) {
    var m = /^([^—–:]{3,90}?)\s*[—–:]\s*(.*)$/.exec(text);
    if (m) { heading = m[1]; text = m[2]; } else { heading = text.slice(0, 90); text = ""; }
  }
  text = text.replace(/^[—–:\-\s]+/, "").trim();
  if (!chart) {
    var c = /(^|[.;]\s+)(?:chart|figure)\s*\d*\s*:\s*([^.]+)\.?\s*$/i.exec(text);
    if (c) {
      chart = c[2].trim();
      chart = chart.charAt(0).toUpperCase() + chart.slice(1);
      text = text.slice(0, c.index + (c[1] ? 1 : 0)).trim();
    }
  }
  return { heading: heading.replace(/[\s.:—–-]+$/, "").trim(), claim: text, chart: chart };
}

/* The plan's "Expected answer", for the Check tab. */
function expectedAnswer(blocks) {
  for (var i = 0; i < blocks.length; i++) {
    var t = blockText(blocks[i]).trim();
    if (/^expected answer\b/i.test(t)) {
      var rest = t.replace(/^expected answer\s*[:—–-]?\s*/i, "");
      if (rest) return rest;
      var next = blocks[i + 1];
      return next ? blockText(next).trim() : "";
    }
  }
  return "";
}

function startWriting() {
  saveNow();
  var d = serialize();
  var all = d.blocks;
  var cut = all.length;
  for (var i = 0; i < all.length; i++) {
    if (all[i].type === "heading" && /^writer'?s notes$/i.test((all[i].text || "").replace(/’/g, "'"))) { cut = i; break; }
  }
  var planBlocks = all.slice(0, cut).filter(function (b) {
    return ["p", "heading", "list", "quote", "table", "divider"].indexOf(b.type) !== -1 &&
      (b.type !== "p" || textOf(b.html).trim());
  });
  var outline = parseOutline(planBlocks);
  // the writer's own notes from under "Writer's Notes" become notes
  var mine = [];
  all.slice(cut + 1).forEach(function (b) {
    (b.type === "list" ? b.items.map(textOf) : [blockText(b)]).forEach(function (t) {
      t = (t || "").trim();
      if (t) mine.push({ id: bid(), kind: "mine", text: t, html: "", source: "", url: "", section: "",
                         at: new Date().toISOString(), used: false });
    });
  });
  var skeleton = [];
  outline.forEach(function (p) {
    skeleton.push({ id: bid(), type: "heading", level: 2, text: p.heading });
    skeleton.push({ id: bid(), type: "p", html: "" });
    if (p.claim) skeleton.push({ id: bid(), type: "placeholder", role: "text", text: p.claim });
    if (p.chart) skeleton.push({ id: bid(), type: "placeholder", role: "chart", text: p.chart });
  });
  if (!skeleton.length) skeleton.push({ id: bid(), type: "p", html: "" });
  pushUndo("start writing");
  d.blocks = skeleton;
  if (/plan for approval|not a draft/i.test(d.dek || "")) d.dek = "";
  d.plan = { blocks: planBlocks, approved_at: new Date().toISOString(),
             approved_by: (S.me && (S.me.name || S.me.email)) || "" };
  d.notes = mine.concat(S.notes);
  renderDraft(d);
  changed();
  var first = $('.dk-block[data-type="p"]', blocksEl());
  if (first) focusBlock(first, false);
  toast(outline.length
    ? "The plan is in Research › Plan. Your draft now has " + outline.length + " sections, one per outline point."
    : "No outline was found, so you start from a blank page. The plan is in Research › Plan.", true);
  showPane("research");
  if (RT.tabs[0]) activateTab(RT.tabs[0]);
}

/* ---------------------------------------------------------------- progress */

/* Each section of the draft (a level-2 heading and what follows it): its
   words, the reminders left in it, and a status. */
function sectionStatus() {
  var out = [];
  var cur = null;
  $all(".dk-block", blocksEl()).forEach(function (el) {
    var m = S.models[el.getAttribute("data-id")];
    if (!m) return;
    if (m.type === "heading" && m.level === 2) {
      cur = { id: m.id, text: readBlock(el).text || "Untitled section", words: 0, reminders: 0, figures: 0, el: el };
      out.push(cur);
      return;
    }
    if (!cur) return;
    if (m.type === "placeholder") cur.reminders++;
    else if (TEXT_TYPES[m.type]) cur.words += ((el.querySelector(".dk-content").textContent || "").match(/\S+/g) || []).length;
    else if (FIGURE_TYPES[m.type]) cur.figures++;
  });
  out.forEach(function (s) {
    s.status = !s.words ? "Not Started" : s.reminders ? "Writing" : "Done";
    s.cls = !s.words ? "todo" : s.reminders ? "doing" : "done";
  });
  return out;
}

function goToBlock(id) {
  var el = blocksEl().querySelector('.dk-block[data-id="' + id + '"]');
  if (!el) { toast("That part is no longer in the draft."); return; }
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  el.classList.add("dk-flash");
  setTimeout(function () { el.classList.remove("dk-flash"); }, 1200);
  var nxt = el;
  var m = S.models[id];
  if (m && m.type === "heading") {
    // land in the first paragraph of the section, ready to write
    var n = el.nextElementSibling;
    while (n && (S.models[n.getAttribute("data-id")] || {}).type !== "p" &&
           (S.models[n.getAttribute("data-id")] || {}).type !== "heading") n = n.nextElementSibling;
    if (n && (S.models[n.getAttribute("data-id")] || {}).type === "p") nxt = n;
  }
  focusBlock(nxt, true);
}

/* ---------------------------------------------------------------- check */

/* A paragraph or list item with figures in it and no footnote. Years and
   section numbers do not count; percentages, decimals, grouped thousands and
   money do. */
var FIGURE_RE = /(\d[\d,]*\.\d+|\d{1,3}(,\d{3})+|\d+(\.\d+)?\s?(%|pp\b|percent|bn\b|billion|million|trillion|tn\b)|[¥$€£]\s?\d)/i;

function unsourced() {
  var out = [];
  $all(".dk-block", blocksEl()).forEach(function (el) {
    var m = S.models[el.getAttribute("data-id")];
    if (!m || (m.type !== "p" && m.type !== "list" && m.type !== "quote")) return;
    var parts = m.type === "list" ? $all("li", el) : [el.querySelector(".dk-text")];
    parts.forEach(function (part) {
      if (!part) return;
      var text = (part.textContent || "").replace(/\s+/g, " ").trim();
      var hit = FIGURE_RE.exec(text);
      if (hit && !part.querySelector("sup[data-note]")) {
        out.push({ id: m.id, figure: hit[0].trim(), text: text });
      }
    });
  });
  return out;
}

function lastParagraph() {
  var ps = $all('.dk-block[data-type="p"] .dk-text', blocksEl()).map(function (x) {
    return (x.textContent || "").replace(/\s+/g, " ").trim();
  }).filter(function (t) { return t; });
  return ps.length ? ps[ps.length - 1] : "";
}

function clip(text, n) { return text.length > n ? text.slice(0, n - 1) + "…" : text; }

function renderCheckPane(res) {
  var box = $("#dk-pane-check");
  var server = res.problems.filter(function (p) { return p.indexOf("From the plan, ") !== 0; });
  var left = $all('.dk-block[data-type="placeholder"]', blocksEl()).map(function (el) {
    var m = S.models[el.getAttribute("data-id")];
    return { id: m.id, role: m.role, text: m.text, where: headingAbove(el) };
  });
  var loose = unsourced();
  var fix = left.length + server.length;
  var look = loose.length + (S.plan ? 1 : 0);
  var html = '<p class="dk-ck-sum">' + (fix ? fix + " to fix before publishing" : "Nothing blocks publishing") +
    (look ? ", " + look + " to look at" : "") + ".</p>";

  if (fix) {
    html += '<p class="dk-ck-h">Fix Before Publishing</p><ul class="dk-ck">' +
      left.map(function (p) {
        return '<li><span class="dk-ck-t">' + (p.role === "chart" ? "Planned chart still empty" : "Point still to make") +
          (p.where ? " in “" + escapeHtml(p.where) + "”" : "") + ": " + escapeHtml(clip(p.text, 160)) + "</span>" +
          '<button type="button" class="dk-mini" data-goto="' + p.id + '">Go to It</button></li>';
      }).join("") +
      server.map(function (p) { return '<li><span class="dk-ck-t">' + escapeHtml(p) + "</span>" + fixButton(p) + "</li>"; }).join("") +
      "</ul>";
  }
  if (look) {
    html += '<p class="dk-ck-h">Worth a Look</p><ul class="dk-ck">' +
      loose.map(function (u) {
        return '<li><span class="dk-ck-t">A figure with no footnote: <strong>' + escapeHtml(u.figure) + "</strong> in “" +
          escapeHtml(clip(u.text, 90)) + '”</span><button type="button" class="dk-mini" data-goto="' + u.id + '">Go to It</button></li>';
      }).join("") +
      (S.plan ? titleCheck() : "") + "</ul>";
  }
  if (S.plan) html += progressHtml(left);
  if (!fix) html += '<p class="dk-ready">Ready to publish as version ' + res.version + ".</p>";
  box.innerHTML = html;
  $all("[data-goto]", box).forEach(function (b) {
    b.addEventListener("click", function () { goToBlock(b.getAttribute("data-goto")); });
  });
  $all("[data-fix]", box).forEach(function (b) {
    b.addEventListener("click", function () {
      var f = b.getAttribute("data-fix");
      if (f === "title") { $("#dk-title").focus(); $("#dk-title").scrollIntoView({ block: "center" }); return; }
      showPane("details");
      var target = $("#dk-" + f);
      if (target) { target.focus(); target.scrollIntoView({ block: "center" }); }
    });
  });
  var keep = $("[data-titleok]", box);
  if (keep) keep.addEventListener("click", function () { keep.closest("li").innerHTML = '<span class="dk-ck-t muted">Title checked against the draft.</span>'; });
}

/* A server problem that a field fixes gets a button that goes to the field. */
function fixButton(p) {
  var f = /^Add a title/.test(p) ? "title" : /summary/i.test(p) && /^Add a summary/.test(p) ? "summary"
    : /web address/i.test(p) ? "slug" : /Choose the market/.test(p) ? "market" : /author/i.test(p) && /Choose at least/.test(p) ? "authors" : "";
  return f ? '<button type="button" class="dk-mini" data-fix="' + f + '">' + (f === "title" ? "Go to It" : "Set It") + "</button>" : "";
}

function titleCheck() {
  var exp = expectedAnswer(S.plan.blocks);
  var last = lastParagraph();
  return '<li class="dk-ck-title"><span class="dk-ck-t">Does the title still match what the draft found?</span>' +
    '<dl class="dk-ck-cmp"><dt>Title</dt><dd>' + escapeHtml($("#dk-title").value || "No title yet") + "</dd>" +
    (exp ? "<dt>The plan expected</dt><dd>" + escapeHtml(clip(exp, 260)) + "</dd>" : "") +
    "<dt>The draft ends</dt><dd>" + escapeHtml(last ? clip(last, 260) : "Nothing written yet.") + "</dd></dl>" +
    '<span class="dk-ck-acts"><button type="button" class="dk-mini" data-titleok="1">Still Matches</button>' +
    '<button type="button" class="dk-mini" data-fix="title">Edit Title</button></span></li>';
}

function progressHtml(left) {
  var secs = sectionStatus();
  var written = secs.filter(function (s) { return s.words; }).length;
  var planned = parseOutline(S.plan.blocks).filter(function (p) { return p.chart; }).length;
  var empty = left.filter(function (p) { return p.role === "chart"; }).length;
  var unused = S.notes.filter(function (n) { return !n.used && n.kind !== "mine"; }).length;
  function row(label, a, b) {
    var pct = b ? Math.round(100 * a / b) : 0;
    return '<div class="dk-ck-prog"><span>' + label + '</span><span class="num">' + a + " of " + b + "</span></div>" +
      '<div class="dk-ck-bar" role="img" aria-label="' + a + " of " + b + '"><i style="width:' + pct + '%"></i></div>';
  }
  return '<p class="dk-ck-h">Against the Plan</p>' +
    (secs.length ? row("Sections written", written, secs.length) : "") +
    (planned ? row("Planned charts placed", Math.max(0, planned - empty), planned) : "") +
    '<div class="dk-ck-prog"><span>Notes not yet used</span><span class="num">' + unused + "</span></div>";
}
