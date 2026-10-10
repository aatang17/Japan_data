# PLAN — PloverResearch as a Publishing Platform (2C and 2B)

> **Status:** v1, 2026-10-09. §7 steps 1–2 **built 2026-10-09** (not yet committed or deployed);
> step 3 deferred until the trial is running (user's choice). **2026-10-10:** §8 added —
> every person has their own publication, and each publication sets up its own AI. **Built
> 2026-10-10** (not yet committed or deployed); see §8.9.
>
> **One-liner:** The place to write and sell research that is built on data — where every
> chart is live official data, frozen at the moment of publication, citable, and
> corrected in public — sold to individual writers (2C) and to research teams (2B).
>
> **Builds on:** the research desk already in the admin console (`app/research.py`,
> `desk.html`, AI tab, MCP drafting). See memories `research-desk-and-staff-logins` and
> `desk-writing-flow`. Related: [PLAN-INVESTMENT-ASSISTANT.md](PLAN-INVESTMENT-ASSISTANT.md)
> (the paid tier for readers), [PLAN-PLATFORM-VISION.md](PLAN-PLATFORM-VISION.md).

---

## 1. Bottom line

1. **Don't build "a better Substack".** Ghost and beehiiv already take 0% of a writer's
   subscription money against Substack's 10%, and Substack is still the default. Price
   is not what keeps writers there. The reader network is: Substack's app and
   recommendations bring in subscribers no writer can find alone.
2. **Compete where Substack can't follow: data-backed research.** On Substack a chart is
   a pasted picture. On Plover it is the real series, frozen at publication, with a
   source line, a CSV and a version history. That matters to people whose readers check
   the numbers: economists, equity analysts, strategists, policy researchers.
3. **One product, two buyers.** The writing tool is the same. Individuals (2C) pay for
   publishing and payments. Teams (2B) pay for review, access control, readership
   numbers and an audit trail. The 2B side is where the money is; the 2C side is where
   the reputation and the content come from.
4. **It also sells the data business.** Every chart an outside writer publishes is a
   Plover chart with a Plover source link. Writers become the distribution channel.

## 2. What we already have, and what is missing

**Already built (and unusual):**

| Have | Why it matters against Substack |
| --- | --- |
| Charts drawn from Plover data, frozen at publication date | Substack has no live data; screenshots can't be checked |
| Published versions can't be changed; corrections are v2 with a note | Research readers want to know what was said and when |
| Planning → drafting flow, research tabs, notes with sources | Built for how analysts work, not for essayists |
| AI drafting on the writer's own Claude/ChatGPT account | We don't pay for the writer's AI |
| Drafting over MCP from Claude or Codex | Writers can work from their own AI tools |
| RSS feed, `.md` copy of each article, sitemap, llms.txt | Findable by search engines and AI search |

**Missing before anyone outside the company can use it:**

1. **Public sign-up and separate publications.** Today the desk is one publication
   (PloverResearch) and writers are staff inside the admin console. Each writer or team
   needs their own publication, URL and branding. This is the largest technical change.
2. **Email sending.** A newsletter is an email first. We have no email provider wired up
   (the refresh alarm is waiting on a Resend key for the same reason).
3. **Subscriber lists.** Import (Substack lets writers export their list), sign-up
   forms, unsubscribe, bounce handling.
4. **Payments.** Readers paying writers, through Stripe Connect, so the money goes to
   the writer and we never hold it.
5. **Charts from the writer's own data.** Plover data covers macro and filings. An
   analyst also needs to chart a spreadsheet they built. Without this, most pieces will
   still need a pasted picture.
6. **Custom domains**, and a plain reading page for subscribers (comments can wait).

## 3. Who buys what

### 2C — individual writers

**Who:** independent economists and strategists, ex-sell-side analysts gone solo,
academics, finance writers already on Substack. Asia and Japan first, because that is
our data depth and the user's network.

**What they get:** write with real data charts, publish free or paid, send by email,
keep 100% of subscription money.

**Pricing (to test, not settled):**

| Plan | Price | What's in it |
| --- | --- | --- |
| Free | $0 | Publish with Plover data charts, Plover branding, up to ~1,000 email subscribers |
| Writer | ~$25/mo | Paid subscriptions at 0% fee, custom domain, own-data charts, unlimited email |
| Writer Pro | ~$75/mo | Adds the Investment Assistant data tools (deep company data, screens, alerts) |

Why a monthly fee and not Substack's 10%: research writers price high and have few
subscribers ($500–$2,000 a year each). A 10% cut on that is large and they notice it. A
flat fee is easier to sell to that writer. Our costs (email, data) are low and AI runs
on their account.

### 2B — research teams

Ranked by how likely they are to buy and how fast:

1. **Independent research boutiques (2–20 analysts).** Too small for BlueMatrix (the
   standard sell-side publishing system, serving ~1,000 research firms), too serious for
   Substack. They need: review before publishing, client lists with access control,
   who-read-what reports, and a permanent archive. **Best first 2B target.**
2. **In-house teams that publish to outsiders:** think tanks, investor relations teams,
   bank and broker economics teams below the top tier, consultancies. Same needs, plus
   their brand on the page.
3. **Buy-side internal research** (funds writing notes for their own PMs). Private
   publication, no email to outsiders. This overlaps with the Investment Assistant; sell
   them as one package.

**What a team pays for, on top of the writer plan:**

- Roles: writer, editor, compliance reviewer, publisher. Nothing goes out without
  approval when the team turns that on.
- Client lists and access control: which client sees which piece.
- Readership reports: who opened what, for how long (this is what sales teams use to
  call clients — the user knows this from the desk).
- A compliance archive: every version, every approval, every send, kept and exportable.
- Single sign-on, own domain, own branding.

**Pricing (to test):** ~$100 per writer per month for small teams; annual firm
contracts in the low five figures for compliance, sign-on and readership reporting.
That matches the "Firm" tier already planned for the Investment Assistant, so a firm can
buy both under one contract.

### Later — a reader bundle

Once there are enough good writers, sell institutions **one subscription to read all of
them**, and share the money with writers by readership. This is Smartkarma's model
(Singapore, independent Asia research, one fee for the buy-side, revenue paid out by
engagement). Smartkarma is a direct competitor on this part, so it is a later option,
not the opening move. Our difference would be data-backed pieces and citable charts.

## 4. How to roll it out

Each phase has a gate. Don't start the next phase until the gate is passed.

| Phase | What | Gate to move on |
| --- | --- | --- |
| **0 — Use it ourselves** (now–Nov 2026) | Publish *Asia Economics Observations* on PloverResearch alongside Substack. Add email sending. | Every post goes out from Plover for 2 months without falling back to Substack |
| **1 — Invited writers** (Dec 2026–Feb 2027) | Separate publications, writer sign-up by invitation, Substack list import, own-data charts. Free. 5–10 writers from the user's network. | At least 5 writers publish twice a month for 2 months |
| **2 — Paid 2C** (Mar–May 2027) | Stripe Connect paid subscriptions, Writer plan, custom domains, open sign-up | 20 paying writers; writers' paid subscribers growing |
| **3 — Teams (2B)** (from Apr 2027, can overlap Phase 2) | Roles and approval, client lists, readership reports, compliance archive, sign-on | 3 boutiques on paid annual contracts |
| **4 — Reader bundle** | Institutional subscription across writers | Decide only after Phase 3 |

The first 2B pilot can start during Phase 1 with one friendly boutique, on hand-built
settings, to learn what compliance teams actually ask for before building it.

## 5. Risks

1. **Regulation of paid investment opinions.** In some countries, selling opinions on
   named stocks for money needs a licence. Japan in particular has a registration
   regime for investment advice. We must get legal advice before Phase 2 on: whether
   we, as the platform, carry any duty; what writers must disclose; and whether paid
   pieces naming stocks need restrictions by country. Today the Platform Vision plan keeps Plover
   out of advice regulation as a data and publishing product — outside writers change
   that picture.
2. **Moderation and liability.** Other people's content on our domain. We need terms of
   use, a takedown process, and a rule that writers' pieces are clearly theirs, not
   Plover's.
3. **Focus.** The data business is the core and its value grows only if the monthly
   ingest keeps running. A publishing platform needs support, email deliverability and
   payments work. Phases 0–1 are cheap; Phase 2 onward needs either more people or a
   clear sign of demand.
4. **Email deliverability.** Bulk email from a new sender lands in spam until the domain
   builds a record. Use an established provider and warm up slowly.
5. **Separate-publication change touches the data model.** The research store is
   PloverResearch-only today. Adding publications must keep the existing rules: published
   versions can't change, charts frozen at publication.

## 6. Decisions for the user

1. **Fee model for 2C:** flat monthly fee with 0% cut (recommended), or a percentage like
   Substack.
2. **First 2B segment:** independent boutiques (recommended), or in-house IR / think
   tanks.
3. **Phase 0 go-ahead:** move *Asia Economics Observations* onto PloverResearch, with
   Substack kept running in parallel.
4. **Legal review** timing: before Phase 2 opens paid subscriptions to outside writers.

## 7. How to structure it (added 2026-10-09)

### The publication is the unit

Everything hangs off a **publication**, as on Substack and Ghost. PloverResearch becomes
publication #1. A 2B team is not a separate product: it is a publication on the Team
plan, with extra features switched on.

| Thing | Belongs to | Holds |
| --- | --- | --- |
| Publication | its owner | name, address, branding, plan (Free / Writer / Team), Stripe account, sending domain |
| Member | one publication | a person and a role (below) |
| Article | one publication | drafts and immutable published versions, as today; slug unique within the publication |
| Reader | the platform (one account everywhere) | email, sign-in |
| Subscription | reader × publication | free, paid, complimentary, or granted by a team's client list |

**Roles within a publication:**

| Role | Can do |
| --- | --- |
| Owner | everything, including billing and members |
| Editor | edit and publish any article in the publication |
| Writer | write and preview their own articles; cannot publish |
| Reviewer (Team plan) | approve or send back; required before publish when the team turns approval on |

The Writer role is also the answer for trial users today: they can draft, and the
owner publishes.

### Three kinds of login, kept apart

1. **Plover staff** — the admin console (`app/staff.py`), for operations only.
   Writers leave it.
2. **Writers** — a writer home holding the desk. They sign in with the reader account
   (`app/accounts.py`, email-link sign-in, already built), so one person can be a reader
   and a writer, as on Substack.
3. **Readers** — `app/accounts.py`, unchanged.

### Addresses

- First: `/p/<publication>/<slug>` on the Plover domain.
- Writer plan: their own domain.
- PloverResearch's existing `/research/<slug>` URLs keep working forever (citable URLs).

### Money and email

- **Stripe Connect:** each publication links its own Stripe account; readers pay the
  writer directly and we never hold their money. Writers pay us for their plan through
  our own Stripe account.
- **Email:** Resend is already wired for sign-in links. Extend it to newsletters:
  shared sending domain on Free, the writer's own domain on paid plans.

### Run it as its own service

Same code repository, separate running service, calling the data API for charts.
Reasons:

1. A deploy of the data site is downtime while ingests run (Railway boot window), and
   the backfill copies after each deploy slow the desk for about an hour. Outside
   writers and paying subscribers can't absorb that.
2. Outside writers' content and logins stay away from the data side.

One SQLite file per store, with a publication id on each row, is enough for hundreds of
publications. Move to Postgres only if the service needs more than one server.

### What was built (2026-10-09)

- **Steps 1–2 done.** `app/writers.py` (roles), `app/writer_api.py` (Writer Desk API),
  `web/write.html` + `assets/write.js` (Writer Desk), publications/members in
  `app/research.py` (the articles table is rebuilt once on first open; every existing
  article becomes PloverResearch's), `/p/<publication>` pages in `app/research_pages.py`.
- **Differences from the sketch above:**
  - A writer is still a record in `app/staff.py`, so AI settings, keys and the Google link
    carry over. They sign in by **email link** (`app/accounts.py`) or, for the Plover team,
    by password.
  - The admin **Writing** permission is kept and means *editor of PloverResearch*
    (*owner* with Team). Memberships add to it; they don't replace it.
  - Until email sending is set up, owners **hand over sign-in links** themselves (72 hours,
    single use). Members are admitted past `ACCOUNTS_ALLOWED_EMAILS` automatically.
  - The API stays under `/admin/api` so the team's password cookie still reaches it; step 3
    can move it.
  - The team's connectors (Plover's keys) serve PloverResearch articles only. The skills
    and house style do **not**: they are one list for the whole site, so every
    publication's AI runs follow PloverResearch's, and only PloverResearch editors can
    change them (Admin → AI Setup). §8 fixes this.
  - Only the Team permission opens a publication. §8 replaces this.

### Build order

1. Publications and roles in the research store, with PloverResearch as #1. This alone
   makes trials safe.
2. Move the desk out of the admin console into the writer home, signed in through
   `accounts.py`.
3. **Every person has a publication, and each publication has its own AI setup** (§8).
   Needed before Phase 1: an invited writer must not write in PloverResearch's house style.
4. Split the publishing side into its own service.
5. Newsletter sending, subscriber lists, import from Substack.
6. Stripe Connect paid subscriptions (after the legal review in §5).

## 8. Every person has their own publication (added 2026-10-10)

**Assumption:** every person who writes on the platform owns a publication, as on
Substack. Some will also be members of other people's publications (a 2B team, a guest
spot). Nothing about a person's AI setup should then come from PloverResearch.

### 8.1 A publication for every writer

- **Invitation opens it.** While writers come by invitation (Phase 1), the Plover team
  invites a person, and that person's publication is opened with them as owner. With
  open sign-up (Phase 2), the first sign-in to the Writer Desk asks for a name and an
  address, and opens it.
- **One owned publication per person on Free.** More on paid plans.
- `writers.can_create_publications` stops requiring the Team permission. The rule
  becomes: a signed-in writer who owns no publication yet may open one.
- PloverResearch stays publication #1, owned by the Plover team.

### 8.2 What moves to the publication, and what stays with the person

| Setting | Belongs to | Who edits it | Today |
| --- | --- | --- | --- |
| Skills | publication | owner, editors | one list for the site (`team_skills`) |
| House style | publication | owner, editors | one text for the site (`team_settings`) |
| Connectors (outside tool servers and their keys) | publication | owner only | one list, PloverResearch only (`team_connectors`) |
| AI account (provider, model, key or Claude / Codex sign-in) | person | the person | already per person (`staff_ai`) |
| Google Drive | person | the person | already per person (`staff_google`) |
| AI connection keys for Claude Code / Codex | person | the person | already per person (`staff_keys`) |

Writers in a publication *use* its skills, house style and connectors; they can't change
them. Connectors are owner-only because they decide what data a run can reach and whose
keys it uses.

### 8.3 Which setup a run uses

- A run on an article uses **that article's publication's** skills, house style and
  connectors. The same writer gets different skills in different publications.
- A run with no article (a Claude Code session that hasn't opened one yet) uses the
  person's **own** publication's setup.
- A publication's connector keys never reach a run on another publication's article.
  This is the rule `research_ai._team_tools` enforces today for PloverResearch, made
  general: compare the connector's publication with the article's.

### 8.4 A new publication's starting setup

- It gets **its own copy** of the nine starter skills (Brainstorm … Headlines, Data
  Flash) and the default house style. They are the owner's to edit or delete. A starter
  skill they deleted is not put back.
- If we later improve a starter skill, publications that never edited it get the new
  text. Edited copies are left alone. (This is how the seeds behave today, per
  publication instead of once.)
- No connectors. The owner adds their own.
- The default house style is Plover's institutional style. A writer with a different
  voice changes it on day one, so the AI Setup page should say so plainly.

### 8.5 Where people do it

- **Writer Desk → the publication → AI Setup.** Three parts: Skills, House Style,
  Connectors. The same editor the admin page has today (`ai-setup-admin.js`), pointed
  at the publication.
- **Writer Desk → My Account** holds the personal parts: AI account, Google Drive, AI
  connection keys.
- **Admin → AI Setup** becomes PloverResearch's AI Setup, or a link to it in the Writer
  Desk. Admin keeps only operations.

### 8.6 Data changes (research and staff stores, not the macro schema)

- Add `publication_id` to `team_skills` and `team_connectors`. Existing rows become
  publication 1 (PloverResearch). Skill names and slugs become unique **within** a
  publication, not across the site.
- House style moves from one `team_settings` key to one row per publication.
- Limits (40 skills, 12 connectors) count per publication.
- `skills.py` and `connectors.py` take a publication id on every call. `research_ai`
  passes the article's publication id. Nothing reads a site-wide list any more.
- Every change goes into the audit trail with the publication's id.

### 8.7 Checks before calling it done

1. A writer in publication 2 sees publication 2's skills in the AI tab, not
   PloverResearch's. The prompt the model receives contains publication 2's house style.
2. Editing or deleting a skill in publication 2 leaves publication 1 untouched.
3. A run on a publication 2 article gets no PloverResearch connector tools or keys
   (check the run's credentials file, not just the tool list).
4. A writer (not editor) in publication 2 can't save a skill or a connector. The server
   refuses, not only the page.
5. A newly opened publication shows the nine starter skills straight away.
6. PloverResearch's existing skills, house style and connectors are unchanged after the
   migration.

### 8.8 Left for later

- **Personal skills** on top of the publication's, for a writer who works across
  several publications. Not needed while most people have one publication.
- **Sharing a skill** between publications, or a public skill library.
- The **Investment Assistant** uses the same skills store. When the two merge, it takes
  the person's own publication's skills.

### 8.9 What was built (2026-10-10)

- **Assistant Settings** (the name replaces "AI Setup") is a tab on every publication in the
  Writer Desk: `#/p/<id>/assistant`, API under `/admin/api/write/publications/{id}/assistant`
  (`app/writer_api.py`). Admin → Assistant Settings stays, for PloverResearch only.
- `team_skills` and `team_connectors` carry `publication_id`; the skills table is rebuilt once
  so slugs are unique per publication (`staff._skills_per_publication`). House style and seed
  markers are per-publication keys in `team_settings`; PloverResearch keeps its old keys.
- A run takes its skills, house style and connectors from its article's publication
  (`research_ai._publication`); the AI tab asks with `?article=`. Its credentials file holds
  only that publication's connector keys.
- A writer who owns no publication can open one of their own (owner = themselves); the Plover
  team still opens them for anyone. Opening one goes straight to it.
- Delete a skill or remove a connector is one click with 8 seconds to Undo.
- **Not done:** Google Drive is still connected from the admin page only (§8.5 puts it in My
  Account). Outside writers cannot connect Drive yet.
- Tests: `tests/test_publication_assistant.py` covers the six checks in §8.7, plus the store
  upgrade and opening your own publication.

## Sources checked (2026-10-09)

- Substack fee 10% of paid subscriptions plus Stripe: [Schoolmaker](https://schoolmaker.com/blog/substack-pricing), [Ruzuku](https://www.ruzuku.com/learn/articles/substack-pricing)
- beehiiv and Ghost take 0% of subscriptions: [Ghost vs beehiiv 2026](https://www.passivekit.com/?p=429), [fees compared](https://emaillistvalidation.com/blog/substack-beehiiv-ghost-fees-paid-subscriptions-compared/)
- Smartkarma model (one buy-side fee, paid out by engagement): [Finextra](https://www.finextra.com/pressarticle/72353/smartkarma-expands-to-north-america), [Financial IT](https://financialit.net/node/23222)
- BlueMatrix (authoring, compliance, distribution; ~1,000 research firms): [BlueMatrix](https://www.bluematrix.com/sellside), [Thoma Bravo](https://www.thomabravo.com/press-releases/bluematrix-accelerates-transition-into-core-infrastructure-for-ai-driven-research-strengthens-leadership-to-scale-platform)
