# manusa/podman-mcp-server ships no container image — only an npm/PyPI
# wrapper and raw GitHub release binaries (verified against the repo's
# .github/workflows/: build.yaml has no docker/build-push step,
# release.yaml only publishes to npm). This Dockerfile packages the
# official linux-amd64 release binary directly instead.
FROM debian:bookworm-slim

ARG PODMAN_MCP_VERSION=v0.0.15

# curl is kept (not purged after the download below) — the compose
# healthcheck for this service needs it, since the image otherwise
# ships neither wget nor nc.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl docker.io \
    && curl -fsSL -o /usr/local/bin/podman-mcp-server \
       "https://github.com/manusa/podman-mcp-server/releases/download/${PODMAN_MCP_VERSION}/podman-mcp-server-linux-amd64" \
    && chmod +x /usr/local/bin/podman-mcp-server \
    && rm -rf /var/lib/apt/lists/*

# podman-mcp-server's "cli" backend (pkg/podman/podman_cli.go) only
# ever looks for a binary literally named "podman"/"podman.exe" —
# despite AGENTS.md describing it as "available when podman or docker
# binary is in PATH", the actual findBinary() check never tries
# "docker". Its "api" backend also doesn't help against a Docker
# socket: it speaks the Podman REST API (pkg/bindings), which isn't
# wire-compatible with the Docker Engine API CONTAINER_HOST points it
# at. Caught when the container panicked at startup with "no podman
# implementation available: api (not available), cli (not available)".
#
# Fix: alias `podman` to the real `docker` CLI. The three subcommands
# this server actually calls (inspect <name>, container list -a
# [--format json], logs <name>) have identical syntax in both CLIs, so
# the alias is safe for exactly the tool surface agent/config.yaml
# allowlists (container_list/inspect/logs) — this was not extended to
# cover container_run/stop/remove or any image/network/volume
# subcommand, which may not translate as cleanly.
RUN ln -s /usr/bin/docker /usr/local/bin/podman

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/podman-mcp-server"]
