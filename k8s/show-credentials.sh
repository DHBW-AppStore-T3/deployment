#!/usr/bin/env bash
# Prints the login data of one environment from its cluster Secrets.
#   export KUBECONFIG=...; k8s/show-credentials.sh staging|prod
set -euo pipefail
cd "$(dirname "$0")"
ENV_NAME=${1:?usage: show-credentials.sh staging|prod}
NS=$(awk '/^  namespace:/{print $2}' "environments/$ENV_NAME.yaml")
HOST=$(awk '/^  host:/{print $2; exit}' "environments/$ENV_NAME.yaml")
get() { kubectl -n "$NS" get secret keycloak-secret -o "jsonpath={.data.$1}" | base64 -d; }
echo "AppStore:  https://$HOST"
echo "Keycloak admin console (not on the public host):"
echo "           kubectl -n $NS port-forward svc/keycloak 8080, then http://localhost:8080/admin/"
echo "           user admin, password $(get admin-password)"
if [ "$ENV_NAME" = staging ]; then
  echo "Demo users of realm dhbw (dozent.demo = teacher, admin.demo = admin,"
  echo "            student1.demo ... student4.demo): password $(get demo-password)"
fi
MOODLE_HOST=$(awk '/^moodle:/{f=1} f&&/^  host:/{print $2; exit}' "environments/$ENV_NAME.yaml")
echo "Moodle:    https://$MOODLE_HOST"
echo "           user admin, password $(kubectl -n "$NS" get secret moodle-admin -o jsonpath='{.data.password}' | base64 -d)"
echo "           demo users (see moodle.setup.demoUsers): password $(kubectl -n "$NS" get secret moodle-demo -o jsonpath='{.data.password}' 2>/dev/null | base64 -d)"
