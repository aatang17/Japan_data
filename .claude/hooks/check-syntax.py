#!/usr/bin/env python3
"""After every file Claude edits: does it still parse?

Runs on PostToolUse for Edit / Write / MultiEdit / NotebookEdit. A file that
no longer parses is reported straight back to Claude (exit 2), before it can
reach a browser or a reader:

  .py           compiled by observatory/.venv's Python (3.9, as the laptop runs)
  .js / .mjs    node --check
  .html         every inline <script> block, node --check
  .json         parsed
  .sh           sh -n

See CLAUDE.md "Checks that run every time".
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[2]
PY = REPO / "observatory" / ".venv" / "bin" / "python"


def problems_in(path):
    """A list of what is wrong with one file; empty when it parses."""
    ext = path.suffix.lower()
    if ext == ".py":
        py = str(PY) if PY.exists() else sys.executable
        r = subprocess.run([py, "-m", "py_compile", str(path)], capture_output=True, text=True)
        return [r.stderr.strip()] if r.returncode else []
    if ext in (".js", ".mjs"):
        r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        return [r.stderr.strip()] if r.returncode else []
    if ext == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            return ["%s: %s" % (path, exc)]
        return []
    if ext == ".sh":
        r = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
        return [r.stderr.strip()] if r.returncode else []
    if ext == ".html":
        out = []
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(?is)<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", text):
            attrs, body = m.group("attrs"), m.group("body")
            if "src=" in attrs or not body.strip():
                continue
            if re.search(r"type=[\"'](application/(ld\+)?json|text/template)", attrs):
                continue
            line = text[:m.start("body")].count("\n") + 1
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                f.write(body)
                tmp = f.name
            try:
                r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
                if r.returncode:
                    out.append("%s: inline script starting at line %d: %s"
                               % (path, line, r.stderr.strip().splitlines()[-1]))
            finally:
                os.unlink(tmp)
        return out
    return []


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = data.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not raw:
        return 0
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = pathlib.Path(data.get("cwd") or os.getcwd()) / path
    if not path.exists():
        return 0
    problems = problems_in(path)
    if problems:
        sys.stderr.write("The file you just saved no longer parses. Fix it before anything "
                         "else:\n" + "\n".join(problems) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
