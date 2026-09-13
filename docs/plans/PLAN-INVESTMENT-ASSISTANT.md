# Investment Assistant — a PM workspace on top of the Observatory

> Status: **draft for discussion**, 11 September 2026, revised the same day into an
> *agent portal* shape after reviewing Funfo Agent OS. Nothing here is built.
> Companion: the design canvas of the four screens (link in the session that produced this
> plan). Strategy context: [PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md).

---

## 1. What it is, in one paragraph

Today the Observatory is a library: every number is there, but the reader has to go and
look. The Investment Assistant turns it into a desk. A portfolio manager or analyst signs
in, names the companies they cover, and from then on the platform watches those companies
for them: a new filing, a buyback that stalls, a cross-holding sold down, a board change, a
CPI print — each arrives as an event with the source attached. Their research notes pin to
the numbers they cite. Their own Claude reads the same data over MCP. And they can extend
the desk with their own tools — a saved screen, a custom column, an internal data source —
without us writing code for them.

**This is the paid product.** The public site stays free and is the funnel. The Assistant
is what the "Individual" and "Firm" tiers buy (see the pricing note in §7).

## 2. Why this and not a chat box

Two settled decisions shape it:

- **We do not host an LLM.** `ASK_ENABLED` stays off. Professional users will not trust our
  model over the numbers, and it is a support liability. The assistant in this plan is
  the user's *own* Claude (or any MCP client), connected to our MCP server. We supply the
  data, the tool trail, and the workspace; they supply the model and the judgement.
- **The moat is vintages.** An *alert* is nothing more than the difference between two
  vintages of the same dataset, filtered to the names a user cares about. Alerts are the
  first commercial use of the vintage archive, and they only get better as it deepens.

So the product is *not* "ask questions in a box". It is a **desk of specialists**: named,
versioned analyst-agents that each own a job (watch buybacks, read filings, brief on CPI),
run on a schedule against the Observatory's tools, and post what they find with the filing
attached. The LLM runs on the **customer's own model key**; the Observatory hosts the
schedule, the tools and the audit trail, never a model of its own. That is a deliberate
step past "no LLM at all" and is the one decision in this plan that changes a settled rule.

## 3. The shape: an agent portal

Seven sections behind an icon rail, in the pattern of an agent operating system, tailored
to an investor's desk:

| Section | What the user does there | Investor tailoring |
| --- | --- | --- |
| **Inbox** | Approvals waiting on them, finished runs, events on their names, shared threads. | The approval card is the key control: a specialist reads freely; a Slack post or email waits for a person. |
| **Desk** | Their hired specialists under their name, each with last run and next run; the `#desk` feed where specialists post with their tool trail. | Feed posts carry the filing id and the Official-as-filed badge, or the derived tag with a formula. |
| **Specialists** | The talent pool: hire a ready-made analyst. Each card is a brief + Observatory tools + workflows + a version. | Coverage Clerk, Buyback Monitor, Macro Briefer, Unwind Scout, Filing Reader, Board & Pay Analyst, Claim Checker, Model Feeder, Note Writer. |
| **Research** | Threads with a specialist; each keeps its own memory. Notes pin to a number and its vintage. | The specialist's page shows what it watches and the tool behind each item. |
| **Files** | The specialist's workspace: rules, run logs, exports, the coverage list. | Everything a specialist writes is a file the user can read. |
| **Audit** | Tools ranked by who uses them; runs, calls, tokens, approvals; MCP connections. | Trust is auditable, not asserted: no specialist has any other route to a number. |
| **Settings** | Model key, Observatory key, approval policy, delivery, external MCP servers, members, licence. | The approval policy is one table: read freely · own workspace freely · outward asks first · **no order routing, ever**. |

A **specialist** is: a brief (versioned like software), a tool list drawn from the 26 MCP
tools plus the user's own declared tools, a schedule or trigger (nightly refresh, each new
filing, each release), and a delivery target. It is the unit we sell, update and support.

## 4. What "add their own tools" means — and what it does not

Three kinds, in order of how soon we can ship them:

1. **Declarative tools (no code).** A saved screen becomes a tool the assistant can call
   ("my_activist_screen"). A custom column is a formula over published metrics
   (`fcf_yen / market_cap`), shown with its formula, never a badge — same trust contract as
   every derived rate. Alert rules are tools of the same kind.
2. **External MCP servers.** The user registers another MCP server (their firm's internal
   research, a broker feed, their own model). Their Claude sees both servers side by side.
   We store only the URL and a label — never their credentials.
3. **Uploaded code (Python snippets running on our servers).** **Not in scope.** Hosting
   user code is a security surface and a support burden that a two-person data vendor
   cannot carry. If a firm needs this, they run it on their side and expose it as an MCP
   server (kind 2).

## 5. Architecture — what has to change

The golden rule (datasets are adapters, core never changes) still holds for datasets. The
Assistant is **not a dataset**; it is a new namespace, like the cross-shareholding DB.

- **Accounts.** The first user-facing login. Email magic link, no passwords. An account owns
  an API key, a coverage list, rules, notes, tools. Firms are a group of accounts.
- **Workspace store.** Per-user state lives in its **own store** — SQLite on the `data/`
  volume (or Postgres on Railway if concurrency demands it). It must **not** go into the
  macro or equity DuckDB files: ingest guardrail 5 says the serving process never writes to
  them, and user data must survive a dataset rebuild.
- **Event engine.** Runs after each ingest and after the nightly equity refresh: for each
  dataset that changed, diff the new vintage against the previous one, restrict to rows
  touching any covered name or subscribed series, write events. Rules are evaluated on
  events. Delivery: in-portal feed, daily email digest, Slack webhook.
- **Notes pinned to numbers.** A note stores the citable URL of the view and the vintage
  (release id + SHA-256) it was written against. If the number is later revised, the note
  shows both — the moat made visible.
- **MCP, per user.** The connect URL carries the user's key. Their coverage list and saved
  screens are exposed as tools (`my_coverage`, `my_screens`). Every call is logged and
  shown in the Research thread, as the home-page demo already promises.
- **Health.** Every new job (event engine, digest sender) reports to
  `/api/v1/catalog/health`. A silent alert pipeline is worse than none.

## 6. Milestones

| # | Milestone | Done when | Est. |
| --- | --- | --- | --- |
| M0 | Accounts + per-user keys + model key | Email-link sign-in; the user's Observatory key and their own model key stored (hashed / encrypted); keys revocable from the admin console | 2 wks |
| M1 | Runner + two specialists | A scheduler runs a specialist against the MCP tools on the user's model key; Coverage Clerk and Buyback Monitor post to `#desk` with tool trails; runs and calls recorded in Audit; health reports the runner | 4 wks |
| M2 | Inbox + approval policy + delivery | Approval cards gate every outward action; morning digest; Slack | 2 wks |
| M3 | Specialists pool + Desk | The talent-pool page, hire/open, versions and updates; the desk view; Macro Briefer, Unwind Scout, Filing Reader | 3 wks |
| M4 | Research, Files, own tools | Threads with memory; notes pinned to vintages; saved screens and formula columns as tools; external MCP servers | 4 wks |

Order matters: **M1 plus M2 is sellable on its own.** A Buyback Monitor that asks "may I
post: Toyota's window closed with ¥684bn unspent" the morning after the filing is the thing
a PM will pay for. Everything after deepens the lock-in.

## 7. Pricing, in one line each

- **Free:** the public site, unchanged.
- **Individual (~$50–100/month):** one account, one coverage list, alerts, notes, MCP key.
- **Firm (low five figures/year):** shared coverage lists, Slack delivery, external MCP
  servers, a licence letter, a support address.

## 8. Risks

| Risk | Treatment |
| --- | --- |
| Accounts open a security surface we have never had | Magic links only; no passwords stored; keys hashed; rate limits per key; one reviewer pass before launch |
| A per-user write path in the serving process | Separate store with its own file; DuckDB datasets stay read-only in the API |
| Alert noise kills trust faster than no alerts | Ship five event types, not fifty; every event carries its source line; digest, not push, by default |
| "Own tools" drifts into hosting user code | Kinds 1 and 2 only (§4); write it into this plan and the README |
| Hosting agent runs re-opens the "no LLM" decision | Specialists run on the customer's model key; every post carries its tool trail and filing id; the approval policy is fixed for outward actions; `ASK_ENABLED` on the public site stays off |
| A specialist posts a wrong number under our name | Posts are the specialist's, attributed as such, and every figure links to the filing; derived values carry the formula, never a badge |

## 9. Open decisions

- SQLite on the volume vs Postgres for the workspace store.
- Whether firms need SSO before the first firm sale (probably yes for a bank, no for a fund).
- Whether the runner is our own scheduler or a hosted agent runtime (Funfo-style "agent computer" per workspace). Own scheduler first; it is smaller.
- Which five event types ship in M2. Candidates: new annual report; buyback monthly report
  (progress, window close, unspent); cross-holding reduced or exited; board change; 5%
  filing; CPI and BOJ releases for subscribed series.
