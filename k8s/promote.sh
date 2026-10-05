#!/usr/bin/env bash
# Promote staging to prod: opens a PR into spike/main that changes ONLY the k8s/
# tree (the manifests and the image tags built on spike/dev). A human merges it;
# production then runs exactly the images that were tested on staging.
#
# Why not merge spike/dev into spike/main: the two branches also differ outside
# k8s/ on purpose (main carries reverts that dev does not), and a merge would
# drag those along.
#
#   k8s/promote.sh
set -euo pipefail
REPO=DHBW-AppStore-T3/deployment
git fetch -q origin spike/dev spike/main
SHA=$(git rev-parse --short origin/spike/dev)
BR="promote/staging-$SHA"
WT=$(mktemp -d)
trap 'git worktree remove --force "$WT" 2>/dev/null || true' EXIT
git worktree add -q -b "$BR" "$WT" origin/spike/main
cd "$WT"
git rm -rq k8s
git checkout -q origin/spike/dev -- k8s
if git diff --cached --quiet; then echo "prod already matches staging ($SHA): nothing to promote"; exit 0; fi
git commit -q -m "chore(k8s): promote staging $SHA to prod"
git push -q origin "$BR"
gh pr create --repo "$REPO" --base spike/main --head "$BR" \
  --title "Promote staging $SHA to prod (k8s/)" \
  --body "Brings the k8s/ tree of spike/dev ($SHA) to spike/main: manifests and the tested image tags. Nothing outside k8s/ changes. Merge to roll prod out."
