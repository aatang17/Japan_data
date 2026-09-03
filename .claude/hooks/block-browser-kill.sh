#!/bin/sh
# Refuse any Bash command that would kill a browser by application name.
#
# Killing "Google Chrome" by name takes down the user's real browser window
# (and every other agent's browser) along with the headless one. Scoped kills
# are fine: --headless=new, a --user-data-dir you chose, or a profile name.
# See the P0 rule in CLAUDE.md and memory/chrome-cli-screenshot-traps.md.

cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null)
[ -z "$cmd" ] && exit 0

# Does a kill command name a browser?
printf '%s' "$cmd" | grep -qiE '(pkill|killall)[^;&|]*(chrome|chromium|safari|firefox|msedge)' || exit 0

# ...but allow it when the same kill is scoped to a process we launched.
printf '%s' "$cmd" | grep -qiE '(pkill|killall)[^;&|]*(headless|user-data-dir|profile|remote-debugging)' && exit 0

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Blocked: this kills the browser by application name, which terminates the user's real Chrome window and other agents' browsers, not just your headless one. Kill only the process you launched -- e.g. pkill -f -- \"--headless=new\" -- or use its PID. See the P0 rule in CLAUDE.md."}}
JSON
exit 0
