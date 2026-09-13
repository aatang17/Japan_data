/* The API reference, rendered from what the server actually serves.

   Two sources, both live: the OpenAPI schema (/api/openapi.json) for the
   endpoint list, each handler's docstring and its parameters, and the dataset
   registry (/api/v1/catalog/manifests) for every dataset's card. A
   hand-written reference drifted from the code within weeks; this one cannot,
   because it is the code's own description of itself. What the page adds is
   order, grouping, and a working example per endpoint. */
(function () {
  "use strict";

  // Product areas in reading order: what is on the server, the statistical
  // datasets, then the company disclosures grouped by the question they answer.
  var TAG_ORDER = [
    "Catalog", "Datasets", "Company",
    "Cross-shareholdings", "Shareholder register", "5% filings",
    "Boards and pay", "AGM votes", "Buybacks",
    "Financials", "Segments and customers", "Facilities", "Peer groups",
    "Representation",
  ];
  var TRUST_LABEL = { official: "Official statistic", derived: "Calculated", model: "Model estimate" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // Docstrings are written in a light reStructuredText: ``code``, *emphasis*,
  // blank lines between paragraphs. Escape first, then mark up.
  function prose(text) {
    if (!text) return "";
    return text.trim().split(/\n\s*\n/).map(function (para) {
      var h = esc(para.replace(/\s*\n\s*/g, " "));
      h = h.replace(/``([^`]+)``/g, "<code>$1</code>").replace(/`([^`]+)`/g, "<code>$1</code>");
      h = h.replace(/(^|\s)\*([^*]+)\*(?=[\s.,;:)]|$)/g, "$1<i>$2</i>");
      return "<p>" + h + "</p>";
    }).join("");
  }

  function pathHtml(p) {
    return esc(p).replace(/\{([a-z_]+)\}/g, '<span class="var">{$1}</span>');
  }

  function schemaType(s) {
    if (!s) return "";
    if (s.type) return s.type;
    if (s.anyOf) {
      var ts = s.anyOf.map(function (x) { return x.type; }).filter(function (t) { return t && t !== "null"; });
      return ts.join(" | ");
    }
    return "";
  }

  function fmtDefault(s) {
    if (!s || s.default === undefined || s.default === null || s.default === "") return "—";
    return String(s.default);
  }

  // The datasets that offer a shared endpoint, read from their cards: a card's
  // endpoints are concrete (/api/v1/cpi-jp/contributions) and the schema's are
  // templates (/api/v1/{dataset}/contributions).
  function datasetsFor(template, manifests) {
    var suffix = template.replace("/api/v1/{dataset}", "");
    return manifests.filter(function (m) {
      var eps = m.endpoints || {};
      return Object.keys(eps).some(function (k) {
        return eps[k] === "/api/v1/" + m.id + suffix;
      });
    }).map(function (m) { return m.id; });
  }

  // A working URL for every endpoint: the one the handler names, else the
  // template with its placeholders filled by a real value.
  function exampleFor(path, op, offered) {
    var x = op["x-example"];
    if (x) return x;
    var url = path;
    if (url.indexOf("{dataset}") >= 0) {
      if (!offered.length) return null;
      url = url.replace("{dataset}", offered[0]);
    }
    url = url.replace("{sec_code}", "7203").replace("{code}", "7203").replace("{dataset_id}", "cpi-jp");
    if (/\{[a-z_]+\}/.test(url)) return null;
    var required = (op.parameters || []).filter(function (p) { return p.in === "query" && p.required; });
    if (required.length) return null;
    return url;
  }

  function renderOp(path, method, op, manifests) {
    var params = (op.parameters || []).filter(function (p) { return p.in === "query"; });
    var offered = path.indexOf("{dataset}") >= 0 ? datasetsFor(path, manifests) : [];
    var example = exampleFor(path, op, offered);
    var id = "ep-" + path.replace(/^\/api\/v1\//, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "");

    var h = '<article class="ep" id="' + esc(id) + '">';
    h += '<div class="ep-head"><span class="ep-method">' + esc(method.toUpperCase()) + "</span>" +
      '<code class="ep-path">' + pathHtml(path) + "</code></div>";
    h += prose(op.description || op.summary || "");

    if (offered.length) {
      h += '<p class="ep-for"><b>Offered by:</b> ' + offered.map(function (d) {
        return '<a href="#ds-' + esc(d) + '"><code>' + esc(d) + "</code></a>";
      }).join(" ") + "</p>";
    }

    if (params.length) {
      h += '<div class="table-wrap"><table class="data ep-params" data-no-enhance><thead><tr>' +
        "<th>Parameter</th><th>Type</th><th>Default</th><th>Description</th></tr></thead><tbody>";
      params.forEach(function (p) {
        h += "<tr><td><code>" + esc(p.name) + "</code>" + (p.required ? ' <span class="req">required</span>' : "") + "</td>" +
          '<td class="muted">' + esc(schemaType(p.schema)) + "</td>" +
          '<td class="muted">' + esc(fmtDefault(p.schema)) + "</td>" +
          "<td>" + esc(p.description || "") + "</td></tr>";
      });
      h += "</tbody></table></div>";
    }

    if (example) {
      h += '<div class="ep-try"><a class="api-link" href="' + esc(example) + '">' + esc(example) + "</a></div>";
    }
    return h + "</article>";
  }

  function renderEndpoints(schema, manifests) {
    var tagDesc = {};
    (schema.tags || []).forEach(function (t) { tagDesc[t.name] = t.description || ""; });
    var groups = {};
    var count = 0;
    Object.keys(schema.paths).forEach(function (path) {
      var ops = schema.paths[path];
      Object.keys(ops).forEach(function (method) {
        var op = ops[method];
        // A route-level tag is appended after its router's; the last is the
        // specific one.
        var tags = op.tags || ["Other"];
        var tag = tags[tags.length - 1];
        (groups[tag] = groups[tag] || []).push({ path: path, method: method, op: op });
        count++;
      });
    });
    var order = TAG_ORDER.slice();
    Object.keys(groups).forEach(function (t) { if (order.indexOf(t) < 0) order.push(t); });

    var h = "";
    order.forEach(function (tag) {
      var list = groups[tag];
      if (!list) return;
      list.sort(function (a, b) { return a.path < b.path ? -1 : a.path > b.path ? 1 : 0; });
      var tid = "api-" + tag.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      h += '<h3 class="ep-group" id="' + esc(tid) + '">' + esc(tag) +
        ' <span class="ep-count">' + list.length + "</span></h3>";
      if (tagDesc[tag]) h += prose(tagDesc[tag]);
      list.forEach(function (e) { h += renderOp(e.path, e.method, e.op, manifests); });
    });
    document.getElementById("endpoints-body").innerHTML = h;
    var note = document.getElementById("endpoints-note");
    if (note) note.textContent = count + " endpoints";
  }

  function measuresTable(ms) {
    if (!ms || !ms.length) return "";
    var h = '<div class="table-wrap"><table class="data ep-params" data-no-enhance><thead><tr>' +
      "<th>Measure</th><th>Unit</th><th>Trust</th><th>Calculation</th></tr></thead><tbody>";
    ms.forEach(function (m) {
      h += "<tr><td><code>" + esc(m.id) + "</code><div class=\"muted\">" + esc(m.label || "") + "</div></td>" +
        '<td class="muted">' + esc(m.unit || "") + "</td>" +
        "<td>" + esc(TRUST_LABEL[m.trust] || m.trust || "") + "</td>" +
        "<td>" + (m.calc ? esc(m.calc) : '<span class="muted">As published</span>') + "</td></tr>";
    });
    return h + "</tbody></table></div>";
  }

  function renderDataset(m) {
    var v = m.vintage || {};
    var src = m.source || {};
    var name = (m.name && m.name.en) || m.id;
    var qual = [m.frequency, v.history_from ? "from " + v.history_from : null, m.id]
      .filter(Boolean).join(" · ");
    var h = '<details class="ds" id="ds-' + esc(m.id) + '"><summary><span>' + esc(name) +
      (m.name && m.name.ja ? ' <span class="ja">' + esc(m.name.ja) + "</span>" : "") +
      '</span><span class="ds-note">' + esc(qual) + "</span></summary><div class=\"ds-body\">";
    if (m.summary) h += "<p>" + esc(m.summary) + "</p>";
    h += "<p><b>Source:</b> " + esc(src.publisher || "") +
      (src.document ? " — " + esc(src.document) : "") +
      (src.url ? ' (<a href="' + esc(src.url) + '" rel="noopener">source page</a>)' : "") + "<br>" +
      (src.credit ? "<b>Credit line:</b> " + esc(src.credit) + "<br>" : "") +
      "<b>Keys:</b> " + esc((m.keys || []).join(", ")) +
      " · <b>Shape:</b> " + esc(m.shape || "") +
      " · <b>Point-in-time:</b> " + (v.as_of_supported ? "as_of supported" : "not supported") +
      (m.page ? ' · <a href="' + esc(m.page) + '">Page</a>' : "") + "</p>";
    h += measuresTable(m.measures);
    var eps = m.endpoints || {};
    var keys = Object.keys(eps);
    if (keys.length) {
      h += "<p><b>Endpoints</b></p><ul class=\"ep-list\">";
      keys.forEach(function (k) {
        var url = eps[k];
        var link = /\{[a-z_]+\}/.test(url) ? "<code>" + pathHtml(url) + "</code>" :
          '<a class="api-link" href="' + esc(url) + '">' + esc(url) + "</a>";
        h += "<li>" + link + ' <span class="muted">' + esc(k.replace(/_/g, " ")) + "</span></li>";
      });
      h += "</ul>";
    }
    if (m.notes && m.notes.length) {
      h += "<p><b>Notes</b></p><ul>" + m.notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul>";
    }
    if (m.available === false) h += '<p class="muted">Not published on this server yet.</p>';
    return h + "</div></details>";
  }

  function renderDatasets(manifests, sections) {
    var byId = {};
    manifests.forEach(function (m) { byId[m.id] = m; });
    var h = "", n = 0, placed = {};
    (sections || []).forEach(function (s) {
      var ids = (s.datasets || []).filter(function (id) { return byId[id]; });
      if (!ids.length) return;
      h += '<h3 class="ep-group" id="sec-' + esc(s.id) + '">' + esc(s.label) +
        ' <span class="ep-count">' + ids.length + "</span></h3>";
      ids.forEach(function (id) { h += renderDataset(byId[id]); placed[id] = true; n++; });
    });
    var rest = manifests.filter(function (m) { return !placed[m.id]; });
    if (rest.length) {
      h += '<h3 class="ep-group">Other</h3>';
      rest.forEach(function (m) { h += renderDataset(m); n++; });
    }
    document.getElementById("datasets-body").innerHTML = h;
    var note = document.getElementById("datasets-note");
    if (note) note.textContent = n + " datasets";
  }

  // A link into a card must land on open text, not a closed row.
  function openHashTarget() {
    var id = location.hash.slice(1);
    if (!id) return;
    var el = document.getElementById(id);
    while (el) {
      if (el.tagName === "DETAILS") el.open = true;
      el = el.parentElement;
    }
    el = document.getElementById(id);
    if (el) el.scrollIntoView();
  }

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error(url + " → " + r.status);
      return r.json();
    });
  }

  function fail(where, err) {
    var el = document.getElementById(where);
    if (el) el.innerHTML = '<p class="muted">Could not load this section (' + esc(err && err.message || err) +
      "). The schema itself is at <a href=\"/api/openapi.json\">/api/openapi.json</a>.</p>";
  }

  Promise.all([
    getJSON("/api/openapi.json"),
    getJSON("/api/v1/catalog/manifests"),
    getJSON("/api/v1/catalog/sections"),
  ]).then(function (res) {
    var schema = res[0];
    var mf = res[1];
    var manifests = Array.isArray(mf) ? mf : (mf.manifests || mf.datasets || []);
    var sections = (res[2] && res[2].sections) || [];
    try { renderEndpoints(schema, manifests); } catch (e) { fail("endpoints-body", e); }
    try { renderDatasets(manifests, sections); } catch (e) { fail("datasets-body", e); }
    openHashTarget();
  }).catch(function (e) {
    fail("endpoints-body", e);
    fail("datasets-body", e);
  });
  window.addEventListener("hashchange", openHashTarget);
})();
