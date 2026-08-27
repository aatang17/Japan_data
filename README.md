# Japan Data Observatory

Institutional-grade Japanese economic and corporate data: CPI price statistics,
BOJ balance-sheet data, and EDINET corporate filings (cross-shareholdings,
boards & pay, buybacks) — with point-in-time vintages and a citable URL for
every view.

**Live:** <https://web-production-c9178.up.railway.app>

## Repo layout

| Folder         | What it is                                                        |
| -------------- | ----------------------------------------------------------------- |
| `observatory/` | The product: FastAPI + DuckDB backend, vanilla-JS dashboards      |
| `equity/`      | EDINET/TDnet capture and extraction pipelines (run off-server)    |
| `docs/plans/`  | Product plans and methodology                                     |
| `CLAUDE.md`    | House rules — **read before contributing**                        |

## Quick start (EDINET dashboards — no keys needed)

```bash
cd observatory
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
mkdir -p data && cp seed/equity.duckdb data/equity.duckdb
./.venv/bin/uvicorn app.main:app --port 8007
```

Then open:

- <http://localhost:8007/holdings.html> — cross-shareholdings
- <http://localhost:8007/governance.html> — boards & pay
- <http://localhost:8007/buyback.html> — buybacks

APIs live under `/api/v1/equity/...` (`observatory/app/equity_api.py`,
`governance_api.py`, `buyback_api.py`). The CPI pages need a one-time ingest —
see [observatory/README.md](observatory/README.md).

## Contributing

- Read [CLAUDE.md](CLAUDE.md) first — trust and design rules are the product.
- Code must run on **Python 3.9** (no `match`, no `X | Y` unions).
- Frontend is vanilla JS + vendored ECharts — no frameworks, no npm, no build
  step, no CDN references.
- Never open `seed/equity.duckdb` directly — DuckDB rewrites it on open and
  dirties git. Copy it to `data/` (as in the quick start).
- Work on a branch and open a PR. **Never push to `main`** — it deploys to
  production. No auto-reload locally: restart uvicorn after Python changes.

## Sources

Statistics Bureau of Japan (e-Stat) · Bank of Japan · company filings on
EDINET (FSA) and TDnet. All data as published; calculated figures carry their
formula.
