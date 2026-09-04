/* Party profiles: the classification layer, and the screen for filling it in.

   Three views, in the order the work happens:

     #queue          5% filers with no profile yet, ranked by how much they
                     file — the work queue, so the next thing worth typing is
                     always at the top.
     #parties        what has been classified, sorted least-complete first.
     #parties/<id>   the profile form.

   The form's options are never hard-coded here: /parties/vocab serves the same
   lists the validator enforces, so the dropdown can't offer a value the save
   would reject. And the derived label from the filing's own 事業内容 is shown
   beside the classified class rather than instead of it — where the two disagree
   that is a judgement worth seeing, not an error to hide. */
"use strict";

var VOCAB = null;          /* filled once, from /parties/vocab */
var QUEUE_MIN_FILINGS = 5; /* the approved first pass: 5+ filings, institutions */

function put(path, body) {
  return api(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function del(path) {
  return api(path, { method: "DELETE" });
}

function withVocab() {
  if (VOCAB) return Promise.resolve(VOCAB);
  return api("/parties/vocab").then(function (v) { VOCAB = v; return v; });
}

function labelIn(list, value) {
  for (var i = 0; i < list.length; i++) if (list[i].value === value) return list[i].label;
  return null;
}

function opts(list, selected, blank) {
  var html = blank ? '<option value="">' + escapeHtml(blank) + "</option>" : "";
  return html + list.map(function (o) {
    return '<option value="' + escapeHtml(o.value) + '"' +
      (o.value === selected ? " selected" : "") + ">" + escapeHtml(o.label) + "</option>";
  }).join("");
}

function meter(pct) {
  return '<span class="meter"><span style="width:' + Math.max(0, Math.min(100, pct)) +
    '%"></span></span>' + pct + "%";
}

/* Classification values are OUR judgement, never a published statistic. They get
   the neutral outline — never the Official badge, which on this platform means
   "exactly as the source published it". */
function curatedBadge(text) {
  return '<span class="badge badge-neutral">' + escapeHtml(text) + "</span>";
}

function clip(text, n) {
  var t = String(text || "");
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

/* The source keys themselves, not a count: an identity registry that hides the
   identifiers makes you open a profile to answer "who is E06485?", and the
   table's own filter box can then find a party by its code. */
function keyList(aliases) {
  var codes = (aliases || []).map(function (a) { return a.key_value; });
  if (!codes.length) return MISSING;
  var shown = codes.slice(0, 3).map(esc).join(" ");
  return codes.length > 3 ? shown + ' <span class="muted">+' + (codes.length - 3) + "</span>" : shown;
}

function esc(v) { return escapeHtml(v === null || v === undefined ? "" : String(v)); }
function orMissing(v) { return (v === null || v === undefined || v === "") ? MISSING : escapeHtml(String(v)); }

/* ---------- the work queue ---------- */

function viewQueue(target) {
  target.innerHTML = '<div class="admin-loading">Loading the classification queue…</div>';
  Promise.all([
    api("/parties/candidates?min_filings=" + QUEUE_MIN_FILINGS +
        "&include_individuals=false&unprofiled_only=true&limit=400"),
    api("/parties"),
  ]).then(function (both) {
    var queue = both[0].candidates;
    var store = both[1];

    /* Coverage, not queue length, is the number that says whether classification
       is getting anywhere: a hundred profiles are worth little if the filers that
       actually file are still unattributed. */
    var covered = both[0].filings_total
      ? (100 * both[0].filings_attributed / both[0].filings_total) : 0;
    var kpis =
      kpi(queue.length.toLocaleString("en-US"), "Awaiting A Profile", queue.length ? "danger" : "ok") +
      kpi(store.total.toLocaleString("en-US"), "Profiles Written", "") +
      kpi(covered.toFixed(1) + "%", "Filings Attributed", covered >= 80 ? "ok" : "danger") +
      kpi(both[0].filings_unattributed.toLocaleString("en-US"), "Filings Unattributed", "");

    var rows = queue.map(function (c) {
      var flags = "";
      if (c.ever_proposal) flags += '<span class="badge badge-warn">Proposal</span> ';
      if (c.ever_borrowed) flags += '<span class="badge badge-info">Borrowed</span>';
      return '<tr class="clickable" data-code="' + esc(c.edinet_code) + '">' +
        "<td><strong>" + orMissing(c.name_en || c.name_raw) + "</strong>" +
        (c.name_en && c.name_raw ? '<div class="muted">' + esc(c.name_raw) + "</div>" : "") +
        "</td>" +
        '<td class="mono">' + esc(c.edinet_code) + "</td>" +
        "<td>" + curatedBadge(c.derived_type_label) +
        (c.business_ja
          ? '<div class="muted">' + esc(clip(c.business_ja, 30)) + "</div>" : "") +
        "</td>" +
        '<td class="num">' + c.filings.toLocaleString("en-US") + "</td>" +
        '<td class="num">' + c.issuers.toLocaleString("en-US") + "</td>" +
        '<td class="num">' + orMissing(c.last_filed) + "</td>" +
        "<td>" + (flags || MISSING) + "</td>" +
        "</tr>";
    }).join("");

    target.innerHTML =
      '<div class="admin-page-head"><h1>Classification Queue</h1><span class="spacer"></span>' +
      '<button type="button" class="btn btn-primary" id="new-party">New Profile</button>' +
      '<p class="admin-page-sub">Institutional 5% filers with ' + QUEUE_MIN_FILINGS +
      " or more filings and no profile yet, most active first. Click a row to open a " +
      "profile prefilled with what that filer states about itself.</p></div>" +
      '<div class="kpi-row">' + kpis + "</div>" +
      (queue.length ? "" :
        '<div class="admin-alert"><span class="head">Queue clear.</span> ' +
        "Every institutional filer at this threshold has a profile.</div>") +
      '<div class="admin-section">Unprofiled Filers <span class="note">the business ' +
      "is quoted from the filing — evidence to start from, not classification</span></div>" +
      '<div class="table-wrap"><table class="data">' +
      "<thead><tr><th>Filer</th><th>EDINET</th><th>Filed Business (事業内容)</th>" +
      '<th class="num">Filings</th><th class="num">Issuers</th>' +
      '<th class="num">Last Filed</th><th>Flags</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div>";

    document.getElementById("new-party").addEventListener("click", function () {
      location.hash = "#parties/new";
    });
    var trs = target.querySelectorAll("tr.clickable");
    for (var i = 0; i < trs.length; i++) {
      trs[i].addEventListener("click", function () {
        location.hash = "#parties/new/" + this.getAttribute("data-code");
      });
    }
  }).catch(function (err) {
    target.innerHTML = loadFailed("the classification queue", err);
  });
}

/* ---------- the profile list ---------- */

var LIST_STATE = { q: "", party_class: "", tier: "" };

function viewParties(target) {
  target.innerHTML = '<div class="admin-loading">Loading profiles…</div>';
  withVocab().then(function () {
    return api("/parties?q=" + encodeURIComponent(LIST_STATE.q) +
      "&party_class=" + encodeURIComponent(LIST_STATE.party_class) +
      "&tier=" + encodeURIComponent(LIST_STATE.tier));
  }).then(function (data) {
    var items = data.parties;
    var groups = items.filter(function (p) { return !p.parent_id; }).length;
    var codes = items.reduce(function (n, p) {
      return n + (p.aliases || []).filter(function (a) {
        return a.key_type === "edinet_code"; }).length;
    }, 0);
    var reviewed = items.filter(function (p) { return p.confidence !== "unreviewed"; }).length;

    var kpis =
      kpi(data.total.toLocaleString("en-US"), "Profiles", "") +
      kpi(groups.toLocaleString("en-US"), "Group Parents", "") +
      kpi(codes.toLocaleString("en-US"), "Source Keys Mapped", "") +
      kpi(reviewed + " / " + items.length, "Reviewed",
          reviewed === items.length ? "ok" : "danger");

    var rows = items.map(function (p) {
      var strategies = (p.strategy_labels || []).length
        ? p.strategy_labels.map(function (s) { return escapeHtml(s); }).join(", ")
        : MISSING;
      var isGroup = !p.parent_id;
      return '<tr class="clickable" data-id="' + esc(p.party_id) + '">' +
        "<td><strong>" + esc(p.display) + "</strong>" +
        (isGroup ? ' <span class="badge badge-info">Group</span>' : "") +
        (p.legal_name_ja ? '<div class="muted">' + esc(p.legal_name_ja) + "</div>" : "") +
        "</td>" +
        /* A parent has no group above it — the badge on its name already says
           it IS one — so the cell is a gap, and its rows stay one line. An arm
           shows the group it rolls up to, with which arm it is beneath. */
        "<td>" + (isGroup ? MISSING
          : esc(p.group_label || "") +
            (p.group_role_label ? '<div class="muted">' + esc(p.group_role_label) + "</div>" : "")) +
        "</td>" +
        "<td>" + (p.party_class_label ? curatedBadge(p.party_class_label) : MISSING) + "</td>" +
        "<td>" + strategies + "</td>" +
        '<td class="mono">' + keyList(p.aliases) + "</td>" +
        '<td class="num" data-sort="' + p.completeness + '">' + meter(p.completeness) + "</td>" +
        '<td class="num">' + (p.updated_at ? esc(fmtStamp(p.updated_at)) : MISSING) + "</td>" +
        "</tr>";
    }).join("");

    target.innerHTML =
      '<div class="admin-page-head"><h1>Party Profiles</h1><span class="spacer"></span>' +
      '<button type="button" class="btn" id="party-export">Export To Repo</button>' +
      '<button type="button" class="btn btn-primary" id="party-new">New Profile</button>' +
      '<p class="admin-page-sub">Who each fund, company and person is, classified by hand ' +
      "and keyed to our own identifier. Least complete first, so the next thing to " +
      "finish is at the top. Every value here is our judgement — internal only.</p></div>" +
      '<div class="kpi-row">' + kpis + "</div>" +
      '<div id="export-note"></div>' +
      '<div class="curate-bar">' +
      '<div class="field"><label for="f-class">Class</label><select id="f-class">' +
      opts(VOCAB.party_class, LIST_STATE.party_class, "All classes") + "</select></div>" +
      '<div class="field"><label for="f-tier">Coverage</label><select id="f-tier">' +
      opts(VOCAB.coverage_tier, LIST_STATE.tier, "All tiers") + "</select></div>" +
      "</div>" +
      '<div class="table-wrap"><table class="data">' +
      '<colgroup><col style="width:22%"><col style="width:16%"><col style="width:12%">' +
      '<col style="width:17%"><col style="width:15%"><col style="width:8%">' +
      '<col style="width:10%"></colgroup>' +
      "<thead><tr><th>Party</th><th>Group</th><th>Class</th><th>Strategy</th>" +
      '<th>Source Keys</th><th class="num">Complete</th>' +
      '<th class="num">Updated (UTC)</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div>";

    document.getElementById("f-class").addEventListener("change", function () {
      LIST_STATE.party_class = this.value; viewParties(target);
    });
    document.getElementById("f-tier").addEventListener("change", function () {
      LIST_STATE.tier = this.value; viewParties(target);
    });
    document.getElementById("party-new").addEventListener("click", function () {
      location.hash = "#parties/new";
    });
    document.getElementById("party-export").addEventListener("click", function () {
      var btn = this;
      btn.disabled = true;
      post("/parties/export").then(function (r) {
        btn.disabled = false;
        document.getElementById("export-note").innerHTML =
          '<div class="admin-alert"><span class="head">Exported.</span> ' +
          esc(r.parties) + " profiles written to <code>observatory/curation/parties.json</code>. " +
          "Commit that file to version this classification.</div>";
      }).catch(function (err) {
        btn.disabled = false;
        document.getElementById("export-note").innerHTML = loadFailed("the export", err);
      });
    });
    var trs = target.querySelectorAll("tr.clickable");
    for (var i = 0; i < trs.length; i++) {
      trs[i].addEventListener("click", function () {
        location.hash = "#parties/" + this.getAttribute("data-id");
      });
    }
  }).catch(function (err) {
    target.innerHTML = loadFailed("the party profiles", err);
  });
}

/* ---------- the profile form ---------- */

/* Sections in the order a profile gets filled: who it is, what kind of money
   it is, which source rows belong to it, then the slower research fields. */
function section(title, note) {
  return '<div class="admin-section">' + escapeHtml(title) +
    (note ? ' <span class="note">' + escapeHtml(note) + "</span>" : "") + "</div>";
}

function textField(id, label, value, hint, wide) {
  return '<div class="field' + (wide ? " wide" : "") + '"><label for="' + id + '">' +
    escapeHtml(label) + "</label>" +
    '<input type="text" id="' + id + '" value="' + esc(value) + '">' +
    (hint ? '<span class="hint">' + escapeHtml(hint) + "</span>" : "") + "</div>";
}

function areaField(id, label, value, hint) {
  return '<div class="field wide"><label for="' + id + '">' + escapeHtml(label) + "</label>" +
    '<textarea id="' + id + '">' + esc(value) + "</textarea>" +
    (hint ? '<span class="hint">' + escapeHtml(hint) + "</span>" : "") + "</div>";
}

function numField(id, label, value, hint) {
  return '<div class="field"><label for="' + id + '">' + escapeHtml(label) + "</label>" +
    '<input type="number" id="' + id + '" min="0" step="any" value="' +
    (value === null || value === undefined ? "" : esc(value)) + '">' +
    (hint ? '<span class="hint">' + escapeHtml(hint) + "</span>" : "") + "</div>";
}

function selectField(id, label, list, value, blank, hint) {
  return '<div class="field"><label for="' + id + '">' + escapeHtml(label) + "</label>" +
    '<select id="' + id + '">' + opts(list, value, blank) + "</select>" +
    (hint ? '<span class="hint">' + escapeHtml(hint) + "</span>" : "") + "</div>";
}

function flagField(id, label, value, hint) {
  var list = [{ value: "", label: "Unknown" },
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" }];
  var current = value === true ? "yes" : value === false ? "no" : "";
  return '<div class="field"><label for="' + id + '">' + escapeHtml(label) + "</label>" +
    '<select id="' + id + '" data-flag="1">' + opts(list, current, null) + "</select>" +
    (hint ? '<span class="hint">' + escapeHtml(hint) + "</span>" : "") + "</div>";
}

function aliasRow(alias) {
  var a = alias || { key_type: "edinet_code", key_value: "", note: "" };
  return '<div class="alias-row">' +
    '<select class="a-type" aria-label="Key type">' +
    opts(VOCAB.alias_key_types.map(function (t) {
      return { value: t, label: t.replace(/_/g, " ").replace(/\b\w/g, function (c) {
        return c.toUpperCase(); }) };
    }), a.key_type, null) + "</select>" +
    '<input type="text" class="a-value" value="' + esc(a.key_value) + '" aria-label="Key value">' +
    '<input type="text" class="a-note note-cell" value="' + esc(a.note) +
    '" placeholder="Note (optional)" aria-label="Note">' +
    '<button type="button" class="del" title="Remove this key" aria-label="Remove this key">×</button>' +
    "</div>";
}

/* The filings' own words about the codes this profile claims. Read-only, and
   the point of it is the last column: where our classification disagrees with
   what the filer states, that shows up as a flag rather than being hidden. */
function evidencePanel(party) {
  var rows = party.evidence || [];
  if (!rows.length) {
    return section("Filed Evidence") +
      '<p class="prov-line">No EDINET code on this profile yet, so there is nothing ' +
      "to check it against. Add one under Source Keys.</p>";
  }
  var body = rows.map(function (e) {
    var mismatch = party.party_class && e.derived_type !== party.party_class &&
      !(party.party_class === "unknown");
    return "<tr>" +
      '<td class="mono">' + esc(e.edinet_code) + "</td>" +
      "<td>" + orMissing(e.name_raw) + "</td>" +
      "<td>" + orMissing(e.business_ja) + "</td>" +
      "<td>" + esc(e.derived_type_label) + "</td>" +
      '<td class="num">' + e.filings.toLocaleString("en-US") + "</td>" +
      '<td class="num">' + orMissing(e.last_filed) + "</td>" +
      "<td>" + (mismatch
        ? '<span class="badge badge-warn">Differs</span>'
        : '<span class="badge badge-neutral">Agrees</span>') + "</td>" +
      "</tr>";
  }).join("");
  return section("Filed Evidence", "what these filers state about themselves — not classification") +
    '<div class="table-wrap"><table class="data" data-no-enhance>' +
    "<thead><tr><th>EDINET</th><th>Filed Name</th><th>Filed Business (事業内容)</th>" +
    '<th>Filed Type</th><th class="num">Filings</th><th class="num">Last Filed</th>' +
    "<th>Vs Classification</th></tr></thead><tbody>" + body + "</tbody></table></div>" +
    '<p class="prov-line">“Differs” is not an error: a filer states a licence, not ' +
    "what kind of investor it is. It is a prompt to check the profile, not to change it.</p>";
}

function viewPartyDetail(target, partyId, prefillCode) {
  target.innerHTML = '<div class="admin-loading">Loading profile…</div>';
  var isNew = partyId === "new";
  withVocab().then(function () {
    if (isNew && prefillCode) {
      return api("/parties/candidates?min_filings=1&include_individuals=true" +
                 "&unprofiled_only=false&limit=2000").then(function (r) {
        var hit = null;
        for (var i = 0; i < r.candidates.length; i++) {
          if (r.candidates[i].edinet_code === prefillCode) { hit = r.candidates[i]; break; }
        }
        if (!hit) return blankParty();
        var p = blankParty();
        p.display_name = hit.name_en || hit.name_raw || "";
        p.legal_name_ja = hit.name_raw || "";
        p.legal_name_en = hit.name_en || "";
        p.aliases = [{ key_type: "edinet_code", key_value: hit.edinet_code,
                       note: "filed as " + (hit.name_raw || "") }];
        p.confidence = "unreviewed";
        p.prefill_note = hit;
        return p;
      });
    }
    if (isNew) return blankParty();
    return api("/parties/" + encodeURIComponent(partyId));
  }).then(function (party) {
    return api("/parties?limit=2000").then(function (all) {
      renderForm(target, party, isNew, all.parties);
    });
  }).catch(function (err) {
    target.innerHTML = loadFailed("the profile", err);
  });
}

function blankParty() {
  return { party_id: null, aliases: [], strategy: [], tags: [],
           lifecycle: "active", holder_role: "beneficial_owner", public: false };
}

function renderForm(target, party, isNew, allParties) {
  var V = VOCAB;
  var parentOptions = allParties
    .filter(function (p) { return p.party_id !== party.party_id; })
    .map(function (p) {
      return { value: p.party_id, label: (p.display || p.party_id) +
        (p.group_name ? " — group" : "") };
    })
    .sort(function (a, b) { return a.label.localeCompare(b.label); });

  var prefill = party.prefill_note;
  var head =
    '<div class="admin-page-head"><h1>' +
    escapeHtml(isNew ? "New Profile" : (party.display || party.party_id)) + "</h1>" +
    '<span class="spacer"></span>' +
    '<button type="button" class="btn" id="p-back">Back To List</button>' +
    '<p class="admin-page-sub">' +
    (isNew
      ? "Everything on this form is our own judgement and stays internal. Nothing " +
        "here changes a filing or a stored release."
      : "Identifier <code>" + esc(party.party_id) + "</code> · " +
        (party.completeness || 0) + "% complete · last edited " +
        (party.updated_at ? esc(fmtStamp(party.updated_at)) : MISSING) +
        (party.updated_by ? " by " + esc(party.updated_by) : "")) +
    "</p></div>";

  var banner = "";
  if (prefill) {
    banner = '<div class="admin-alert"><span class="head">Prefilled from the filings.</span> ' +
      "Names and the EDINET key come from " + esc(prefill.filings) + " filing(s) by " +
      esc(prefill.edinet_code) + ", which states its business as “" +
      orMissing(prefill.business_ja) + "”. That reads as <strong>" +
      esc(prefill.derived_type_label) + "</strong> — evidence to start from, " +
      "not a class we have saved for you.</div>";
  } else if (party.confidence === "unreviewed") {
    banner = '<div class="admin-alert"><span class="head">Not reviewed.</span> ' +
      "This profile was seeded from the group map and the filers' own business " +
      "descriptions. Check it, then clear the Confidence field.</div>";
  }

  var identity =
    section("Identity", "the group name lives on the parent, so no arm has to stand for the group") +
    '<div class="form-grid">' +
    textField("f-display_name", "Display Name", party.display_name,
              "What appears in a table row, e.g. Nomura Asset Management") +
    textField("f-legal_name_en", "Legal Name (English)", party.legal_name_en) +
    textField("f-legal_name_ja", "Legal Name (Japanese)", party.legal_name_ja) +
    selectField("f-parent_id", "Parent", parentOptions, party.parent_id,
                "None — this is a top-level party",
                "Set this on an arm; leave empty on the group itself") +
    textField("f-group_name", "Group Name", party.group_name,
              "Only on a group parent, e.g. Nomura") +
    selectField("f-group_role", "Group Role", V.group_role, party.group_role, "Not set",
                "Which arm of the group this entity is") +
    selectField("f-lifecycle", "Status", V.lifecycle, party.lifecycle, "Not set") +
    textField("f-successor_party_id", "Successor Party", party.successor_party_id,
              "If merged or renamed, the profile that replaced it") +
    "</div>";

  var classification =
    section("Classification", "three fields, because one label cannot say all three things") +
    '<div class="form-grid">' +
    selectField("f-party_class", "Class (required)", V.party_class, party.party_class,
                "Choose one", "What it legally is") +
    selectField("f-holder_role", "Register Role", V.holder_role, party.holder_role, "Not set",
                "Why it is on the register — a 信託口 account is not the owner") +
    "</div>" +
    '<div class="field wide" style="margin-top:12px"><label>Strategy</label>' +
    '<div class="check-grid" id="f-strategy">' +
    V.strategy.map(function (s) {
      var on = (party.strategy || []).indexOf(s.value) !== -1;
      return "<label><input type=\"checkbox\" value=\"" + esc(s.value) + '"' +
        (on ? " checked" : "") + "> " + escapeHtml(s.label) + "</label>";
    }).join("") +
    '</div><span class="hint">How it invests. Pick as many as apply; leave empty for ' +
    "an operating company or a nominee.</span></div>";

  var aliases =
    section("Source Keys", "one key belongs to one profile — a duplicate would double-count a ranking") +
    '<div id="alias-list">' +
    ((party.aliases || []).map(aliasRow).join("") || aliasRow(null)) +
    "</div>" +
    '<button type="button" class="btn" id="alias-add" style="margin-top:6px">Add Key</button>' +
    '<p class="prov-line">EDINET codes tie this profile to the 5% filings; a name key ' +
    "ties it to register rows that carry no code.</p>";

  var registration =
    section("Registration And Disclosure") +
    '<div class="form-grid">' +
    textField("f-jurisdiction", "Jurisdiction Of Incorporation", party.jurisdiction) +
    textField("f-hq_country", "Head Office Country", party.hq_country) +
    textField("f-hq_city", "Head Office City", party.hq_city) +
    textField("f-founded_year", "Founded", party.founded_year) +
    textField("f-lei", "LEI", party.lei) +
    textField("f-sec_code", "Listed Ticker", party.sec_code, "If the party itself is listed") +
    textField("f-fsa_registration", "FSA Registration (金商)", party.fsa_registration) +
    textField("f-home_regulator", "Home Regulator", party.home_regulator) +
    textField("f-website", "Website", party.website) +
    flagField("f-files_13f", "Files US 13F", party.files_13f) +
    flagField("f-stewardship_code_signatory", "Japan Stewardship Code",
              party.stewardship_code_signatory) +
    flagField("f-pri_signatory", "PRI Signatory", party.pri_signatory) +
    flagField("f-publishes_voting_records", "Publishes Voting Records",
              party.publishes_voting_records) +
    textField("f-voting_records_url", "Voting Records URL", party.voting_records_url) +
    "</div>";

  var money =
    section("Assets Under Management", "state the as-of and the source, or the figure is not citable") +
    '<div class="form-grid">' +
    numField("f-aum_amount_musd", "AUM, US$ Millions", party.aum_amount_musd) +
    numField("f-japan_equity_aum_musd", "Japan Equity AUM, US$ Millions",
             party.japan_equity_aum_musd) +
    textField("f-aum_currency", "Reporting Currency", party.aum_currency) +
    textField("f-aum_as_of", "AUM As Of", party.aum_as_of, "YYYY-MM-DD") +
    textField("f-aum_source", "AUM Source", party.aum_source, "Where the figure came from", true) +
    "</div>";

  var ourView =
    section("Our View", "internal only — none of this reaches the public API") +
    '<div class="form-grid">' +
    selectField("f-coverage_tier", "Coverage Tier", V.coverage_tier, party.coverage_tier,
                "Not set", "Drives nothing but the order of this list") +
    selectField("f-activist", "Activist", V.activist, party.activist, "Not set") +
    textField("f-confidence", "Confidence", party.confidence,
              "Clear this once you have reviewed the profile") +
    textField("f-source", "Source", party.source, "Where these classification values came from") +
    textField("f-as_of", "As Of", party.as_of, "YYYY-MM-DD") +
    textField("f-tags", "Tags", (party.tags || []).join(", "), "Comma separated") +
    areaField("f-thesis", "Thesis", party.thesis, "One or two lines on why this party matters") +
    areaField("f-key_people", "Key People", party.key_people) +
    areaField("f-contacts", "Contacts", party.contacts) +
    areaField("f-notes", "Notes", party.notes) +
    "</div>" +
    '<div class="form-grid" style="margin-top:12px">' +
    flagField("f-public", "Publishable", party.public,
              "Leave as No for now; nothing is published in this milestone") +
    "</div>";

  var actions =
    '<div class="form-actions">' +
    '<button type="button" class="btn btn-primary" id="p-save">' +
    (isNew ? "Create Profile" : "Save Changes") + "</button>" +
    '<button type="button" class="btn" id="p-cancel">Cancel</button>' +
    '<span class="spacer"></span>' +
    '<span class="save-status" id="p-status"></span>' +
    (isNew ? "" : '<button type="button" class="btn btn-danger" id="p-delete">Delete</button>') +
    "</div>";

  target.innerHTML = head + banner + identity + classification + aliases +
    registration + money + ourView +
    (isNew ? "" : evidencePanel(party)) + actions;

  document.getElementById("alias-add").addEventListener("click", function () {
    var box = document.getElementById("alias-list");
    box.insertAdjacentHTML("beforeend", aliasRow(null));
  });
  document.getElementById("alias-list").addEventListener("click", function (e) {
    if (!e.target.classList.contains("del")) return;
    var rows = this.querySelectorAll(".alias-row");
    if (rows.length === 1) {
      /* Never leave the operator with no row to type into. */
      var inputs = rows[0].querySelectorAll("input");
      for (var i = 0; i < inputs.length; i++) inputs[i].value = "";
      return;
    }
    e.target.parentNode.parentNode.removeChild(e.target.parentNode);
  });

  function goBack() { location.hash = "#parties"; }
  document.getElementById("p-back").addEventListener("click", goBack);
  document.getElementById("p-cancel").addEventListener("click", goBack);

  document.getElementById("p-save").addEventListener("click", function () {
    var btn = this;
    var status = document.getElementById("p-status");
    var body = collectForm();
    btn.disabled = true;
    status.className = "save-status";
    status.textContent = "Saving…";
    var request = isNew ? post("/parties", body)
                        : put("/parties/" + encodeURIComponent(party.party_id), body);
    request.then(function (saved) {
      status.className = "save-status good";
      status.textContent = "Saved.";
      if (isNew) location.hash = "#parties/" + saved.party_id;
      else viewPartyDetail(target, saved.party_id, null);
    }).catch(function (err) {
      btn.disabled = false;
      status.className = "save-status bad";
      /* The API's message names the field and why — show it as it is rather
         than replacing it with a generic failure. */
      status.textContent = "Not saved: " + (err.message || String(err));
    });
  });

  var delBtn = document.getElementById("p-delete");
  if (delBtn) {
    delBtn.addEventListener("click", function () {
      if (!window.confirm("Delete the profile for " + (party.display || party.party_id) +
                          "? The filings are untouched; only this classification is removed.")) return;
      var status = document.getElementById("p-status");
      del("/parties/" + encodeURIComponent(party.party_id)).then(goBack)
        .catch(function (err) {
          status.className = "save-status bad";
          status.textContent = "Not deleted: " + (err.message || String(err));
        });
    });
  }
}

function collectForm() {
  function val(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    var v = el.value.trim();
    return v === "" ? null : v;
  }
  function flag(id) {
    var v = val(id);
    return v === null ? null : v === "yes";
  }
  var body = {};
  ["display_name", "legal_name_en", "legal_name_ja", "group_name", "group_role",
   "lifecycle", "successor_party_id", "parent_id", "party_class", "holder_role",
   "jurisdiction", "hq_country", "hq_city", "founded_year", "lei", "sec_code",
   "fsa_registration", "home_regulator", "website", "voting_records_url",
   "aum_currency", "aum_as_of", "aum_source", "coverage_tier", "activist",
   "confidence", "source", "as_of", "thesis", "key_people", "contacts", "notes"
  ].forEach(function (f) { body[f] = val("f-" + f); });

  ["aum_amount_musd", "japan_equity_aum_musd"].forEach(function (f) {
    body[f] = val("f-" + f);
  });
  ["files_13f", "stewardship_code_signatory", "pri_signatory",
   "publishes_voting_records", "public"].forEach(function (f) {
    body[f] = flag("f-" + f);
  });

  var tags = val("f-tags");
  body.tags = tags ? tags.split(",") : [];

  body.strategy = [];
  var boxes = document.querySelectorAll("#f-strategy input[type=checkbox]");
  for (var i = 0; i < boxes.length; i++) {
    if (boxes[i].checked) body.strategy.push(boxes[i].value);
  }

  body.aliases = [];
  var rows = document.querySelectorAll("#alias-list .alias-row");
  for (var j = 0; j < rows.length; j++) {
    var value = rows[j].querySelector(".a-value").value.trim();
    if (!value) continue;
    body.aliases.push({
      key_type: rows[j].querySelector(".a-type").value,
      key_value: value,
      note: rows[j].querySelector(".a-note").value.trim() || null,
    });
  }
  return body;
}
