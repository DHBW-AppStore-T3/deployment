#!/usr/bin/env bash
# Installs the gitleaks CLI (the upstream gitleaks-action needs a paid licence for
# organization repos, the binary is MIT). The one place that names the version:
# secret-scan.yml and k8s-bump.yml both call this script.
set -euo pipefail
GITLEAKS_VERSION=8.21.2
curl -sSfL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
  | sudo tar -xz -C /usr/local/bin gitleaks
gitleaks version
