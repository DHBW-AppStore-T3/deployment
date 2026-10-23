#!/usr/bin/env python3
"""PreToolUse guardrail for the legacy VM host appstore-prod-01 (HARNESS.md System 3.2/5.4).

LEGACY: the app now runs on Kubernetes (read-only visibility via the
appstore-mcp server) and the VM has been decommissioned, so this hook
normally never matches. It stays as a harmless safety net: it blocks
state-changing docker/podman calls over SSH to that old host name/IP
and only allows read-only container inspection.

Almost entirely read-only, with one deliberate write exception: a
`docker restart <name>` for a specific, named, non-stateful container
in RESTART_ALLOWLIST — the /restart-service skill's one permitted
action, used only after /diagnose-production plus explicit human
confirmation (System 5.4). Everything else state-changing (rm, stop,
compose, image ops, multi-target or unlisted restarts) stays blocked.

Reads the PreToolUse Bash payload from stdin, exits 0 (allow) unless
the command both targets appstore-prod-01 AND contains a
docker/podman subcommand outside what's permitted, in which case it
exits 2 with a message on stderr, which Claude Code surfaces to the
model as a blocked-command explanation instead of running it.
"""
import json
import re
import sys

# Read-only container inspection (legacy VM allowlist).
ALLOWED_SUBCOMMANDS = {
    "ps",
    "inspect",
    "logs",
    "images",
    "network",  # network ls / inspect are read-only enough to allow
    "version",
    "info",
}

# Any of these anywhere in a docker/podman invocation is destructive or
# state-changing and must never run against appstore-prod-01 without a
# human directly typing it outside of an automated tool call.
BLOCKED_SUBCOMMANDS = {
    "run",
    "exec",
    "rm",
    "rmi",
    "stop",
    "kill",
    "down",
    "up",
    "build",
    "push",
    "pull",
    # `docker compose` is blocked wholesale, including its read-only
    # subcommands (ps/logs) — those already have dedicated, reviewed
    # entry points (`make prod-ps`, `make prod-logs` in the Makefile),
    # so there's no legitimate reason for a raw `ssh ... docker compose`
    # call, and a bare "compose" match can't tell `ps` from `down`
    # without parsing quoting/flags this hook deliberately keeps simple.
    "compose",
    "system",  # docker system prune, etc.
    "volume",  # volume rm is one flag away
}
# NOTE: "restart" is intentionally NOT in BLOCKED_SUBCOMMANDS — it is
# handled separately below via RESTART_ALLOWLIST, not via the blanket
# ALLOWED_SUBCOMMANDS set. A bare `docker restart <anything>` is still
# refused; only the exact container names the /restart-service skill
# documents are permitted, and only as `docker restart <name>` — never
# `docker compose restart` (still caught by the "compose" block above).

# HARNESS.md System 5.4: after a human has confirmed a fix via
# /diagnose-production, a restart of one of these specific containers
# is the one write action this host permits. Anything not in this
# exact list — including the stateful data stores — stays blocked.
#
# Legacy names; Hermes was replaced by appstore-mcp and the VMs are gone.
RESTART_ALLOWLIST = {
    "backend-prod",
    "worker-prod",
    "frontend-prod",
    "caddy-prod",
    "keycloak-prod",
    "podman-mcp-prod",
    "moodle-prod",
}

PROD_HOST_PATTERN = re.compile(r"\bappstore-(vm|agent)\b|2001:7c0:1b20:c913:1::15a")
DOCKER_INVOCATION_PATTERN = re.compile(r"\b(?:sudo\s+)?(?:docker|podman)\b")
# Captures the docker/podman invocation plus everything after it up to
# end of command/quote/pipe/semicolon, so `restart` handling can check
# the actual argument, not just the subcommand word.
RESTART_ARGS_PATTERN = re.compile(
    r"\b(?:sudo\s+)?(?:docker|podman)\s+restart\s+([^\"';|&]+)"
)


def extract_subcommand(command: str) -> str | None:
    match = DOCKER_INVOCATION_PATTERN.search(command)
    if not match:
        return None
    rest = command[match.end():].strip()
    if not rest:
        return None
    # Strip everything but letters — SSH-quoted commands like
    # `ssh host "docker ps"` leave a trailing quote glued to the word
    # (`ps"`), and flags/pipes/semicolons need the same treatment.
    first_token = rest.split()[0]
    return re.sub(r"[^a-z]", "", first_token.lower()) or None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # never block on a parse failure — fail open, not closed

    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "")
    if not command:
        return 0

    if not PROD_HOST_PATTERN.search(command):
        return 0  # not targeting appstore-prod-01 — out of scope for this hook

    subcommand = extract_subcommand(command)
    if subcommand is None:
        return 0  # ssh to the host without an inline docker/podman call — allow

    if subcommand == "restart":
        match = RESTART_ARGS_PATTERN.search(command)
        target = match.group(1).strip() if match else ""
        # Exactly one bare container name, nothing else on the line —
        # `docker restart a b` (multiple targets) or trailing flags are
        # refused too, since /restart-service's contract is "one named
        # container", not "whatever docker restart's argv happens to be".
        if target in RESTART_ALLOWLIST and " " not in target.strip():
            return 0
        print(
            f"Blocked: 'docker restart {target or '<unparsed>'}' against "
            "appstore-prod-01 is outside the /restart-service allowlist "
            f"({', '.join(sorted(RESTART_ALLOWLIST))}). Stateful data stores "
            "(postgres/rabbitmq/redis/etc.) and multi-target restarts are "
            "never permitted through this hook — use a direct human SSH "
            "session for those.",
            file=sys.stderr,
        )
        return 2

    if subcommand in BLOCKED_SUBCOMMANDS or subcommand not in ALLOWED_SUBCOMMANDS:
        print(
            f"Blocked: '{subcommand}' against appstore-prod-01 is outside the "
            f"HARNESS.md System 3.2 allowlist ({', '.join(sorted(ALLOWED_SUBCOMMANDS))}). "
            "This host runs production infrastructure — state-changing docker/podman "
            "commands need a human to run them directly, not through an automated tool call. "
            "The app runs on Kubernetes now; use the appstore MCP server for read-only inspection.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
