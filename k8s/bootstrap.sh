#!/usr/bin/env bash
# One-time setup of one AppStore environment on the k3s cluster.
# Creates the namespace and every Secret (nothing secret lives in git), then
# applies the environment's Argo CD root application, which syncs the rest from
# the environment's branch (staging: dev, prod: main).
#
#   export KUBECONFIG=/path/to/kubeconfig-ma_wwi_24sea_appstore_g3.yaml
#   [GHCR_PULL_TOKEN_FILE=/path/to/token] k8s/bootstrap.sh staging|prod
#
# Idempotent: existing Secrets and keys are left alone (rotating a Fernet key
# or a database password by accident would lock people out); a key that is
# missing in an existing Secret is added. The generated logins are printed
# once, when they are created. The exception is the image pull Secret
# ghcr-pull: given GHCR_PULL_TOKEN_FILE (a token with read:packages only), it
# is created or replaced, so an expired token can be swapped.
set -euo pipefail
cd "$(dirname "$0")"
ENV_NAME=${1:?usage: bootstrap.sh staging|prod}
case "$ENV_NAME" in staging|prod) ;; *) echo "unknown environment: $ENV_NAME" >&2; exit 2;; esac
NS=$(awk '/^  namespace:/{print $2}' "environments/$ENV_NAME.yaml")

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

rand() { python3 -c 'import secrets,sys;print(secrets.token_urlsafe(int(sys.argv[1])))' "${1:-24}"; }
# A Fernet key: 32 random bytes, url-safe base64.
fernet() { python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())'; }
have() { kubectl -n "$NS" get secret "$1" >/dev/null 2>&1; }
key() { kubectl -n "$NS" get secret "$1" -o "jsonpath={.data.$2}" | base64 -d; }
has_key() { [ -n "$(kubectl -n "$NS" get secret "$1" -o "jsonpath={.data.$2}" 2>/dev/null)" ]; }
# Add key $2 with value $3 to Secret $1 unless it has one already.
add_key() {
  has_key "$1" "$2" && return 0
  kubectl -n "$NS" patch secret "$1" --type merge \
    -p "$(python3 -c 'import json,sys;print(json.dumps({"stringData":{sys.argv[1]:sys.argv[2]}}))' "$2" "$3")" >/dev/null
}
# A login for a CloudNativePG managed role (kubernetes.io/basic-auth).
db_login() {
  have "$1" || kubectl -n "$NS" create secret generic "$1" --type=kubernetes.io/basic-auth \
    --from-literal=username="$2" --from-literal=password="$(rand)"
}
NEW=()

# --- Postgres roles (CNPG, k8s/manifests/platform/templates/postgres.yaml)
db_login keycloak-db keycloak
db_login appstore-t3-db appstore_t3
db_login appstore-worker-db appstore_worker
db_login moodle-db moodle

# --- Keycloak: admin, demo users (staging), clients
if ! have keycloak-secret; then
  ADMINPW=$(rand 18); DEMOPW=$(rand 12)
  kubectl -n "$NS" create secret generic keycloak-secret \
    --from-literal=admin-password="$ADMINPW" --from-literal=demo-password="$DEMOPW"
  NEW+=("Keycloak admin (kubectl -n $NS port-forward svc/keycloak 8080, then http://localhost:8080/admin/, user admin): $ADMINPW")
  [ "$ENV_NAME" = staging ] && NEW+=("Demo users of realm dhbw (dozent.demo, admin.demo, student1-4.demo): $DEMOPW")
fi
add_key keycloak-secret bff-client-secret "$(rand 32)"
add_key keycloak-secret appstore-backend-client-secret "$(rand 32)"

# --- Our AppStore (k8s/charts/appstore, secretName appstore-t3)
DB_HOST=postgres-cluster-rw:5432
if ! have appstore-t3; then
  kubectl -n "$NS" create secret generic appstore-t3 \
    --from-literal=database-url="postgresql://appstore_t3:$(key appstore-t3-db password)@$DB_HOST/appstore_t3?sslmode=require" \
    --from-literal=worker-database-url="postgresql://appstore_worker:$(key appstore-worker-db password)@$DB_HOST/appstore_t3?sslmode=require" \
    --from-literal=credential-encryption-key="$(fernet)" \
    --from-literal=results-encryption-key="$(fernet)" \
    --from-literal=keycloak-client-secret="$(key keycloak-secret appstore-backend-client-secret)" \
    --from-literal=lti13-session-secret="$(rand 48)"
fi
# Task results have a key of their own (the pod deployer gets no other).
add_key appstore-t3 results-encryption-key "$(fernet)"
# The self-service-ui's oauth2-proxy: 32 characters = a 32-byte cookie secret.
add_key appstore-t3 self-service-cookie-secret "$(rand 24)"

# --- appstore-mcp (k8s/charts/appstore-mcp, secretName appstore-mcp). Only the token
# signing key is generated here; the GitHub OAuth app credentials (and an optional
# read-only GitHub PAT) are created by a human, see appstore-mcp docs/OPERATIONS.md:
#   kubectl -n <ns> patch secret appstore-mcp --type merge -p '{"stringData":{"github-client-id":"<ID>","github-client-secret":"<SECRET>"}}'
# Empty placeholders keep the keys visible; an existing Secret is never touched
# (a missing signing key is added).
if ! have appstore-mcp; then
  kubectl -n "$NS" create secret generic appstore-mcp \
    --from-literal=token-signing-key="$(fernet)" \
    --from-literal=static-tokens="" \
    --from-literal=github-client-id="" \
    --from-literal=github-client-secret="" \
    --from-literal=github-api-token="" >/dev/null
  echo "Secret appstore-mcp created: still needs github-client-id and github-client-secret (appstore-mcp docs/OPERATIONS.md)"
fi
add_key appstore-mcp token-signing-key "$(fernet)"

# --- Moodle (k8s/charts/moodle): the admin login of the first install. The
# database login is moodle-db above. Changing this Secret later changes
# nothing in Moodle (change the password there).
if ! have moodle-admin; then
  MOODLEPW=$(rand 18)
  kubectl -n "$NS" create secret generic moodle-admin --from-literal=password="$MOODLEPW"
  NEW+=("Moodle admin (user admin, https://$(awk '/^moodle:/{f=1} f&&/^  host:/{print $2; exit}' "environments/$ENV_NAME.yaml")): $MOODLEPW")
fi

# Password of Moodle's demo users (moodle.setup.demoUsers; created by the chart's
# `configure` init container). Staging: the same as the Keycloak demo users.
if ! have moodle-demo; then
  if [ "$ENV_NAME" = staging ]; then DEMOPW=$(key keycloak-secret demo-password); else DEMOPW=$(rand 12); fi
  kubectl -n "$NS" create secret generic moodle-demo --from-literal=password="$DEMOPW"
  [ "$ENV_NAME" = staging ] || NEW+=("Moodle demo users (dozent, student1, student2): $DEMOPW")
fi

# --- Pulling our private images (images.pullSecrets in environments/*.yaml).
# The token goes from the file to kubectl's stdin, never into an argument.
if [ -n "${GHCR_PULL_TOKEN_FILE:-}" ]; then
  python3 - "$GHCR_PULL_TOKEN_FILE" "$NS" <<'PY' | kubectl apply -f - >/dev/null
import base64, json, sys
token = open(sys.argv[1], encoding="utf-8").read().strip()
auth = base64.b64encode(f"x:{token}".encode()).decode()
config = json.dumps({"auths": {"ghcr.io": {"auth": auth}}})
print(json.dumps({"apiVersion": "v1", "kind": "Secret", "type": "kubernetes.io/dockerconfigjson",
                  "metadata": {"name": "ghcr-pull", "namespace": sys.argv[2]},
                  "data": {".dockerconfigjson": base64.b64encode(config.encode()).decode()}}))
PY
  echo "image pull Secret ghcr-pull written"
elif ! have ghcr-pull; then
  echo "WARNING: no Secret ghcr-pull; our images cannot be pulled. Run again with GHCR_PULL_TOKEN_FILE." >&2
fi

# The CloudNativePG operator is cluster-wide (shared by both environments).
kubectl apply -f argocd/cluster/cnpg.yaml
kubectl apply -f "argocd/roots/$ENV_NAME.yaml"

if ((${#NEW[@]})); then
  echo; echo "== Generated credentials - store them in a password manager, they are not shown again =="
  printf '%s\n' "${NEW[@]}"
fi
echo "Environment $ENV_NAME (namespace $NS). Watch: kubectl -n argocd get applications | grep $ENV_NAME"
