#!/usr/bin/env bash
# Whether an image digest was built by the CI of its component, from the branch of
# the environment, at the commit of its tag. The component's CI signs that origin
# when it pushes the image (actions/attest: SLSA build provenance, signed keylessly
# with the GitHub identity of that very workflow run), so nothing but that workflow,
# run from that branch, can produce it.
#
#   verify-image.sh <component> <tag: sha-<hex>> <digest: sha256:<64 hex>> <branch: dev|main>
#
# Fails unless the attestation names the component's repository and workflow,
# refs/heads/<branch>, the full commit of the tag and a GitHub-hosted runner.
# Needs GH_TOKEN (reads the commit and the attestations) and a docker login to
# ghcr.io that may read the package: gh resolves the image there, and the packages
# are private (each grants this repository read access: package settings,
# "Manage Actions access").
set -euo pipefail

COMPONENT=$1 TAG=$2 DIGEST=$3 BRANCH=$4
ORG=DHBW-AppStore-T3   # exact spelling: gh compares repository and workflow case-sensitively

case "$COMPONENT" in
  backend)         REPO=backend         PACKAGE=backend         WORKFLOW=ci.yml ;;
  worker)          REPO=worker          PACKAGE=worker          WORKFLOW=ci.yml ;;
  worker-pods)     REPO=worker          PACKAGE=worker-pods     WORKFLOW=ci.yml ;;
  frontend)        REPO=frontend        PACKAGE=frontend        WORKFLOW=ci.yml ;;
  appstore-mcp)    REPO=appstore-mcp    PACKAGE=appstore-mcp    WORKFLOW=ci.yml ;;
  self-service-ui) REPO=self-service-ui PACKAGE=self-service-ui WORKFLOW=ci.yml ;;
  moodle)          REPO=moodle_appstore PACKAGE=moodle_appstore WORKFLOW=moodle-image.yml ;;
  *) echo "unknown component '$COMPONENT'" >&2; exit 1 ;;
esac
[[ "$TAG" =~ ^sha-([0-9a-f]{7,40})$ ]] || { echo "tag must be sha-<hex>, got '$TAG'" >&2; exit 1; }
SHORT=${BASH_REMATCH[1]}
[[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "digest must be sha256:<64 hex>, got '$DIGEST'" >&2; exit 1; }
[[ "$BRANCH" =~ ^(dev|main)$ ]] || { echo "branch must be dev or main, got '$BRANCH'" >&2; exit 1; }

# The tag carries the commit abbreviated, the attestation in full.
COMMIT=$(gh api "repos/$ORG/$REPO/commits/$SHORT" --jq .sha)

gh attestation verify "oci://ghcr.io/dhbw-appstore-t3/$PACKAGE@$DIGEST" \
  --repo "$ORG/$REPO" \
  --signer-workflow "$ORG/$REPO/.github/workflows/$WORKFLOW" \
  --source-ref "refs/heads/$BRANCH" \
  --source-digest "$COMMIT" \
  --deny-self-hosted-runners
echo "$COMPONENT $TAG ($DIGEST): built by $REPO/.github/workflows/$WORKFLOW from $BRANCH at $COMMIT"
