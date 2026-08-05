/* Plain-language questions over the published series.

   The answer is prose, so it gets prose treatment — but it carries the same
   provenance contract as every other number on the site: the release it was
   answered from, and the exact lookups behind it, expandable in place.

   The section stays hidden unless the server reports the feature configured;
   an unconfigured deployment shows no broken affordance. */
"use strict";

const ASK_DATASET = "cpi-jp";

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

/* Answers are plain prose with "- " bullets — no markdown beyond that.
   Everything is escaped first; nothing from the model reaches innerHTML raw. */
function renderAnswer(text) {
  const blocks = fixMinus(text).split(/\n\s*\n/);
  let html = "";
  for (const block of blocks) {
    const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
    if (!lines.length) continue;
    if (lines.every((l) => /^[-•*]\s+/.test(l))) {
      html += "<ul>" + lines
        .map((l) => "<li>" + escapeHtml(l.replace(/^[-•*]\s+/, "")) + "</li>")
        .join("") + "</ul>";
    } else {
      html += "<p>" + escapeHtml(lines.join(" ")) + "</p>";
    }
  }
  return html || "<p>" + escapeHtml(text) + "</p>";
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
  if (!calls.length) return "";
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

function renderResult(data) {
  const rel = data.release || {};
  const calls = data.tool_calls || [];
  const months = new Set(calls.map((c) => c.latest_period).filter(Boolean));
  const asOf = months.size ? fmtPeriodLong([...months].sort().pop())
    : fmtPeriodLong(rel.latest_period);
  return '<div class="ask-answer">'
    + '<div class="ask-body">' + renderAnswer(data.answer) + "</div>"
    + '<p class="ask-foot">Answered from published data through ' + escapeHtml(asOf)
    + " · retrieved " + escapeHtml(fmtStamp(rel.retrieved_at)) + "</p>"
    + renderLookups(calls, rel)
    + "</div>";
}

function initAsk() {
  const section = document.getElementById("ask");
  if (!section) return;
  const form = document.getElementById("ask-form");
  const input = document.getElementById("ask-input");
  const button = document.getElementById("ask-submit");
  const out = document.getElementById("ask-out");
  const hint = document.getElementById("ask-hint");

  fetch("/api/v1/agent/info")
    .then((r) => r.json())
    .then((info) => {
      if (!info.enabled) return; // stays hidden
      section.hidden = false;
      // the server owns the limit; the markup default is only a fallback
      if (info.max_question_chars) input.maxLength = info.max_question_chars;
    })
    .catch(() => { /* leave hidden */ });

  // Separated by spacing rather than punctuation: the row wraps at narrow
  // widths, and a wrapped delimiter always strands one at the end of a line.
  const tryLabel = document.createElement("span");
  tryLabel.className = "ask-try";
  tryLabel.textContent = "Try:";
  hint.appendChild(tryLabel);
  for (const q of SUGGESTIONS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ask-suggest";
    b.textContent = q;
    b.addEventListener("click", () => { input.value = q; submit(); });
    hint.appendChild(b);
  }

  let inFlight = false;

  function submit() {
    const question = input.value.trim();
    if (!question || inFlight) return;
    inFlight = true;
    button.disabled = true;
    out.innerHTML = '<p class="ask-working">Looking up the data…</p>'
      + '<div class="skeleton" style="height:72px"></div>';

    fetch("/api/v1/" + ASK_DATASET + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question }),
    })
      .then((r) => r.json().then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((res) => {
        if (res.ok) {
          out.innerHTML = renderResult(res.body);
          return;
        }
        // The server's own detail names server-side configuration; readers get
        // what happened and what still works instead.
        let msg = "The question could not be answered just now. Try again, or "
          + "use the charts and tables below — they are unaffected.";
        if (res.status === 429) {
          msg = "Too many questions in the last minute. Try again shortly.";
        } else if (res.status === 503) {
          msg = "Question answering is unavailable right now. The charts and "
            + "tables on this page are unaffected.";
        }
        out.innerHTML = '<p class="state-error">' + escapeHtml(msg) + "</p>";
      })
      .catch(() => {
        out.innerHTML = '<p class="state-error">Could not reach the server.</p>';
      })
      .finally(() => { inFlight = false; button.disabled = false; });
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
}

initAsk();
