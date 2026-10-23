#!/usr/bin/env bash
# Promote staging to prod: opens a PR dev -> main. A human (or the required
# checks, with auto-merge) merges it; Argo CD's prod-root tracks main.
#
# Image digests do not need it: the component CIs roll their own `main` builds
# out on prod (k8s-bump.yml). This is for everything else in this repository
# (charts, policy, platform, realm files).
#
#   k8s/promote.sh
set -euo pipefail
REPO=DHBW-AppStore-T3/deployment
git fetch -q origin dev main
if [ -z "$(git rev-list origin/main..origin/dev)" ]; then echo "main already contains dev: nothing to promote"; exit 0; fi
SHA=$(git rev-parse --short origin/dev)
gh pr create --repo "$REPO" --base main --head dev \
  --title "Promote dev $SHA to prod" \
  --body "Brings dev ($SHA) to main: charts, policy and platform manifests. Merging rolls the change out on prod. The image digests of prod are written separately (k8s/images/prod.yaml, by the component CIs on main)."
