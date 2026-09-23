"""Delivery: the only code that sends anything outward, and it runs only from
an approval a person decided. A run never calls this."""
import json
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 15


class DeliveryError(Exception):
    pass


def slack(webhook_url, text):
    """Post one message to a Slack incoming webhook."""
    if not webhook_url:
        raise DeliveryError("No Slack webhook is stored for this desk.")
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", "replace")[:200]
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as exc:
        raise DeliveryError("Slack answered %s." % exc.code)
    except urllib.error.URLError as exc:
        raise DeliveryError("Slack could not be reached (%s)." % exc.reason)
