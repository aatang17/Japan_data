/* Admin → Assistant Settings: PloverResearch's skills, house style and
   connectors, and the signed-in person's Google Drive. The AI tab uses them on
   PloverResearch's articles (app/research_ai.py); the API is
   app/ai_setup_api.py. Every other publication keeps its own in the Writer
   Desk (write.js, #/p/<id>/assistant).

   Writers edit skills and the house style. Connectors and the team's Drive
   switch need the Team permission: they decide what an AI run can reach.
   Loaded before admin.js; uses its api(), post(), ME and loadFailed(). */
"use strict";

var AIS = { data: null, open: null };

function aisSend(method, path, body) {
  return api(path, { method: method, headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) });
}

var GOOGLE_FLASH = {
  connected: ["ok", "Google Drive is connected. The AI tab can now search and read your files."],
  refused: ["bad", "Google Drive was not connected: the Google sign-in was cancelled."],
  expired: ["bad", "That Google sign-in took too long or was started elsewhere. Try again."],
  failed: ["bad", "Google did not complete the connection. Try again; if it repeats, disconnect " +
    "Plover in your Google account's third-party access and connect once more."],
};

function viewAISetup(target) {
  target.innerHTML = '<div class="admin-loading">Loading assistant settings…</div>';
  api("/ai/setup").then(function (d) {
    AIS.data = d;
    drawAISetup(target);
  }).catch(function (err) { target.innerHTML = loadFailed("assistant settings", err); });
}

function aisFlash() {
  var m = /[?&]google=([a-z]+)/.exec(location.search);
  if (!m || !GOOGLE_FLASH[m[1]]) return "";
  var f = GOOGLE_FLASH[m[1]];
  try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) { /* ignore */ }
  return '<div class="' + (f[0] === "ok" ? "ais-ok" : "admin-alert") + '" role="status">' + escapeHtml(f[1]) + "</div>";
}

function drawAISetup(target) {
  var d = AIS.data;
  target.innerHTML =
    '<div class="admin-page-head"><h1>Assistant Settings</h1>' +
    '<p class="admin-page-sub">PloverResearch\'s skills, house style and connections, used by the AI tab on its articles. ' +
    "Other publications keep their own in the Writer Desk; Google Drive is each person's own.</p></div>" +
    aisFlash() +
    '<div class="admin-section">Skills <span class="note">' + d.skills.length + "</span></div>" +
    '<p class="ais-sub">Playbooks the AI follows. A writer picks one in the AI tab, or the AI opens ' +
    "one itself when an instruction matches its description.</p>" +
    '<ul class="ais-list" id="ais-skills">' + d.skills.map(skillRow).join("") + "</ul>" +
    '<button type="button" class="btn" id="ais-add-skill">Add Skill</button>' +
    '<div id="ais-skill-new"></div>' +
    '<div class="admin-section">House Style</div>' +
    '<p class="ais-sub">Sent with every run: how anything written into a draft should read.</p>' +
    '<div class="field ais-wide"><textarea id="ais-style" rows="12" maxlength="8000" aria-label="House style">' +
    escapeHtml(d.house_style) + "</textarea></div>" +
    '<div class="edit-acts"><button type="button" class="btn btn-primary" id="ais-style-save">Save House Style</button>' +
    '<button type="button" class="btn" id="ais-style-reset">Reset to Default</button>' +
    '<span class="hint" id="ais-style-msg"></span></div>' +
    '<div class="admin-section">Google Drive</div>' + googleBlock(d) +
    '<div class="admin-section">Connectors <span class="note">' + d.connectors.length + "</span></div>" +
    '<p class="ais-sub">Outside tool servers (MCP) a run may call: a research database, a notes app, ' +
    "an internal tool. Each call is listed in the AI tab's steps." +
    (d.can_manage ? "" : " Adding and changing connectors needs the Team permission.") + "</p>" +
    (d.connectors.length ? '<ul class="ais-list" id="ais-conns">' + d.connectors.map(connRow).join("") + "</ul>"
      : '<p class="table-empty">No connectors yet.</p>') +
    (d.can_manage ? '<button type="button" class="btn" id="ais-add-conn">Add Connector</button><div id="ais-conn-new"></div>' : "");
  wireAISetup(target);
}

/* ---------- skills ---------- */

function skillRow(s) {
  return '<li data-skill="' + s.id + '"><div class="ais-row">' +
    '<span class="ais-main"><strong>' + escapeHtml(s.name) + "</strong> " +
    '<span class="ais-desc">' + escapeHtml(s.description) + "</span></span>" +
    (s.writes ? "" : '<span class="badge badge-neutral">Answers Only</span>') +
    (s.enabled ? "" : '<span class="badge badge-neutral">Off</span>') +
    '<button type="button" class="btn" data-skill-edit="' + s.id + '">Edit</button></div>' +
    '<div class="ais-edit" id="skill-edit-' + s.id + '" hidden></div></li>';
}

function skillForm(s) {
  s = s || { name: "", description: "", instructions: "", enabled: true, writes: true };
  return '<div class="form-grid">' +
    '<div class="field"><label>Name</label><input type="text" data-f="name" maxlength="60" value="' + escapeHtml(s.name) + '"></div>' +
    '<div class="field"><label>Status</label><label class="ais-check"><input type="checkbox" data-f="enabled"' +
    (s.enabled ? " checked" : "") + "> Offered in the AI tab</label>" +
    '<label class="ais-check"><input type="checkbox" data-f="writes"' +
    (s.writes ? " checked" : "") + "> Can change the draft</label>" +
    '<span class="hint">Untick for a skill that only answers, such as Brainstorm or Review: the writer keeps editing while it runs.</span></div>' +
    '<div class="field wide"><label>When to Use It</label><input type="text" data-f="description" maxlength="300" value="' +
    escapeHtml(s.description) + '"><span class="hint">One line. The AI reads it to decide when the skill applies.</span></div>' +
    '<div class="field wide"><label>Steps</label><textarea data-f="instructions" rows="16" maxlength="20000">' +
    escapeHtml(s.instructions) + '</textarea><span class="hint">Plain Markdown: what to do, in order, and what never to do. ' +
    "The AI has the draft tools, Plover's data, web pages, Google Drive and the connectors. " +
    "To end with a button for the next step, tell it to call <code>offer_next_step</code> with a label, a skill and an instruction.</span></div></div>" +
    '<div class="edit-acts"><button type="button" class="btn btn-primary" data-act="save">Save</button>' +
    '<button type="button" class="btn" data-act="cancel">Cancel</button>' +
    (s.id ? '<button type="button" class="btn btn-danger" data-act="delete">Delete</button>' : "") +
    '<span class="hint" data-msg></span></div>';
}

function formValues(box) {
  var out = {};
  Array.prototype.forEach.call(box.querySelectorAll("[data-f]"), function (el) {
    out[el.getAttribute("data-f")] = el.type === "checkbox" ? el.checked : el.value;
  });
  return out;
}

function openSkill(target, s, box) {
  box.innerHTML = skillForm(s);
  box.hidden = false;
  var msg = box.querySelector("[data-msg]");
  box.querySelector('[data-act="cancel"]').addEventListener("click", function () { box.hidden = true; box.innerHTML = ""; });
  box.querySelector('[data-act="save"]').addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    var v = formValues(box);
    (s ? aisSend("PUT", "/ai/skills/" + s.id, v) : post("/ai/skills", v)).then(function () {
      viewAISetup(target);
    }).catch(function (err) { b.disabled = false; msg.className = "hint bad"; msg.textContent = err.message; });
  });
  var del = box.querySelector('[data-act="delete"]');
  if (del) del.addEventListener("click", function () {
    if (del.getAttribute("data-armed") !== "1") {
      del.setAttribute("data-armed", "1");
      del.textContent = "Delete — Click Again";
      return;
    }
    del.disabled = true;
    aisSend("DELETE", "/ai/skills/" + s.id).then(function () { viewAISetup(target); })
      .catch(function (err) { del.disabled = false; msg.textContent = err.message; });
  });
  var first = box.querySelector("input[type=text]");
  if (first && !s) first.focus();
}

/* ---------- Google Drive ---------- */

function googleBlock(d) {
  var g = d.google;
  var html = "";
  if (!g.configured) {
    html += '<div class="admin-alert"><span class="head">Google sign-in is not set up on this server.</span> ' +
      "In Google Cloud, create an OAuth client (Web application) with Google Drive API enabled, add " +
      '<code>' + escapeHtml(g.redirect_uri) + "</code> as an authorised redirect URI, and set " +
      "<code>GOOGLE_OAUTH_CLIENT_ID</code> and <code>GOOGLE_OAUTH_CLIENT_SECRET</code> on the server.</div>";
  }
  html += '<p class="ais-sub">Read-only: the AI can search your Drive and read a Doc, Sheet, PDF or text ' +
    "file. It never creates, edits or deletes anything there.</p>";
  if (d.can_manage) {
    html += '<label class="ais-check"><input type="checkbox" id="ais-g-team"' + (g.team_enabled ? " checked" : "") +
      "> Allow Google Drive for the team</label>";
  } else if (!g.team_enabled) {
    html += '<p class="ais-sub">Switched off for the team.</p>';
  }
  if (!g.personal) {
    html += '<p class="ais-sub">Sign in with your own account to connect your Drive.</p>';
  } else if (g.connected) {
    html += '<div class="ais-row ais-g"><span class="ais-main"><span class="badge badge-ok">Connected</span> ' +
      escapeHtml(g.email || "") + "</span>" +
      '<button type="button" class="btn" id="ais-g-off">Disconnect</button></div>';
  } else if (g.configured && g.team_enabled) {
    html += '<button type="button" class="btn btn-primary" id="ais-g-on">Connect Google Drive</button>';
  }
  return html + '<span class="hint" id="ais-g-msg"></span>';
}

/* ---------- connectors ---------- */

var AUTH_LABEL = { none: "No key", bearer: "Bearer key", header: "Key in a header" };

function connRow(c) {
  var state = c.last_error
    ? '<span class="badge badge-danger">Not Reachable</span>'
    : (c.checked_at ? '<span class="badge badge-ok">' + c.tools.filter(function (t) { return t.on; }).length +
      " of " + c.tools.length + " Tools On</span>" : '<span class="badge badge-neutral">Not Checked</span>');
  return '<li data-conn="' + c.id + '"><div class="ais-row">' +
    '<span class="ais-main"><strong>' + escapeHtml(c.label) + '</strong> <span class="ais-desc mono">' +
    escapeHtml(c.url) + "</span></span>" + (c.enabled ? "" : '<span class="badge badge-neutral">Off</span>') + state +
    '<button type="button" class="btn" data-conn-open="' + c.id + '">' + (AIS.data.can_manage ? "Manage" : "Tools") +
    "</button></div>" + '<div class="ais-edit" id="conn-' + c.id + '" hidden></div></li>';
}

function connForm(c) {
  c = c || { label: "", url: "", auth_kind: "none", header_name: "", enabled: true };
  return '<div class="form-grid">' +
    '<div class="field"><label>Name</label><input type="text" data-f="label" maxlength="40" value="' + escapeHtml(c.label) + '"></div>' +
    '<div class="field"><label>Server Address</label><input type="text" data-f="url" placeholder="https://…/mcp" value="' + escapeHtml(c.url) + '"></div>' +
    '<div class="field"><label>Sign-in</label><select data-f="auth_kind">' +
    Object.keys(AUTH_LABEL).map(function (k) {
      return '<option value="' + k + '"' + (k === c.auth_kind ? " selected" : "") + ">" + AUTH_LABEL[k] + "</option>";
    }).join("") + "</select></div>" +
    '<div class="field" data-hdr' + (c.auth_kind === "header" ? "" : " hidden") + '><label>Header Name</label>' +
    '<input type="text" data-f="header_name" placeholder="X-API-Key" value="' + escapeHtml(c.header_name || "") + '"></div>' +
    '<div class="field wide" data-key' + (c.auth_kind === "none" ? " hidden" : "") + '><label>Key</label>' +
    '<input type="password" data-f="key" autocomplete="off" placeholder="' +
    (c.has_key ? "Stored key ending " + escapeHtml(c.key_last4 || "") + " — paste to replace" : "Paste the key") + '">' +
    '<span class="hint">Stored encrypted; never shown again.</span></div>' +
    (c.id ? '<div class="field"><label>Status</label><label class="ais-check"><input type="checkbox" data-f="enabled"' +
      (c.enabled ? " checked" : "") + "> Available to AI runs</label></div>" : "") +
    "</div>";
}

function toolList(c) {
  if (!c.tools.length) return '<p class="ais-sub">' + (c.last_error ? escapeHtml(c.last_error) : "No tools listed yet. Press Check.") + "</p>";
  return (c.last_error ? '<p class="bad">Last check: ' + escapeHtml(c.last_error) + "</p>" : "") +
    '<p class="ais-sub">Tools the AI may call' + (c.server_name ? " (" + escapeHtml(c.server_name) + ")" : "") + ":</p>" +
    '<ul class="ais-tools">' + c.tools.map(function (t) {
      return '<li><label class="ais-check"><input type="checkbox" data-tool="' + escapeHtml(t.name) + '"' +
        (t.on ? " checked" : "") + (AIS.data.can_manage ? "" : " disabled") + "> <span class=\"mono\">" +
        escapeHtml(t.name) + "</span> " + escapeHtml((t.description || "").slice(0, 160)) + "</label></li>";
    }).join("") + "</ul>";
}

function openConn(target, c, box) {
  var manage = AIS.data.can_manage;
  box.innerHTML = (c ? toolList(c) : "") + (manage ? connForm(c) +
    '<div class="edit-acts"><button type="button" class="btn btn-primary" data-act="save">' + (c ? "Save" : "Add and Check") + "</button>" +
    (c ? '<button type="button" class="btn" data-act="check">Check Now</button>' : "") +
    '<button type="button" class="btn" data-act="cancel">Cancel</button>' +
    (c ? '<button type="button" class="btn btn-danger" data-act="delete">Remove</button>' : "") +
    '<span class="hint" data-msg></span></div>' : "");
  box.hidden = false;
  var msg = box.querySelector("[data-msg]");
  function fail(b) { return function (err) { if (b) b.disabled = false; if (msg) { msg.className = "hint bad"; msg.textContent = err.message; } }; }
  var kind = box.querySelector('[data-f="auth_kind"]');
  if (kind) kind.addEventListener("change", function () {
    box.querySelector("[data-hdr]").hidden = kind.value !== "header";
    box.querySelector("[data-key]").hidden = kind.value === "none";
  });
  Array.prototype.forEach.call(box.querySelectorAll("[data-tool]"), function (cb) {
    cb.addEventListener("change", function () {
      cb.disabled = true;
      aisSend("PUT", "/ai/connectors/" + c.id + "/tools", { tool: cb.getAttribute("data-tool"), on: cb.checked })
        .then(function () { cb.disabled = false; }).catch(function (err) { cb.checked = !cb.checked; cb.disabled = false; alertMsg(err); });
    });
  });
  function alertMsg(err) { if (msg) { msg.className = "hint bad"; msg.textContent = err.message; } }
  if (!manage) return;
  box.querySelector('[data-act="cancel"]').addEventListener("click", function () { box.hidden = true; box.innerHTML = ""; });
  box.querySelector('[data-act="save"]').addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    msg.className = "hint";
    msg.textContent = c ? "Saving…" : "Connecting to the server…";
    var v = formValues(box);
    (c ? aisSend("PUT", "/ai/connectors/" + c.id, v) : post("/ai/connectors", v)).then(function (res) {
      AIS.open = res.id;
      viewAISetup(target);
    }).catch(fail(b));
  });
  var chk = box.querySelector('[data-act="check"]');
  if (chk) chk.addEventListener("click", function () {
    chk.disabled = true;
    msg.className = "hint";
    msg.textContent = "Connecting…";
    post("/ai/connectors/" + c.id + "/check").then(function () { AIS.open = c.id; viewAISetup(target); }).catch(fail(chk));
  });
  var del = box.querySelector('[data-act="delete"]');
  if (del) del.addEventListener("click", function () {
    if (del.getAttribute("data-armed") !== "1") {
      del.setAttribute("data-armed", "1");
      del.textContent = "Remove — Click Again";
      return;
    }
    del.disabled = true;
    aisSend("DELETE", "/ai/connectors/" + c.id).then(function () { viewAISetup(target); }).catch(fail(del));
  });
}

/* ---------- wiring ---------- */

function wireAISetup(target) {
  var d = AIS.data;
  Array.prototype.forEach.call(target.querySelectorAll("[data-skill-edit]"), function (b) {
    b.addEventListener("click", function () {
      var id = Number(b.getAttribute("data-skill-edit"));
      var box = document.getElementById("skill-edit-" + id);
      if (!box.hidden) { box.hidden = true; box.innerHTML = ""; return; }
      openSkill(target, d.skills.filter(function (s) { return s.id === id; })[0], box);
    });
  });
  document.getElementById("ais-add-skill").addEventListener("click", function () {
    openSkill(target, null, document.getElementById("ais-skill-new"));
  });

  var styleMsg = document.getElementById("ais-style-msg");
  document.getElementById("ais-style-save").addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    aisSend("PUT", "/ai/house-style", { text: document.getElementById("ais-style").value }).then(function (res) {
      b.disabled = false;
      d.house_style = res.house_style;
      styleMsg.className = "hint";
      styleMsg.textContent = "Saved. The next run uses it.";
    }).catch(function (err) { b.disabled = false; styleMsg.className = "hint bad"; styleMsg.textContent = err.message; });
  });
  document.getElementById("ais-style-reset").addEventListener("click", function () {
    document.getElementById("ais-style").value = d.default_house_style;
    styleMsg.className = "hint";
    styleMsg.textContent = "Default restored here. Save to use it.";
  });

  var gMsg = document.getElementById("ais-g-msg");
  var team = document.getElementById("ais-g-team");
  if (team) team.addEventListener("change", function () {
    team.disabled = true;
    aisSend("PUT", "/ai/google/team", { on: team.checked }).then(function () { viewAISetup(target); })
      .catch(function (err) { team.checked = !team.checked; team.disabled = false; gMsg.textContent = err.message; });
  });
  var on = document.getElementById("ais-g-on");
  if (on) on.addEventListener("click", function () {
    on.disabled = true;
    on.textContent = "Opening Google…";
    post("/ai/google/start").then(function (res) { location.href = res.url; })
      .catch(function (err) { on.disabled = false; on.textContent = "Connect Google Drive"; gMsg.className = "hint bad"; gMsg.textContent = err.message; });
  });
  var off = document.getElementById("ais-g-off");
  if (off) off.addEventListener("click", function () {
    off.disabled = true;
    post("/ai/google/disconnect").then(function () { viewAISetup(target); })
      .catch(function (err) { off.disabled = false; gMsg.textContent = err.message; });
  });

  Array.prototype.forEach.call(target.querySelectorAll("[data-conn-open]"), function (b) {
    b.addEventListener("click", function () {
      var id = Number(b.getAttribute("data-conn-open"));
      var box = document.getElementById("conn-" + id);
      if (!box.hidden) { box.hidden = true; box.innerHTML = ""; return; }
      openConn(target, d.connectors.filter(function (c) { return c.id === id; })[0], box);
    });
  });
  var add = document.getElementById("ais-add-conn");
  if (add) add.addEventListener("click", function () { openConn(target, null, document.getElementById("ais-conn-new")); });
  if (AIS.open) {
    var box = document.getElementById("conn-" + AIS.open);
    var c = d.connectors.filter(function (x) { return x.id === AIS.open; })[0];
    AIS.open = null;
    if (box && c) openConn(target, c, box);
  }
}
