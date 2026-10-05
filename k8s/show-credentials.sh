#!/usr/bin/env bash
# Prints the login data of one environment from its cluster Secrets.
#   export KUBECONFIG=...; k8s/show-credentials.sh staging|prod
set -euo pipefail
cd "$(dirname "$0")"
ENV_NAME=${1:?usage: show-credentials.sh staging|prod}
NS=$(awk '/^  namespace:/{print $2}' "environments/$ENV_NAME.yaml")
HOST=$(awk '/^  host:/{print $2}' "environments/$ENV_NAME.yaml")
SSO=$(awk '/^  ssoHost:/{print $2}' "environments/$ENV_NAME.yaml")
get() { kubectl -n "$NS" get secret keycloak-secret -o "jsonpath={.data.$1}" | base64 -d; }
echo "UI:        https://$HOST"
echo "Keycloak:  https://$SSO/admin   user admin   password $(get admin-password)"
echo "Demo users (faculty@cs.example = Dozent, cs-student@cs.com = student,"
echo "            root.admin@uni.example = AppStore admin): password $(get demo-password)"
