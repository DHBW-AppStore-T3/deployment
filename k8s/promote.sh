#!/usr/bin/env bash
# Promote staging to prod: opens a PR dev -> main. A human merges it once the
# release checklist in its description is complete (the check "PR Checklist"
# blocks the merge until every box is ticked); Argo CD's prod-root tracks main.
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
# The description is the release template of dev (.github/pull_request_template/release.md),
# unticked: the person promoting fills in the PR list and ticks what they checked.
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
git show origin/dev:.github/pull_request_template/release.md > "$BODY"
gh pr create --repo "$REPO" --base main --head dev \
  --title "Promote dev $SHA to prod" --body-file "$BODY"
