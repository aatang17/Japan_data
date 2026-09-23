"""Code does the bookkeeping; the model only writes the note.

A monitor's mechanical work — fetch each covered company's latest filings,
compare with last time, list what changed — needs no judgement, so it is done
here with the same tool layer the model would have used (tools_v2.run_tool),
at zero tokens. The model then sees a short digest instead of raw filing data:
a ten-company run costs a few thousand tokens rather than a few hundred
thousand, and a modest model is enough because the hard part is already done.

State between runs is a workspace file on the hire (state/coverage.json), so
"what changed" is a diff of two digests and every change carries the document
id that proves it. Sources on the resulting post come from here, not from the
model.
"""
import datetime
import json

from .. import tools_v2

STATE_PATH = "state/coverage.json"
LINES = ("revenue", "operating_income", "ordinary_income", "profit")


def _tool(name, args):
    text, is_error = tools_v2.run_tool(name, args)
    if is_error:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _num(v):
    return v if isinstance(v, (int, float)) else None


def earnings_for(code):
    """The newest earnings release and its headline lines, or None."""
    d = _tool("get_company", {"code": code, "dataset": "earnings-releases", "limit": 3})
    data = (d or {}).get("data") or {}
    rel = data.get("release") or {}
    if not rel.get("doc_key"):
        return None
    lines = []
    for r in data.get("results") or []:
        if r.get("line") in LINES:
            lines.append({"line": r.get("line"), "label": r.get("label"),
                          "value": _num(r.get("value")), "prior": _num(r.get("prior_value")),
                          "yoy_pct": _num(r.get("yoy_pct_published"))})
    prog = None
    for f in data.get("forecast") or []:
        if f.get("line") == "profit" and _num(f.get("progress_pct")) is not None:
            prog = f["progress_pct"]
    return {"doc": rel["doc_key"], "filed": rel.get("filed_date"), "title": rel.get("title"),
            "fiscal_period": rel.get("fiscal_period"), "period": rel.get("period_label"),
            "correction": bool(rel.get("is_correction")), "lines": lines,
            "profit_progress_pct": prog, "cite": (d or {}).get("cite")}


def buybacks_for(code):
    """Each buyback programme's state, newest resolution first."""
    d = _tool("get_company", {"code": code, "dataset": "buybacks", "limit": 5})
    data = (d or {}).get("data") or {}
    out = []
    for p in data.get("programs") or []:
        out.append({"resolved": p.get("resolution_date"), "window_start": p.get("window_start"),
                    "window_end": p.get("window_end"), "authorised_yen": _num(p.get("authorised_yen")),
                    "bought_yen": _num(p.get("cumulative_yen")), "done_pct": _num(p.get("completion_pct")),
                    "unspent_yen": _num(p.get("unspent_yen")), "state": p.get("lifecycle"),
                    "state_label": p.get("lifecycle_label"), "doc": p.get("last_doc_id"),
                    "as_of": p.get("last_as_of")})
    out.sort(key=lambda p: p.get("resolved") or "", reverse=True)
    return {"programmes": out, "cite": (d or {}).get("cite")}


def build(coverage):
    """The digest of a coverage list: one entry per company."""
    companies = []
    for c in coverage:
        code = c["sec_code"]
        companies.append({"code": code, "name": c.get("name") or code,
                          "earnings": earnings_for(code), "buybacks": buybacks_for(code)})
    return {"as_of": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"), "companies": companies}


def diff(prev, cur):
    """What changed between two digests: a list of plain-language changes,
    each with the document ids that show it."""
    changes = []
    before = dict((c["code"], c) for c in (prev or {}).get("companies") or [])
    for c in cur["companies"]:
        code, name = c["code"], c["name"]
        old = before.get(code)
        if old is None:
            changes.append({"code": code, "kind": "added", "text": "%s (%s) joined the coverage list." % (name, code), "sources": []})
            continue
        e, oe = c.get("earnings"), old.get("earnings")
        if e and (not oe or e["doc"] != oe["doc"]):
            what = "corrected earnings release" if e.get("correction") else "new earnings release"
            changes.append({"code": code, "kind": "earnings", "sources": [e["doc"]],
                            "text": "%s (%s): %s for %s, filed %s." % (name, code, what, e.get("period") or e.get("fiscal_period"), e.get("filed"))})
        old_progs = dict((p.get("resolved"), p)
                         for p in (old.get("buybacks") or {}).get("programmes") or [])
        for p in (c.get("buybacks") or {}).get("programmes") or []:
            op = old_progs.get(p.get("resolved"))
            if op is None:
                changes.append({"code": code, "kind": "buyback_new", "sources": [p["doc"]] if p.get("doc") else [],
                                "text": "%s (%s): new buyback programme resolved %s, window %s to %s." % (name, code, p.get("resolved"), p.get("window_start"), p.get("window_end"))})
            elif op.get("state") != p.get("state"):
                changes.append({"code": code, "kind": "buyback_state", "sources": [p["doc"]] if p.get("doc") else [],
                                "text": "%s (%s): buyback resolved %s moved from '%s' to '%s'." % (name, code, p.get("resolved"), op.get("state_label") or op.get("state"), p.get("state_label") or p.get("state"))})
            elif op.get("doc") != p.get("doc") and p.get("doc"):
                changes.append({"code": code, "kind": "buyback_report", "sources": [p["doc"]],
                                "text": "%s (%s): new monthly buyback report to %s." % (name, code, p.get("as_of"))})
    return changes


def _yen(v):
    if v is None:
        return "not stated"
    if abs(v) >= 1e12:
        return "¥%.2ftn" % (v / 1e12)
    if abs(v) >= 1e8:
        return "¥%.1fbn" % (v / 1e9)
    return "¥%dm" % round(v / 1e6)


def render(cur, changes, first_run):
    """The digest as short text for the model. Nothing the model needs is
    left out; nothing it does not need is put in."""
    lines = []
    if first_run:
        lines.append("First run: no earlier state to compare with. Describe the current position of each company.")
    elif changes:
        lines.append("Changes since the last run:")
        for ch in changes:
            lines.append("- " + ch["text"] + (" [%s]" % ", ".join(ch["sources"]) if ch["sources"] else ""))
    else:
        lines.append("No changes since the last run.")
    lines.append("")
    lines.append("Current position, per company:")
    for c in cur["companies"]:
        lines.append("")
        lines.append("%s (%s)" % (c["name"], c["code"]))
        e = c.get("earnings")
        if e:
            parts = []
            for l in e["lines"]:
                if l["value"] is None:
                    continue
                s = "%s %s" % (l["label"], _yen(l["value"]))
                if l["yoy_pct"] is not None:
                    s += " (%+.1f%% y/y, as published)" % l["yoy_pct"]
                parts.append(s)
            lines.append("  Latest earnings: %s, filed %s [%s]%s" % (
                e.get("period") or e.get("fiscal_period"), e.get("filed"), e["doc"],
                " (correction)" if e.get("correction") else ""))
            if parts:
                lines.append("  " + "; ".join(parts))
            if e.get("profit_progress_pct") is not None:
                lines.append("  Full-year profit forecast %.1f%% reached (calculated: cumulative result / company forecast)" % e["profit_progress_pct"])
        else:
            lines.append("  Latest earnings: none on file")
        progs = (c.get("buybacks") or {}).get("programmes") or []
        if progs:
            for p in progs[:2]:
                lines.append("  Buyback resolved %s: %s; window %s to %s; authorised %s, bought %s%s [%s, to %s]" % (
                    p.get("resolved"), p.get("state_label") or p.get("state"), p.get("window_start"), p.get("window_end"),
                    _yen(p.get("authorised_yen")), _yen(p.get("bought_yen")),
                    " (%.1f%%, calculated: bought / authorised)" % p["done_pct"] if p.get("done_pct") is not None else "",
                    p.get("doc"), p.get("as_of")))
        else:
            lines.append("  Buybacks: none on file")
    return "\n".join(lines)


def sources(cur, changes):
    """Every document id the note can rest on, changes first, no repeats."""
    seen = []
    for ch in changes:
        for s in ch["sources"]:
            if s not in seen:
                seen.append(s)
    for c in cur["companies"]:
        e = c.get("earnings")
        if e and e["doc"] not in seen:
            seen.append(e["doc"])
        for p in ((c.get("buybacks") or {}).get("programmes") or [])[:2]:
            if p.get("doc") and p["doc"] not in seen:
                seen.append(p["doc"])
    return seen
