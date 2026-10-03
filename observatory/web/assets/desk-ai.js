/* Research Desk, part three: the AI tab.

   A writer connects their own model once — their Claude plan through Claude
   Code, their ChatGPT plan through Codex, or an OpenAI or Anthropic API key —
   then gives the open article an instruction. The server runs it against
   this draft only (app/research_ai.py): it reads and changes the draft,
   reads Plover data and web pages, and runs the checklist. It cannot publish.

   While it works, the canvas is paused (inert) so nobody's typing collides
   with its saves; the steps it takes are listed as they happen. When it
   finishes, the draft is reloaded from the server. "Undo AI Changes" puts
   back the "Before AI" copy the server kept in History, as a new revision.

   Loaded before desk.js; uses its helpers ($, S, api, send, renderDraft …)
   only inside functions, which run after both files have loaded. */
"use strict";

var AI = { settings: null, job: null, poll: null, codexPoll: null, setup: false };

var AI_EXAMPLES = [
  ["Draft from My Notes", "Turn my notes in the draft into a finished article: a clear argument, short paragraphs, and charts from Plover data where they help."],
  ["Add a Chart", "Add a Plover chart that supports the main point, with one sentence introducing it."],
  ["Check the Numbers", "Check every number in the draft against Plover data. Correct any that are wrong and tell me what you changed."],
  ["Tighten the Writing", "Tighten the writing: cut repetition and filler, keep my argument and every number."],
];

var AI_HELP = {
  claude_code: "Uses your Claude subscription. On your own computer, in Terminal, run " +
    "<code>claude setup-token</code>, sign in when the browser opens, and paste the token it prints " +
    "(it starts with <code>sk-ant-</code>). The token lasts a year.",
  codex: "Uses your ChatGPT subscription. Press Connect, open the link, sign in to ChatGPT and enter the code shown.",
  openai: "Paste an API key from platform.openai.com. Usage is billed to that account.",
  anthropic: "Paste an API key from console.anthropic.com. Usage is billed to that account.",
};

function aiKey() { return "dk-ai-job-" + ID; }

function renderAIPane() {
  var box = $("#dk-pane-ai");
  if (AI.job && AI.job.status === "running") return drawAI();
  box.innerHTML = '<p class="muted">Loading…</p>';
  api("/research/ai").then(function (s) {
    AI.settings = s;
    var saved = null;
    try { saved = localStorage.getItem(aiKey()); } catch (e) { /* storage blocked */ }
    if (saved && !AI.job) {
      return api("/research/ai/jobs/" + saved).then(function (j) {
        AI.job = j;
        if (j.status === "running") { pauseCanvas(true); followJob(); }
        drawAI();
      }).catch(function () { forgetJob(); drawAI(); });
    }
    drawAI();
  }).catch(function (err) {
    box.innerHTML = '<p class="bad">' + escapeHtml(err.message) + "</p>";
  });
}

function aiReady(s) {
  return s && s.provider && s.providers.some(function (p) { return p.key === s.provider && p.ready; });
}

function drawAI() {
  var box = $("#dk-pane-ai");
  var s = AI.settings;
  if (!s) return;
  if (AI.setup || !aiReady(s)) return drawSetup(box, s);
  var label = (s.providers.filter(function (p) { return p.key === s.provider; })[0] || {}).label;
  var running = AI.job && AI.job.status === "running";
  box.innerHTML =
    '<div class="dk-ai-using"><span>Using <strong>' + escapeHtml(label) + "</strong>" +
    (s.model ? ' <span class="mono">' + escapeHtml(s.model) + "</span>" : "") + "</span>" +
    '<button type="button" class="linkish" id="dk-ai-change"' + (running ? " disabled" : "") + ">Change</button></div>" +
    '<form id="dk-ai-form" class="dk-ai-form">' +
    '<label class="dk-flabel" for="dk-ai-text">Instruction</label>' +
    '<textarea id="dk-ai-text" rows="5" maxlength="8000" placeholder="What should it do with this draft?"' +
    (running ? " disabled" : "") + "></textarea>" +
    '<div class="dk-ai-ex">' + AI_EXAMPLES.map(function (e, i) {
      return '<button type="button" class="dk-mini" data-ex="' + i + '"' + (running ? " disabled" : "") + ">" +
        escapeHtml(e[0]) + "</button>";
    }).join("") + "</div>" +
    '<button type="submit" class="btn btn-primary" id="dk-ai-run"' + (running ? " disabled" : "") + ">" +
    (running ? "Working…" : "Run") + "</button></form>" +
    '<div id="dk-ai-job"></div>';
  $("#dk-ai-change").addEventListener("click", function () { AI.setup = true; drawAI(); });
  $all("[data-ex]", box).forEach(function (b) {
    b.addEventListener("click", function () {
      var ta = $("#dk-ai-text");
      ta.value = AI_EXAMPLES[Number(b.getAttribute("data-ex"))][1];
      ta.focus();
    });
  });
  $("#dk-ai-form").addEventListener("submit", function (e) {
    e.preventDefault();
    runAI($("#dk-ai-text").value);
  });
  drawJob();
}

function drawSetup(box, s) {
  var pick = s.provider || "claude_code";
  box.innerHTML =
    '<p class="hint">Connect your own AI once. It works on the open draft only and cannot publish. ' +
    "Your key or sign-in is stored encrypted and used only for your runs.</p>" +
    (s.keychain ? "" : '<p class="bad">This server cannot store keys yet: ASSISTANT_SECRET is not set.</p>') +
    '<fieldset class="dk-ai-prov"><legend class="dk-flabel">Connect With</legend>' +
    s.providers.map(function (p) {
      return '<label><input type="radio" name="dk-ai-p" value="' + p.key + '"' +
        (p.key === pick ? " checked" : "") + "> " + escapeHtml(p.label) +
        (p.ready ? ' <span class="dk-ai-ok">Connected</span>' : "") + "</label>";
    }).join("") + "</fieldset>" +
    '<div id="dk-ai-setup"></div>';
  $all('input[name="dk-ai-p"]', box).forEach(function (r) {
    r.addEventListener("change", function () { drawProvider(r.value); });
  });
  drawProvider(pick);
}

function drawProvider(p) {
  var s = AI.settings;
  var el = $("#dk-ai-setup");
  clearInterval(AI.codexPoll);
  var model = s.provider === p ? s.model : "";
  var missing = (p === "claude_code" && !s.claude_available) || (p === "codex" && !s.codex_available);
  var html = '<p class="hint">' + AI_HELP[p] + "</p>";
  if (missing) {
    html += '<p class="bad">' + (p === "codex" ? "Codex" : "Claude Code") + " is not installed on this server yet.</p>";
  }
  if (p === "openai" || p === "anthropic") {
    var have = s.provider === p && s.key_last4;
    html += '<div class="field"><label for="dk-ai-key">API Key</label>' +
      '<input type="password" id="dk-ai-key" autocomplete="off" placeholder="' +
      (have ? "Stored key ending " + escapeHtml(s.key_last4) + " — paste to replace" : "Paste the key") + '"></div>';
  } else if (p === "claude_code") {
    html += '<div class="field"><label for="dk-ai-tok">Token</label>' +
      '<input type="password" id="dk-ai-tok" autocomplete="off" placeholder="' +
      (s.claude_token ? "A token is stored — paste to replace" : "sk-ant-…") + '"></div>';
  } else {
    html += '<div id="dk-ai-codex"></div>';
  }
  html += '<div class="field"><label for="dk-ai-model">Model</label>' +
    '<select id="dk-ai-model" disabled><option>Loading…</option></select>' +
    '<input type="text" id="dk-ai-model-other" maxlength="80" placeholder="Model name, exactly as the provider writes it" hidden>' +
    '<span class="hint" id="dk-ai-model-note"></span></div>' +    '<div class="dk-ai-acts"><button type="button" class="btn btn-primary" id="dk-ai-save">Save</button>' +
    (aiReady(s) ? '<button type="button" class="btn" id="dk-ai-cancel">Cancel</button>' : "") +
    forgetButton(p, s) + "</div>" +
    '<p class="bad" id="dk-ai-err" hidden></p>';
  el.innerHTML = html;
  if (p === "codex") drawCodex();
  loadModels(p, model);
  $("#dk-ai-model").addEventListener("change", modelNote);
  if ($("#dk-ai-key")) $("#dk-ai-key").addEventListener("change", function () {
    var k = this.value.trim();
    if (k) loadModels(p, $("#dk-ai-model").value, k);
  });
  $("#dk-ai-save").addEventListener("click", function () { saveProvider(p); });
  if ($("#dk-ai-cancel")) $("#dk-ai-cancel").addEventListener("click", function () { AI.setup = false; drawAI(); });
  if ($("#dk-ai-forget")) $("#dk-ai-forget").addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    send("POST", "/research/ai/forget", { what: b.getAttribute("data-what") }).then(function (res) {
      AI.settings = res;
      toast("Removed.");
      drawAI();
    }).catch(function (err) { b.disabled = false; aiErr(err.message); });
  });
}

var MODEL_DEFAULT = {
  claude_code: "Default (Claude Code chooses)",
  codex: "Default (Codex chooses)",
};

/* The model menu: what this writer's plan or key actually offers, from the
   server; "Default" first, "Other…" last for a name the list does not show. */
function loadModels(p, current, key) {
  var sel = $("#dk-ai-model");
  if (!sel) return;
  sel.disabled = true;
  sel.innerHTML = "<option>Loading…</option>";
  send("POST", "/research/ai/models", { provider: p, key: key || null }).then(function (res) {
    if (!$("#dk-ai-model") || $("#dk-ai-model") !== sel) return;
    var opts = [];
    var def = MODEL_DEFAULT[p] || (res.default ? "Default (" + res.default + ")" : "Default");
    opts.push({ id: "", label: def, note: "" });
    res.models.forEach(function (m) { opts.push(m); });
    var known = opts.some(function (o) { return o.id === (current || ""); });
    if (current && !known) opts.push({ id: current, label: current, note: "Saved earlier; not in the current list." });
    opts.push({ id: "__other", label: "Other…", note: "" });
    sel.innerHTML = opts.map(function (o) {
      return '<option value="' + escapeHtml(o.id) + '" data-note="' + escapeHtml(o.note || "") + '"' +
        (o.id === (current || "") ? " selected" : "") + ">" + escapeHtml(o.label) + "</option>";
    }).join("");
    sel.disabled = false;
    modelNote(res.error);
  }).catch(function (err) {
    sel.innerHTML = '<option value="">Default</option><option value="__other">Other…</option>';
    sel.disabled = false;
    modelNote(err.message);
  });
}

function modelNote(problem) {
  var sel = $("#dk-ai-model");
  var other = $("#dk-ai-model-other");
  var note = $("#dk-ai-model-note");
  if (!sel || !note) return;
  var opt = sel.options[sel.selectedIndex];
  other.hidden = sel.value !== "__other";
  if (!other.hidden) other.focus();
  var text = typeof problem === "string" && problem ? problem : (opt && opt.getAttribute("data-note")) || "";
  note.textContent = text;
  note.className = typeof problem === "string" && problem ? "bad" : "hint";
}

function chosenModel() {
  var sel = $("#dk-ai-model");
  if (!sel || sel.disabled) return null;
  if (sel.value === "__other") return ($("#dk-ai-model-other").value || "").trim() || null;
  return sel.value || null;
}

function forgetButton(p, s) {
  var what = (p === "openai" || p === "anthropic") ? (s.provider === p && s.key_last4 ? "key" : "")
    : p === "claude_code" ? (s.claude_token ? "claude" : "") : (s.codex.connected ? "codex" : "");
  return what ? '<button type="button" class="btn btn-danger" id="dk-ai-forget" data-what="' + what + '">Remove</button>' : "";
}

function aiErr(msg) {
  var e = $("#dk-ai-err");
  if (!e) return toast(msg);
  e.textContent = msg;
  e.hidden = !msg;
}

function drawCodex() {
  var el = $("#dk-ai-codex");
  if (!el) return;
  var c = AI.settings.codex;
  if (c.connected) {
    el.innerHTML = '<p class="dk-ai-ok-line">Signed in to ChatGPT' + (c.email ? " as " + escapeHtml(c.email) : "") + ".</p>";
  } else if (c.pending) {
    el.innerHTML = '<ol class="dk-ai-steps-how"><li>Open <a href="' + escapeHtml(c.pending.url) +
      '" target="_blank" rel="noopener">' + escapeHtml(c.pending.url) + "</a></li>" +
      "<li>Sign in to ChatGPT and enter this code:</li></ol>" +
      '<p class="dk-ai-code mono">' + escapeHtml(c.pending.code) + "</p>" +
      '<p class="hint">Waiting for you to finish signing in…</p>';
    watchCodex();
  } else {
    el.innerHTML = (c.error ? '<p class="bad">' + escapeHtml(c.error) + "</p>" : "") +
      '<button type="button" class="btn" id="dk-ai-codex-go">Connect ChatGPT</button>';
    $("#dk-ai-codex-go").addEventListener("click", function () {
      var b = this;
      b.disabled = true;
      b.textContent = "Asking for a code…";
      send("POST", "/research/ai/codex/login").then(function (res) {
        AI.settings.codex = { connected: false, pending: { url: res.url, code: res.code } };
        drawCodex();
      }).catch(function (err) {
        b.disabled = false;
        b.textContent = "Connect ChatGPT";
        aiErr(err.message);
      });
    });
  }
}

function watchCodex() {
  clearInterval(AI.codexPoll);
  AI.codexPoll = setInterval(function () {
    if (!$("#dk-ai-codex")) return clearInterval(AI.codexPoll);
    api("/research/ai/codex").then(function (c) {
      if (c.pending) return;
      clearInterval(AI.codexPoll);
      AI.settings.codex = c;
      drawCodex();
      if (c.connected) loadModels("codex", "");
    }).catch(function () { /* keep waiting */ });
  }, 3000);
}

function saveProvider(p) {
  var b = $("#dk-ai-save");
  var body = { provider: p, model: chosenModel() };
  if ($("#dk-ai-key")) body.key = $("#dk-ai-key").value.trim() || null;
  if ($("#dk-ai-tok")) body.claude_token = $("#dk-ai-tok").value.trim() || null;
  if (p === "codex" && !AI.settings.codex.connected) return aiErr("Connect ChatGPT first.");
  if (p === "claude_code" && !body.claude_token && !AI.settings.claude_token) return aiErr("Paste the token first.");
  b.disabled = true;
  b.textContent = body.key ? "Checking the key…" : "Saving…";
  aiErr("");
  send("PUT", "/research/ai", body).then(function (res) {
    AI.settings = res;
    AI.setup = false;
    toast("Connected.");
    drawAI();
  }).catch(function (err) {
    b.disabled = false;
    b.textContent = "Save";
    aiErr(err.message);
  });
}

/* ---------------------------------------------------------------- a run */

function runAI(text) {
  text = (text || "").trim();
  if (!text) { $("#dk-ai-text").focus(); return; }
  var b = $("#dk-ai-run");
  b.disabled = true;
  b.textContent = "Saving your draft…";
  // the model must start from what is on screen
  saveNow().then(function () {
    if (S.seq !== S.savedSeq) throw new Error("Your latest changes are not saved yet; try again in a moment.");
    b.textContent = "Starting…";
    return send("POST", "/research/articles/" + ID + "/ai", { instruction: text });
  }).then(function (job) {
    AI.job = job;
    AI.lastInstruction = text;
    try { localStorage.setItem(aiKey(), job.id); } catch (e) { /* storage blocked */ }
    pauseCanvas(true);
    drawAI();
    followJob();
  }).catch(function (err) {
    b.disabled = false;
    b.textContent = "Run";
    toast(err.message);
  });
}

function pauseCanvas(on) {
  var c = $("#dk-canvas");
  if (!c) return;
  c.inert = on;
  c.classList.toggle("dk-paused", on);
  if (on) {
    showBanner("info", "The AI is working on this draft. Editing is paused until it finishes; " +
      "its changes appear here when it is done.", "ai");
  } else {
    hideBanner("ai");
  }
}

function followJob() {
  clearTimeout(AI.poll);
  AI.poll = setTimeout(function () {
    api("/research/ai/jobs/" + AI.job.id).then(function (j) {
      AI.job = j;
      if (j.status === "running") { drawJob(); followJob(); return; }
      finishJob(j);
    }).catch(function (err) {
      if (err.status === 404) {
        // the server restarted: the run is gone, the draft holds what it saved
        AI.job = { status: "failed", steps: [], error: "The run was interrupted (the server restarted). " +
          "Whatever it had saved is in the draft; History has the copy from before it started.", changed: true };
        finishJob(AI.job);
        return;
      }
      followJob();
    });
  }, 1500);
}

function finishJob(j) {
  var done = function () { pauseCanvas(false); drawAI(); };
  if (!j.changed) return done();
  api("/research/articles/" + ID).then(function (a) {
    pushUndo("ai");
    S.article = a;
    S.base = a.revision;
    renderDraft(a.draft);
    S.savedSeq = S.seq;
    clearBackup();
    setStatus("saved");
    done();
  }).catch(function (err) { toast(err.message); done(); });
}

function forgetJob() {
  try { localStorage.removeItem(aiKey()); } catch (e) { /* storage blocked */ }
}

var AI_STATUS = { running: "Working", done: "Finished", failed: "Stopped" };

function drawJob() {
  var el = $("#dk-ai-job");
  var j = AI.job;
  if (!el || !j) return;
  var steps = j.steps || [];
  el.innerHTML =
    '<div class="dk-ai-head"><span class="dk-flabel">' + escapeHtml(AI_STATUS[j.status] || "") +
    (j.provider_label ? " · " + escapeHtml(j.provider_label) : "") + "</span>" +
    (j.seconds !== undefined ? '<span class="num muted">' + fmtSecs(j.seconds) + "</span>" : "") + "</div>" +
    (steps.length ? '<ol class="dk-ai-steps">' + steps.map(function (s) {
      return '<li class="' + (s.kind === "error" ? "bad" : "") + '">' + escapeHtml(s.text) + "</li>";
    }).join("") + "</ol>" : (j.status === "running" ? '<p class="muted">Reading the draft…</p>' : "")) +
    (j.reply ? '<div class="dk-ai-reply">' + escapeHtml(j.reply).replace(/\n/g, "<br>") + "</div>" : "") +
    (j.error ? '<p class="bad">' + escapeHtml(j.error) + "</p>" : "") +
    (undoable(j) ? '<button type="button" class="btn" id="dk-ai-undo">Undo AI Changes</button>' : "");
  var u = $("#dk-ai-undo");
  if (u) u.addEventListener("click", function () {
    u.disabled = true;
    api("/research/articles/" + ID + "/history/" + j.before_history_id).then(function (res) {
      pushUndo("undo ai");
      renderDraft(res.draft);
      changed();
      u.remove();
      forgetJob();
      toast("Put back the draft from before the AI run. It saves as a new revision.", true);
    }).catch(function (err) { u.disabled = false; toast(err.message); });
  });
}

/* Undo is offered while the draft is still as the run left it: once anyone
   has edited it, History is the place to go back (the "Before AI" copy). */
function undoable(j) {
  return j.status !== "running" && j.changed && j.before_history_id &&
    (j.revision_after === undefined || j.revision_after === null || j.revision_after === S.base);
}

function fmtSecs(n) {
  return n < 60 ? n + " s" : Math.floor(n / 60) + " min " + (n % 60) + " s";
}
