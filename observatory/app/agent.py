"""Natural-language question answering over the published datasets.

The agent has no direct database access. It reaches the data only through the
tools below, which are thin wrappers over the same functions that serve
/api/v1 — so every number it can state is a number the API already publishes,
computed by the same code, from the same release. Each tool call is recorded
and returned to the caller alongside the answer, which is what lets the UI show
the reader exactly which lookups produced a given response.

Talks to any OpenAI-compatible chat-completions endpoint. DeepSeek's API uses
the same request and response shape as OpenAI's, so this one client covers
both: set DEEPSEEK_API_KEY to use DeepSeek, or OPENAI_API_KEY to use OpenAI
directly. Without either, /ask returns 503 and the rest of the app is
unaffected. Requires the `openai` package (see requirements.txt) — it is the
client library for both providers, not an OpenAI-exclusive dependency.
"""
import contextvars
import datetime
import json
import os

from . import api

try:
    from openai import OpenAI
except ImportError:  # optional dependency — see requirements.txt
    OpenAI = None

# Checked in order; the first with a key set wins. DEEPSEEK_API_KEY comes
# first because a deployment that set it chose DeepSeek deliberately.
# LLM_BASE_URL / LLM_MODEL (below) override either provider's defaults, so
# this same list also covers any other OpenAI-compatible endpoint — point
# LLM_BASE_URL at it and set OPENAI_API_KEY to its key.
_PROVIDERS = [
    {"key_env": "DEEPSEEK_API_KEY", "base_url": "https://api.deepseek.com",
     "default_model": "deepseek-chat"},
    {"key_env": "OPENAI_API_KEY", "base_url": None,
     "default_model": "gpt-4o-mini"},
]

MAX_TOKENS = 2000
# Tool round trips per question; one that needs more has gone off the rails
# rather than found something.
MAX_ITERATIONS = 12

# Stamped on every answer. Bump whenever SYSTEM changes, so a logged or
# reported answer can be traced to the wording that produced it.
SYSTEM_VERSION = "obs-ask-2"

# Tool results are the bulk of the input tokens. These bound how much a single
# question can pull into context.
DEFAULT_MONTHS = 36
POINT_BUDGET = 1500
MAX_SEARCH_ROWS = 100

# Conversation replay. Enough turns for a follow-up to make sense, few enough
# that a long chat cannot grow the request without bound.
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CHARS = 4000

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

Describe what the series show, never why they moved. "Electricity fell 1.7% in \
the year to June 2026" is in the data; "electricity fell because of fuel-cost \
adjustments" is a causal claim the data cannot support and the site does not \
publish. Where a decomposition tool hands you the arithmetic, say a group \
"contributed" or "accounts for" that many percentage points — that is \
mechanical, not causal. Otherwise leave the explanation out, even when you think \
you know it. The same holds for how a series is built: describe an index only as \
the tools describe it, and never characterise from your own background knowledge \
what it covers, excludes, or adjusts for.

When a question needs data these tools do not reach, say so and point to the \
part of this site that does — the Item Explorer for individual series, the \
Methodology page for definitions and sources. Never send the reader to an \
outside agency, vendor, or portal for something this site publishes.

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


def _weight_pct(weight_per_10000):
    """Basket weight as a percent of the basket.

    The stored unit is parts per 10,000, which the model reliably mis-scales
    when asked to convert it (a 341 came back as "0.341"). Converting here
    leaves nothing to get wrong — the field name states the unit and the value
    is already in it.
    """
    return None if weight_per_10000 is None else round(weight_per_10000 / 100.0, 2)


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

def list_datasets():
    """List the published datasets, with what each one covers."""
    _record("list_datasets", {})
    try:
        return json.dumps(api.catalog(), ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — surfaced to the model, not raised
        return _fail(str(exc))


def search_series(query, dataset="cpi-jp", limit=25):
    """Find series by name (English or Japanese) or exact series code."""
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
            "basket_weight_pct": _weight_pct(s["weight"]), "as_of": s["as_of"],
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


def get_series_values(series_codes, measure="yoy", dataset="cpi-jp",
                      start="", end=""):
    """Get the history of one or more series, as a level or a rate of change."""
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


def get_overview(dataset="cpi-jp"):
    """Get the current state of inflation at the latest published month."""
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
            "basket_weight_pct": _weight_pct(g["weight"]), "yoy": _round(g["yoy"], 2),
            "mom": _round(g["mom"], 2),
        } for g in raw["groups"]],
    }, ensure_ascii=False)


def get_contributions(dataset="cpi-jp", start="", end=""):
    """Split headline year-over-year inflation into percentage points by group."""
    args = {"dataset": dataset, "start": start or None, "end": end or None}
    try:
        from_month = start or _window_start(_release_of(dataset), 13)
        raw = api.contributions(dataset, start=from_month, end=end or None)
    except Exception as exc:  # noqa: BLE001
        _record("get_contributions", args, note="failed")
        return _fail(str(exc))
    groups = [{
        "code": g["code"], "name_en": g["name_en"], "name_ja": g["name_ja"],
        "basket_weight_pct": _weight_pct(g["weight"]),
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


def get_breadth(threshold=2.0, dataset="cpi-jp-items", start="", end=""):
    """Measure how broad inflation is across individually priced items."""
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


TOOL_IMPLS = {
    "list_datasets": list_datasets,
    "search_series": search_series,
    "get_series_values": get_series_values,
    "get_overview": get_overview,
    "get_contributions": get_contributions,
    "get_breadth": get_breadth,
}

# OpenAI-style function-calling schemas — the format DeepSeek also consumes.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_datasets",
            "description": (
                "List the published datasets, with what each one covers. Use "
                "this when you are unsure which table holds the series a "
                "question needs."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_series",
            "description": (
                "Find series by name, in English or Japanese, or by exact "
                "series code. Returns each match with its code, its basket "
                "weight as a percent of the whole basket, its latest index "
                "value, and its latest year-over-year and month-over-month "
                "rates. Use the code it returns to pull history with "
                "get_series_values."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "English text, Japanese text, or an exact series "
                            "code. Empty returns every series in the dataset."),
                    },
                    "dataset": {
                        "type": "string",
                        "enum": ["cpi-jp", "cpi-jp-items"],
                        "description": (
                            "'cpi-jp' for the ~80 category aggregates, "
                            "'cpi-jp-items' for the ~740 detailed items."),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum rows to return, up to 100.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_series_values",
            "description": (
                "Get the history of one or more series, as a level or a rate "
                "of change."),
            "parameters": {
                "type": "object",
                "properties": {
                    "series_codes": {
                        "type": "string",
                        "description": (
                            "Comma-separated series codes from search_series, "
                            "up to 6."),
                    },
                    "measure": {
                        "type": "string",
                        "enum": ["index", "yoy", "mom", "ann3m"],
                        "description": (
                            "'index' for the published index level (2020 = "
                            "100), 'yoy' for year-over-year %, 'mom' for "
                            "month-over-month %, or 'ann3m' for the 3-month "
                            "annualized rate %."),
                    },
                    "dataset": {"type": "string", "enum": ["cpi-jp", "cpi-jp-items"]},
                    "start": {
                        "type": "string",
                        "description": (
                            "First month as 'YYYY-MM'. Defaults to the most "
                            "recent 36 months."),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "Last month as 'YYYY-MM'. Defaults to the latest "
                            "available."),
                    },
                },
                "required": ["series_codes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overview",
            "description": (
                "Get the current state of inflation at the latest published "
                "month: headline, core, and core-core year-over-year rates, "
                "headline month-over-month and 3-month annualized, and each "
                "major expenditure group's year-over-year rate and basket "
                "weight as a percent. Start here for \"what is inflation "
                "now\" questions."),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "enum": ["cpi-jp"],
                        "description": (
                            "The detailed-item table has no aggregate "
                            "overview."),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_contributions",
            "description": (
                "Split headline year-over-year inflation into percentage "
                "points by group. Answers \"what is driving inflation\" — how "
                "much of the headline rate each major expenditure group "
                "accounts for. Contributions sum to the headline rate up to a "
                "small rounding residual, returned separately."),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string", "enum": ["cpi-jp"]},
                    "start": {
                        "type": "string",
                        "description": (
                            "First month as 'YYYY-MM'. Defaults to the most "
                            "recent 13 months."),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "Last month as 'YYYY-MM'. Defaults to the latest "
                            "available."),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_breadth",
            "description": (
                "Measure how broad inflation is across individually priced "
                "items: the share up at least the threshold year-over-year, "
                "the share rising at all, and the share falling. Broad "
                "inflation means most items rising rather than a few large "
                "movers."),
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "description": (
                            "Year-over-year % defining \"rising fast\". 2.0 "
                            "is the site default."),
                    },
                    "dataset": {"type": "string", "enum": ["cpi-jp-items"]},
                    "start": {
                        "type": "string",
                        "description": (
                            "First month as 'YYYY-MM'. Defaults to the most "
                            "recent 60 months."),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "Last month as 'YYYY-MM'. Defaults to the latest "
                            "available."),
                    },
                },
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# provider resolution + the agent loop
# ---------------------------------------------------------------------------

class AgentUnavailable(Exception):
    """No usable credentials, no SDK installed, or the upstream call failed."""


def _resolve_provider():
    """Config for whichever provider has a key set, or None."""
    if OpenAI is None:
        return None
    for p in _PROVIDERS:
        key = os.environ.get(p["key_env"])
        if key:
            return {
                "api_key": key,
                "base_url": os.environ.get("LLM_BASE_URL", p["base_url"]),
                "model": os.environ.get("LLM_MODEL", p["default_model"]),
            }
    return None


def available():
    """True when the server has the SDK and credentials to call a provider."""
    return _resolve_provider() is not None


def unavailable_reason():
    if OpenAI is None:
        return "The openai package is not installed on this server."
    return ("No API credentials configured (set DEEPSEEK_API_KEY or "
            "OPENAI_API_KEY).")


def model_name():
    """The model that will be used, or None if no provider is configured."""
    config = _resolve_provider()
    return config["model"] if config else None


def _tool_result(name, args_json):
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        return _fail("Unknown tool '%s'." % name)
    try:
        args = json.loads(args_json) if args_json else {}
    except (json.JSONDecodeError, TypeError):
        return _fail("Could not parse arguments for '%s'." % name)
    try:
        return impl(**args)
    except Exception as exc:  # noqa: BLE001 — surfaced to the model, not raised
        return _fail(str(exc))


def _history_messages(history):
    """The visible prior turns, sanitised, oldest-first.

    Only the prose the reader actually saw is replayed — never the tool-call
    and tool-result turns from earlier questions, which are the bulk of the
    tokens and would grow the request without bound. A follow-up that needs
    figures looks them up again, which also keeps every answer tied to the
    current release rather than to a stale earlier fetch.
    """
    out = []
    for turn in (history or [])[-MAX_HISTORY_MESSAGES:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
    return out


def ask(question, dataset="cpi-jp", history=None):
    """Answer a question about the data. Returns the answer and its lookups.

    `history` is the visible conversation so far — a list of
    {"role": "user"|"assistant", "content": str} — which makes follow-ups
    like "and core?" resolvable. The server keeps no conversation state: the
    thread lives in the browser and is replayed each turn. That is safe here
    because every tool is read-only over already-public data, so a forged
    history can at worst produce an odd answer about published statistics.
    """
    config = _resolve_provider()
    if config is None:
        raise AgentUnavailable(unavailable_reason())

    client_kwargs = {"api_key": config["api_key"]}
    if config["base_url"]:
        client_kwargs["base_url"] = config["base_url"]
    client = OpenAI(**client_kwargs)

    calls = []
    _CALLS.set(calls)
    prior = _history_messages(history)
    # Name the dataset once, on the opening turn; repeating it every follow-up
    # is noise the model has to read past.
    prompt = ("Question about the %s dataset: %s" % (dataset, question)
              if dataset and not prior else question)

    messages = [{"role": "system", "content": SYSTEM}]
    messages.extend(prior)
    messages.append({"role": "user", "content": prompt})
    usage = {"prompt_tokens": 0, "completion_tokens": 0}

    for _ in range(MAX_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_tokens=MAX_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001 — network/auth/rate-limit errors
            raise AgentUnavailable("Upstream error from the model API (%s)." % exc)

        choice = response.choices[0]
        msg = choice.message
        if response.usage:
            usage["prompt_tokens"] += response.usage.prompt_tokens or 0
            usage["completion_tokens"] += response.usage.completion_tokens or 0

        if not msg.tool_calls:
            if choice.finish_reason == "content_filter":
                answer = ("I can't answer that one. Try asking about Japanese "
                          "consumer prices — a category, an item, or what is "
                          "driving the headline rate.")
            else:
                answer = (msg.content or "").strip()
                if choice.finish_reason == "length":
                    answer += "\n\n(Answer cut short at the length limit.)"
            return {
                "answer": answer,
                "tool_calls": calls,
                "model": config["model"],
                "system_version": SYSTEM_VERSION,
                "stop_reason": choice.finish_reason,
                "usage": usage,
            }

        # Record the assistant's tool-call turn, then resolve each call and
        # feed the results back before asking for the next turn.
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            result = _tool_result(tc.function.name, tc.function.arguments)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": result})

    raise AgentUnavailable(
        "The question needed more lookups than allowed; try asking something "
        "narrower.")
