/* Click-to-sort for the platform's data tables.

   The Item Explorer already had this behaviour written inline; this is the
   same convention factored out so every other table can adopt it without
   restating it — same markup (`th.sortable[data-key]`, a `.arrow` span),
   same interaction (click a column to rank by it, click again to reverse),
   same `aria-sort`. The CSS it needs is already in app.css.

   What it adds over an inline version, and the reason it is worth sharing:

   - **Missing values never sort as zero.** They collect at the bottom in
     both directions. A market with no published figure is not the smallest
     one, and reversing the sort must not parade the gaps to the top.
   - **Ties keep their source order**, so a re-sort on a column with many
     equal values doesn't shuffle rows that did not move.
   - Numeric columns open on the largest value, because "which is biggest"
     is what a ranking is nearly always asked; text columns open A–Z.

   Deliberately generic: a page builds its own rows and markup, and nothing
   here knows what a market or a maturity is. */
"use strict";

/* Compare two values for a sort, gaps always last. dir is "asc" | "desc". */
function compareForSort(a, b, dir) {
  const aMissing = a === null || a === undefined ||
    (typeof a === "number" && Number.isNaN(a));
  const bMissing = b === null || b === undefined ||
    (typeof b === "number" && Number.isNaN(b));
  if (aMissing && bMissing) return 0;
  if (aMissing) return 1;
  if (bMissing) return -1;
  let cmp;
  if (typeof a === "string" || typeof b === "string") {
    cmp = String(a).toLowerCase().localeCompare(String(b).toLowerCase());
  } else {
    cmp = a - b;
  }
  return dir === "asc" ? cmp : -cmp;
}

/* Sort row objects by key/dir. Returns a new array; the sort is stable. */
function sortRows(rows, key, dir) {
  if (!key) return rows.slice();
  return rows
    .map((row, i) => ({ row: row, i: i }))
    .sort((x, y) => compareForSort(x.row[key], y.row[key], dir) || (x.i - y.i))
    .map(d => d.row);
}

/* The direction a column should open in when first chosen. */
function defaultSortDir(type) {
  return type === "text" ? "asc" : "desc";
}

/* Header row from column definitions, in the Item Explorer's markup.

   cols: [{key, label, num, type: "num"|"text", nosort, title}]
   A column with no key, or nosort, renders as a plain header. */
function sortableHead(cols, key, dir) {
  return "<tr>" + cols.map(c => {
    const sortable = c.key && !c.nosort;
    const active = sortable && c.key === key;
    const cls = [c.num ? "num" : "", sortable ? "sortable" : ""]
      .filter(Boolean).join(" ");
    const arrow = active
      ? '<span class="arrow">' + (dir === "asc" ? "▲" : "▼") + "</span>" : "";
    return '<th scope="col"' + (cls ? ' class="' + cls + '"' : "") +
      (sortable ? ' data-key="' + escapeHtml(c.key) +
        '" data-type="' + (c.type || "num") + '"' : "") +
      (active ? ' aria-sort="' +
        (dir === "asc" ? "ascending" : "descending") + '"' : "") +
      (c.title ? ' title="' + escapeHtml(c.title) + '"' : "") +
      ">" + escapeHtml(c.label) + arrow + "</th>";
  }).join("") + "</tr>";
}

/* Wire the headers inside `root`. onSort(key, dir) fires on each click.

   Re-wiring after a re-render is safe: the listeners were attached to the
   header cells that the re-render just replaced. */
function wireSort(root, currentKey, currentDir, onSort) {
  if (!root) return;
  Array.prototype.forEach.call(root.querySelectorAll("th.sortable"), th => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-key");
      const dir = key === currentKey
        ? (currentDir === "desc" ? "asc" : "desc")
        : defaultSortDir(th.getAttribute("data-type"));
      onSort(key, dir);
    });
  });
}

/* --- progressive enhancement for tables the page has already rendered -------

   Everything above works on row *objects*, which suits a page that builds its
   rows from data. Most tables on this platform build their markup as a string
   instead, and retrofitting each one to the object API would mean rewriting a
   dozen renderers. This half works on the rendered DOM: give it a table and it
   makes every column sortable and adds a filter box, whatever built the rows.

   It is deliberately conservative about types. A column is numeric only if
   the cells that carry a value all parse as numbers, so a column of company
   names is never sorted as though "3M" were three. Values come from a cell's
   `data-sort` when it has one — always prefer that for anything the eye reads
   differently from the machine (a date, a yen figure with a unit suffix). */

/* "−563,048" -> -563048 · "+0.54%" -> 0.54 · "—" -> null · "Tokyo" -> NaN */
function cellSortValue(td) {
  const explicit = td.getAttribute("data-sort");
  if (explicit !== null) {
    const n = Number(explicit);
    return explicit.trim() === "" ? null : (Number.isNaN(n) ? explicit : n);
  }
  const raw = (td.textContent || "").trim();
  if (raw === "" || raw === MISSING || raw === "-") return null;
  // strip grouping, the true minus, a leading plus, and a trailing unit
  const cleaned = raw
    .replace(/−/g, "-")
    .replace(/,/g, "")
    .replace(/^\+/, "")
    .replace(/\s*(%|pp|persons|households|人|世帯)$/i, "")
    .trim();
  if (cleaned === "" || !/^-?\d*\.?\d+$/.test(cleaned)) return raw;
  return Number(cleaned);
}

function columnIsNumeric(rows, index) {
  let seen = 0;
  for (const tr of rows) {
    const td = tr.cells[index];
    if (!td) continue;
    const v = cellSortValue(td);
    if (v === null) continue;
    if (typeof v !== "number") return false;
    seen++;
  }
  return seen > 0;
}

/* The row of <th> a reader clicks: the last one, so a table with a grouping
   band above its column names attaches to the names. */
function headerCells(table) {
  const head = table.tHead;
  if (!head || !head.rows.length) return [];
  const row = head.rows[head.rows.length - 1];
  return Array.prototype.slice.call(row.cells);
}

function bodyRows(table) {
  const out = [];
  Array.prototype.forEach.call(table.tBodies, tb => {
    Array.prototype.forEach.call(tb.rows, tr => {
      // A row that spans the table is a note or a sub-table, not a record.
      if (tr.cells.length && tr.cells[0].colSpan > 1) return;
      out.push(tr);
    });
  });
  return out;
}

/* Apply the stored query and sort to the live DOM. */
function applyTableState(state) {
  const table = state.table;
  const rows = bodyRows(table);
  rows.forEach((tr, i) => { if (tr._srcIndex === undefined) tr._srcIndex = i; });

  const q = state.query.trim().toLowerCase();
  let shown = 0;
  rows.forEach(tr => {
    const hit = !q || (tr.textContent || "").toLowerCase().indexOf(q) >= 0;
    tr.hidden = !hit;
    if (hit) shown++;
  });

  if (state.sortIndex !== null) {
    const dir = state.sortDir;
    const idx = state.sortIndex;
    const ordered = rows.slice().sort((a, b) => {
      const av = a.cells[idx] ? cellSortValue(a.cells[idx]) : null;
      const bv = b.cells[idx] ? cellSortValue(b.cells[idx]) : null;
      return compareForSort(av, bv, dir) || (a._srcIndex - b._srcIndex);
    });
    const tb = table.tBodies[0];
    ordered.forEach(tr => tb.appendChild(tr));
  }

  // Only touch the sort indicators on a table whose sort we own. A page that
  // sorts its own rows draws its own arrow, and stripping it would leave the
  // reader with no idea which column the table is ranked by.
  if (!state.pageSorted) headerCells(table).forEach((th, i) => {
    const arrow = th.querySelector(".arrow");
    if (arrow) arrow.remove();
    if (i === state.sortIndex) {
      th.setAttribute("aria-sort", state.sortDir === "asc" ? "ascending" : "descending");
      const span = document.createElement("span");
      span.className = "arrow";
      span.textContent = state.sortDir === "asc" ? "▲" : "▼";
      th.appendChild(span);
    } else {
      th.removeAttribute("aria-sort");
    }
  });

  if (state.count) {
    state.count.textContent = q
      ? shown + " of " + rows.length + " rows"
      : rows.length + " rows";
  }
  if (state.empty) {
    state.empty.hidden = shown !== 0 || !q;
    if (shown === 0 && q) {
      state.empty.textContent = "No rows match “" + state.query.trim() + "”.";
    }
  }
}

/* Give a rendered table click-to-sort and a filter box.

   `table` may be the table or any element containing exactly one. Safe to call
   again after the page re-renders the rows: the toolbar lives outside the
   table, so it survives an innerHTML swap, and the query is re-applied.

   opts: { sort: bool (default true), filter: bool (default true),
           placeholder: string, noun: string } */
function enhanceTable(target, opts) {
  opts = opts || {};
  const table = target && (target.tagName === "TABLE" ? target : target.querySelector("table"));
  if (!table) return null;

  // The toolbar is a sibling of the table's wrapper so that re-rendering the
  // table's innerHTML — which every page here does — cannot destroy it.
  const anchor = table.closest(".table-wrap") || table;
  let state = anchor._tableState;
  if (!state) {
    state = { table: table, query: "", sortIndex: null, sortDir: "desc" };
    anchor._tableState = state;

    if (opts.filter !== false) {
      const bar = document.createElement("div");
      bar.className = "table-tools";
      const id = "tf-" + Math.random().toString(36).slice(2, 8);
      bar.innerHTML =
        '<label class="visually-hidden" for="' + id + '">Filter rows</label>' +
        '<input type="search" id="' + id + '" class="table-filter" ' +
          'placeholder="' + escapeHtml(opts.placeholder || "Filter rows…") + '" ' +
          'autocomplete="off" spellcheck="false">' +
        '<span class="table-count num"></span>';
      anchor.parentNode.insertBefore(bar, anchor);
      state.input = bar.querySelector("input");
      state.count = bar.querySelector(".table-count");
      state.input.addEventListener("input", () => {
        state.query = state.input.value;
        applyTableState(state);
      });

      const empty = document.createElement("p");
      empty.className = "table-empty";
      empty.hidden = true;
      anchor.parentNode.insertBefore(empty, anchor.nextSibling);
      state.empty = empty;
    }
  }
  state.table = table;
  if (state.input) state.query = state.input.value;

  // A page that sorts its own rows marks its headers with `data-key` — both
  // sortableHead() above and the Item Explorer's own header builder do. Adding
  // a DOM sort on top would give those tables two handlers fighting over one
  // click, so the filter is added and the sort is left to the page.
  const pageSorted = headerCells(table).some(th => th.hasAttribute("data-key")) ||
    table.hasAttribute("data-no-enhance-sort");
  state.pageSorted = pageSorted || opts.sort === false;
  if (opts.sort !== false && !pageSorted) {
    const rows = bodyRows(table);
    headerCells(table).forEach((th, i) => {
      if (th.hasAttribute("data-nosort") || th.dataset.enhanced === "1") return;
      // A column where nothing is orderable — a sparkline, an actions cell —
      // must not offer a sort that silently does nothing.
      const orderable = rows.some(tr => tr.cells[i] && cellSortValue(tr.cells[i]) !== null);
      if (!orderable) return;
      th.dataset.enhanced = "1";
      const numeric = columnIsNumeric(rows, i);
      th.classList.add("sortable");
      th.addEventListener("click", () => {
        state.sortDir = state.sortIndex === i
          ? (state.sortDir === "desc" ? "asc" : "desc")
          : defaultSortDir(numeric ? "num" : "text");
        state.sortIndex = i;
        applyTableState(state);
      });
    });
  }

  applyTableState(state);
  return state;
}

/* --- the default, applied without per-table wiring --------------------------

   A page should not have to remember to make its tables sortable. Any table
   with a header row and enough rows to be worth ranking gets the treatment as
   soon as it is in the DOM, and again whenever a page re-renders its rows —
   which every page here does by replacing innerHTML.

   Opt out with `data-no-enhance` on the table. Small tables are left alone:
   below the threshold a filter box is clutter and a sort is pointless. */

const AUTO_ENHANCE_MIN_ROWS = 6;
let autoEnhancing = false;

function autoEnhanceTables(root) {
  if (autoEnhancing) return;
  autoEnhancing = true;
  try {
    const scope = root && root.querySelectorAll ? root : document;
    Array.prototype.forEach.call(scope.querySelectorAll("table"), table => {
      if (table.hasAttribute("data-no-enhance")) return;
      if (!table.tHead || !table.tBodies.length) return;
      if (bodyRows(table).length < AUTO_ENHANCE_MIN_ROWS) return;
      enhanceTable(table, {
        placeholder: table.getAttribute("data-filter-placeholder") || "Filter rows…",
      });
    });
    // A toolbar whose table has been replaced wholesale is orphaned; drop it
    // rather than leave a filter box wired to nothing.
    Array.prototype.forEach.call(document.querySelectorAll(".table-tools"), bar => {
      const next = bar.nextElementSibling;
      if (!next || !next.querySelector || (!next.matches("table") && !next.querySelector("table"))) {
        bar.remove();
      }
    });
  } finally {
    autoEnhancing = false;
  }
}

/* Watch for tables arriving or being re-rendered. Coalesced to one pass per
   frame: a page that rebuilds five tables in a loop should cost one pass. */
(function watchForTables() {
  if (typeof MutationObserver === "undefined") return;
  const options = { childList: true, subtree: true };
  let queued = false;
  // The pass itself mutates the DOM — it inserts a toolbar and reorders rows —
  // so it must not be observing while it runs, or each pass would schedule the
  // next one and the page would re-sort itself sixty times a second.
  const run = () => {
    queued = false;
    observer.disconnect();
    try {
      autoEnhanceTables(document);
    } finally {
      observer.takeRecords();
      observer.observe(document.body, options);
    }
  };
  const observer = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    (window.requestAnimationFrame || setTimeout)(run, 16);
  });
  const start = () => {
    autoEnhanceTables(document);
    observer.observe(document.body, options);
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
