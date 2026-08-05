/* Ask — a floating assistant over the published series.

   A launcher in the corner opens a chat panel. Answers are prose, so they get
   prose treatment, but each one carries the same provenance contract as every
   other number on the site: the release it came from and the exact lookups
   behind it, expandable in place.

   Conversation state lives here, in the browser, and is replayed to the server
   on each turn — the API keeps none. That is safe because every tool behind it
   is read-only over already-published statistics.

   The widget mounts itself on any page that loads this file, and stays absent
   unless the server reports the feature configured — an unconfigured
   deployment shows no broken affordance. */
"use strict";

const ASK_DATASET = "cpi-jp";
/* Visible turns kept client-side. The server clamps too; this stops a long
   session growing the request forever. */
const ASK_MAX_HISTORY = 12;

/* raw tool name -> what the reader sees; never render the raw value */
const LOOKUP_LABELS = {
  list_datasets: "Dataset catalogue",
  search_series: "Series search",
  get_series_values: "Series history",
  get_overview: "Latest overview",
  get_contributions: "Group contributions",
  get_breadth: "Item breadth",
};

const SUGGESTIONS = [
  "What is driving inflation right now?",
  "How much has rice risen in the past year?",
  "Is inflation broad or concentrated?",
];

/* The model is asked for a true minus; this catches an ASCII hyphen used as
   one. A digit-leading hyphen after whitespace or an opening bracket is a
   negative number — dates ("2026-06") and hyphenated words have no such gap. */
function fixMinus(text) {
  return text.replace(/(^|[\s(\[])-(?=\d)/g, "$1−");
}

/* Inline markdown, applied to ALREADY-ESCAPED text so nothing from the model
   can reach innerHTML raw. Only `**bold**` and `` `code` ``.

   The prompt asks for no bold, and the model emits it anyway — a soft
   formatting rule is not something a cheap model reliably honours, so the
   renderer handles what arrives rather than leaving literal asterisks on
   screen. Anything else degrades to plain text; it never breaks. */
function inlineMd(escaped) {
  return escaped
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
}

/* Answers are prose with "- " bullets, plus the inline marks above. */
function renderAnswer(text) {
  const blocks = fixMinus(text).split(/\n\s*\n/);
  let html = "";
  for (const block of blocks) {
    const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
    if (!lines.length) continue;
    if (lines.every((l) => /^[-•*]\s+/.test(l))) {
      html += "<ul>" + lines
        .map((l) => "<li>" + inlineMd(escapeHtml(l.replace(/^[-•*]\s+/, ""))) + "</li>")
        .join("") + "</ul>";
    } else {
      html += "<p>" + inlineMd(escapeHtml(lines.join(" "))) + "</p>";
    }
  }
  return html || "<p>" + inlineMd(escapeHtml(text)) + "</p>";
}

function lookupDetail(call) {
  const a = call.args || {};
  const bits = [];
  if (a.dataset) bits.push(a.dataset);
  if (a.query) bits.push('"' + a.query + '"');
  if (a.series_codes) bits.push(a.series_codes);
  if (a.measure) bits.push(MEASURE_SHORT[a.measure] || a.measure);
  if (a.threshold !== undefined) bits.push("threshold " + fmtRate(a.threshold));
  if (call.note) bits.push(call.note);
  return bits.join(" · ");
}

/* Distinct source releases behind an answer, in first-use order. A question
   can span both tables, so this is not always the path dataset's release. */
function sourcesUsed(calls, release) {
  const seen = new Map();
  for (const c of calls) {
    if (c.source_name && !seen.has(c.source_name)) {
      seen.set(c.source_name, c.latest_period);
    }
  }
  if (!seen.size && release && release.source_name) {
    seen.set(release.source_name, release.latest_period);
  }
  return [...seen.entries()];
}

function renderLookups(calls, release) {
  // A follow-up ("and core?") is often answered from figures already fetched
  // earlier in the thread, with no new lookup. Saying so keeps the provenance
  // contract intact — silence would read as a number from nowhere.
  if (!calls.length) {
    return '<p class="ask-foot ask-carried">Figures carried from earlier in '
      + "this conversation.</p>";
  }
  const rows = calls.map((c) =>
    '<span class="ask-lookup-what">'
    + escapeHtml(LOOKUP_LABELS[c.tool] || c.tool) + "</span>"
    + '<span class="ask-lookup-detail">' + escapeHtml(lookupDetail(c))
    + "</span>").join("");
  const used = sourcesUsed(calls, release);
  const sources = used.map((s) => escapeHtml(s[0])
    + (s[1] ? " · data through " + escapeHtml(fmtPeriodLong(s[1])) : "")
  ).join("<br>");
  const noun = calls.length === 1 ? "lookup" : "lookups";
  return '<details class="calc"><summary>Data used — ' + calls.length + " " + noun
    + '</summary><div class="calc-body">'
    + '<div class="ask-lookups">' + rows + "</div>"
    + '<div class="ask-lookups ask-sources">'
    + '<span class="ask-lookup-what">' + (used.length === 1 ? "Source" : "Sources")
    + '</span><span class="ask-lookup-detail">' + sources + "</span></div>"
    + '<p class="ask-trust">Index values are official statistics as released; '
    + "rates of change are calculated from published index values. "
    + '<a href="methodology.html#trust">Definitions</a></p>'
    + "</div></details>";
}

/* ---- the widget ---- */

function initAsk() {
  if (document.getElementById("ask-root")) return;

  fetch("/api/v1/agent/info")
    .then((r) => r.json())
    .then((info) => { if (info.enabled) mountAsk(info); })
    .catch(() => { /* stay absent */ });
}

function mountAsk(info) {
  const root = document.createElement("div");
  root.id = "ask-root";
  root.innerHTML = [
    '<button type="button" class="ask-launcher" id="ask-launcher"',
    '        aria-expanded="false" aria-controls="ask-panel">Ask about this data</button>',
    '<div class="ask-scrim" id="ask-scrim" hidden></div>',
    '<section class="ask-panel" id="ask-panel" role="dialog" aria-modal="false"',
    '         aria-labelledby="ask-title" hidden>',
    '  <header class="ask-panel-head">',
    '    <h2 id="ask-title">Ask about this data</h2>',
    '    <button type="button" class="ask-close" id="ask-close"',
    '            aria-label="Close">Close</button>',
    "  </header>",
    '  <div class="ask-thread" id="ask-thread" aria-live="polite"></div>',
    '  <form class="ask-compose" id="ask-form">',
    '    <label class="visually-hidden" for="ask-input">Your question</label>',
    '    <input type="text" id="ask-input" autocomplete="off" maxlength="500"',
    '           placeholder="Ask a question…">',
    '    <button type="submit" class="btn btn-primary" id="ask-send">Send</button>',
    "  </form>",
    "</section>",
  ].join("\n");
  document.body.appendChild(root);

  const launcher = root.querySelector("#ask-launcher");
  const scrim = root.querySelector("#ask-scrim");
  const panel = root.querySelector("#ask-panel");
  const closeBtn = root.querySelector("#ask-close");
  const thread = root.querySelector("#ask-thread");
  const form = root.querySelector("#ask-form");
  const input = root.querySelector("#ask-input");
  const send = root.querySelector("#ask-send");

  if (info.max_question_chars) input.maxLength = info.max_question_chars;

  /* The visible conversation. Sent to the server each turn; it stores none. */
  const history = [];
  let inFlight = false;

  function open() {
    panel.hidden = false;
    scrim.hidden = false;
    launcher.setAttribute("aria-expanded", "true");
    if (!thread.childElementCount) renderEmptyState();
    input.focus();
  }

  function close() {
    panel.hidden = true;
    scrim.hidden = true;
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  }

  function scrollToEnd() { thread.scrollTop = thread.scrollHeight; }

  function renderEmptyState() {
    const el = document.createElement("div");
    el.className = "ask-empty";
    el.innerHTML = "<p>Answered from the series published here — every figure "
      + "is looked up, never recalled.</p>";
    const list = document.createElement("div");
    list.className = "ask-suggestions";
    for (const q of SUGGESTIONS) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ask-suggest";
      b.textContent = q;
      b.addEventListener("click", () => { input.value = q; submit(); });
      list.appendChild(b);
    }
    el.appendChild(list);
    thread.appendChild(el);
  }

  function clearEmptyState() {
    const el = thread.querySelector(".ask-empty");
    if (el) el.remove();
  }

  function addUser(text) {
    const el = document.createElement("div");
    el.className = "ask-msg ask-msg-user";
    el.textContent = text;
    thread.appendChild(el);
    scrollToEnd();
  }

  function addPending() {
    const el = document.createElement("div");
    el.className = "ask-msg ask-msg-agent ask-pending";
    el.innerHTML = '<p class="ask-working">Looking up the data…</p>'
      + '<div class="skeleton" style="height:52px"></div>';
    thread.appendChild(el);
    scrollToEnd();
    return el;
  }

  function fillAnswer(el, data) {
    const rel = data.release || {};
    const calls = data.tool_calls || [];
    const months = new Set(calls.map((c) => c.latest_period).filter(Boolean));
    const asOf = months.size ? fmtPeriodLong([...months].sort().pop())
      : fmtPeriodLong(rel.latest_period);
    el.className = "ask-msg ask-msg-agent";
    el.innerHTML = '<div class="ask-body">' + renderAnswer(data.answer) + "</div>"
      + (calls.length
        ? '<p class="ask-foot">Answered from published data through '
          + escapeHtml(asOf) + "</p>"
        : "")
      + renderLookups(calls, rel);
    scrollToEnd();
  }

  function fillError(el, status) {
    // The server's own detail names server-side configuration; readers get
    // what happened and what still works instead.
    let msg = "The question could not be answered just now. Try again, or use "
      + "the charts and tables on the page — they are unaffected.";
    if (status === 429) {
      msg = "Too many questions in the last minute. Try again shortly.";
    } else if (status === 503) {
      msg = "Question answering is unavailable right now. The charts and "
        + "tables on the page are unaffected.";
    }
    el.className = "ask-msg ask-msg-agent";
    el.innerHTML = '<p class="state-error">' + escapeHtml(msg) + "</p>";
    scrollToEnd();
  }

  function submit() {
    const question = input.value.trim();
    if (!question || inFlight) return;
    inFlight = true;
    send.disabled = true;
    input.value = "";
    clearEmptyState();
    addUser(question);
    const pending = addPending();

    fetch("/api/v1/" + ASK_DATASET + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: question,
        history: history.slice(-ASK_MAX_HISTORY),
      }),
    })
      .then((r) => r.json().then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((res) => {
        if (res.ok) {
          fillAnswer(pending, res.body);
          // Only successful exchanges enter the replayed thread; a failed turn
          // would otherwise teach the model that an error was its own answer.
          history.push({ role: "user", content: question });
          history.push({ role: "assistant", content: res.body.answer || "" });
          while (history.length > ASK_MAX_HISTORY) history.shift();
        } else {
          fillError(pending, res.status);
        }
      })
      .catch(() => fillError(pending, 0))
      .finally(() => {
        inFlight = false;
        send.disabled = false;
        input.focus();
      });
  }

  launcher.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  scrim.addEventListener("click", close);
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) close();
  });
}

initAsk();
