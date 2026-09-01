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
