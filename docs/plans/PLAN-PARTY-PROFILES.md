# Party Profiles — a reusable identity layer for funds, companies and people

> Status: approved 2026-09-03. Surface: `/admin.html#parties`.
> Related: [`PLAN-CROSS-SHAREHOLDING-DB.md`](PLAN-CROSS-SHAREHOLDING-DB.md),
> [`PLAN-BOARD-AND-PAY.md`](PLAN-BOARD-AND-PAY.md).

---

## The problem

Every equity surface names the same institutions over and over, and none of them
agree on who they are:

| Pool | Distinct identities | With an EDINET code |
| --- | --- | --- |
| 5% filers (`eq_lvh_holders`) | 1,655 | 1,654 |
| Register top-10 (`eq_major_shareholders`) | 12,574 name keys | 2,002 |
| Board seats (`eq_board`) | 48,716 people | none |

So the EDINET code cannot be the identifier: 17,345 of 25,320 register rows have
none, BlackRock files under sixteen codes, and no director has one at all. What
is needed is our own identifier with the source keys hanging off it as aliases.

Two further facts set the shape of the model:

- **Arms are not the group.** Nomura files under eight codes covering an asset
  manager, a broker-dealer, a bank and a trust bank. Nomura Securities' 5% stake
  is a trading book; Nomura Asset Management's is client money. They must be
  nameable separately *and* rollable up, and the roll-up must never be the
  default arithmetic.
- **The biggest names on the register are not owners.** 日本カストディ銀行(信託口)
  and 日本マスタートラスト信託銀行(信託口) are the two most frequent names in
  `eq_major_shareholders` — 2,324 rows — and both are nominees. Any ownership
  ranking that counts them as holders is wrong today.

## What this is not

It does not replace [`app/filer_labels.py`](../../observatory/app/filer_labels.py).
That module reads `filer_type` from the filing's own 事業内容 and is *evidence*:
auditable, derived, applied at serve time, never stored. Profiles are a
**curated layer beside it**, our judgement rather than the filing's words. Both
render, and where they disagree the disagreement is a work queue, not a bug.

## Identity model

```
party            our own stable id, one per real-world entity
  ├─ parent_id   self-link: arm -> group  (Nomura AM -> Nomura)
  └─ aliases     (key_type, key_value) -> party_id
                 key_type in edinet_code | name_key | sec_code | person_key
```

The alias table is the whole point: one join and a profile is reusable across
all seven equity datasets, not just the 5% list.

### Naming — four fields, so no arm has to stand for the group

| Field | Example |
| --- | --- |
| `legal_name_ja` | 野村アセットマネジメント株式会社 |
| `legal_name_en` | Nomura Asset Management Co., Ltd. |
| `display_name` | Nomura Asset Management |
| `group_role` | Asset management |

with `group_name` carried by the parent party ("Nomura"). A filing row shows the
arm; a group view rolls up and can break the arms out.

## Type — three fields, not one list

One flat list forces false choices: Evo Fund is a hedge fund *and* a
convert-arb shop; Nomura AM is an asset manager running both index and active
money.

1. **`party_class`** — what it legally is. One value, required.
2. **`strategy`** — how it invests. Zero or many, investors only.
3. **`holder_role`** — why it is on the register. One value. This is the field
   that separates the 信託口 nominee rows from beneficial owners.

Vocabularies live in one place, `app/parties.py`, and are served to the admin
form so the options can never drift from what validation accepts.

## Storage — a JSON file, not a table

`admin_api.py` is read-only against DuckDB by design (Ingest Guardrail 5: the
serving process never writes to the database). Curation therefore lives where
the audit trail lives — a file under `data/admin/`, written atomically:

```
data/admin/parties.json            live store, on the mounted volume
observatory/curation/parties.json  git-committed copy; seeds an empty volume
```

At ~1,700 entities this is a few hundred KB, loads in milliseconds, and makes
the approved "export to git" backup nearly free: the store *is* the export.
Nothing here touches `eq_*`, so no vintage is ever rewritten.

## Visibility

Every profile carries `public: true|false`. Nothing reaches `/api/v1` in this
milestone, but the flag exists from day one so a public party page can be
switched on later without re-modelling. Curated values must render as
**Curated** with `source` and `as_of` — never the Official Statistic badge.

## Scope of the first pass

The work queue is the 255 institutional 5% filers with five or more filings —
the overwhelming majority of filing activity, and a few evenings of typing
rather than months. The remaining 777 institutions and 623 individuals stay
derived-only until promoted. The 20 groups already hand-mapped in
`filer_labels.GROUPS` seed the parent parties.

## Milestones

- **M1 (this one)** — store, vocabularies, admin API, admin page, work queue,
  git export/import, seed from `filer_labels.GROUPS`.
- **M2** — alias merge tool for `eq_major_shareholders` name keys; nominee
  flags applied to the ownership surfaces.
- **M3** — computed behaviour panel (campaign count, borrowings, holding
  period) and the derived-vs-curated disagreement queue.
- **M4** — decide on a public `/party/{id}` page.
