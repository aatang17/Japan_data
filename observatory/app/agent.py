"""Natural-language question answering over the published datasets.

The agent has no direct database access. It reaches the data only through the
shared tool layer in tools.py — thin wrappers over the same functions that
serve /api/v1 — so every number it can state is a number the API already
publishes, computed by the same code, from the same release. Each tool call is
recorded and returned to the caller alongside the answer, which is what lets
the UI show the reader exactly which lookups produced a given response. The
MCP endpoint (mcp.py) serves the same tool layer to external AI clients.

Talks to any OpenAI-compatible chat-completions endpoint. DeepSeek's API uses
the same request and response shape as OpenAI's, so this one client covers
both: set DEEPSEEK_API_KEY to use DeepSeek, or OPENAI_API_KEY to use OpenAI
directly. Without either, /ask returns 503 and the rest of the app is
unaffected. Requires the `openai` package (see requirements.txt) — it is the
client library for both providers, not an OpenAI-exclusive dependency.
"""
import json
import os

from .tools import _CALLS, TOOL_SCHEMAS, run_tool

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
    try:
        args = json.loads(args_json) if args_json else {}
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Could not parse arguments for '%s'." % name})
    return run_tool(name, args)[0]


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
