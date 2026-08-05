"""Natural-language question answering over the published datasets.

The agent has no direct database access. It reaches the data only through the
tools below, which are thin wrappers over the same functions that serve
/api/v1 — so every number it can state is a number the API already publishes,
computed by the same code, from the same release. Each tool call is recorded
and returned to the caller alongside the answer, which is what lets the UI show
the reader exactly which lookups produced a given response.

Requires ANTHROPIC_API_KEY in the environment; without it /ask returns 503 and
the rest of the app is unaffected.
"""
import contextvars
import datetime
import json
import os

from anthropic import beta_tool

from . import api

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
# Interactive surface: the tools do the arithmetic, so the model is reasoning
# over small result sets rather than deriving anything. Raise to "high" if
# answers start to feel shallow on multi-step comparisons.
EFFORT = "medium"
# Each iteration is one model turn; a question needing more than this many
# lookups has gone off the rails rather than found something.
MAX_ITERATIONS = 12

# Tool results are the bulk of the input tokens. These bound how much a single
# question can pull into context.
DEFAULT_MONTHS = 36
POINT_BUDGET = 1500
MAX_SEARCH_ROWS = 100

SYSTEM = """\
You answer questions about Japanese consumer price data for the Observatory, a \
public statistics site. Readers are analysts, journalists, and policy staff who \
will quote your numbers.

Every number you state comes from a tool call in this conversation. You hold no \
reliable CPI figures in memory and the data is revised and extended monthly, so \
look up whatever you are asked about instead of answering from prior knowledge. \
When a lookup returns nothing, say the figure is not available — never estimate \
it, never interpolate it, and never read a missing value as zero.

Two tables are available. cpi-jp holds the roughly 80 published category \
aggregates: headline CPI, core (less fresh food), core-core (less fresh food and \
energy), and the ten major expenditure groups. cpi-jp-items holds roughly 740 \
series at full item depth — individual goods and services such as rice, \
electricity, or university fees. Questions about a specific product belong in the \
detailed table.

The trust contract this site publishes on outranks every other convention here. \
Index values (2020 = 100) are official statistics exactly as the Statistics \
Bureau of Japan released them. Year-over-year, month-over-month, and 3-month \
annualized rates are calculated by this system from those published index \
values; they are not themselves official figures, and each tool returns the \
formula it used. A calculated rate described as an official statistic is the one \
error that damages the site's credibility, so keep the two distinct whenever the \
distinction could matter to the reader.

The tools compute every rate of change on offer — request the measure you need \
rather than deriving it. Where you genuinely must compare two figures, such as a \
group's contribution this month against last, give both inputs next to the \
difference so the reader can check the subtraction.

Quote rates to one decimal place with a percent sign (2.7%), differences between \
rates in percentage points (+0.3 pp), and index levels to one decimal (113.6). \
Write negative numbers with a true minus sign: −0.4%. Name the reference month of \
every figure.

Answer in a few sentences of plain prose, leading with the figure or finding the \
question asked for and following with the context that makes it meaningful. Use \
"- " bullets only for a real list of items; no headings, no markdown tables, no \
bold. Don't narrate your lookups or name the tools — the interface already shows \
the reader which data you pulled.

The site covers Japanese consumer prices and nothing else. For a question it \
cannot answer — other countries, wages, GDP, or where inflation goes next — say \
briefly what the data does cover and stop. Do not forecast."""


# ---------------------------------------------------------------------------
# call recording
# ---------------------------------------------------------------------------

# One list per in-flight request. The endpoint runs in a threadpool worker and
# anyio copies the context into it, so each question gets its own log.
_CALLS = contextvars.ContextVar("agent_calls")


def _log():
    try:
        return _CALLS.get()
    except LookupError:
        return []


def _record(tool, args, release=None, note=None):
    entry = {"tool": tool, "args": {k: v for k, v in args.items() if v is not None}}
    if release:
        entry["release_id"] = release.get("release_id")
        entry["latest_period"] = release.get("latest_period")
        entry["source_name"] = release.get("source_name")
    if note:
        entry["note"] = note
    _log().append(entry)
    return entry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fail(message):
    """Tool-level failure the model can recover from, not a request failure."""
    return json.dumps({"error": message})


def _round(v, dp):
    return None if v is None else round(v, dp)


def _release_of(dataset):
    con = api._con()
    try:
        return api._release(con, dataset)
    finally:
        con.close()


def _window_start(release, months):
    """ISO 'YYYY-MM' this many months before the release's latest period."""
    latest = datetime.date.fromisoformat(release["latest_period"])
    return api._months_ago(latest, months - 1).strftime("%Y-%m")


def _trim_points(series, budget):
    """Keep the most recent points across all series within a token budget."""
    total = sum(len(s["points"]) for s in series)
    if total <= budget:
        return False
    per = max(12, budget // max(1, len(series)))
    for s in series:
        s["points"] = s["points"][-per:]
    return True


# ---------------------------------------------------------------------------
# tools
#
# api.py's handlers carry FastAPI Query() defaults, which are Query objects
# rather than plain values when the functions are called directly. Every
# parameter is therefore passed explicitly below.
# ---------------------------------------------------------------------------

@beta_tool
def list_datasets() -> str:
    """List the published datasets, with what each one covers.

    Use this when you are unsure which table holds the series a question needs.
    """
    _record("list_datasets", {})
    try:
        return json.dumps(api.catalog(), ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — surfaced to the model, not raised
        return _fail(str(exc))


@beta_tool
def search_series(query: str, dataset: str = "cpi-jp", limit: int = 25) -> str:
    """Find series by name, in English or Japanese, or by exact series code.

    Returns each match with its code, weight in the basket, latest index value,
    and latest year-over-year and month-over-month rates. Use the code it
    returns to pull history with get_series_values.

    Args:
        query: English text, Japanese text, or an exact series code. Empty
            returns every series in the dataset.
        dataset: 'cpi-jp' for the ~80 category aggregates, 'cpi-jp-items' for
            the ~740 detailed items.
        limit: Maximum rows to return, up to 100.
    """
    args = {"query": query, "dataset": dataset, "limit": limit}
    try:
        raw = api.series_list(dataset, q=query or "")
    except Exception as exc:  # noqa: BLE001
        _record("search_series", args, note="failed")
        return _fail(str(exc))
    limit = max(1, min(int(limit), MAX_SEARCH_ROWS))
    rows = []
    for s in raw["series"][:limit]:
        rows.append({
            "code": s["code"], "name_en": s["name_en"], "name_ja": s["name_ja"],
            "weight_per_10000": s["weight"], "as_of": s["as_of"],
            "index": _round(s["index"], 1), "yoy": _round(s["yoy"], 2),
            "mom": _round(s["mom"], 2),
            "discontinued": s["discontinued"],
        })
    _record("search_series", args, raw["release"],
            note="%d of %d matches" % (len(rows), raw["count"]))
    return json.dumps({
        "dataset": dataset, "query": query, "total_matches": raw["count"],
        "returned": len(rows), "as_of_release": raw["release"]["latest_period"],
        "index_trust": "official", "rate_trust": "calculated",
        "series": rows,
    }, ensure_ascii=False)


@beta_tool
def get_series_values(series_codes: str, measure: str = "yoy",
                      dataset: str = "cpi-jp",
                      start: str = "", end: str = "") -> str:
    """Get the history of one or more series, as a level or a rate of change.

    Args:
        series_codes: Comma-separated series codes from search_series, up to 6.
        measure: 'index' for the published index level (2020 = 100), 'yoy' for
            year-over-year %, 'mom' for month-over-month %, or 'ann3m' for the
            3-month annualized rate %.
        dataset: 'cpi-jp' or 'cpi-jp-items'.
        start: First month as 'YYYY-MM'. Defaults to the most recent 36 months.
        end: Last month as 'YYYY-MM'. Defaults to the latest available.
    """
    args = {"series_codes": series_codes, "measure": measure, "dataset": dataset,
            "start": start or None, "end": end or None}
    codes = ",".join([c.strip() for c in series_codes.split(",") if c.strip()][:6])
    if not codes:
        return _fail("No series codes given.")
    try:
        from_month = start or _window_start(_release_of(dataset), DEFAULT_MONTHS)
        raw = api.observations(dataset, series=codes, measure=measure,
                               start=from_month, end=end or None)
    except Exception as exc:  # noqa: BLE001
        _record("get_series_values", args, note="failed")
        return _fail(str(exc))
    dp = 1 if measure == "index" else 2
    out = [{
        "code": s["code"], "name_en": s["name_en"], "name_ja": s["name_ja"],
        "points": [[p, _round(v, dp)] for p, v in s["points"]],
    } for s in raw["series"]]
    truncated = _trim_points(out, POINT_BUDGET)
    _record("get_series_values", args, raw["release"],
            note="%s, from %s" % (measure, from_month))
    return json.dumps({
        "dataset": dataset, "measure": measure, "unit": raw["unit"],
        "trust": "official" if measure == "index" else "calculated",
        "calc": raw["calc"], "truncated_to_recent": truncated,
        "as_of_release": raw["release"]["latest_period"],
        "series": out,
    }, ensure_ascii=False)


@beta_tool
def get_overview(dataset: str = "cpi-jp") -> str:
    """Get the current state of inflation at the latest published month.

    Returns the headline, core and core-core year-over-year rates, headline
    month-over-month and 3-month annualized, and the year-over-year rate and
    basket weight of each major expenditure group. Start here for "what is
    inflation now" questions.

    Args:
        dataset: 'cpi-jp'. The detailed-item table has no aggregate overview.
    """
    try:
        raw = api.overview(dataset)
    except Exception as exc:  # noqa: BLE001
        _record("get_overview", {"dataset": dataset}, note="failed")
        return _fail(str(exc))
    _record("get_overview", {"dataset": dataset}, raw["release"])
    return json.dumps({
        "dataset": dataset,
        "latest_period": raw["release"]["latest_period"],
        "source": raw["release"]["source_name"],
        "stale": raw["stale"],
        "headline_figures": [{
            "label": t["label"], "series_code": t["series_code"],
            "value": _round(t["value"], 2), "unit": t["unit"],
            "change_vs_prior_month_pp": _round(t["delta_pp"], 2),
            "trust": "official" if t["measure"] == "index" else "calculated",
            "calc": t["calc"],
        } for t in raw["tiles"]],
        "groups": [{
            "code": g["code"], "name_en": g["name_en"], "name_ja": g["name_ja"],
            "weight_per_10000": g["weight"], "yoy": _round(g["yoy"], 2),
            "mom": _round(g["mom"], 2),
        } for g in raw["groups"]],
    }, ensure_ascii=False)


@beta_tool
def get_contributions(dataset: str = "cpi-jp", start: str = "",
                      end: str = "") -> str:
    """Split headline year-over-year inflation into percentage points by group.

    Answers "what is driving inflation" — how much of the headline rate each
    major expenditure group accounts for. Contributions sum to the headline
    rate up to a small rounding residual, which is returned separately.

    Args:
        dataset: 'cpi-jp'.
        start: First month as 'YYYY-MM'. Defaults to the most recent 13 months.
        end: Last month as 'YYYY-MM'. Defaults to the latest available.
    """
    args = {"dataset": dataset, "start": start or None, "end": end or None}
    try:
        from_month = start or _window_start(_release_of(dataset), 13)
        raw = api.contributions(dataset, start=from_month, end=end or None)
    except Exception as exc:  # noqa: BLE001
        _record("get_contributions", args, note="failed")
        return _fail(str(exc))
    groups = [{
        "code": g["code"], "name_en": g["name_en"], "name_ja": g["name_ja"],
        "weight_per_10000": g["weight"],
        "points": [[p, _round(v, 3)] for p, v in g["points"]],
    } for g in raw["groups"]]
    _trim_points(groups, POINT_BUDGET)
    _record("get_contributions", args, raw["release"], note="from %s" % from_month)
    return json.dumps({
        "dataset": dataset, "unit": "pp", "trust": "calculated",
        "calc": raw["calc"],
        "as_of_release": raw["release"]["latest_period"],
        "headline_yoy": {
            "code": raw["headline"]["code"], "name_en": raw["headline"]["name_en"],
            "points": [[p, _round(v, 3)] for p, v in raw["headline"]["points"]],
        },
        "groups": groups,
        "residual": [[p, _round(v, 3)] for p, v in raw["residual"]["points"]],
    }, ensure_ascii=False)


@beta_tool
def get_breadth(threshold: float = 2.0, dataset: str = "cpi-jp-items",
                start: str = "", end: str = "") -> str:
    """Measure how broad inflation is across individually priced items.

    For each month, the share of detailed items whose price is up at least the
    threshold on a year earlier, the share rising at all, and the share
    falling. Broad inflation means most items rising rather than a few large
    movers.

    Args:
        threshold: Year-over-year % defining "rising fast". 2.0 is the site
            default.
        dataset: 'cpi-jp-items'.
        start: First month as 'YYYY-MM'. Defaults to the most recent 60 months.
        end: Last month as 'YYYY-MM'. Defaults to the latest available.
    """
    args = {"threshold": threshold, "dataset": dataset,
            "start": start or None, "end": end or None}
    try:
        raw = api.breadth(dataset, threshold=float(threshold))
    except Exception as exc:  # noqa: BLE001
        _record("get_breadth", args, note="failed")
        return _fail(str(exc))
    from_month = start or _window_start(raw["release"], 60)
    lo, hi = from_month + "-01", (end + "-01") if end else None
    points = [p for p in raw["points"]
              if p["period"] >= lo and (hi is None or p["period"] <= hi)]
    _record("get_breadth", args, raw["release"], note="from %s" % from_month)
    return json.dumps({
        "dataset": dataset, "unit": "%", "trust": "calculated",
        "calc": raw["calc"], "threshold": raw["threshold"],
        "item_universe": raw["item_universe"],
        "as_of_release": raw["release"]["latest_period"],
        "points": points[-POINT_BUDGET:],
    }, ensure_ascii=False)


TOOLS = [list_datasets, search_series, get_series_values, get_overview,
         get_contributions, get_breadth]


# ---------------------------------------------------------------------------
# the agent loop
# ---------------------------------------------------------------------------

class AgentUnavailable(Exception):
    """No usable credentials, or the upstream call failed."""


_client = None


def _anthropic():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def available():
    """True when the server has credentials to call the API."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    try:
        c = _anthropic()
    except Exception:  # noqa: BLE001
        return False
    return bool(c.api_key or getattr(c, "auth_token", None))


def ask(question, dataset="cpi-jp"):
    """Answer a question about the data. Returns the answer and its lookups."""
    if not available():
        raise AgentUnavailable(
            "The question answering service is not configured on this server "
            "(no ANTHROPIC_API_KEY).")

    import anthropic

    calls = []
    _CALLS.set(calls)
    prompt = ("Question about the %s dataset: %s" % (dataset, question)
              if dataset else question)

    try:
        runner = _anthropic().beta.messages.tool_runner(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": EFFORT},
            tools=TOOLS,
            max_iterations=MAX_ITERATIONS,
            messages=[{"role": "user", "content": prompt}],
        )
        final = None
        usage = {"input_tokens": 0, "output_tokens": 0,
                 "cache_read_input_tokens": 0}
        for message in runner:
            final = message
            for k in usage:
                usage[k] += getattr(message.usage, k, 0) or 0
    except anthropic.APIStatusError as exc:
        raise AgentUnavailable("Upstream error from the model API (%s)."
                               % exc.status_code)
    except anthropic.APIConnectionError:
        raise AgentUnavailable("Could not reach the model API.")

    if final is None:
        raise AgentUnavailable("The model returned no response.")

    if final.stop_reason == "refusal":
        answer = ("I can't answer that one. Try asking about Japanese consumer "
                  "prices — a category, an item, or what is driving the "
                  "headline rate.")
    else:
        answer = "\n".join(b.text for b in final.content if b.type == "text").strip()

    if final.stop_reason == "max_tokens":
        answer += "\n\n(Answer cut short at the length limit.)"

    return {
        "answer": answer,
        "tool_calls": calls,
        "model": MODEL,
        "stop_reason": final.stop_reason,
        "usage": usage,
    }
