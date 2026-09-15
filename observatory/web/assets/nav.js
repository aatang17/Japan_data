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
   data-section="" — it gets the bar with nothing marked current.

   A third tier exists only where one destination has more than one view of the
   same data (Inflation: the headline page and the item table). Those are the
   page entry's `tabs`, and they are deliberately NOT a third sticky bar — the
   strip is rendered inside the content column, into a placeholder the page
   puts at the top of <main>:

     <div class="page-tabs" data-page-tabs></div>

   The placeholder is filled on DOMContentLoaded, since <main> does not exist
   yet when this script runs. A page with no placeholder simply gets no tabs. */

var NAV_BRAND = "Plover Analytics";
// Simplified Plover Analytics mark for the header. Decorative: the adjacent
// text already names the brand, so it is aria-hidden rather than repeating it
// to a screen reader.
var BRAND_MARK =
  '<svg class="brand-mark" viewBox="0 0 128 128" width="20" height="20" aria-hidden="true" focusable="false">' +
  '<g fill="none" stroke="currentColor" stroke-width="8" stroke-linejoin="round" stroke-linecap="round">' +
  '<circle cx="64" cy="64" r="54"/><path d="M22 86 L46 56 L62 70 L86 44 L106 58"/></g>' +
  '<g fill="currentColor"><circle cx="46" cy="56" r="8"/><circle cx="86" cy="44" r="8"/></g>' +
  '<g fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round" opacity=".55">' +
  '<path d="M30 100 H62"/><path d="M74 100 H98"/></g></svg>';


var NAV_SECTIONS = [
  {
    id: "macro", label: "Macro", suffix: "Macro",
    pages: [
      { id: "overview", label: "Overview", href: "macro.html" },
      // Inflation is one destination with two views. The headline page and
      // the item table are the same dataset family read at two depths, and
      // as two peers in the strip they read as unrelated products. A page
      // with `tabs` owns them; nav.js renders the third tier in-page.
      { id: "inflation", label: "Inflation", href: "cpi.html",
        tabs: [
          { id: "inflation", label: "Overview", href: "cpi.html" },
          { id: "explorer", label: "Item Explorer", href: "explorer.html" },
          // The other cuts of the same index the Bureau publishes, each a
          // dataset of its own read by the same page script.
          { id: "tokyo", label: "Tokyo Advance", href: "tokyo.html" },
          { id: "goods-services", label: "Goods & Services", href: "goods-services.html" },
          { id: "cpi-sa", label: "Seasonally Adjusted", href: "cpi-sa.html" },
          { id: "cpi-long", label: "Since 1946", href: "cpi-long.html" },
        ] },
      // The national accounts and the corporate survey are the two
      // activity datasets: what the economy produced, and what companies
      // earned and invested doing it. They sit before the balance sheets.
      { id: "gdp", label: "GDP", href: "gdp.html" },
      // Public finance sits beside the national accounts: the general
      // account is one legal account of one tier of government, and the
      // GFS view on the same page is the whole of it.
      { id: "fiscal", label: "Public Finance", href: "fiscal.html" },
      { id: "corporate", label: "Corporate Finance", href: "corporate.html" },
      { id: "boj", label: "Bank of Japan", href: "boj.html" },
      // Banks sit beside the central bank: the FSA's bad-loan and earnings
      // summaries and the JBA's per-bank statements are the private-sector
      // half of the same credit story, and one page reads them together.
      { id: "banks", label: "Banks", href: "banks.html" },
      { id: "rates", label: "Yield Curve", href: "rates.html" },
    ],
  },
  {
    // Trade is customs data, not a macro aggregate: one industry's exports
    // and imports by partner country answer an industry question. Each page
    // is one slice of the same Ministry of Finance table, read by the same
    // script; the strip names the industry, not the dataset.
    id: "trade", label: "Trade", suffix: "Trade",
    pages: [
      { id: "semis", label: "Semiconductors", href: "semis.html" },
      { id: "autos", label: "Motor Vehicles", href: "autos.html" },
      { id: "energy", label: "Energy", href: "energy.html" },
      { id: "machinery", label: "Machinery", href: "machinery.html" },
      { id: "pharma", label: "Pharmaceuticals", href: "pharma.html" },
      { id: "food", label: "Food", href: "food.html" },
    ],
  },
  {
    // Population and the vote-weight page are one subject read two ways:
    // the register counts people, and Vote Weight divides seats by them.
    // Neither is a price, a rate or a balance sheet.
    id: "demographics", label: "Demographics", suffix: "Demographics",
    pages: [
      { id: "population", label: "Population", href: "population.html" },
      { id: "representation", label: "Vote Weight", href: "representation.html" },
    ],
  },
  {
    // Tourism left Macro once it was more than one page. Arrivals, guest
    // nights and the regional detail are three views of one story and were
    // pushing the macro strip past what a phone can show at all.
    id: "tourism", label: "Tourism", suffix: "Tourism",
    pages: [
      { id: "inbound", label: "Arrivals", href: "inbound.html" },
      { id: "accommodation", label: "Guest Nights", href: "accommodation.html" },
      { id: "regions", label: "Regions", href: "lodging-regions.html" },
    ],
  },
  {
    // Agriculture is its own section, not a macro page: rice price, stock,
    // cost of production and farm-input prices are four datasets that are
    // only useful read against each other, and none of them is a macro
    // aggregate.
    id: "agriculture", label: "Agriculture", suffix: "Agriculture",
    pages: [
      { id: "rice", label: "Rice & Farm Prices", href: "rice.html" },
      { id: "ja", label: "Co-operatives", href: "ja.html" },
    ],
  },
  {
    id: "equities", label: "Equities", suffix: "Equities",
    // Thirteen datasets as thirteen peers overran the strip at every width.
    // They are grouped by the question they answer — who holds it, who runs
    // it, what it reports — and each group's pages are its in-page tabs.
    // A group's id is its first tab's, so the strip entry and that page are
    // one destination. Every URL is unchanged.
    pages: [
      { id: "overview", label: "Overview", href: "equities.html" },
      { id: "holdings", label: "Ownership", href: "holdings.html",
        tabs: [
          { id: "holdings", label: "Cross-Shareholdings", href: "holdings.html" },
          { id: "ownership", label: "Register", href: "ownership.html" },
          { id: "stakes", label: "5% Filings", href: "stakes.html" },
        ] },
      { id: "governance", label: "Governance", href: "governance.html",
        tabs: [
          { id: "governance", label: "Boards & Pay", href: "governance.html" },
          { id: "agm", label: "AGM Votes", href: "agm.html" },
          { id: "buyback", label: "Buybacks", href: "buyback.html" },
        ] },
      { id: "financials", label: "Financials", href: "financials.html",
        tabs: [
          { id: "financials", label: "Statements", href: "financials.html" },
          { id: "facilities", label: "Facilities & Land", href: "facilities.html" },
          { id: "customers", label: "Customers", href: "customers.html" },
        ] },
      { id: "company", label: "Company Profile", href: "company.html" },
      { id: "screener", label: "Screens", href: "screener.html",
        tabs: [
          { id: "screener", label: "Screener", href: "screener.html" },
          { id: "cohorts", label: "Peer Groups", href: "cohorts.html" },
        ] },
    ],
  },
  {
    id: "connect", label: "Data Access", suffix: "Data Access",
    pages: [
      { id: "connect", label: "Setup", href: "connect.html" },
      { id: "manual", label: "Manual", href: "manual.html" },
      { id: "api", label: "API Reference", href: "api.html" },
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
  //
  // The mark is inlined rather than an <img> on purpose: an SVG loaded through
  // <img> is an isolated document, so `currentColor` resolves to black there
  // and the ring disappears against the navy header. Inline, it inherits
  // --obs-header-ink and is correct in both themes for free. It is also the
  // simplified line-art mark, not the full-colour disc: at 20px the detailed
  // version is an indistinct blob, and the header is the one place the mark is
  // always small. assets/favicon.svg is the same reasoning applied to the tab
  // icon; assets/logo.svg keeps the full-colour disc for large uses.
  var brand = '<a class="brand" href="index.html">' + BRAND_MARK + esc(NAV_BRAND) +
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

  // A page owning tabs stays marked current while any of its tabs is open —
  // otherwise opening the Item Explorer would un-highlight Inflation and the
  // strip would show no current page at all.
  function owns(p) {
    if (p.id === pageId) return true;
    for (var t = 0; p.tabs && t < p.tabs.length; t++) {
      if (p.tabs[t].id === pageId) return true;
    }
    return false;
  }

  // Second tier: only where a section has somewhere else to go.
  if (section && section.pages.length > 1) {
    var sub = document.createElement("nav");
    sub.className = "site-subnav";
    sub.setAttribute("aria-label", section.label);
    sub.innerHTML = '<div class="inner">' + section.pages.map(function (p) {
      return '<a href="' + esc(p.href) + '"' +
        (owns(p) ? ' aria-current="page"' : "") + ">" +
        esc(p.label) + "</a>";
    }).join("") + "</div>";
    header.parentNode.insertBefore(sub, header.nextSibling);

    // The strip scrolls sideways on a phone, and a section's later pages sit
    // off-screen — so the page you are actually on can be invisible. Bring it
    // into view once, without scrolling the document itself.
    var inner = sub.firstChild;
    var current = inner.querySelector('a[aria-current="page"]');
    if (current && inner.scrollWidth > inner.clientWidth) {
      inner.scrollLeft = Math.max(0, current.offsetLeft - 20);
    }
  }

  // Third tier: the views of one destination, in the content column.
  var group = null;
  for (var j = 0; section && j < section.pages.length; j++) {
    if (section.pages[j].tabs && owns(section.pages[j])) group = section.pages[j];
  }
  if (!group) return;
  document.addEventListener("DOMContentLoaded", function () {
    var slot = document.querySelector("[data-page-tabs]");
    if (!slot) return;
    slot.setAttribute("role", "navigation");
    slot.setAttribute("aria-label", group.label);
    slot.innerHTML = group.tabs.map(function (t) {
      return '<a href="' + esc(t.href) + '"' +
        (t.id === pageId ? ' aria-current="page"' : "") + ">" +
        esc(t.label) + "</a>";
    }).join("");
  });
})();

/* Contents row: one link per section band, generated from the page's own
   h2 headings so no page has to maintain a list. It sits under the page head
   (or the tab strip, where there is one) and marks the section in view.
   Pages with fewer than two sections get nothing; the home page, whose
   bands are promotional rather than navigational, opts out with body.page-home. */
(function renderContents() {
  var toc = null, heads = [], links = [];

  function build() {
    if (document.body.classList.contains("page-home")) return;
    var main = document.querySelector("main");
    if (!main) return;
    heads = Array.prototype.filter.call(main.querySelectorAll("h2"), function (h) {
      return h.offsetParent !== null && h.textContent.trim();
    });
    if (heads.length < 2) { if (toc) { toc.remove(); toc = null; } return; }

    function esc(s) {
      return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
    function label(h) {
      var c = h.cloneNode(true);
      Array.prototype.forEach.call(c.querySelectorAll(".h2-note"), function (n) { n.remove(); });
      return c.textContent.replace(/\s+/g, " ").trim();
    }
    var used = {};
    heads.forEach(function (h) {
      if (!h.id) {
        var base = "s-" + label(h).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
        var id = base, k = 2;
        while (used[id] || document.getElementById(id)) id = base + "-" + (k++);
        h.id = id;
      }
      used[h.id] = true;
    });

    if (!toc) {
      toc = document.createElement("nav");
      toc.className = "page-toc";
      toc.setAttribute("aria-label", "Contents");
      var after = main.querySelector(".page-tabs") || main.querySelector(".page-head") ||
        main.querySelector("#stale-banner");
      if (after) after.insertAdjacentElement("afterend", toc);
      else main.insertAdjacentElement("afterbegin", toc);
    }
    toc.innerHTML = '<span class="page-toc-label">Contents</span>' + heads.map(function (h) {
      return '<a href="#' + esc(h.id) + '">' + esc(label(h)) + "</a>";
    }).join("");
    links = Array.prototype.slice.call(toc.querySelectorAll("a"));
    mark();
  }

  // The section in view is the last heading above the sticky header.
  function mark() {
    // A section is current once its heading has reached the strip's bottom
    // edge (or the header's, where the strip does not stick).
    var line = 80, current = null;
    if (toc && getComputedStyle(toc).position === "sticky") line = toc.getBoundingClientRect().bottom + 12;
    heads.forEach(function (h) { if (h.getBoundingClientRect().top <= line) current = h; });
    links.forEach(function (a, i) {
      if (heads[i] === current) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
  }
  var ticking = false;
  window.addEventListener("scroll", function () {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () { mark(); ticking = false; });
  }, { passive: true });

  // Sections that only appear once data arrives are picked up by the
  // later passes; a page whose sections are all in the markup is unchanged.
  // The strip sticks under whatever is already stuck (header, and the
  // sub-nav where it is sticky), and a jump to a section lands below all of
  // it. Both are measured, not assumed: the header wraps on a phone and the
  // sub-nav only sticks on wider screens.
  function setStack() {
    var header = document.querySelector(".site-header");
    var sub = document.querySelector(".site-subnav");
    var stack = header ? header.offsetHeight : 0;
    if (sub && getComputedStyle(sub).position === "sticky") stack += sub.offsetHeight;
    var root = document.documentElement;
    root.style.setProperty("--obs-stack", stack + "px");
    var tocH = toc && getComputedStyle(toc).position === "sticky" ? toc.offsetHeight : 0;
    root.style.scrollPaddingTop = (stack + tocH + 8) + "px";
  }
  window.addEventListener("resize", setStack);

  document.addEventListener("DOMContentLoaded", function () {
    build();
    setStack();
    // Per-company views appear when a company is chosen; the row follows.
    // Mutations inside the row itself are its own rebuilds and are ignored.
    if (!window.MutationObserver) return;
    var main = document.querySelector("main"), timer = null;
    if (!main) return;
    new MutationObserver(function (records) {
      var outside = records.some(function (r) { return !(toc && toc.contains(r.target)); });
      if (!outside) return;
      clearTimeout(timer);
      timer = setTimeout(function () { build(); setStack(); }, 400);
    }).observe(main, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class", "style"] });
  });
  window.addEventListener("load", function () {
    build(); setStack();
    // A deep link scrolled before the stack was measured; land it again.
    if (location.hash) {
      var target = document.getElementById(location.hash.slice(1));
      if (target) target.scrollIntoView();
    }
    setTimeout(function () { build(); setStack(); }, 2500);
  });
})();
