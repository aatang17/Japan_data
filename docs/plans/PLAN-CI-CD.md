# PLAN — CI/CD: what must be true before anything ships

> **Status:** BUILT 2026-09-16 — §7 records what changed against this plan.
>
> **One-liner:** three gates, in order of how much they can save us — a GitHub
> Actions suite that blocks a red commit from reaching Railway, a full-data run
> that must pass on the machine that has the data, and a nightly watchdog that
> asks production whether it is still serving fresh numbers.
>
> Nothing here changes the app. No new runtime dependency, no build step, no
> second service.

---

## 1. Why, before how

The platform has had four incidents worth naming, and only one of them was a
bug in the ordinary sense:

| When | What happened | Would CI have caught it? |
|---|---|---|
| Aug 2026 | July CPI fetched, archived, never published; the site served June for three weeks | No — a watchdog would |
| Aug 2026 | 5% filings stopped on the 6th; nothing noticed for four weeks | No — a watchdog would |
| 2026-09-05 | `fastapi>=0.110,<1` resolved differently in the image than on the laptop; **all nineteen manifests were rejected in production while every test passed locally** | Yes — a pinned install on both Pythons |
| 2026-09-09 | A redeploy spent an hour in the financials extractor, hit the healthcheck timeout, and took the working container down with it | Partly — a boot-time budget check |

So the honest ranking is: **the watchdog is worth more than the test suite**, and
the test suite is worth most where the laptop and the container disagree. That
ordering shapes everything below. A CI framework that only ran unit tests would
have prevented one of these four.

## 2. The three tiers

### Tier 1 — Checks (GitHub Actions, blocking, ~2 min, no data)

Runs on every push and pull request, on **Python 3.9 and 3.12** — the laptop's
version and the container's. Four steps:

1. `pip install -r requirements.txt` — the pinned versions, then assert the
   resolved versions equal the pins. This is the 2026-09-05 defect, gated.
2. `python -m unittest discover -s tests -t .` — must be green with **no
   database present**.
3. `python -m app.registry --check` — 51 manifests, every endpoint resolves.
4. `python ci/guards.py` — the static P0 checks in §3.

There is no data in CI: no volume, no DuckDB file, no e-Stat key, and no network
calls to e-Stat, the BOJ or the MoF. That is deliberate (§4) and it has a price,
which is the next tier.

### Tier 2 — Full run (the machine with the data, blocking by convention)

`python ci/suite.py --mode full`, run before a deploy. Identical suite, but on a
machine that holds `data/observatory.duckdb` and `data/equity.duckdb`, and with
one extra rule: **a test that skipped for want of data is a failure here.**
Without that rule the skip mechanism is a quiet way to delete a test.

The numbers, measured 2026-09-16: 219 tests collected. With data 219 run and 17
skip; without data 215 run and **99 skip — 45% of the suite** goes green in CI
without executing. (215, not 219: `tests/test_sec.py` raises `SkipTest` in
`setUpClass`, and a class-level skip leaves the run count without leaving the
file. That is the mechanism the floor in `ci/suite.py` exists to catch.) Tier 2
is what exercises the numbers; Tier 1 exercises the code around them.

Installed as a `pre-push` hook, so it runs without being remembered. A hook is
bypassable with `--no-verify`; that is accepted, because Tier 1 is not.

A third case sits between the two, and the runner names it separately: the
databases are present but **a slice inside them was never built locally** —
right now the JPX/Nikkei classification tables, which 17 cohort tests need and
which have never existed on this laptop. That is not CI's condition and it is
not a healthy full run either, so `--mode full` prints it on every run with the
command that fills it, and `--strict` turns it into a failure. A gap that stops
being printed is a gap that becomes permanent.

### Tier 3 — Watchdog (GitHub Actions, cron, against production)

`python ci/smoke.py --base-url https://ploveranalytics.com`, nightly and after
every deploy:

- `/api/v1/catalog/datasets` answers, and lists what the registry expects.
- `/api/v1/catalog/health?strict=1` is not a 503 — which is to say the refresh
  heartbeat is inside `REFRESH_MAX_AGE_HOURS` and no dataset is stale.
- A real number round-trips: latest `cpi-jp` headline YoY is present, numeric,
  and carries its formula.
- One rendered page and one company page return 200 with a meta description.
- `/sitemap.xml`, its two children, and `/robots.txt` answer.

A failure emails on the workflow failure — no new alerting service, no token.
This is the tier that catches the two staleness incidents, and the only one that
looks at what customers actually receive.

## 3. P0s — the gates that must never be weakened

1. **CI never touches production data.** No volume, no live DB, no write path,
   no source fetch. A test that needs numbers skips in Tier 1 and runs in Tier 2.
2. **A skipped test is not a pass.** Tier 1 accepts a skip only with a
   registered data-absence reason (`tests/_data.py`); any other skip fails the
   build. Tier 2 accepts none of them. And both tiers enforce a floor on the
   number of tests collected, because a suite that silently shrinks is the same
   defect wearing a different hat.
3. **Both Pythons, every run.** Local is 3.9.6, the container is 3.12. Only the
   matrix catches a `match` statement or an `X | Y` annotation.
4. **What ships is what was tested.** The four web pins move together and are
   asserted after install. Loosening the DuckDB pin (`>=1.4,<1.6`) fails the
   guard.
5. **Ingest failure stays non-fatal to boot.** Guard: `start.sh` carries no
   `set -e`, and every ingest, extractor and heartbeat call keeps a `|| echo`
   fallback. A helpful `set -e` there takes the whole site down on a bad day at
   e-Stat.
6. **The serving process never opens a database for writing.** Guard: every
   `duckdb.connect()` in an `app/*_api.py` passes `read_only=True`. One writer,
   and it runs while the server is stopped.
7. **The trust contract is machine-checked.** `TRUST_LABELS` holds exactly
   `official` and `model`; a derived measure carries a formula, never a badge.
8. **No new runtime dependency reaches the front end.** Guard: no external
   `<script src>` or `<link href>` anywhere in `web/`. Vendored ECharts only.
9. **Never bypass a red gate to ship.** Not `--no-verify`, not "deploy anyway",
   not a weakened validation to make an ingest pass. The gates are the product's
   credibility, and a gate that gets switched off under pressure was decoration.

## 4. Deliberately not gated

- **The real ingests.** They would hammer e-Stat on every push and fail on the
  source's bad days, which teaches us to ignore red builds. Ingest correctness
  is covered by adapter tests on fixtures, and by the watchdog on the far side.
- **The screenshot gate.** Headless Chrome at three viewports is too slow and
  too flaky to block a push. It stays a manual step (the `ui-ux-design` skill)
  and could later run nightly, keeping the images as artifacts.
- **Deploy on every commit.** A deploy with a mounted volume means the old
  container stops before the new one starts, so every deploy is downtime.
  Batching is correct here; auto-deploy on green is not.
- **Coverage as a number.** It would measure the wrong thing on a suite whose
  real subject is data.

## 5. CD: the deploy side

Railway builds from `observatory/Dockerfile` on push to `main`.

1. **Turn on "wait for CI" in the Railway service settings.** This is a console
   setting, not a file in this repo, and it is the single most valuable switch
   in this plan: without it a red commit deploys anyway and Tier 1 is advisory.
2. Deploy deliberately, in batches, not per commit.
3. After the deploy reports healthy, run Tier 3 against production.
4. **Rollback is a redeploy of the previous image** from the Railway dashboard.
   The volume is not rolled back and must not be: vintages are immutable, so
   rolling code back never rolls data back. Nothing in a rollback should need
   to touch `data/`.
5. Watch the boot window. The healthcheck timeout is 3600s and the serve-first
   path in `start.sh` keeps a normal boot short; the two levers when a boot
   threatens to run long are `INGEST_DATASETS` and `EQUITY_CATCH_UP_DAYS=0`,
   both environment-only, both pullable without a deploy.

## 6. Files

| Path | What it is |
|---|---|
| `.github/workflows/checks.yml` | Tier 1 — matrix suite, registry check, guards |
| `.github/workflows/watchdog.yml` | Tier 3 — nightly smoke against production |
| `observatory/ci/guards.py` | The static P0 checks in §3 |
| `observatory/ci/suite.py` | The suite runner with the skip policy and the floor |
| `observatory/ci/smoke.py` | Live checks against a base URL |
| `observatory/tests/_data.py` | Which databases this machine has, and the one place a data-absence skip reason is spelled |
| `observatory/ci/pre-push` | The hook that runs Tier 2 (install by symlink) |

`ci/` is not copied into the image — none of it runs in production.

## 7. Built

**2026-09-16.** Built as planned. What the build itself turned up:

- **Two tests were already red**, both from one cause: `/sitemap.xml` became an
  *index* of two child sitemaps in `622ade1`, and `test_seo` and `test_prerender`
  still read it as a flat list of pages. A test that walks an index, finds two
  URLs that answer 200, and passes is worse than no test. Fixed by walking the
  children; the company half is sampled at both ends rather than fetched four
  thousand times. A third latent failure came out with it — the Search Console
  verification file is excluded from the sitemap by name, which the test did not
  know.
- **Sixteen tests needed a data guard** to make a data-free run green. They now
  skip with a registered reason and are enforced by Tier 2. The alternative was
  a synthetic fixture database, which would need updating on every schema change
  and still could not satisfy the tests that assert real values.
- **Eight static guards**, not ten — and every one was verified twice: it passes
  on today's code, and it fails when its invariant is broken on a throwaway copy.
  A guard that has never failed proves nothing.
- **Tier 1 was run for real on both interpreters.** 3.9.6 locally and 3.12.13
  inside `python:3.12-slim` — the same image the container is built from. Both
  green: 215 tests, 8 guards, 51 manifests.
- **The 3.12 run found four latent defects** the laptop never showed: invalid
  escape sequences (`"\s"` in a plain string) in `equity/extract.py`,
  `lvh_extract.py`, `facility_extract.py` and `seg_extract.py` — a
  DeprecationWarning on 3.9, a SyntaxWarning on 3.12, an error in some future
  Python. Fixed, and the syntax guard now compiles with warnings promoted to
  errors so the next one fails the build instead of scrolling past.
- **Full mode found a real gap on the first run:** 17 cohort tests have never
  executed on this laptop, because `data/equity.duckdb` here has no
  classification tables. Not fixed by this plan — filling it means running
  `equity/class_extract.py`, which fetches from JPX and Nikkei — but it is now
  printed on every pre-push run instead of being invisible.
- **The watchdog was run against production** and the site is healthy: 41
  datasets, CPI through July 2026, heartbeat 0.6 hours old, every derived tile
  carrying its formula.

### Still to do by hand

1. **Turn on "wait for CI" in the Railway service settings.** Until that switch
   is on, a red commit deploys anyway and Tier 1 is advisory. It is the highest
   value item in this plan and it cannot be done from this repo.
2. The `pre-push` hook is installed in this working copy
   (`.git/hooks/pre-push` → `observatory/ci/pre-push`). A fresh clone needs the
   symlink again — hooks are not version-controlled.
