"""Outbound email, in one place.

Two callers want a mailbox for quite different reasons — accounts.py sends
sign-in links to readers, refresh.py sends fault alarms to us — and both need
the same three things: the Resend credential, a plain-text body, and a
delivery that cannot take the caller down with it. This module is that, and
nothing else. It knows about Resend; nobody else has to.

Development delivery
--------------------
Without RESEND_API_KEY and RESEND_FROM the message is printed to the log and
reported as "logged". That is how the sign-in flow is tested on a laptop, and
it is what production did for both callers until 2026-09-20 — worth saying
out loud, because a log-only alarm is indistinguishable from no alarm. The
health report names the delivery mode for exactly that reason.
"""
import json
import os
import urllib.error
import urllib.request


def configured():
    """True when a real mailbox is reachable; False means log-only."""
    return bool((os.environ.get("RESEND_API_KEY") or "").strip()
                and (os.environ.get("RESEND_FROM") or "").strip())


def send(to_address, subject, text, html=None, timeout=10):
    """Send one message. Returns 'sent' or 'logged'; raises on a real failure.

    A caller that must tell a human whether delivery worked (accounts.py owes
    a reader who was told to check an inbox) catches the exception. A caller
    that must never crash on it (the alarm) catches it and carries on.
    """
    key = (os.environ.get("RESEND_API_KEY") or "").strip()
    sender = (os.environ.get("RESEND_FROM") or "").strip()
    if not key or not sender:
        print("[mail] to %s — %s\n%s" % (to_address, subject, text), flush=True)
        return "logged"

    body = {"from": sender, "to": [to_address], "subject": subject, "text": text}
    if html:
        body["html"] = html
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
        return "sent"
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        print("[mail] resend %s: %s" % (exc.code, detail), flush=True)
        raise
    except Exception as exc:                                 # network, DNS, timeout
        print("[mail] resend failed: %r" % (exc,), flush=True)
        raise
