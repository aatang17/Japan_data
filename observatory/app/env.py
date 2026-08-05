"""Load observatory/.env into the process environment.

Twelve lines instead of a python-dotenv dependency, because the only thing
that ever lives in this file is a provider API key. Imported for its side
effect by main.py before the API module reads any credential, so that
`uvicorn app.main:app` picks the key up without the caller having to export
it — the failure mode otherwise is a server that starts fine and silently
hides the ask box.

A real environment variable always wins: `.env` is the local-development
fallback, never an override of what the deployment set.
"""
import pathlib

ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"


def load(path=ENV_PATH):
    """Set any KEY=value in `path` that isn't already in the environment."""
    import os

    if not path.exists():
        return {}
    loaded = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        # tolerate quoted values; a key set in the real environment wins
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded
