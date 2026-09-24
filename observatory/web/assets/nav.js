/* The site header, rendered from one description of the platform.

   Every page once carried its own hand-copied header, and they had already
   drifted apart — the cross-shareholding page listed four destinations, the
   CPI pages three, and neither offered the AI connector at all. The structure
   below is now the only place a section, a page, or a label is named.

   A page declares where it sits and includes this script directly after its
   header shell, so the bar is in the DOM before any page script looks for it:

     <header class="site-header" data-section="macro" data-page="explorer"></header>
     <script src="assets/nav.js"></script>

   Two tiers. The navy bar carries the markets — Japan, United States — in
   full words, plus Docs and the reader's controls at the right: which country
   you are looking at is the first thing every page says. The light strip
   beneath it carries the current market's sections; a section with more than
   one page opens a menu of them. A small trail at the top of the content
   (Japan / Macro / Yield Curve) repeats the place in words. The landing page
   belongs to no section and sets data-section="" — it gets the last market
   visited, with no section marked current.

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


// Two markets, separated at the top of the bar: a reader works in one
// market at a time, and the two stand on different sources (e-Stat, the BOJ
// and EDINET; the SEC and the Treasury). Each section belongs to one market
// or is "shared" (data access, methodology), and the bar shows only the
// current market's sections plus the shared ones. A shared page stays in the
// market the reader came from, remembered per browser.
var NAV_MARKETS = [
  { id: "jp", label: "Japan", entry: "macro.html" },
  { id: "us", label: "United States", entry: "us-treasury.html" },
];

var NAV_SECTIONS = [
  {
    id: "macro", market: "jp", label: "Macro", suffix: "Macro",
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
    id: "trade", market: "jp", label: "Trade", suffix: "Trade",
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
    id: "demographics", market: "jp", label: "Demographics", suffix: "Demographics",
    pages: [
      { id: "population", label: "Population", href: "population.html" },
      { id: "representation", label: "Vote Weight", href: "representation.html" },
    ],
  },
  {
    // Tourism left Macro once it was more than one page. Arrivals, guest
    // nights and the regional detail are three views of one story and were
    // pushing the macro strip past what a phone can show at all.
    id: "tourism", market: "jp", label: "Tourism", suffix: "Tourism",
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
    id: "agriculture", market: "jp", label: "Agriculture", suffix: "Agriculture",
    pages: [
      { id: "rice", label: "Rice & Farm Prices", href: "rice.html" },
      { id: "ja", label: "Co-operatives", href: "ja.html" },
    ],
  },
  {
    id: "equities", market: "jp", label: "Equities", suffix: "Equities",
    // Thirteen datasets as thirteen peers overran the strip at every width.
    // They are grouped by the question they answer — who holds it, who runs
    // it, what it reports — and each group's pages are its in-page tabs.
    // A group's id is its first tab's, so the strip entry and that page are
    // one destination. Every URL is unchanged.
    // The strip leads with the company page — one company is what a reader
    // arrives wanting — while the navy bar still lands on the Overview, which
    // is the directory of what the section holds.
    entry: "equities.html",
    pages: [
      // One destination, two views of one company: everything we hold on it,
      // and the segment-vs-customs lens that used to be the whole page.
      { id: "company", label: "Company Profile", href: "company.html",
        tabs: [
          { id: "company", label: "Profile", href: "company.html" },
          { id: "customs", label: "Customs Lens", href: "customs-lens.html" },
        ] },
      { id: "overview", label: "Overview", href: "equities.html" },
      { id: "holdings", label: "Ownership", href: "holdings.html",
        tabs: [
          { id: "holdings", label: "Cross-Shareholdings", href: "holdings.html" },
          { id: "ownership", label: "Register", href: "ownership.html" },
          { id: "stakes", label: "5% Filings", href: "stakes.html" },
          { id: "shorts", label: "Short Positions", href: "shorts.html" },
        ] },
      { id: "governance", label: "Governance", href: "governance.html",
        tabs: [
          { id: "governance", label: "Boards & Pay", href: "governance.html" },
          { id: "agm", label: "AGM Votes", href: "agm.html" },
          { id: "buyback", label: "Buybacks", href: "buyback.html" },
          { id: "risks", label: "Business Risks", href: "risks.html" },
        ] },
      { id: "financials", label: "Financials", href: "financials.html",
        tabs: [
          { id: "financials", label: "Statements", href: "financials.html" },
          { id: "earnings", label: "Earnings Releases", href: "earnings.html" },
          { id: "facilities", label: "Facilities & Land", href: "facilities.html" },
          { id: "customers", label: "Customers", href: "customers.html" },
        ] },
      // Market activity: what the whole market is doing, as opposed to what
      // one company filed. Both pages are weekly JPX aggregates.
      { id: "margin", label: "Market", href: "margin.html",
        tabs: [
          { id: "margin", label: "Margin Balances", href: "margin.html" },
          { id: "flows", label: "Investor Flows", href: "flows.html" },
        ] },
      { id: "screener", label: "Screens", href: "screener.html",
        tabs: [
          { id: "screener", label: "Screener", href: "screener.html" },
          { id: "cohorts", label: "Peer Groups", href: "cohorts.html" },
        ] },
    ],
  },
  {
    // US prices and pay, all from the BLS except the Atlanta Fed tracker.
    // Inflation owns its cuts as tabs, as Japan's does; retail prices and
    // wages are separate questions and separate pages.
    id: "us-prices", market: "us", label: "Prices & Wages", suffix: "US Prices",
    pages: [
      { id: "us-inflation", label: "Inflation", href: "us-inflation.html",
        tabs: [
          { id: "us-inflation", label: "Overview", href: "us-inflation.html" },
          { id: "us-explorer", label: "Item Explorer", href: "us-explorer.html" },
          { id: "us-cpi-sa", label: "Seasonally Adjusted", href: "us-cpi-sa.html" },
          { id: "us-cpi-areas", label: "Regions & Metro Areas", href: "us-cpi-areas.html" },
          { id: "us-weights", label: "Basket Weights", href: "us-weights.html" },
        ] },
      { id: "us-prices", label: "Retail Prices", href: "us-prices.html" },
      { id: "us-wages", label: "Wages", href: "us-wages.html" },
    ],
  },
  {
    id: "us-rates", market: "us", label: "Rates", suffix: "US Rates",
    pages: [
      { id: "us-treasury", label: "Treasury Yields", href: "us-treasury.html" },
    ],
  },
  {
    // The US large caps held at full filed depth (company-facts, 2009 on).
    // One page: the covered list, and each company's record behind ?t=.
    id: "us-companies", market: "us", label: "Companies", suffix: "US Companies",
    pages: [
      { id: "us-companies", label: "Company Financials", href: "us-companies.html" },
    ],
  },
  {
    // Everything about using the data rather than the data itself — how to
    // connect, the manual, the API reference and the methodology — is one
    // section. As two sections ("Data Access", "Methodology") they took a
    // sixth of the bar and pushed it off the edge once the market switch and
    // a signed-in account were added. Every URL is unchanged, and every page
    // footer still links the methodology directly.
    id: "connect", market: "shared", label: "Docs", suffix: "Docs",
    pages: [
      { id: "connect", label: "Setup", href: "connect.html" },
      { id: "manual", label: "Manual", href: "manual.html" },
      { id: "api", label: "API Reference", href: "api.html" },
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

  // The brand always returns to the landing page. It carries no section
  // suffix any more: the market tab, the strip and the trail at the top of
  // the page each name where the reader is, and a screenshot keeps all three.
  //
  // The mark is inlined rather than an <img> on purpose: an SVG loaded through
  // <img> is an isolated document, so `currentColor` resolves to black there
  // and the ring disappears against the navy header. Inline, it inherits
  // --obs-header-ink and is correct in both themes for free. It is also the
  // simplified line-art mark, not the full-colour disc: at 20px the detailed
  // version is an indistinct blob, and the header is the one place the mark is
  // always small. assets/favicon.svg is the same reasoning applied to the tab
  // icon; assets/logo.svg keeps the full-colour disc for large uses.
  var brand = '<a class="brand" href="index.html">' + BRAND_MARK + esc(NAV_BRAND) + "</a>";

  // Which market the reader is in. A market page says so itself; a shared
  // page (Docs) and the landing page keep the market last visited.
  var isDocs = !!section && section.market === "shared";
  var market = section && !isDocs ? section.market : null;
  try {
    if (market) localStorage.setItem("obs-market", market);
    else market = localStorage.getItem("obs-market");
  } catch (e) { /* storage blocked: fall back to Japan below */ }
  if (market !== "us") market = "jp";
  var marketObj = NAV_MARKETS[market === "us" ? 1 : 0];

  // First tier: the markets, in full words, and nothing else. The one
  // question the navy bar answers is "which country am I looking at".
  var markets = '<nav class="site-nav" aria-label="Market">' +
    NAV_MARKETS.map(function (m) {
      return '<a href="' + esc(m.entry) + '"' +
        (!isDocs && m.id === market ? ' aria-current="page"' : "") + ">" +
        esc(m.label) + "</a>";
    }).join("") + "</nav>";

  header.innerHTML =
    '<div class="inner">' + brand + markets +
    '<div class="header-right">' +
    '<a class="header-link" href="connect.html"' +
      (isDocs ? ' aria-current="page"' : "") + ">Docs</a>" +
    '<span class="header-asof" id="header-asof"></span>' +
    '<span class="header-account" id="header-account"></span>' +
    '<button class="theme-toggle" type="button">Dark Mode</button>' +
    "</div></div>";

  // The account control asks the server who is signed in, and renders nothing
  // at all where accounts are not switched on — a "Sign in" link to a feature
  // that does not exist is worse than no link. The slot reserves its width, so
  // the bar cannot jump when the answer arrives.
  (function accountSlot() {
    var slot = document.getElementById("header-account");
    if (!slot || !window.fetch) return;
    fetch("/api/v1/account/me", { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (r.status === 404) return null;               // feature off
        // on, nobody signed in; while sign-in is invite-only the public
        // header offers nothing (the invited use signin.html directly)
        if (r.status === 401) return r.json().catch(function () { return {}; })
          .then(function (b) { return b && b.invite_only ? null : { email: null }; });
        if (!r.ok) return null;
        return r.json();
      })
      .then(function (me) {
        if (!me) return;
        var here = location.pathname.replace(/^\//, "") + location.search;
        if (!me.email) {
          slot.innerHTML = '<a href="signin.html?returnTo=' + encodeURIComponent(here) +
            '">Sign in</a>';
          return;
        }
        // A fixed-width "Account" control, not the address: an email is as
        // long as its owner made it, and the bar has no room to give. The
        // address is the first line of the menu, and the button's title.
        slot.innerHTML = '<span class="acct-menu">' +
          '<button type="button" aria-expanded="false" title="Signed in as ' +
          esc(me.email) + '">Account \u25be</button>' +
          '<span class="acct-pop" hidden>' +
          '<span class="acct-who">' + esc(me.email) + "</span>" +
          '<a href="#" data-do="signout">Sign out</a></span></span>';
        var btn = slot.querySelector("button");
        var pop = slot.querySelector(".acct-pop");
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          var open = pop.hidden;
          pop.hidden = !open;
          btn.setAttribute("aria-expanded", String(open));
        });
        document.addEventListener("click", function (e) {
          if (!pop.hidden && !slot.contains(e.target)) {
            pop.hidden = true;
            btn.setAttribute("aria-expanded", "false");
          }
        });
        pop.addEventListener("click", function (e) {
          var item = e.target.closest("[data-do='signout']");
          if (!item) return;
          e.preventDefault();
          // A reload rather than a redirect: whichever page the reader is on
          // is still readable signed out, so they stay where they were.
          fetch("/api/v1/account/signout", { method: "POST" })
            .then(function () { location.reload(); })
            .catch(function () { location.reload(); });
        });
      })
      .catch(function () { /* the header is not the place to report this */ });
  })();

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

  // Second tier: the current market's sections (or, on a Docs page, the
  // Docs pages). A section with one page is a plain link; a section with more
  // opens a menu of its pages, and a page's in-page views are listed under it
  // so everything in the market is two clicks from anywhere.
  var stripSections = isDocs ? [] : NAV_SECTIONS.filter(function (s) {
    return s.market === market;
  });
  var sub = document.createElement("nav");
  sub.className = "site-subnav";
  sub.setAttribute("aria-label", isDocs ? "Docs" : marketObj.label + " sections");
  var items = isDocs
    ? section.pages.map(function (p) {
        return '<a href="' + esc(p.href) + '"' +
          (owns(p) ? ' aria-current="page"' : "") + ">" + esc(p.label) + "</a>";
      })
    : stripSections.map(function (s, n) {
        var current = s === section;
        if (s.pages.length === 1) {
          return '<a href="' + esc(s.pages[0].href) + '"' +
            (current ? ' aria-current="page"' : "") + ">" + esc(s.label) + "</a>";
        }
        return '<button type="button" class="subnav-sec" data-sec="' + n + '"' +
          ' aria-expanded="false" aria-haspopup="true"' +
          (current ? ' aria-current="true"' : "") + ">" + esc(s.label) +
          ' <span class="caret" aria-hidden="true">\u25be</span></button>';
      });
  sub.innerHTML = '<div class="inner">' + items.join("") + "</div>" +
    '<div class="subnav-panel" hidden></div>';
  header.parentNode.insertBefore(sub, header.nextSibling);

  var inner = sub.firstChild;
  var panel = sub.lastChild;
  var openBtn = null;

  function closePanel() {
    if (!openBtn) return;
    openBtn.setAttribute("aria-expanded", "false");
    openBtn = null;
    panel.hidden = true;
  }

  function openPanel(btn) {
    var s = stripSections[Number(btn.getAttribute("data-sec"))];
    var count = 0;
    panel.innerHTML = s.pages.map(function (p) {
      count += 1 + (p.tabs ? p.tabs.length - 1 : 0);
      var views = (p.tabs || []).filter(function (t) { return t.href !== p.href; });
      return '<div class="grp"><a href="' + esc(p.href) + '"' +
        (owns(p) ? ' aria-current="page"' : "") + ">" + esc(p.label) + "</a>" +
        views.map(function (t) {
          return '<a class="view" href="' + esc(t.href) + '"' +
            (t.id === pageId ? ' aria-current="page"' : "") + ">" + esc(t.label) + "</a>";
        }).join("") + "</div>";
    }).join("");
    panel.className = "subnav-panel" + (count > 14 ? " wide" : "");
    panel.hidden = false;
    // Under its button, but never past the right edge of the viewport. The
    // panel is a child of the strip, not of the scrolling row, so the row's
    // sideways scroll on a phone can never clip it.
    var sr = sub.getBoundingClientRect(), br = btn.getBoundingClientRect();
    var left = Math.max(8, Math.min(br.left - sr.left - 12,
                                    sr.width - panel.offsetWidth - 8));
    panel.style.left = left + "px";
    btn.setAttribute("aria-expanded", "true");
    openBtn = btn;
  }

  inner.addEventListener("click", function (e) {
    var btn = e.target.closest(".subnav-sec");
    if (!btn) return;
    e.stopPropagation();
    if (openBtn === btn) { closePanel(); return; }
    closePanel();
    openPanel(btn);
  });
  document.addEventListener("click", function (e) {
    if (openBtn && !panel.contains(e.target)) closePanel();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && openBtn) { var b = openBtn; closePanel(); b.focus(); }
  });
  window.addEventListener("resize", closePanel);
  inner.addEventListener("scroll", closePanel);

  // The strip scrolls sideways on a phone, and a market's later sections sit
  // off-screen — so the one you are in can be invisible. Bring it into view
  // once, without scrolling the document itself.
  var here = inner.querySelector('[aria-current]');
  if (here && inner.scrollWidth > inner.clientWidth) {
    inner.scrollLeft = Math.max(0, here.offsetLeft - 20);
  }

  // The trail at the top of the content: market, section, page. It is what
  // the brand suffix used to do — name the place in words a screenshot keeps
  // — with the country first, since that is the distinction readers lose.
  if (section) {
    var pageLabel = "";
    section.pages.forEach(function (p) {
      if (p.id === pageId) pageLabel = p.label;
      (p.tabs || []).forEach(function (t) {
        if (t.id === pageId && t.href !== p.href) pageLabel = p.label + " \u00b7 " + t.label;
      });
    });
    var trail = isDocs
      ? [["Docs", "connect.html"]]
      : [[marketObj.label, marketObj.entry],
         [section.label, section.entry || section.pages[0].href]];
    if (pageLabel && pageLabel !== section.label) trail.push([pageLabel, null]);
    document.addEventListener("DOMContentLoaded", function () {
      var main = document.querySelector("main");
      if (!main || document.body.classList.contains("page-home")) return;
      var el = document.createElement("nav");
      el.className = "crumbs";
      el.setAttribute("aria-label", "You are here");
      el.innerHTML = trail.map(function (c) {
        return c[1] ? '<a href="' + esc(c[1]) + '">' + esc(c[0]) + "</a>"
                    : '<span aria-current="page">' + esc(c[0]) + "</span>";
      }).join('<span class="sep" aria-hidden="true">/</span>');
      main.insertAdjacentElement("afterbegin", el);
    });
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

/* ---------- section notes: two lines, then a toggle ----------

   Every section carries a paragraph explaining what its numbers are. They
   average four or five lines, and stacked above a chart they push the thing
   the reader came for below the fold. The first two lines carry the
   definition; the rest are caveats — read once, then in the way.

   So the note is folded to two lines with a "More" toggle beside it. The
   text is never removed: it stays in the DOM, so find-on-page, a crawler,
   and the prerendered answer pages all see the whole paragraph. A note that
   already fits gets no toggle, and the fit is measured again on resize,
   because a note that fits on a wide screen will not on a phone. */
(function () {
  var COLLAPSED_LINES = 2;

  function wrap(p) {
    if (p.querySelector(".section-sub-text")) return p.querySelector(".section-sub-text");
    var span = document.createElement("span");
    span.className = "section-sub-text";
    while (p.firstChild) span.appendChild(p.firstChild);
    p.appendChild(span);
    return span;
  }

  function fits(p, text) {
    // Measured while clamped: a clamped box that is not overflowing is short
    // enough to show whole. Nothing to measure on a hidden section.
    if (!p.offsetParent && p.offsetHeight === 0) return null;
    var had = p.classList.contains("is-clamped");
    p.classList.add("is-clamped");
    var over = text.scrollHeight - text.clientHeight > 1;
    if (!had) p.classList.remove("is-clamped");
    return !over;
  }

  function apply(p) {
    var text = wrap(p);
    var short = fits(p, text);
    if (short === null) {
      // Laid out in a hidden section; measure it when it is on screen.
      p.classList.add("section-sub-unmeasured");
      return;
    }
    p.classList.remove("section-sub-unmeasured");
    var btn = p.querySelector(".section-sub-more");
    if (short) {
      p.classList.remove("is-clamped");
      if (btn) btn.remove();
      return;
    }
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "section-sub-more";
      btn.addEventListener("click", function () {
        var folded = p.classList.toggle("is-clamped");
        btn.textContent = folded ? "More" : "Less";
        btn.setAttribute("aria-expanded", folded ? "false" : "true");
      });
      p.appendChild(btn);
      // Opened by hand, a note stays open until its section is redrawn.
      p.classList.add("is-clamped");
      btn.textContent = "More";
      btn.setAttribute("aria-expanded", "false");
    }
  }

  // Measuring costs a layout read, so a note that still has its wrapper is
  // left alone unless the window changed width. Without that guard the sweep
  // and the contents strip above take turns mutating the page, and a page
  // that never stops mutating never gets swept at all.
  var busy = false;
  function sweep(remeasure) {
    busy = true;
    var notes = document.querySelectorAll("p.section-sub");
    Array.prototype.forEach.call(notes, function (p) {
      if (remeasure || !p.querySelector(".section-sub-text") ||
          p.classList.contains("section-sub-unmeasured")) apply(p);
    });
    // Our own wrapping and toggling mutate the page too; the records they
    // cause reach the observer before this clears the flag.
    setTimeout(function () { busy = false; }, 0);
  }

  document.addEventListener("DOMContentLoaded", function () { sweep(true); });
  window.addEventListener("load", function () {
    sweep(true);
    setTimeout(function () { sweep(true); }, 2500);
  });

  var timer = null;
  window.addEventListener("resize", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { sweep(true); }, 200);
  });

  // Sections that only appear once data arrives are picked up here, and so is
  // a note a page rewrites itself — the population history note changes with
  // the view, which drops our wrapper on the floor.
  document.addEventListener("DOMContentLoaded", function () {
    if (!window.MutationObserver) return;
    var main = document.querySelector("main");
    if (!main) return;
    var pending = null;
    new MutationObserver(function () {
      if (busy || pending) return;             // a fixed window, never pushed back
      pending = setTimeout(function () { pending = null; sweep(false); }, 400);
    }).observe(main, { childList: true, subtree: true });
  });
})();
