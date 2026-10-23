#!/usr/bin/env bash
# Creates (or updates) the Keycloak client `appstore-self-service` in the LIVE
# realm dhbw of one environment. Keycloak imports a realm file only into a new
# database and never changes an existing realm, so for a running environment the
# client from k8s/manifests/platform/files/dhbw-realm.json has to be created
# through the admin REST API once. The definition is taken from the rendered
# realm (ConfigMap keycloak-realm), so there is one source of truth.
#
#   export KUBECONFIG=/path/to/kubeconfig-ma_wwi_24sea_appstore_g3.yaml
#   k8s/keycloak-self-service-client.sh staging|prod
#
# Needs kubectl, curl, python3. The admin password is read from the Secret
# keycloak-secret into a shell variable and sent to Keycloak only; it is never
# printed. Idempotent. The ConfigMap only has the client once the environment's
# platform application has synced the change.
set -euo pipefail
cd "$(dirname "$0")"
ENV_NAME=${1:?usage: keycloak-self-service-client.sh staging|prod}
case "$ENV_NAME" in staging|prod) ;; *) echo "unknown environment: $ENV_NAME" >&2; exit 2;; esac
NS=$(awk '/^  namespace:/{print $2}' "environments/$ENV_NAME.yaml")
REALM=dhbw CLIENT=appstore-self-service PORT=8080   # the admin hostname of the master realm is http://localhost:8080

CLIENT_JSON=$(kubectl -n "$NS" get configmap keycloak-realm -o 'jsonpath={.data.dhbw-realm\.json}' |
  python3 -c 'import json,sys; r=json.load(sys.stdin); c=[c for c in r["clients"] if c["clientId"]==sys.argv[1]]; sys.exit("client missing in the rendered realm: sync the platform app first") if not c else print(json.dumps(c[0]))' "$CLIENT")

kubectl -n "$NS" port-forward svc/keycloak "$PORT:8080" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  curl -fsS -o /dev/null "http://localhost:$PORT/realms/master" 2>/dev/null && break
  [ "$i" = 30 ] && { echo "Keycloak not reachable on localhost:$PORT (port in use?)" >&2; exit 1; }
  sleep 1
done

ADMIN_PW=$(kubectl -n "$NS" get secret keycloak-secret -o 'jsonpath={.data.admin-password}' | base64 -d)
# The password goes over stdin of curl (--data-urlencode @-), not into argv.
TOKEN=$(printf 'password=%s' "$ADMIN_PW" | curl -fsS "http://localhost:$PORT/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password -d username=admin --data-urlencode @- |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
unset ADMIN_PW

api() { curl -fsS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$@"; }
BASE="http://localhost:$PORT/admin/realms/$REALM/clients"
ID=$(api "$BASE?clientId=$CLIENT" | python3 -c 'import json,sys; l=json.load(sys.stdin); print(l[0]["id"] if l else "")')
if [ -z "$ID" ]; then
  api -X POST "$BASE" -d "$CLIENT_JSON" >/dev/null
  echo "created client $CLIENT in realm $REALM ($ENV_NAME)"
else
  api -X PUT "$BASE/$ID" -d "$CLIENT_JSON" >/dev/null
  echo "updated client $CLIENT in realm $REALM ($ENV_NAME)"
fi
