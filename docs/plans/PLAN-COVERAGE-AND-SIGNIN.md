# Coverage List + Email Sign-In — UI/UX plan

> Status: **sign-in built 16 September 2026** — `observatory/web/signin.html`,
> `web/assets/signin.js`, `app/accounts.py`, the header slot in `nav.js`. Delivery is
> Resend. The coverage list itself is still to build.
> Parent: [PLAN-INVESTMENT-ASSISTANT.md](PLAN-INVESTMENT-ASSISTANT.md) — this is the front
> half of M0 (accounts) and the first half of M1 (coverage), UI only.
> Design gate: the `ui-ux-design` skill. Reference architecture for sign-in: the GSA
> platform's passwordless reader login (`~/Projects/gsa-platform`,
> `docs/features/auth-and-roles.md`), minus institutions.

---

## 1. Scope

**In:** a sign-in screen (email link, no password), the link-redemption screen, an account
control in the header, and a Coverage page where a signed-in user keeps a list of companies.

**Out, deliberately:** alerts and the event feed (they need the diff engine), notes, saved
screens, API keys, firms, teams, passwords, institutional access, SSO, and any per-user
write path into the DuckDB files.

**Day-one value, without alerts.** The Coverage page must be worth opening before a single
alert exists. It is: *my companies, what the platform holds on each, and the newest filing
we have for them* — one click from each to the company profile. Alerts arrive later into a
slot this layout already reserves.

## 2. The question each screen answers

| Screen | "A user opens this to find out…" |
| --- | --- |
| `signin.html` | …how to get into my account. One field, one button, nothing else. |
| `signin.html?token=…` | …whether my link worked. |
| `coverage.html` | …which companies I follow, and what we hold on each right now. |

## 3. Sign-in — `web/signin.html` + `assets/signin.js`

One page, four states. The site header and sub-nav stay (a signed-out visitor is still a
reader of the public site); the content column narrows to a single card, `max-width: 420px`,
left-aligned text, top of the content column — not a vertically centred hero.

### 3.1 State A — ask

```
┌ Sign In ─────────────────────────────────────┐
│ Enter your email and we will send a          │
│ single-use sign-in link. There is no         │
│ password.                                    │
│                                              │
│ Email address *                              │
│ ┌──────────────────────────────────────────┐ │
│ │ you@firm.com                             │ │
│ └──────────────────────────────────────────┘ │
│ ┌───────────────────────────┐                │
│ │ Email Me a Sign-in Link   │  ← .btn-primary│
│ └───────────────────────────┘                │
│ An account saves your coverage list. The     │
│ public site stays free without one.          │
└──────────────────────────────────────────────┘
```

- `type="email"`, `autocomplete="email"`, visible `<label>` — never a placeholder as label.
- Button disabled until the field is non-empty; label becomes "Sending…" while in flight.
- Signing in and signing up are the same action: clicking the emailed link proves the
  address and creates the session. No separate "verify your address" round trip, no second
  form. (GSA's `SigninLinkForm` behaviour; it is the reason the copy never says "register".)
- `?returnTo=` is honoured for same-site relative paths only, defaulting to `coverage.html`.

### 3.2 State B — sent (replaces the form in the same card, `role="status"`)

> **Check your email**
> We sent a sign-in link to **you@firm.com**. It works once and expires in 30 minutes.
> _Use a different address_ ← text button, returns to State A

No redirect. The address stays on screen so a typo is visible.

### 3.3 State C — redeeming (`signin.html?token=…`)

H1 "Signing you in…", one line of sub-copy. The token is exchanged exactly once (guard a
double run) and the page then does a full navigation to `returnTo`, so the header renders
against the new session.

### 3.4 State D — link dead

> **This link has expired**
> Sign-in links work once and expire after 30 minutes. Request a new one and it will arrive
> in a moment. → primary "Send Me a New Link" (returns to State A, address prefilled if the
> token carried it)

### 3.5 Errors

Inline alert **above** the field (`role="alert"`), outline-only red, never a filled pill.
Translate, never surface a raw body: *what happened · what to do next*. A mail-delivery
failure is a real error and says so — we never claim an email was sent that was not.

### 3.6 What differs from GSA

| GSA has | Here |
| --- | --- |
| Password tab beside the link | **Link only.** No password ever stored. |
| Institutional login (CARSI), IP ranges | None. |
| Cloudflare Turnstile CAPTCHA | None — a CDN script breaks the no-dependencies rule. Per-address and per-IP rate limits on the send endpoint instead. |
| Newsletter opt-in checkbox | None. |
| Username-or-email identifier | Email only. |
| NextAuth JWT, React | Vanilla JS + a signed HttpOnly session cookie set by FastAPI. |

## 4. Header account control (`assets/nav.js`)

`header-right` gains one slot, before the theme toggle:

- **Signed out:** a plain text link "Sign in".
- **Signed in:** a text button showing the address (middle-truncated to ~22 chars) opening a
  small menu: **Coverage** · **Sign out**. Downward, below the sticky header, no avatar
  circle, no filled chip.

The nav renders synchronously from a static list; account state is fetched. Reserve the
slot's width so the header does not jump when the answer arrives, and render nothing (not a
spinner) until it does.

## 5. Coverage — `web/coverage.html` + `assets/coverage.js`

### 5.1 Layout, top to bottom

A **coverage matrix**, not a list of rows: the names you follow run down the side, the ten
company datasets run across the top, one mark per cell.

```
  Coverage                                    Filings held to 2026-09-14
  The companies you follow. Every figure is as filed; nothing here is computed.

  ┌ 🔍 Company name in English or Japanese, or securities code ─────────────┐
  └────────────────────────────────────────────────────────────────────────┘

  ══ COMPANIES ════════════════════════════════════════  6 of 100 ═════════

  Company                XS REG 5% B&P AGM BUY FIN FAC SEG SEC  Held  Latest
  ─────────────────────────────────────────────────────────────────────────
  7203 Toyota Motor      ●  ●   ●  ●   ●   ●   ●   ●   ●   ○    9/10  2026-06-10
  8306 Mitsubishi UFJ    ●  ●   ●  ●   ●   ●   ●   ●   ●   ○    9/10  2026-06-24
  4755 Rakuten Group     ●  ●   ●  ●   ●   ○   ●   ●   ●   ○    8/10  2026-03-26
  6502 Toshiba           ●  ●   ●  ●   ○   ○   ○   ○   ●   ○    5/10  2023-06-28
  ─────────────────────────────────────────────────────────────────────────
  Names covered          6  6   6  6   5   4   5   5   6   0
```

Read a row: where that company's gaps are. Read a column: which dataset is thin across
everything you follow. The bottom line counts each column, so a dataset covering none of
your names — SEC filings, for a Japan-only list — is visible without opening anything.

### 5.2 The parts

| Part | Shows | From |
| --- | --- | --- |
| Row head | Code, English name, filed Japanese name and industry beneath. Sticky when the matrix scrolls sideways. | company identity |
| Ten cells | Filled = filings held in that dataset; open = nothing filed. Each carries its dataset name for a screen reader, not only the mark. | `/coverage` |
| Held | `9 / 10`, so the matrix sorts by how complete a name is | the cells |
| Latest filing | Newest filing held; `—` when none. A date older than a year is marked. | `vintage.filed_date` |
| Bottom line | How many of your names each dataset covers | the cells |
| Remove | Asks in the row — "Remove? Yes · Cancel" — never a modal | — |

### 5.3 States

- **Empty:** heading, one line — "You are not following any companies yet." — the search
  field focused, and three real starters as text buttons (Toyota 7203 · MUFG 8306 ·
  Sony 6758). No illustration, no empty-state graphic.
- **Signed out:** the page still renders at its own URL (citable), with the table replaced
  by one line and a primary "Sign In" button carrying `?returnTo=coverage.html`. Never a
  silent redirect.
- **Loading:** existing `.skeleton` rows, not a spinner.
- **Adding:** the row appears immediately in a muted state and settles when the server
  confirms; a failure removes it and shows an inline alert.
- **Removing:** the button becomes "Remove? Yes · Cancel" in place. No modal.
- **Stale data:** the existing `#stale-banner` at the top, as every other page.
- **Full:** at the tier cap the h2 note reads `100 of 100` and the search field explains
  what to remove first.

### 5.3a How it behaves

- Every column sorts on a click, ascending then descending, the arrow showing which — from
  `sortable.js`, never a hand-written sort.
- The search field takes arrow keys and Enter as well as the mouse; Escape closes it, and
  the results list must not be clipped by the card it opens inside.
- An added row appears at once and settles when the server confirms; a failed save takes the
  row back out and says why above the field.
- Removing asks in the row — "Remove? Yes · Cancel" — never in a modal.
- Emptying the list returns the empty state, so the page is never a bare heading over
  nothing.

### 5.4 Mobile (390)

The company column is pinned and the ten dataset columns scroll under it — four or five
show, the rest are a swipe away, with Held, Latest filing and Remove at the far end of the
same scroll. The search results list must not be clipped by the card it sits in — the known
`overflow:hidden` trap in Step 9 of the design skill.

## 6. Entry points elsewhere

- **`company.html`:** an outline "Follow" / "Following" button beside the h1. The page's
  filled action stays Download CSV — one primary per view. Signed out, it links to
  `signin.html?returnTo=company.html%3Fcode%3D7203`.
- **`screener.html` / `cohorts.html`:** "Add all to coverage" on a result set. Useful, but
  defer until the list itself is in use.

## 7. What has to exist behind it (not this plan's detail)

New namespace, not a dataset — the golden rule is untouched.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/account/signin-link` | ✅ send a link; 5/hour per address, 40/hour per IP |
| `POST /api/v1/account/session` | ✅ redeem a single-use token, set the HttpOnly cookie |
| `GET /api/v1/account/me` | ✅ `{email}` or 401 — what the header asks |
| `POST /api/v1/account/signout` | ✅ clear the cookie and drop that session |
| `GET/POST/DELETE /api/v1/me/coverage` | still to build — the list |

Built notes: `ACCOUNTS_ENABLED` is the kill switch, so with it unset the routes are not
mounted, `/me` 404s and the page says accounts are not open yet. Without `RESEND_API_KEY`
the link is written to the server log instead of emailed, which is how the flow is tested
locally (`ACCOUNTS_DEV_LINKS=1` also returns it in the response — laptop only). Account
paths are excluded from the shared response cache by prefix in `app/cache.py`: a per-reader
answer must never be served to somebody else.

Store: a **separate SQLite file** on the `data/` volume (`workspace.db`). Guardrail 5 stands
— the serving process still never writes DuckDB, and user data survives a dataset rebuild.

## 8. Components and tokens

Reuse: `.metric-card`, the `h2` navy band, `.search-rail` / `.search-field`, `.table-wrap`,
`sortable.js`, `.btn` / `.btn-primary`, `.banner`, `.skeleton`, `.badge` (unused here).

New, minimal, tokens only: `.form-card`, `.form-field`, `.form-label`, `.form-input`,
`.form-hint`, `.form-alert` appended to `app.css`. No new runtime dependency, no CDN, no
build step, no `--obs-*` redefinition.

## 9. Look-at-it gate (before this is ever called done)

Screenshots at **390 / 768 / 1280 / 1440, light and dark**, and:

- worst-case row: longest Japanese name (三菱ＵＦＪフィナンシャル・グループ), a company with
  `1 / 10` held, and one with no filing date at all (`—`, not blank, not `0`);
- the account menu opened at every width — not clipped, not painted under the next section;
- the add-company dropdown opened inside the card at 390;
- the sent state, the expired-link state and an inline error, each rendered, not imagined;
- tab order through the sign-in form, and `role="status"` / `role="alert"` announced.

## 10. Decisions (settled 15 September 2026)

1. **Nav placement: no nav entry.** Coverage is reached from the header account menu and
   from the Follow button on a company page. It becomes a top-level section only when
   Alerts and Research join it — the design skill's "ask before a top-level nav item" rule
   is respected by not adding one.
2. **Sign-up is open** to anyone with an email address, rate-limited per address and per IP.
   Coverage is free for now; the list is the funnel into the paid tier.
3. **Companies only.** Series (CPI, the JGB curve) come later, as a second list or a type
   column — not in this build.
4. **The company universe is report-filers** (16 Sep 2026): anything that has filed an
   annual securities report — 4,586 entities, of which 3,813 carry a ticker and 773 are
   unlisted filers addressed by EDINET code. The other 6,788 EDINET codes (5% filers,
   individuals, foreign funds, counterparties named in someone else's filing) are searchable
   inside a company's page but are not companies you can follow.

Still open: session length (proposed 30 days, sliding) against the link's 30-minute expiry.
