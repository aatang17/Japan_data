"""The Investment Assistant: a desk of specialists over the Observatory's tools.

Its own namespace, like the cross-shareholding database: the golden rule for
datasets does not apply here, and nothing here writes a dataset file. See
docs/plans/PLAN-INVESTMENT-ASSISTANT.md for what it is and
docs/plans/ARCH-INVESTMENT-ASSISTANT-AGENT.md for how a run works.

Two kill switches, both off by default: ACCOUNTS_ENABLED (there is no desk
without a signed-in person) and ASSISTANT_ENABLED. With either unset the
router is not mounted and /assistant.html says the desk is not open.
"""
import os

from .. import accounts


def enabled():
    flag = str(os.environ.get("ASSISTANT_ENABLED", "")).strip().lower() in (
        "1", "true", "yes", "on")
    return flag and accounts.enabled()
