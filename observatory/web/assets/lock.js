/* One click, one request.

   Added to the head of every page by the server (app/prerender.py,
   app/research_pages.py), so no page can ship without it. It wraps
   window.fetch:

   - A request that changes something (POST, PUT, PATCH, DELETE) started by a
     click, a form submit or a dropdown change switches that control off until
     the server has answered. A slow reply can no longer turn ten clicks into
     ten keys (2026-10-03, Create Key).
   - The same change sent again while the first is still on its way (same
     method, address and body) is not sent twice: the second caller gets the
     first one's answer.

   Reads, and saves sent with keepalive on the way out of a page, pass
   straight through. Code that must hold a control across several requests in
   a row can call ploverLock(control, promise) itself.

   Every write on the site goes through window.fetch, and ci/guards.py keeps it
   that way (no XMLHttpRequest, no saved copy of fetch). */
(function () {
  "use strict";
  if (!window.fetch || window.fetch.ploverLocked) return;
  var raw = window.fetch;
  var trigger = null;
  var inflight = {};

  var CONTROL = "button, input[type=submit], input[type=button], select, a, [role=button]";

  /* The control the person just used. Kept for the rest of this task and its
     promise callbacks, then dropped, so a timer's save later on locks nothing. */
  function remember(el) {
    if (!el) return;
    trigger = el;
    setTimeout(function () { if (trigger === el) trigger = null; }, 0);
  }
  document.addEventListener("click", function (e) {
    remember(e.target && e.target.closest ? e.target.closest(CONTROL) : null);
  }, true);
  document.addEventListener("submit", function (e) {
    var form = e.target;
    remember(e.submitter || (form.querySelector && form.querySelector("[type=submit], button:not([type])")));
  }, true);
  document.addEventListener("change", function (e) {
    if (e.target && e.target.tagName === "SELECT") remember(e.target);
  }, true);

  function lock(el) {
    if (!el) return null;
    if (el.ploverBusy) { el.ploverBusy += 1; return el; }
    if ("disabled" in el && el.tagName !== "A") {
      if (el.disabled) return null;  // the page switched it off itself: leave it to the page
      el.disabled = true;
      el.ploverHow = "disabled";
    } else {
      el.ploverHow = "pointer";
      el.style.pointerEvents = "none";
    }
    el.ploverBusy = 1;
    el.setAttribute("aria-busy", "true");
    return el;
  }

  function release(el) {
    el.ploverBusy -= 1;
    if (el.ploverBusy > 0) return;
    if (el.ploverHow === "disabled") el.disabled = false;
    else el.style.pointerEvents = "";
    el.removeAttribute("aria-busy");
  }

  window.ploverLock = function (el, promise) {
    var held = lock(el);
    var done = function () { if (held) release(held); };
    Promise.resolve(promise).then(done, done);
    return promise;
  };

  window.fetch = function (input, init) {
    var method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
    if (method === "GET" || method === "HEAD" || (init && init.keepalive)) {
      return raw.call(window, input, init);
    }
    var url = typeof input === "string" ? input : (input && input.url) || String(input);
    var body = init ? init.body : null;
    // Only a text body can be compared; an uploaded file is always sent.
    var key = body == null || typeof body === "string" ? method + " " + url + "\n" + (body || "") : null;
    if (key && inflight[key]) {
      return inflight[key].then(function (r) { return r.clone(); });
    }
    var held = lock(trigger);
    var sent = raw.call(window, input, init);
    if (key) inflight[key] = sent;
    var forget = function () { if (key && inflight[key] === sent) delete inflight[key]; };
    // Switch the control back on once the answer has been read and the page
    // has had its turn to show it, not the moment the first byte arrives.
    var settle = function () { if (held) setTimeout(function () { release(held); }, 0); };
    sent.then(function (r) {
      forget();
      return r.clone().text().then(settle, settle);
    }, function () { forget(); settle(); });
    return key ? sent.then(function (r) { return r.clone(); }) : sent;
  };
  window.fetch.ploverLocked = true;
})();
