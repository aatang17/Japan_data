# -*- coding: utf-8 -*-
"""Type every search box's own examples into a real (hidden) browser.

Starts a private server on a free port over this machine's data, runs
ci/search_examples.mjs against it, and stops the server again — by its own
process id. Needs the data and Chrome, so it runs in the pre-push hook, not
in GitHub's checks.

Run from observatory/:  ./.venv/bin/python ci/search_examples.py [part,part,...]
(the parts pick boxes by key, e.g. "agm,risks"; "lock" picks the lock check)
Exit code 0 if every example finds something, 1 if one does not, 2 if the
check itself could not run.

Why it exists: on 2026-10-03 the research desk's search found nothing for
"CPI", nor for "core CPI", the example printed in its own box, and the
customer lookup suggested "TSMC", which no filing uses. Both passed every
test, because no test typed what the box tells a reader to type.
"""
from __future__ import print_function

import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main(argv):
    only = argv[1] if len(argv) > 1 else ""
    if subprocess.call(["node", "--version"], stdout=subprocess.DEVNULL) != 0:
        print("search examples: node is not installed")
        return 2
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    uvicorn = str(ROOT / ".venv" / "bin" / "uvicorn")
    if not os.path.exists(uvicorn):
        uvicorn = "uvicorn"
    log = open(os.devnull, "w")
    server = subprocess.Popen([uvicorn, "app.main:app", "--port", str(port)],
                              cwd=str(ROOT), env=env, stdout=log, stderr=log)
    try:
        deadline = time.time() + 180
        while True:
            if server.poll() is not None:
                print("search examples: the test server exited while starting "
                      "(is another process writing to the database?)")
                return 2
            try:
                urllib.request.urlopen(base + "/api/v1/catalog/datasets", timeout=5)
                break
            except Exception:  # noqa: BLE001 — not up yet
                if time.time() > deadline:
                    print("search examples: the test server did not start in 3 minutes")
                    return 2
                time.sleep(0.5)
        args = ["node", str(ROOT / "ci" / "search_examples.mjs"), base]
        if only:
            args.append(only)
        return subprocess.call(args, cwd=str(ROOT))
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
