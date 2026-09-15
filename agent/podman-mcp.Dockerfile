# manusa/podman-mcp-server ships no container image — only an npm/PyPI
# wrapper and raw GitHub release binaries (verified against the repo's
# .github/workflows/: build.yaml has no docker/build-push step,
# release.yaml only publishes to npm). This Dockerfile packages the
# official linux-amd64 release binary directly instead.
FROM debian:bookworm-slim

ARG PODMAN_MCP_VERSION=v0.0.15

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL -o /usr/local/bin/podman-mcp-server \
       "https://github.com/manusa/podman-mcp-server/releases/download/${PODMAN_MCP_VERSION}/podman-mcp-server-linux-amd64" \
    && chmod +x /usr/local/bin/podman-mcp-server \
    && apt-get purge -y curl \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/podman-mcp-server"]
