---
description: Fix a dashboard/chart/table UI issue with the Observatory's design guardrails enforced
argument-hint: <what's wrong, and where if you know it>
---

Fix this UI issue: **$ARGUMENTS**

Follow the Observatory design discipline (invoke the `ui-ux-design` skill):

- First tell me the likely cause. If it might be a cache, hard-refresh, wrong-port, or wrong-env issue, check that before concluding it's a bug.
- Do NOT change the data fetch, aggregation, calculation, or pipeline logic to fix a visual problem. If the number itself is wrong, stop and tell me — that's a data bug, not a UI bug.
- Numerics stay tabular and right-aligned with fixed per-column precision and explicit units; missing renders as `—`, never as `0`.
- Trust label, as-of, and vintage must survive the fix — if a change would drop provenance from a surface, stop and tell me.
- Trust badges stay outline-only; never render a raw enum or slug — map to a Title-Case label.
- Every control's state stays in the URL so the view remains shareable and citable.
- Done = you have rendered it at 390 / 768 / 1280 / 1440, opened every dropdown and tooltip, hovered the chart, and looked at it against a worst-case row. Don't declare it fixed from code inspection alone.

If the fix touches more than one file or anything risky, show me the plan first and wait.
