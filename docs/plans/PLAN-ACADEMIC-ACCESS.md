# PLAN — Academic Access (the WRDS question)

> **Status:** PROPOSAL — awaiting approval. Companion to
> [PLAN-JAPAN-MACRO-OBSERVATORY.md](PLAN-JAPAN-MACRO-OBSERVATORY.md), which already ranks
> academics as customer #3: *"Near-zero revenue; citations make us the canonical source.
> Free tier, trivial BibTeX export, low support burden. Treat as marketing."* This plan
> turns that one line into a concrete path.
>
> **One-liner:** Make the Observatory the dataset a Japan-macro paper cites — the way US
> papers cite ALFRED for real-time data — by making it citable (DOIs), bulk-downloadable,
> and clearly licensed, then climbing the distribution ladder from university librarians
> toward a WRDS listing.

---

## 1. What WRDS actually is, and why we can't start there

**WRDS (Wharton Research Data Services)** is a platform run by the Wharton School that
500+ universities in ~37 countries subscribe to. It hosts 350+ TB of vendor data
(Compustat, CRSP, FactSet, S&P Global, RavenPack…) behind one login, one query interface,
and one Python/SAS/PostgreSQL access layer. Researchers love it because every dataset
arrives pre-cleaned, documented, and citable in a standard way.

**How vendors get on it:** there is no self-serve marketplace. Each dataset is a
negotiated **vendor partnership** with WRDS — FactSet, S&P, and smaller shops like DRI
and Structured Data Solutions all have individually negotiated deals. WRDS takes datasets
it believes its subscriber base will demand, because hosting and supporting a dataset
costs them real money.

**Consequence:** a WRDS deal is the *outcome* of academic demand, not the way to create
it. Nobody at WRDS will host a dataset no paper has cited yet. So the plan is a ladder:
make the data academically usable first (cheap, fully in our control), generate the first
citations, then approach institutional channels with evidence.

**The pitch we will eventually make is strong**, because it is the vintage moat again:
the academic literature on data revisions runs on the St. Louis Fed's **ALFRED** archive
and the Philadelphia Fed's Real-Time Data Set — for *US* data. No equivalent
point-in-time archive exists for Japanese CPI item-level data or BOJ balance-sheet data.
Every month our ingest runs, we become more clearly the only source for "what did the
Japan data look like at the time." That is a dataset WRDS-type platforms understand.

## 2. What academics need that we don't have yet

An economist evaluating a dataset for a paper asks four questions. Today we fail three:

| Question | Today | Needed |
| --- | --- | --- |
| Can I get all of it, not one series at a time? | Per-series API + per-chart CSV only | **Bulk download** — one file per dataset per release (CSV, and Parquet for the quant crowd) |
| Can I cite it in a way referees accept? | No | **DOI per release** + a "How to cite" page with copy-paste BibTeX |
| Am I allowed to use it, and can my co-author reproduce it? | No stated terms | **A license/terms page**: free for academic research, redistribution of extracts in replication packages allowed, citation required; source obligations (e-Stat attribution, BOJ credit line) passed through |
| Will it still be there in five years? | Our word | DOI-archived snapshots on a third-party repository (Zenodo/Dataverse) — survives us |

None of these touches the core schema or the API contract. This is presentation and
packaging around data we already store.

## 3. The ladder

### Rung A — Citable and downloadable (build now; ~all software, no partnerships)

1. **Bulk snapshot exports.** For each dataset and each release, a downloadable file with
   the standard metadata header block (source, formulas, license, citation). The
   release/vintage machinery already exists; this is an export surface on top of it.
2. **DOIs via Zenodo.** Zenodo (run by CERN, free, has an API) mints a DOI per deposit
   and supports versioned records — one concept-DOI for "Japan Data Observatory CPI item
   indices", one child DOI per monthly vintage. This is the single cheapest credibility
   move available: a DOI is what turns "some guy's website" into a citable dataset.
   Automating deposit as a post-ingest step keeps it zero-touch.
3. **A "For researchers / How to cite" page.** BibTeX and plain-text citation for the
   platform and per-dataset; the DOI links; a data dictionary (the catalog endpoints
   already carry this); the revision/vintage explanation; the ±0.1 pp derived-rate
   disclosure from Methodology.
4. **Terms of use page.** Academic use free; citation required; extracts may be bundled
   in journal replication packages; e-Stat and BOJ attribution obligations pass through.
   This must exist *before* outreach — a librarian's first question is licensing.

### Rung B — Seed adoption (ongoing, near-zero cost; this is Substack-adjacent work)

1. **University data librarians are the real gatekeepers.** Every research university
   maintains "library guides" listing data sources by topic (NYU, Brown, Cornell,
   Arkansas all surfaced in one search about WRDS). Getting listed on Japan/Asia
   economics libguides is free: a short email to the business/economics data librarian
   with the DOI, the license, and one paragraph on what's unique. Target the ~30
   universities with active Japan-economics faculty first.
2. **Replication-ready by construction.** Every chart URL already encodes full view
   state; add the vintage/as-of parameter when J2's point-in-time API lands and a
   paper's exact data pull becomes one reproducible URL. Advertise that.
3. **One flagship academic user.** A PhD student or faculty member working on Japanese
   inflation or BOJ QT, found through the Substack readership, who uses the vintage data
   in a working paper. The first citation is worth more than any feature.
4. **Working-paper visibility:** RePEc/SSRN searches for Japan CPI / BOJ topics tell us
   exactly who is active; a short personal note beats any announcement.

### Rung C — Institutional channels (only with Rung B evidence in hand)

1. **WRDS vendor partnership.** Approach WRDS directly (there is no form; it's business
   development) with: citations collected, download counts, the ALFRED-for-Japan pitch,
   and a licensing proposal. Expect this to take quarters, not weeks, and possibly to be
   declined until the citation base is real.
2. **Alternatives if WRDS passes,** all reachable earlier and individually worthwhile:
   - **Harvard Dataverse / openICPSR** deposits — free hosting, DOIs, and discovery
     inside the channels economists already search.
   - **Direct university site licenses** — libraries do buy niche datasets directly;
     free-for-academics makes this an access agreement rather than a procurement fight.
   - **LSEG/Refinitiv, CEIC, or Nikkei channel deals** — commercial, different plan.

## 4. Decisions this plan forces

1. **Free means free, but registered or anonymous?** Recommendation: anonymous bulk
   downloads (friction kills citations), with an optional "register for release
   notifications" email list so we can count and contact academic users. Counting users
   is the evidence Rung C runs on.
2. **What exactly gets a DOI?** Recommendation: dataset-level concept DOIs with one
   version per vintage — this makes the vintage moat *visible in the citation graph*.
3. **License text.** We are redistributing e-Stat data (permitted with attribution) and
   BOJ data (credit line + notification obligations, no redistribution restriction —
   verified in the macro plan §6). Our *compilation and derived series* need their own
   terms. Needs one careful drafting pass, not a lawyer-quarter, but do it deliberately.
4. **Sequencing vs J-waves.** Rung A is independent of J1–J6 and small; the natural slot
   is alongside J1. The as-of/vintage API (J2 core change #4) is what makes the academic
   story *unique* rather than merely tidy — Rung B outreach lands hardest after it ships.

## 5. What we are explicitly not doing

- **Not building an accounts/entitlements system** for a free tier. Anonymous access,
  optional email list. An accounts system waits for paying customers, per the macro plan.
- **Not paying for hosting/distribution** (openICPSR paid tiers, conference sponsorships)
  before there is a single citation.
- **Not pitching WRDS now.** A premature pitch burns the one introduction we get.
- **Not weakening the trust contract for convenience** — bulk exports carry the same
  metadata headers, formula disclosures, and never-zero-for-missing rules as every other
  surface.

## 6. Measures of success

- First external DOI resolution / dataset download we didn't trigger ourselves.
- Listed on ≥5 university libguides within two quarters of Rung A shipping.
- First working paper citing the platform (the real milestone; everything above serves it).
- A WRDS conversation that starts with *them* having heard of the dataset.
