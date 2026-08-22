/* The site header, rendered from one description of the platform.

   Every page once carried its own hand-copied header, and they had already
   drifted apart — the cross-shareholding page listed four destinations, the
   CPI pages three, and neither offered the AI connector at all. The structure
   below is now the only place a section, a page, or a label is named.

   A page declares where it sits and includes this script directly after its
   header shell, so the bar is in the DOM before any page script looks for it:

     <header class="site-header" data-section="macro" data-page="explorer"></header>
     <script src="assets/nav.js"></script>

   Two tiers, because the platform has products and products have pages: the
   navy bar carries the sections, and a section with more than one page gets a
   light strip beneath it. The landing page belongs to no section and sets
   data-section="" — it gets the bar with nothing marked current. */

var NAV_BRAND = "Japan Data Observatory";

var NAV_SECTIONS = [
  {
    id: "macro", label: "Macro", suffix: "Macro",
    pages: [
      { id: "overview", label: "Overview", href: "cpi.html" },
      { id: "explorer", label: "Item Explorer", href: "explorer.html" },
    ],
  },
  {
    id: "equities", label: "Equities", suffix: "Equities",
    pages: [
      { id: "holdings", label: "Cross-Shareholdings", href: "holdings.html" },
    ],
  },
  {
    id: "connect", label: "Connect Your AI", suffix: "Connect Your AI",
    pages: [
      { id: "connect", label: "Setup", href: "connect.html" },
      { id: "manual", label: "Manual", href: "manual.html" },
    ],
  },
  {
    id: "methodology", label: "Methodology", suffix: "Methodology",
    pages: [
      { id: "methodology", label: "Methodology", href: "methodology.html" },
    ],
  },
];

(function renderSiteNav() {
  var header = document.querySelector("header.site-header");
  if (!header) return;

  var sectionId = header.getAttribute("data-section") || "";
  var pageId = header.getAttribute("data-page") || "";
  var section = null;
  for (var i = 0; i < NAV_SECTIONS.length; i++) {
    if (NAV_SECTIONS[i].id === sectionId) section = NAV_SECTIONS[i];
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // The brand always returns to the landing page; the suffix names the
  // section so a screenshot of any page says which product it came from.
  var brand = '<a class="brand" href="index.html">' + esc(NAV_BRAND) +
    (section ? ' <span class="ds">/ ' + esc(section.suffix) + "</span>" : "") +
    "</a>";

  var links = NAV_SECTIONS.map(function (s) {
    // A section's first page is its entry point.
    var current = s.id === sectionId;
    return '<a href="' + esc(s.pages[0].href) + '"' +
      (current ? ' aria-current="page"' : "") + ">" + esc(s.label) + "</a>";
  }).join("");

  header.innerHTML =
    '<div class="inner">' + brand +
    '<nav class="site-nav" aria-label="Main">' + links + "</nav>" +
    '<div class="header-right">' +
    '<span class="header-asof" id="header-asof"></span>' +
    '<button class="theme-toggle" type="button">Dark Mode</button>' +
    "</div></div>";

  // Second tier: only where a section has somewhere else to go.
  if (section && section.pages.length > 1) {
    var sub = document.createElement("nav");
    sub.className = "site-subnav";
    sub.setAttribute("aria-label", section.label);
    sub.innerHTML = '<div class="inner">' + section.pages.map(function (p) {
      return '<a href="' + esc(p.href) + '"' +
        (p.id === pageId ? ' aria-current="page"' : "") + ">" +
        esc(p.label) + "</a>";
    }).join("") + "</div>";
    header.parentNode.insertBefore(sub, header.nextSibling);
  }
})();
