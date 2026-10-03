# -*- coding: utf-8 -*-
"""The research desk's AI tab: a writer's own model working on the open draft.

A writer picks a provider once — their Claude plan through Claude Code, their
ChatGPT plan through Codex, or an OpenAI or Anthropic API key — and then gives
the open article an instruction ("draft this from my notes", "add a chart of
core CPI", "check every number"). The model works on that one draft only:

* tools bound to the article: read the draft, replace or add to it, set its
  title / standfirst / summary, run the publish checklist;
* the platform's own read-only data tools (the public MCP set, tools_v2), so
  every number comes from the same functions as /api/v1;
* read_page, the desk's guarded page reader; Codex and Claude Code may also
  search the web with their own built-in search.

It cannot publish, withdraw, delete, or touch another article, and every save
is recorded as "<email> via <provider>" in the draft history, after a "Before
AI" copy that the editor's Undo restores. One run per writer at a time.

Secrets — API keys, the Claude Code token, the Codex sign-in — are sealed with
the assistant keychain (ASSISTANT_SECRET) and opened only for the length of a
run. The CLIs run with their shell, file and browser tools switched off, in an
empty directory, with an environment holding nothing but what they need.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import research, research_doc as rd, research_mcp, research_web, staff, tools_v2
from .assistant import codex as codex_mod, gateway, keychain

PROVIDERS = [
    ("claude_code", "Claude plan (Claude Code)"),
    ("codex", "ChatGPT plan (Codex)"),
    ("openai", "OpenAI API key"),
    ("anthropic", "Anthropic API key"),
]
PROVIDER_LABEL = dict(PROVIDERS)
CLIENT = {"claude_code": "Claude", "codex": "Codex", "openai": "OpenAI", "anthropic": "Claude API"}
DEFAULT_MODEL = {"openai": "gpt-5.5", "anthropic": "claude-sonnet-5-5"}
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or "claude"
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_STEPS = 20
RUN_SECONDS = 600
TOOL_TEXT_MAX = 24000
# Settings the tool server needs to open the same stores; none is a secret.
CHILD_ENV = ("STAFF_DB", "RESEARCH_DIR", "WORKSPACE_DB", "OBSERVATORY_DATA_DIR",
             "OBSERVATORY_DB_PATH", "EQUITY_DB_PATH", "SEC_DB_PATH", "SITE_BASE_URL")

_jobs = {}
_jobs_lock = threading.Lock()
_running = {}          # staff id -> job id


class AIError(ValueError):
    """Worded for the writer."""


# ---------------------------------------------------------------------------
# settings

def _open(ct):
    try:
        return keychain.open_(ct) if ct else None
    except (ValueError, RuntimeError):
        return None


def settings_view(person):
    s = staff.ai_settings(person["id"])
    return {
        "providers": [{"key": k, "label": v, "ready": _ready(k, s)} for k, v in PROVIDERS],
        "provider": s["provider"], "model": s["model"] or "",
        "default_model": DEFAULT_MODEL.get(s["provider"] or "", ""),
        "key_last4": s["key_last4"], "claude_token": bool(s["claude_token_ct"]),
        "codex": codex_status(person), "keychain": keychain.enabled(),
        "claude_available": shutil.which(CLAUDE_BIN) is not None,
        "codex_available": codex_mod.available(),
    }


def _ready(provider, s):
    if provider in ("openai", "anthropic"):
        return bool(s["key_ct"]) and s["provider"] == provider
    if provider == "claude_code":
        return bool(s["claude_token_ct"])
    if provider == "codex":
        return bool(s["codex_auth_ct"])
    return False


def save_settings(person, provider, model=None, key=None, claude_token=None):
    if provider not in PROVIDER_LABEL:
        raise AIError("Choose one of the providers listed.")
    if (key or claude_token) and not keychain.enabled():
        raise AIError("This server cannot store a key yet: ASSISTANT_SECRET is not set on it.")
    fields = {"provider": provider, "model": (model or "").strip()[:80] or None}
    if provider in ("openai", "anthropic"):
        current = staff.ai_settings(person["id"])
        if key:
            key = key.strip()
            try:
                gateway.ping(provider, key, fields["model"] or DEFAULT_MODEL[provider])
            except gateway.GatewayError as exc:
                raise AIError(_key_problem(provider, str(exc)))
            fields["key_ct"] = keychain.seal(key)
            _models.pop((person["id"], provider), None)
            fields["key_last4"] = keychain.last4(key)
        elif not current["key_ct"] or current["provider"] != provider:
            raise AIError("Paste your %s." % PROVIDER_LABEL[provider])
    if provider == "claude_code" and claude_token:
        token = claude_token.strip()
        if not re.match(r"^sk-ant-[A-Za-z0-9_\-]{20,}$", token):
            raise AIError("That does not look like a Claude Code token. Run `claude setup-token` "
                          "and paste the token it prints (it starts with sk-ant-).")
        fields["claude_token_ct"] = keychain.seal(token)
    return staff.set_ai(person["id"], **fields)


def _key_problem(provider, detail):
    """A failed key check in words, without the provider's raw reply."""
    who = "OpenAI" if provider == "openai" else "Anthropic"
    if re.search(r"\b(401|403)\b", detail):
        return ("That key did not work: %s did not accept it. Check you copied all of it, "
                "and that the account has API access." % who)
    if re.search(r"\b429\b", detail):
        return "That key did not work: %s says the account is out of credit or over its limit." % who
    if re.search(r"\b404\b|model.{0,40}(not found|does not exist|not supported)", detail, re.I):
        return "That key did not work with the model named. Clear the model box to use the default."
    return "That key could not be checked just now (%s). Try again in a minute." % detail.split("{")[0].strip()[:120]


def forget(person, what):
    for p in PROVIDER_LABEL:
        _models.pop((person["id"], p), None)
    if what == "key":
        staff.set_ai(person["id"], key_ct=None, key_last4=None)
    elif what == "claude":
        staff.set_ai(person["id"], claude_token_ct=None)
    elif what == "codex":
        staff.set_ai(person["id"], codex_auth_ct=None, codex_email=None)


# ---------------------------------------------------------------------------
# the models each provider offers this writer

# Claude Code's own names; each points at the newest model of its family for
# the pinned Claude Code version (2.1.278: Fable 5.1, Opus 5, Sonnet 5, Haiku 4.5).
CLAUDE_MODELS = [
    {"id": "fable", "label": "Fable", "note": "Most capable. Not on every Claude plan."},
    {"id": "opus", "label": "Opus", "note": "Strong writing and reasoning."},
    {"id": "sonnet", "label": "Sonnet", "note": "Balanced speed and quality."},
    {"id": "haiku", "label": "Haiku", "note": "Fastest; for small edits."},
]
MODELS_TTL = 6 * 3600
_models = {}           # (staff id, provider) -> (fetched at, [models])
# OpenAI lists every model the key can reach; these are not for writing.
_OPENAI_SKIP = re.compile(r"embed|tts|whisper|audio|realtime|transcribe|image|dall-e|moderation|"
                          r"search|babbage|davinci|instruct|computer-use|codex", re.I)


def _get_json(url, headers):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise gateway.GatewayError("The model API answered %s." % exc.code)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        raise gateway.GatewayError("The model API could not be reached (%s)." % exc)


def _openai_models(key):
    body = _get_json(gateway.PROVIDERS["openai"]["base_url"] + "/models",
                     {"Authorization": "Bearer " + key})
    rows = [m for m in body.get("data") or []
            if re.match(r"^(gpt-|o\d|chatgpt-)", m.get("id") or "") and not _OPENAI_SKIP.search(m["id"])]
    rows.sort(key=lambda m: (-(m.get("created") or 0), m["id"]))
    return [{"id": m["id"], "label": m["id"], "note": ""} for m in rows]


def _anthropic_models(key):
    body = _get_json(gateway.PROVIDERS["anthropic"]["base_url"] + "/v1/models?limit=100",
                     {"x-api-key": key, "anthropic-version": gateway.ANTHROPIC_VERSION})
    return [{"id": m["id"], "label": m.get("display_name") or m["id"], "note": m["id"]}
            for m in body.get("data") or [] if m.get("id")]


def _codex_models(staff_id, auth):
    """What Codex offers this ChatGPT account: its own catalog, in its order."""
    if not codex_mod.available():
        raise AIError("Codex is not installed on this server.")
    home = tempfile.mkdtemp(prefix="codex-models-")
    try:
        path = os.path.join(home, "auth.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(auth)
        out = subprocess.run([codex_mod.BIN, "debug", "models"], env=codex_mod._env(home), cwd=home,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45)
        with open(path) as f:
            now = f.read()
        if now and now != auth:          # a refreshed sign-in is kept, as after a run
            staff.set_ai(staff_id, codex_auth_ct=keychain.seal(now))
        try:
            rows = json.loads(out.stdout).get("models") or []
        except (ValueError, AttributeError):
            raise AIError("Codex did not return its model list.")
    finally:
        shutil.rmtree(home, ignore_errors=True)
    rows = [m for m in rows if m.get("visibility") == "list" and m.get("slug")]
    rows.sort(key=lambda m: m.get("priority") or 0)
    return [{"id": m["slug"], "label": m.get("display_name") or m["slug"],
             "note": m.get("description") or ""} for m in rows]


def models(person, provider, key=None):
    """{models: [{id, label, note}], default, error}. A pasted key is listed
    with that key (which also proves it works); otherwise the stored one."""
    if provider not in PROVIDER_LABEL:
        raise AIError("Choose one of the providers listed.")
    out = {"provider": provider, "models": [], "default": DEFAULT_MODEL.get(provider, ""),
           "error": None}
    if provider == "claude_code":
        out["models"] = CLAUDE_MODELS
        return out
    s = staff.ai_settings(person["id"])
    cache_key = (person["id"], provider)
    if not key:
        hit = _models.get(cache_key)
        if hit and time.time() - hit[0] < MODELS_TTL:
            out["models"] = hit[1]
            return out
    try:
        if provider == "codex":
            auth = _open(s["codex_auth_ct"])
            if not auth:
                out["error"] = "Connect ChatGPT first to see the models your plan offers."
                return out
            rows = _codex_models(person["id"], auth)
        else:
            use = (key or "").strip() or (_open(s["key_ct"]) if s["provider"] == provider else None)
            if not use:
                out["error"] = "Paste your key to see the models it can use."
                return out
            rows = _openai_models(use) if provider == "openai" else _anthropic_models(use)
    except (AIError, gateway.GatewayError, subprocess.SubprocessError, OSError) as exc:
        detail = str(exc)
        if provider in ("openai", "anthropic") and re.search(r"\b(401|403)\b", detail):
            out["error"] = _key_problem(provider, detail)
        else:
            out["error"] = "The model list could not be fetched just now. %s" % detail[:160]
        return out
    if not key:
        _models[cache_key] = (time.time(), rows)
    out["models"] = rows
    return out


# ---------------------------------------------------------------------------
# Codex sign-in (its own device code, the same flow as the assistant's)

_logins = {}


def codex_status(person):
    s = staff.ai_settings(person["id"])
    out = {"connected": bool(s["codex_auth_ct"]), "email": s["codex_email"],
           "pending": None, "error": None}
    st = _logins.get(person["id"])
    if st:
        if not st["done"] and time.time() - st["started"] > codex_mod.LOGIN_TIMEOUT:
            _cancel_login(person["id"])
            out["error"] = "The code expired. Start again."
        elif not st["done"]:
            out["pending"] = {"url": st["url"], "code": st["code"]}
        elif st["error"]:
            out["error"] = st["error"]
    return out


def _cancel_login(staff_id):
    st = _logins.pop(staff_id, None)
    if st and not st["done"]:
        st["cancelled"] = True
        try:
            st["proc"].kill()
        except Exception:  # noqa: BLE001
            pass


def codex_login(person):
    if not codex_mod.available():
        raise AIError("Codex is not installed on this server.")
    if not keychain.enabled():
        raise AIError("This server cannot store a sign-in yet: ASSISTANT_SECRET is not set.")
    sid = person["id"]
    _cancel_login(sid)
    home = tempfile.mkdtemp(prefix="codex-login-")
    proc = subprocess.Popen([codex_mod.BIN, "login", "--device-auth"], env=codex_mod._env(home),
                            cwd=home, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    st = {"proc": proc, "url": None, "code": None, "error": None, "done": False,
          "started": time.time()}
    _logins[sid] = st
    ready = threading.Event()

    def watch():
        lines, want = [], False
        for raw in proc.stdout:
            line = codex_mod._ANSI.sub("", raw).strip()
            lines.append(line)
            if not st["url"]:
                m = re.search(r"https://\S+", line)
                if m:
                    st["url"] = m.group(0)
            if "one-time code" in line.lower():
                want = True
                continue
            if want and line and not st["code"]:
                st["code"] = line.split()[0]
            if st["url"] and st["code"]:
                ready.set()
        proc.wait()
        auth = os.path.join(home, "auth.json")
        if proc.returncode == 0 and os.path.exists(auth):
            with open(auth) as f:
                text = f.read()
            staff.set_ai(sid, codex_auth_ct=keychain.seal(text), codex_email=codex_mod._email(text))
            _models.pop((sid, "codex"), None)
        elif not st.get("cancelled"):
            st["error"] = "Sign-in did not finish: " + (" ".join(lines[-3:]) or "no answer")[:300]
        st["done"] = True
        shutil.rmtree(home, ignore_errors=True)
        ready.set()

    threading.Thread(target=watch, daemon=True).start()
    ready.wait(30)
    if not (st["url"] and st["code"]):
        _cancel_login(sid)
        raise AIError(st["error"] or "Codex did not return a sign-in code. Try again.")
    return {"url": st["url"], "code": st["code"],
            "expires_in_minutes": codex_mod.LOGIN_TIMEOUT // 60}


# ---------------------------------------------------------------------------
# the tools

def _schema(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


ARTICLE_TOOLS = [
    {"name": "get_draft",
     "description": "The open article's draft as editable Markdown, with its title, summary, "
                    "web address and any charts still waiting to be copied. Call this first.",
     "parameters": _schema({})},
    {"name": "replace_draft",
     "description": "Replace the whole draft with new Markdown ('# Title' first; conventions in "
                    "the instructions). Charts already copied from pages and uploaded images are "
                    "kept when their lines are kept.",
     "parameters": _schema({"markdown": {"type": "string"},
                            "summary": {"type": "string", "description": "Optional new summary."}},
                           ["markdown"])},
    {"name": "append_to_draft",
     "description": "Add Markdown to the end of the draft, or to the end of the section whose "
                    "heading you name.",
     "parameters": _schema({"markdown": {"type": "string"},
                            "after_heading": {"type": "string"}}, ["markdown"])},
    {"name": "set_details",
     "description": "Change the title, standfirst (dek) or summary.",
     "parameters": _schema({"title": {"type": "string"}, "dek": {"type": "string"},
                            "summary": {"type": "string"}})},
    {"name": "check_article",
     "description": "What still stops the draft being published, and whether every chart can "
                    "be read.",
     "parameters": _schema({})},
    {"name": "read_page",
     "description": "Read a web page by its address and return its text, title, site and date, "
                    "to quote or cite as a footnote.",
     "parameters": _schema({"url": {"type": "string"}}, ["url"])},
]
ARTICLE_TOOL_NAMES = set(t["name"] for t in ARTICLE_TOOLS)


def tool_list():
    data = [{"name": d["name"], "description": d["description"], "parameters": d["inputSchema"]}
            for d in tools_v2.descriptors()]
    return ARTICLE_TOOLS + data


def call_tool(ctx, name, args):
    """(text, is_error) for one tool call within a job context."""
    args = args if isinstance(args, dict) else {}
    person, client, aid = ctx["person"], ctx["client"], ctx["article_id"]
    if name in ARTICLE_TOOL_NAMES:
        if name == "read_page":
            try:
                page = research_web.read(str(args.get("url") or ""))
            except research_web.WebError as exc:
                return json.dumps({"error": str(exc)}), True
            text = "\n".join(b["text"] for b in page["blocks"])[:TOOL_TEXT_MAX]
            return json.dumps({"url": page["url"], "title": page["title"], "site": page["site"],
                               "published": page["published"], "text": text},
                              ensure_ascii=False), False
        cur = research.get(aid)
        if cur is None:
            return json.dumps({"error": "The article no longer exists."}), True
        mapped = {"get_draft": "read_article", "check_article": "check_article"}.get(name, name)
        call_args = {"article_id": aid}
        if name in ("replace_draft", "append_to_draft", "set_details"):
            call_args["base_revision"] = cur["revision"]
            call_args.update(dict((k, v) for k, v in args.items()
                                  if k in ("markdown", "summary", "after_heading", "title", "dek")))
        return research_mcp.run(person, client, mapped, call_args)
    if name in tools_v2.IMPLS:
        text, err = tools_v2.run_tool(name, args)
        return text[:TOOL_TEXT_MAX], err
    return json.dumps({"error": "Unknown tool '%s'." % name}), True


# ---------------------------------------------------------------------------
# jobs

def _system(article, person):
    d = article["draft"]
    return (
        "You are the writing assistant inside the PloverResearch editor, working for %s on "
        "one draft: article %d, \"%s\". The writer gives you an instruction; carry it out on "
        "this draft with the tools, then reply with two to four plain sentences to the writer: "
        "what you changed and anything they should check. You cannot publish; the writer does.\n\n"
        "Call get_draft first. Change the draft only with replace_draft, append_to_draft and "
        "set_details. Keep the writer's own text unless the instruction asks you to change it.\n\n"
        % (person["name"], article["id"], d.get("title") or "Untitled")
    ) + research_mcp.RULES


def _log(job, kind, text):
    job["steps"].append({"at": time.time(), "kind": kind, "text": text[:300]})


def _describe(name, args):
    args = args or {}
    if name == "get_draft":
        return "Read the draft"
    if name == "replace_draft":
        return "Rewrote the draft"
    if name == "append_to_draft":
        return "Added to the draft" + ((" under \"%s\"" % args["after_heading"])
                                       if args.get("after_heading") else "")
    if name == "set_details":
        return "Updated " + ", ".join(k for k in ("title", "dek", "summary") if args.get(k))
    if name == "check_article":
        return "Ran the publish checklist"
    if name == "read_page":
        return "Read %s" % (args.get("url") or "a page")
    if name == "search":
        return "Searched Plover for \"%s\"" % (args.get("query") or "")
    if name == "get_series":
        return "Read series %s" % (args.get("codes") or args.get("code") or args.get("dataset") or "")
    return "Used %s" % name.replace("_", " ")


def start(person, article_id, instruction):
    instruction = (instruction or "").strip()
    if not instruction:
        raise AIError("Tell the AI what to do.")
    if len(instruction) > 8000:
        raise AIError("Keep the instruction under 8,000 characters.")
    article = research.get(article_id)
    if article is None:
        raise AIError("No such article.")
    s = staff.ai_settings(person["id"])
    provider = s["provider"]
    if not provider or not _ready(provider, s):
        raise AIError("Choose and connect a provider first.")
    with _jobs_lock:
        busy = _running.get(person["id"])
        if busy and _jobs.get(busy, {}).get("status") == "running":
            raise AIError("The AI is still working on your last instruction.")
        before = research.mark(article_id, staff.actor_label(person), "Before AI")
        job = {"id": uuid.uuid4().hex[:16], "status": "running", "steps": [], "reply": "",
               "error": None, "article_id": article_id, "staff_id": person["id"],
               "provider": provider, "started": time.time(), "finished": None,
               "before_history_id": before, "revision_before": article["revision"]}
        _jobs[job["id"]] = job
        _running[person["id"]] = job["id"]
    ctx = {"person": person, "client": CLIENT[provider], "article_id": article_id}
    threading.Thread(target=_run, args=(job, ctx, s, instruction, article), daemon=True).start()
    return public(job)


def public(job):
    a = research.get(job["article_id"])
    return {"id": job["id"], "status": job["status"], "steps": job["steps"], "reply": job["reply"],
            "error": job["error"], "provider": job["provider"],
            "provider_label": PROVIDER_LABEL.get(job["provider"]),
            "before_history_id": job["before_history_id"],
            "revision_after": job.get("revision_after"),
            "changed": bool(a) and a["revision"] != job["revision_before"],
            "revision": a["revision"] if a else None,
            "seconds": round((job["finished"] or time.time()) - job["started"])}


def get_job(person, job_id):
    job = _jobs.get(job_id)
    if job is None or job["staff_id"] != person["id"]:
        return None
    return public(job)


def _run(job, ctx, s, instruction, article):
    try:
        provider = s["provider"]
        system = _system(article, ctx["person"])
        if provider in ("openai", "anthropic"):
            reply = _run_api(job, ctx, provider, _open(s["key_ct"]),
                             s["model"] or DEFAULT_MODEL[provider], system, instruction)
        elif provider == "codex":
            reply = _run_codex(job, ctx, s, system, instruction)
        else:
            reply = _run_claude(job, ctx, s, system, instruction)
        job["reply"] = (reply or "").strip() or "Done."
        job["status"] = "done"
    except (AIError, gateway.GatewayError) as exc:
        job["error"] = str(exc)
        job["status"] = "failed"
    except Exception as exc:  # noqa: BLE001 — a failed run must say why, not hang
        job["error"] = "The AI run stopped: %s" % exc
        job["status"] = "failed"
    finally:
        a = research.get(job["article_id"])
        job["revision_after"] = a["revision"] if a else None
        job["finished"] = time.time()


def _run_api(job, ctx, provider, key, model, system, instruction):
    if not key:
        raise AIError("The stored key could not be read; paste it again.")
    tools = tool_list()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": instruction}]
    for _ in range(MAX_STEPS):
        out = gateway.complete(provider, key, model, messages, tools, max_tokens=8000)
        messages.append({"role": "assistant", "content": out["text"],
                         "tool_calls": out["tool_calls"]})
        if not out["tool_calls"]:
            return out["text"]
        for tc in out["tool_calls"]:
            text, err = call_tool(ctx, tc["name"], tc.get("args") or {})
            _log(job, "error" if err else "tool", _describe(tc["name"], tc.get("args")))
            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": tc["name"],
                             "content": text})
    return "I stopped after %d steps; the draft has what I finished." % MAX_STEPS


# ---- the CLIs: one stdio tool server, the same tools ----------------------

def _spec_file(job, ctx, work):
    path = os.path.join(work, "spec.json")
    log = os.path.join(work, "calls.jsonl")
    with open(path, "w") as f:
        json.dump({"staff_id": ctx["person"]["id"], "article_id": ctx["article_id"],
                   "client": ctx["client"], "log": log}, f)
    return path, log


def _child_env():
    env = dict((k, os.environ[k]) for k in CHILD_ENV if os.environ.get(k))
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def _follow(job, log_path, stop):
    """Copy the tool server's call log into the job's steps as it grows."""
    seen = 0
    while True:
        last = stop.is_set()
        try:
            with open(log_path) as f:
                lines = f.readlines()
        except OSError:
            lines = []
        for line in lines[seen:]:
            try:
                ev = json.loads(line)
                _log(job, "error" if ev.get("error") else "tool", _describe(ev["name"], ev.get("args")))
            except (ValueError, KeyError):
                pass
        seen = len(lines)
        if last:
            return
        stop.wait(0.7)


def _prompt(system, instruction):
    return system + "\n\nInstruction from the writer:\n" + instruction


def _run_codex(job, ctx, s, system, instruction):
    if not codex_mod.available():
        raise AIError("Codex is not installed on this server.")
    auth = _open(s["codex_auth_ct"])
    if not auth:
        raise AIError("Codex is not signed in; connect it again in the AI tab.")
    home = tempfile.mkdtemp(prefix="codex-home-")
    work = tempfile.mkdtemp(prefix="codex-work-")
    stop = threading.Event()
    follower = None
    try:
        auth_path = os.path.join(home, "auth.json")
        fd = os.open(auth_path, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(auth)
        spec, log = _spec_file(job, ctx, work)
        last = os.path.join(home, "last.txt")
        child = _child_env()
        child["PYTHONPATH"] = APP_ROOT
        env_table = "{" + ", ".join("%s = %s" % (k, json.dumps(v))
                                    for k, v in child.items()) + "}"
        cmd = [codex_mod.BIN, "exec", "--json", "--ephemeral", "--skip-git-repo-check",
               "--ignore-user-config", "--ignore-rules", "-C", work, "-s", "read-only", "-o", last]
        for feat in codex_mod.DISABLE:
            cmd += ["--disable", feat]
        cmd += ["-c", 'web_search="live"', "-c", 'approval_policy="never"',
                "-c", "mcp_servers.plover.command=" + json.dumps(sys.executable),
                "-c", "mcp_servers.plover.args=" + json.dumps(
                    ["-m", "app.research_ai_mcp", "--spec", spec]),
                "-c", "mcp_servers.plover.cwd=" + json.dumps(APP_ROOT),
                "-c", "mcp_servers.plover.env=" + env_table,
                "-c", "mcp_servers.plover.startup_timeout_sec=30",
                "-c", "mcp_servers.plover.tool_timeout_sec=120"]
        if s["model"]:
            cmd += ["-m", s["model"]]
        cmd.append("-")
        follower = threading.Thread(target=_follow, args=(job, log, stop), daemon=True)
        follower.start()
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=codex_mod._env(home), cwd=work)
        proc.stdin.write(_prompt(system, instruction))
        proc.stdin.close()
        errors = []
        deadline = time.time() + RUN_SECONDS
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            item = ev.get("item") or {}
            if ev.get("type") == "item.completed" and item.get("type") == "web_search":
                _log(job, "web", "Searched the web for \"%s\"" % (item.get("query") or ""))
            if ev.get("type") in ("turn.failed", "error"):
                errors.append(((ev.get("error") or {}).get("message") or ev.get("message") or "")[:300])
            if time.time() > deadline:
                proc.kill()
                errors.append("The run took longer than %d minutes." % (RUN_SECONDS // 60))
                break
        proc.wait()
        if os.path.exists(auth_path):
            with open(auth_path) as f:
                now = f.read()
            if now and now != auth:
                staff.set_ai(ctx["person"]["id"], codex_auth_ct=keychain.seal(now))
        text = open(last).read().strip() if os.path.exists(last) else ""
        if proc.returncode != 0 and not text:
            msg = next((e for e in errors if e), "") or "Codex stopped (exit %s)." % proc.returncode
            if re.search(r"model .*not supported", msg, re.I):
                msg += " Set a model your ChatGPT plan offers in the AI tab (for example gpt-5.6-sol)."
            elif re.search(r"401|unauthori[sz]ed|sign in|log in|login", msg, re.I):
                msg = "The ChatGPT sign-in has expired; connect Codex again. (" + msg + ")"
            raise AIError(msg)
        return text
    finally:
        stop.set()
        if follower is not None:
            follower.join(5)
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def _claude_env(home, token):
    """Only what Claude Code needs: its token, an empty home and config
    directory of its own, and no updates, telemetry or error reports."""
    return {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": home,
            "CLAUDE_CONFIG_DIR": os.path.join(home, ".claude"),
            "CLAUDE_CODE_OAUTH_TOKEN": token,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1",
            "LANG": "C.UTF-8"}


def _run_claude(job, ctx, s, system, instruction):
    if shutil.which(CLAUDE_BIN) is None:
        raise AIError("Claude Code is not installed on this server.")
    token = _open(s["claude_token_ct"])
    if not token:
        raise AIError("The stored Claude Code token could not be read; paste it again.")
    home = tempfile.mkdtemp(prefix="claude-home-")
    work = tempfile.mkdtemp(prefix="claude-work-")
    stop = threading.Event()
    follower = None
    try:
        spec, log = _spec_file(job, ctx, work)
        env = _child_env()
        env["PYTHONPATH"] = APP_ROOT
        mcp = {"mcpServers": {"plover": {
            "type": "stdio", "command": sys.executable,
            "args": ["-m", "app.research_ai_mcp", "--spec", spec], "env": env}}}
        mcp_path = os.path.join(work, "mcp.json")
        with open(mcp_path, "w") as f:
            json.dump(mcp, f)
        # Built-in tools cut to web search and page fetch; everything else is
        # the plover server. dontAsk refuses anything not allowed here.
        cmd = [CLAUDE_BIN, "-p", "--output-format", "stream-json", "--verbose",
               "--no-session-persistence", "--setting-sources", "",
               "--mcp-config", mcp_path, "--strict-mcp-config",
               "--tools", "WebSearch,WebFetch",
               "--allowedTools", "mcp__plover__*,WebSearch,WebFetch",
               "--permission-mode", "dontAsk",
               "--append-system-prompt", system]
        if s["model"]:
            cmd += ["--model", s["model"]]
        follower = threading.Thread(target=_follow, args=(job, log, stop), daemon=True)
        follower.start()
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                env=_claude_env(home, token), cwd=work)
        proc.stdin.write("Instruction from the writer:\n" + instruction)
        proc.stdin.close()
        result, errors = None, []
        deadline = time.time() + RUN_SECONDS
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                if line.strip():
                    errors.append(line.strip()[:300])
                continue
            if ev.get("type") == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use" and b.get("name") == "WebSearch":
                        _log(job, "web", "Searched the web for \"%s\""
                             % ((b.get("input") or {}).get("query") or ""))
                    elif b.get("type") == "tool_use" and b.get("name") == "WebFetch":
                        _log(job, "web", "Read %s" % ((b.get("input") or {}).get("url") or "a page"))
            elif ev.get("type") == "result":
                result = ev
            if time.time() > deadline:
                proc.kill()
                errors.append("The run took longer than %d minutes." % (RUN_SECONDS // 60))
                break
        proc.wait()
        if result and not result.get("is_error"):
            return result.get("result") or ""
        msg = ((result or {}).get("result") or "") or next((e for e in reversed(errors) if e), "") \
            or "Claude Code stopped (exit %s)." % proc.returncode
        if re.search(r"401|invalid.*token|oauth|log ?in|authenticat", msg, re.I):
            msg = ("Claude Code did not accept the token; run `claude setup-token` again and "
                   "paste the new one. (" + msg[:200] + ")")
        raise AIError(msg[:500])
    finally:
        stop.set()
        if follower is not None:
            follower.join(5)
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# endpoints, under the desk's own prefix

router = APIRouter(prefix="/admin/api/research", include_in_schema=False)


def _person(request):
    from .admin_api import _require_admin
    person = _require_admin(request, "writing")
    if person.get("shared") or not person.get("id"):
        raise HTTPException(403, "Sign in with your own account to use the AI tab: "
                                 "its keys and sign-ins are personal.")
    return person


def _audit(request, person, action, detail):
    from .admin_api import _client_ip, audit
    audit(action, detail, _client_ip(request), by=staff.actor_label(person))


class SettingsBody(BaseModel):
    provider: str
    model: Optional[str] = None
    key: Optional[str] = None
    claude_token: Optional[str] = None


class ForgetBody(BaseModel):
    what: str


class ModelsBody(BaseModel):
    provider: str
    key: Optional[str] = None


class RunBody(BaseModel):
    instruction: str


@router.get("/ai")
def ai_get(request: Request):
    return settings_view(_person(request))


@router.put("/ai")
def ai_put(body: SettingsBody, request: Request):
    person = _person(request)
    try:
        save_settings(person, body.provider, body.model, body.key, body.claude_token)
    except AIError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "research_ai_settings", "provider %s%s" % (
        body.provider, " (new key)" if (body.key or body.claude_token) else ""))
    return settings_view(person)


@router.post("/ai/forget")
def ai_forget(body: ForgetBody, request: Request):
    person = _person(request)
    if body.what not in ("key", "claude", "codex"):
        raise HTTPException(400, "Nothing to forget by that name.")
    forget(person, body.what)
    _audit(request, person, "research_ai_forget", body.what)
    return settings_view(person)


@router.post("/ai/models")
def ai_models(body: ModelsBody, request: Request):
    """The models this writer can choose for a provider: Claude Code's own
    names, their ChatGPT plan's Codex catalog, or what their API key lists."""
    person = _person(request)
    try:
        return models(person, body.provider, body.key)
    except AIError as exc:
        raise HTTPException(400, str(exc))


@router.post("/ai/codex/login")
def ai_codex_login(request: Request):
    person = _person(request)
    try:
        return codex_login(person)
    except AIError as exc:
        raise HTTPException(400, str(exc))


@router.get("/ai/codex")
def ai_codex_status(request: Request):
    return codex_status(_person(request))


@router.post("/articles/{article_id}/ai")
def ai_run(article_id: int, body: RunBody, request: Request):
    person = _person(request)
    try:
        job = start(person, article_id, body.instruction)
    except AIError as exc:
        raise HTTPException(400, str(exc))
    _audit(request, person, "research_ai_run", "article %d via %s" % (
        article_id, PROVIDER_LABEL.get(job["provider"])))
    return job


@router.get("/ai/jobs/{job_id}")
def ai_job(job_id: str, request: Request):
    job = get_job(_person(request), job_id)
    if job is None:
        raise HTTPException(404, "No such run")
    return job
