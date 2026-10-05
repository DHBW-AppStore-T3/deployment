#!/usr/bin/env bash
# One-time setup of one AppStore environment on the k3s cluster.
# Creates the namespace and every Secret (nothing secret lives in git), then
# applies the environment's Argo CD root application, which syncs the rest from
# the environment's branch (staging: spike/dev, prod: spike/main).
#
#   export KUBECONFIG=/path/to/kubeconfig-ma_wwi_24sea_appstore_g3.yaml
#   k8s/bootstrap.sh staging|prod
#
# Idempotent: existing Secrets are left alone (rotating a Fernet key or the
# cookie secret by accident would lock people out), so re-running is safe.
# The generated values are printed once at the end of the FIRST run only.
set -euo pipefail
cd "$(dirname "$0")"
ENV_NAME=${1:?usage: bootstrap.sh staging|prod}
case "$ENV_NAME" in staging|prod) ;; *) echo "unknown environment: $ENV_NAME" >&2; exit 2;; esac
NS=$(awk '/^  namespace:/{print $2}' "environments/$ENV_NAME.yaml")

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

rand() { python3 -c 'import secrets,sys;print(secrets.token_urlsafe(int(sys.argv[1])))' "${1:-24}"; }
have() { kubectl -n "$NS" get secret "$1" >/dev/null 2>&1; }
NEW=()

if ! have appstore-db; then
  kubectl -n "$NS" create secret generic appstore-db --type=kubernetes.io/basic-auth \
    --from-literal=username=appstore --from-literal=password="$(rand)"
fi
if ! have keycloak-db; then
  kubectl -n "$NS" create secret generic keycloak-db --type=kubernetes.io/basic-auth \
    --from-literal=username=keycloak --from-literal=password="$(rand)"
fi

if ! have role-provider-db; then
  kubectl -n "$NS" create secret generic role-provider-db --type=kubernetes.io/basic-auth \
    --from-literal=username=roleprovider --from-literal=password="$(rand)"
fi

# Needs the Fernet key of the cryptography package; falls back to the same format by hand.
fernet() { python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())'; }
if ! have appstore-secret; then
  DBPW=$(kubectl -n "$NS" get secret appstore-db -o jsonpath='{.data.password}' | base64 -d)
  RPTOKEN=$(rand 32)
  kubectl -n "$NS" create secret generic appstore-secret \
    --from-literal=database-url="postgresql://appstore:${DBPW}@postgres-cluster-rw:5432/appstore" \
    --from-literal=credential-encryption-key="$(fernet)" \
    --from-literal=role-provider-api-token="$RPTOKEN" \
    --from-literal=smtp-password=''
fi

# read token is shared with appstore-api (appstore-secret), write token is for the seed Job
if ! have role-provider-secret; then
  RPPW=$(kubectl -n "$NS" get secret role-provider-db -o jsonpath='{.data.password}' | base64 -d)
  RPREAD=$(kubectl -n "$NS" get secret appstore-secret -o jsonpath='{.data.role-provider-api-token}' | base64 -d)
  kubectl -n "$NS" create secret generic role-provider-secret \
    --from-literal=db-connection-string="host=postgres-cluster-rw user=roleprovider password=${RPPW} dbname=roleprovider port=5432 sslmode=disable TimeZone=UTC" \
    --from-literal=api-tokens="$RPREAD" --from-literal=api-write-tokens="$(rand 32)"
fi

if ! have keycloak-secret; then
  BFF=$(rand 32)
  ADMINPW=$(rand 18); DEMOPW=$(rand 12)
  kubectl -n "$NS" create secret generic keycloak-secret \
    --from-literal=admin-password="$ADMINPW" --from-literal=demo-password="$DEMOPW" \
    --from-literal=bff-client-secret="$BFF"
  kubectl -n "$NS" create secret generic oauth2-proxy-ui-secret \
    --from-literal=client-id=appstore --from-literal=client-secret="$BFF" \
    --from-literal=cookie-secret="$(python3 -c 'import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  NEW+=("Keycloak admin (https://<sso host>/admin, user admin): $ADMINPW"
        "Demo users (faculty@cs.example, cs-student@cs.com, root.admin@uni.example): $DEMOPW")
fi

kubectl apply -f "argocd/roots/$ENV_NAME.yaml"

if ((${#NEW[@]})); then
  echo; echo "== Generated credentials - store them in a password manager, they are not shown again =="
  printf '%s\n' "${NEW[@]}"
fi
echo "Environment $ENV_NAME (namespace $NS). Watch: kubectl -n argocd get applications | grep $ENV_NAME"
