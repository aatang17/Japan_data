# PLAN — Be the source AI answers cite for Japan data

> **Status:** PHASES 0–1 BUILT 2026-09-18, not yet deployed — §3 records what is done. Bing
> registration is a manual step (§4, Phase 0.2). Phases 2–4 and the §6 panel are still to do.
>
> **One-liner:** when someone asks ChatGPT, Perplexity, Claude or Google "what is
> Japan's inflation rate", the answer should quote our number and link our page.
> Most of the plumbing exists. What is missing is (1) shipping it, (2) pages
> that are shaped like the questions people ask, and (3) proof we are winning.
>
> Written for: Aaron, as the owner deciding what to build next.

---

## 1. How an AI search picks a source (plain language)

An AI answer engine does three things in about two seconds:

1. **Finds candidate pages** in a normal web index. ChatGPT search leans on
   Bing's index plus its own crawler; Google's AI Overviews and AI Mode use
   Google's index; Perplexity keeps its own index; Claude's search uses a
   third-party index. None of them is a new kind of search. They pick from
   pages the old search engines already know.
2. **Fetches a handful of those pages** and reads them *as text*. Most of
   these fetchers do not run JavaScript. If the number only appears after a
   script runs, the fetcher sees an empty page and moves on.
3. **Writes the answer from what it read** and cites the pages whose text
   contained the answer, stated plainly and close to the top.

So four things decide who gets cited, in this order:

| Question the engine is effectively asking | What it means for us |
|---|---|
| Can I fetch this page? | Bots must be allowed, and there must be no login, no paywall, no "verify you are human" wall. |
| Can I read the number without running scripts? | The figure, its date and its source must be in the HTML as text. |
| Does the page answer the question in its first lines? | A page titled with the question, whose first sentence is the answer, beats a page that makes the reader find it. |
| Do I trust this site? | Is it in the index at all, do other sites link to it, do its numbers match the official source, is it kept fresh. |

**Why the legacy sites are beatable.** The point you heard is right, and it is
the whole opening:

- **Paywalled publishers** (Nikkei, Bloomberg, FT, Reuters) either block the
  AI fetchers or serve them a stub. An engine cannot quote a number it cannot
  read, so it quotes whoever is open.
- **Official sources** (e-Stat, BOJ, MOF) are open but built for people who
  already know where to look. e-Stat serves its tables through scripts and
  cp932 CSV downloads. A fetcher gets menus, not numbers.
- **The real incumbent** in AI answers for Japan macro questions is Trading
  Economics: one stable URL per indicator, the latest number in the first
  sentence, dated. It also throttles heavy readers and its history is thin
  and unsourced. That is the format to beat, with better provenance.
- **FRED** is open and trusted, but its Japan series come from the OECD and
  lag the Japanese release by weeks. Freshness is ours to win.

---

## 2. What "winning" means, in numbers

Two measures, checked weekly, from a fixed panel of questions (§6):

- **Citation share** — of the panel questions, how many produce an answer
  that cites ploveranalytics.com on at least one engine.
- **AI referrals** — readers who arrive with an AI assistant as the referrer.
  The admin console already counts these.

| Horizon | Citation share (of a 30-question panel) | Notes |
|---|---|---|
| Today | to be measured in week 1 | almost certainly zero |
| 3 months | 10 of 30 on at least one engine | the English macro questions |
| 6 months | 15 of 30, and cited on two or more engines for 5 | company questions start to land |

AI referrals will be small in absolute terms for a long time. The win is being
*the cited source*: brand, links, and the Substack funnel. Treat visits as a
lagging indicator.

---

## 3. Where we stand today (audited 2026-09-18)

| Piece | Status | Evidence |
|---|---|---|
| Bots allowed, sitemap, `llms.txt` | **Live** | `/robots.txt` allows everything but admin; `/llms.txt` is 25 KB and lists every dataset |
| One canonical address per page, meta descriptions, schema.org Dataset markup | **Live** | `cpi.html` carries one JSON-LD block and a description |
| Sitemap of every company page | **Live** | 4,437 URLs in `sitemap-companies.xml` |
| Google Search Console verified | **Live** | verification file in `web/` |
| AI fetchers and AI referrers counted | **Live** | 21 agents named in `visits.py`, 16 referrer hosts |
| Numbers written into the HTML as text, plus a Markdown copy of every page (`/cpi.md`) | **Built, not live** | `app/readable.py` is untracked; `/cpi.md` returns 404 in production. A crawler that fetched `cpi.html` today got 339 words and no data. Ships with the next deploy |
| Bing Webmaster Tools | **Manual step pending** | registration instructions handed over 2026-09-18 |
| IndexNow | **Built 2026-09-18, not live** | `app/indexnow.py`; the ingest pings after each publish once `INDEXNOW_KEY` is set on Railway; key served at `/indexnow-key.txt` |
| Pages shaped like questions | **Built 2026-09-18, not live** | nine answer pages (`app/answers.py`, `web/japan-inflation-rate.html` and eight more); lead sentence written into the HTML at serve time; Markdown twin and `/api/v1/answers/{slug}` |
| Sitemap `lastmod` | **Built 2026-09-18** | per page, from the newest release date among the datasets it fronts; 30 of 58 pages carry one, the rest have no data behind them |
| Japanese-language pages | **Missing** | `ja.html` is the JA Co-operatives dataset, not a Japanese version |
| Named `Allow` for the AI crawlers in `robots.txt` | **Built 2026-09-18** | sixteen agents named |
| A written record of who cites us | **Missing** | nothing tracks it; the §6 panel starts at deploy |

The short version: the machine-readable layer and the first nine answer pages are
built and tested locally. None of it is live until the next commit and deploy, and
Bing needs a manual registration.

---

## 4. The plan

### Phase 0 — Ship what exists (days, not weeks)

1. **Commit and deploy the readable layer.** After this, every page carries its
   latest reading and a table as plain text, and every page has a Markdown twin.
   Verify in production by fetching `cpi.html` with scripts off and reading the
   number back.
2. **Register with Bing Webmaster Tools** and submit the sitemap. ChatGPT search
   draws on Bing. A site Bing has not indexed cannot be cited there. Import
   from Search Console takes minutes.
3. **Add IndexNow.** One HTTP call that tells Bing (and others that share the
   protocol) "this URL changed". Send it from the ingest, after a release is
   published, for the pages that dataset feeds. Fail-safe: a failed ping
   never fails the ingest.
4. **Put the publication date into the sitemap.** `lastmod` per page from the
   dataset's latest release. The old objection (it would be the deploy time)
   no longer holds.
5. **Keep the bots welcome, in writing.** `robots.txt` allows all agents today.
   Add named `Allow` lines for GPTBot, OAI-SearchBot, ClaudeBot,
   Claude-SearchBot, PerplexityBot, Google-Extended and Applebot so the intent
   survives a future edit. And a rule for the file: if a CDN or bot-protection
   layer ever goes in front of the site, its "block AI crawlers" default must
   be switched off before it goes live. Cloudflare turns it on by default.

### Phase 1 — Question pages (the main work; 2–3 weeks)

Every AI answer is to a question. Today our URLs are dataset names
(`cpi.html`, `boj.html`). Add a small set of **answer pages**, one permanent
URL per question people actually ask, drawn from the same functions that serve
the API so the numbers can never disagree with the charts.

Candidate first set, English, macro:

- What is Japan's inflation rate? (headline CPI, latest month)
- What is Japan's core inflation rate? (ex fresh food; and ex fresh food and energy)
- What is Tokyo's CPI this month? (the advance reading, three weeks early)
- How large is the Bank of Japan's balance sheet?
- How many JGBs does the BOJ hold?
- What is Japan's GDP growth rate?
- What is Japan's population, and how fast is it falling?
- What is Japan's trade balance?
- How many tourists visited Japan last month?
- What is the price of rice in Japan?
- Which companies own the most shares in other Japanese companies?
- Who are the largest shareholders of {company}? (one template, 4,437 pages)

Each page follows one shape, in this order:

1. **Title is the question.**
2. **First sentence is the answer**, with the period and the release date:
   "Japan's consumer prices rose 3.1% in the year to July 2026, the Statistics
   Bureau reported on 22 August 2026." Written by `readable.py`, refreshed on
   every ingest, never by hand.
3. **One line of definition.** What the measure is and what it excludes.
4. **Context that only we can give cheaply:** highest or lowest since when
   (the 1946 series exists for this), the last twelve readings as a table,
   contributions by group.
5. **The chart**, as today.
6. **How to cite this**, and the publisher's credit line.
7. **Links** to the data page, the CSV, the JSON, the Markdown twin.

Rules for these pages:

- They are **not** a second copy of the data pages. The data pages stay the
  place to explore; the answer pages are the place to be quoted. Each links
  to the other.
- No page is published without a real reading behind it. A question page with
  a dash where the number should be is worse than no page.
- **Company pages** already exist. Give each a first paragraph in the same
  spirit: securities code, both names, sector, latest fiscal year's revenue
  and profit, largest holders, board size. The long tail of company questions
  is where 4,437 real pages beat any competitor's one page on "Japanese
  cross-shareholdings".
- Start with ten questions. Add more only from evidence (§6), not from guessing.

### Phase 2 — Freshness (1 week, alongside Phase 1)

Engines prefer the page that was updated most recently *and says so*.

- Every answer page states its release date in the first sentence (above) and
  in a dated line at the foot.
- IndexNow ping and sitemap `lastmod` (Phase 0) make the change visible.
- The nightly watchdog from the CI plan should also check that the live first
  sentence of each answer page matches the API. A stale sentence is a
  credibility problem, not just a ranking one.

### Phase 3 — Being trusted (ongoing)

An engine trusts a domain other sites already point to. Things within reach:

- **The Substack.** Every chart in every post already has to be a permanent
  URL here. Point those links at the answer page for that question, not only
  at the chart. This is the single largest source of inbound links we control.
- **MCP directories.** The MCP server exists. List it where assistants'
  users look for connectors: the Anthropic connector directory, Cursor's
  directory, Smithery, PulseMCP, mcp.so. This is AI distribution that
  bypasses search entirely.
- **Google Dataset Search.** The schema.org Dataset markup is live. Validate it
  with Google's Rich Results test and fix whatever it rejects. Dataset Search
  is how academics find data, and academic citations are links.
- **A "how to cite" page** with one stable format, and a DOI per dataset if we
  ever register with Zenodo or DataCite. Cheap, and the academic tier is
  explicitly part of the customer order.
- **Do not** self-add citations to Wikipedia, buy links, or post the URL into
  forums. It is against the platform rules, it is visible, and the Substack
  is the stated distribution channel.

### Phase 4 — Japanese (decision needed; not before Phase 1 is measured)

A large share of questions about Japanese data are asked in Japanese, and the
competition there is stronger (Nikkei, e-Stat, NHK). A Japanese twin of each
answer page, with `hreflang` links between the pair, is the natural next step.
It roughly doubles the content work and needs native-quality copy. Park it
until the English panel shows the shape is working.

---

## 5. What we will not do

- **No cloaking.** Crawlers and readers get the same page. The readable block
  is visible to a reader who opens it; that is the line and it stays.
- **No generated filler.** Thousands of thin pages get ignored and can hurt
  the whole domain. The company pages are real filings, not filler, but a
  company page with nothing behind it should say so in one line, not pad.
- **No FAQ-schema tricks.** Google stopped showing FAQ rich results for most
  sites in 2023. Write the question and answer as ordinary text.
- **No paid "AI SEO" tools.** The measurement in §6 is a spreadsheet and an
  hour a week.
- **No blocking competitors' bots** or anyone else's. Being the open one is
  the strategy.

---

## 6. How we will know (measurement, from week 1)

**The panel.** Thirty questions, fixed for six months, in English: twenty
macro, ten company. Once a week, ask each on four engines — ChatGPT search,
Perplexity, Claude with search, Google AI Mode — and record which domains are
cited. One row per question per engine per week.

- Week 1 is the baseline. Expect zero. It also shows us *who* is cited today,
  which is the competitor list that matters.
- The manual version takes about an hour. Perplexity, OpenAI and Anthropic
  each expose search with citations through their APIs, so a script can run
  three of the four engines nightly later. Google AI Mode has no API and stays
  manual.

**Already counted in the admin console:** AI fetches by page and by agent,
and AI referrals. Add one view: fetches by agent by *answer page*, so we can
see which pages the engines are reading and which they ignore.

**Search Console and Bing Webmaster** both report impressions and queries.
The queries people type are the source for the next batch of answer pages.

---

## 7. Order and effort

| Step | Effort | Depends on |
|---|---|---|
| Phase 0.1 ship readable + `.md` | half a day | nothing; the code exists |
| Phase 0.2–0.5 Bing, IndexNow, `lastmod`, robots | one day | 0.1 |
| §6 baseline panel, week 1 | one hour, then weekly | nothing |
| Phase 1, first ten answer pages | two to three weeks | 0.1 |
| Phase 1, company first paragraph | three days | 0.1 |
| Phase 2 freshness checks | two days | Phase 1 |
| Phase 3 directories, Dataset Search, cite page | three days, then ongoing | 0.1 |
| Phase 4 Japanese | decide after Phase 1 is measured | Phase 1 |

Two rules from `CLAUDE.md` bind all of it: the platform stays dataset-agnostic
(answer pages are built from the registry and `readable.py`, not hand-written
per dataset), and every number on an answer page carries its trust label and
its source line exactly as the data pages do.
