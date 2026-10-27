#!/usr/bin/env bash
# Deploy the full DHBW AppStore + Moodle stack into the local k3d cluster
# (`k3d-appstore-local`, namespace `appstore-local`) using the production
# Helm charts (`k8s/argocd/cluster/cnpg.yaml`, `k8s/manifests/platform`,
# `k8s/charts/appstore`, `k8s/charts/moodle`).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(cd "$HERE/.." && pwd)"
DEPLOY_DIR="$(cd "$K8S_DIR/.." && pwd)"
ROOT_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"

CLUSTER_NAME="${K3D_CLUSTER_NAME:-appstore-local}"
KUBE_CONTEXT="k3d-${CLUSTER_NAME}"
NS="${LOCAL_K8S_NAMESPACE:-appstore-local}"
DEMO_PASSWORD="${DEV_DEMO_PASSWORD:-DevLocal1234!}"
SKIP_BUILD="${SKIP_BUILD:-0}"
BUILD_ONLY="${BUILD_ONLY:-0}"

CERT_DIR="${HERE}/.certs"

ensure_local_certs() {
  mkdir -p "${CERT_DIR}"
  if [ ! -f "${CERT_DIR}/local-ca.crt" ] || [ ! -f "${CERT_DIR}/local-ca.key" ]; then
    echo "==> Generating local Root CA..."
    cat > "${CERT_DIR}/ca.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no
[req_distinguished_name]
CN = DHBW AppStore Local Dev CA
O = DHBW
[v3_ca]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
EOF
    openssl req -x509 -new -nodes -newkey rsa:2048 \
      -keyout "${CERT_DIR}/local-ca.key" -sha256 -days 3650 \
      -out "${CERT_DIR}/local-ca.crt" -config "${CERT_DIR}/ca.cnf" >/dev/null 2>&1
  fi

  if [ ! -f "${CERT_DIR}/tls.crt" ] || ! openssl x509 -noout -text -in "${CERT_DIR}/tls.crt" 2>/dev/null | grep -q "DNS:\*.apps.localhost"; then
    echo "==> Generating *.localhost TLS certificate with explicit SANs..."
    cat > "${CERT_DIR}/ext.cnf" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
DNS.2 = appstore.localhost
DNS.3 = sso.localhost
DNS.4 = self-service.localhost
DNS.5 = moodle.localhost
DNS.6 = *.localhost
DNS.7 = *.apps.localhost
IP.1 = 127.0.0.1
IP.2 = ::1
EOF
    openssl req -new -nodes -newkey rsa:2048 -keyout "${CERT_DIR}/tls.key" \
      -out "${CERT_DIR}/tls.csr" -subj "/CN=appstore.localhost/O=DHBW AppStore Local" >/dev/null 2>&1
    openssl x509 -req -in "${CERT_DIR}/tls.csr" -CA "${CERT_DIR}/local-ca.crt" -CAkey "${CERT_DIR}/local-ca.key" \
      -CAcreateserial -out "${CERT_DIR}/tls.crt" -days 825 -sha256 -extfile "${CERT_DIR}/ext.cnf" >/dev/null 2>&1
  fi
}

trust_local_ca() {
  if [ "${SKIP_TRUST_CERT:-0}" = "1" ]; then
    return 0
  fi
  local ca_crt="${CERT_DIR}/local-ca.crt"
  local ca_sha1
  ca_sha1="$(openssl x509 -noout -fingerprint -sha1 -in "${ca_crt}" 2>/dev/null | sed 's/.*=//;s/://g')"

  if [ "$(uname -s)" = "Darwin" ] && command -v security >/dev/null 2>&1; then
    local keychain="$HOME/Library/Keychains/login.keychain-db"
    if ! security find-certificate -a -Z -c "DHBW AppStore Local Dev CA" "${keychain}" 2>/dev/null | grep -qi "${ca_sha1:-__none__}"; then
      echo "==> Registering local *.localhost Root CA in macOS Keychain..."
      security add-trusted-cert -r trustRoot -k "${keychain}" "${ca_crt}" || true
    fi
  elif command -v certutil.exe >/dev/null 2>&1; then
    local win_cert_path="${ca_crt}"
    if command -v wslpath >/dev/null 2>&1; then
      win_cert_path="$(wslpath -w "${ca_crt}")"
    elif command -v cygpath >/dev/null 2>&1; then
      win_cert_path="$(cygpath -w "${ca_crt}")"
    fi
    if ! certutil.exe -user -verifystore Root "DHBW AppStore Local Dev CA" 2>/dev/null | grep -qi "${ca_sha1:-__none__}"; then
      echo "==> Registering local *.localhost Root CA in Windows Certificate Store..."
      certutil.exe -user -addstore Root "${win_cert_path}" >/dev/null || true
    fi
  elif [ -d /usr/local/share/ca-certificates ] && command -v update-ca-certificates >/dev/null 2>&1; then
    local target="/usr/local/share/ca-certificates/dhbw-appstore-local-ca.crt"
    if ! cmp -s "${ca_crt}" "${target}" 2>/dev/null; then
      echo "==> Registering local *.localhost Root CA in Linux system CA store..."
      (sudo cp "${ca_crt}" "${target}" && sudo update-ca-certificates >/dev/null) || true
    fi
  fi
}

for cmd in docker k3d kubectl helm openssl python3 git; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Required command '$cmd' not found in PATH." >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Cannot connect to the Docker daemon. Please start Docker first." >&2
  exit 1
fi

for repo in backend worker frontend self-service-ui moodle_appstore; do
  if [ ! -d "${ROOT_DIR}/${repo}" ]; then
    echo "ERROR: Sibling repository '${ROOT_DIR}/${repo}' not found. See docs/dev-setup.md for git clone instructions." >&2
    exit 1
  fi
done

# 1. Ensure k3d cluster exists and is running with ports 80/443 exposed
if ! k3d cluster list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "${CLUSTER_NAME}"; then
  echo "==> Creating k3d cluster '${CLUSTER_NAME}' (ports 80 & 443 -> Traefik)..."
  k3d cluster create "${CLUSTER_NAME}" --wait \
    -p "80:80@loadbalancer" \
    -p "443:443@loadbalancer"
else
  k3d cluster start "${CLUSTER_NAME}" >/dev/null 2>&1 || true
fi

KUBE="kubectl --context ${KUBE_CONTEXT}"

# Determine node architecture inside k3d so docker builds matching images across all architectures (arm64 / amd64)
NODE_ARCH="$(docker exec "k3d-${CLUSTER_NAME}-server-0" uname -m 2>/dev/null || uname -m)"
case "${NODE_ARCH}" in
  aarch64|arm64) TARGET_PLATFORM="linux/arm64" ;;
  x86_64|amd64)  TARGET_PLATFORM="linux/amd64" ;;
  *)             TARGET_PLATFORM="linux/${NODE_ARCH}" ;;
esac

# 2. Build and import local images into k3d containerd (pinned against kubelet GC)
import_image() {
  local tag="$1"
  echo "    -> Importing & pinning ${tag} (${TARGET_PLATFORM}) in ${KUBE_CONTEXT}..."
  docker save "${tag}" | docker exec -i "k3d-${CLUSTER_NAME}-server-0" ctr -n k8s.io images import - >/dev/null
  docker exec "k3d-${CLUSTER_NAME}-server-0" ctr -n k8s.io images label "${tag}" io.cri-containerd.pinned=pinned >/dev/null
}

ensure_cluster_image() {
  local tag="$1"
  if ! docker exec "k3d-${CLUSTER_NAME}-server-0" ctr -n k8s.io images ls -q | grep -qx "${tag}"; then
    import_image "${tag}"
  fi
}

build_with_progress() {
  local step="$1"
  local label="$2"
  shift 2
  echo "==> [${step}] Building ${label} (${TARGET_PLATFORM})..."
  local start_ts
  start_ts="$(date +%s)"
  (
    while sleep 5; do
      local elapsed=$(( $(date +%s) - start_ts ))
      printf "    ⏳ [%s] %s running (%02dm:%02ds elapsed)...\n" "${step}" "${label}" $((elapsed / 60)) $((elapsed % 60))
    done
  ) &
  local timer_pid=$!
  local rc=0
  "$@" || rc=$?
  kill "${timer_pid}" 2>/dev/null || true
  wait "${timer_pid}" 2>/dev/null || true
  if [ "${rc}" -ne 0 ]; then
    return "${rc}"
  fi
  local total=$(( $(date +%s) - start_ts ))
  printf "    ✓ [%s] %s built in %02dm:%02ds\n" "${step}" "${label}" $((total / 60)) $((total % 60))
}

if [ "${SKIP_BUILD}" != "1" ]; then
  echo "==> Building local images from sibling repositories for ${TARGET_PLATFORM}..."
  build_with_progress "1/5" "backend" \
    docker build --platform "${TARGET_PLATFORM}" -t ghcr.io/dhbw-appstore-t3/backend:dev "${ROOT_DIR}/backend"
  import_image ghcr.io/dhbw-appstore-t3/backend:dev

  build_with_progress "2/5" "worker-pods" \
    docker build --platform "${TARGET_PLATFORM}" --target pod-deployer -t ghcr.io/dhbw-appstore-t3/worker-pods:dev "${ROOT_DIR}/worker"
  import_image ghcr.io/dhbw-appstore-t3/worker-pods:dev

  build_with_progress "3/5" "frontend" \
    docker build --platform "${TARGET_PLATFORM}" -t ghcr.io/dhbw-appstore-t3/frontend:dev "${ROOT_DIR}/frontend"
  import_image ghcr.io/dhbw-appstore-t3/frontend:dev

  build_with_progress "4/5" "self-service-ui" \
    docker build --platform "${TARGET_PLATFORM}" -t ghcr.io/dhbw-appstore-t3/self-service-ui:dev "${ROOT_DIR}/self-service-ui"
  import_image ghcr.io/dhbw-appstore-t3/self-service-ui:dev

  MOODLE_STATE_HASH="$({ git -C "${ROOT_DIR}/moodle_appstore" rev-parse HEAD 2>/dev/null; git -C "${ROOT_DIR}/moodle_appstore" status --porcelain 2>/dev/null; git -C "${ROOT_DIR}/moodle_appstore" diff HEAD 2>/dev/null; } | openssl dgst -sha256 | awk '{print $NF}')"
  CURRENT_MOODLE_HASH="$(docker image inspect -f '{{ index .Config.Labels "appstore.local.tree-hash" }}' ghcr.io/dhbw-appstore-t3/moodle_appstore:dev 2>/dev/null || true)"

  if [ "${REBUILD_MOODLE:-0}" = "1" ] || [ "${MOODLE_STATE_HASH}" != "${CURRENT_MOODLE_HASH}" ]; then
    build_with_progress "5/5" "moodle_appstore (first build may take several minutes)" \
      docker build --platform "${TARGET_PLATFORM}" --label "appstore.local.tree-hash=${MOODLE_STATE_HASH}" -t ghcr.io/dhbw-appstore-t3/moodle_appstore:dev "${ROOT_DIR}/moodle_appstore"
    import_image ghcr.io/dhbw-appstore-t3/moodle_appstore:dev
  else
    echo "==> [5/5] Reusing cached ghcr.io/dhbw-appstore-t3/moodle_appstore:dev (no changes in moodle_appstore)"
    ensure_cluster_image ghcr.io/dhbw-appstore-t3/moodle_appstore:dev
  fi
else
  echo "==> Skipping image build (SKIP_BUILD=1); ensuring cached images are in k3d..."
  for img in \
    ghcr.io/dhbw-appstore-t3/backend:dev \
    ghcr.io/dhbw-appstore-t3/worker-pods:dev \
    ghcr.io/dhbw-appstore-t3/frontend:dev \
    ghcr.io/dhbw-appstore-t3/self-service-ui:dev \
    ghcr.io/dhbw-appstore-t3/moodle_appstore:dev; do
    ensure_cluster_image "$img"
  done
fi

if [ "${BUILD_ONLY}" = "1" ]; then
  echo "==> Local images built and imported into ${KUBE_CONTEXT}."
  exit 0
fi

# 3. Configure Traefik default certificate for *.localhost + Namespace & Secrets
ensure_local_certs
trust_local_ca

$KUBE -n kube-system create secret tls local-wildcard-tls \
  --cert="${CERT_DIR}/tls.crt" --key="${CERT_DIR}/tls.key" --dry-run=client -o yaml | $KUBE apply -f - >/dev/null
$KUBE apply -f - >/dev/null <<EOF
apiVersion: traefik.io/v1alpha1
kind: TLSStore
metadata:
  name: default
  namespace: kube-system
spec:
  defaultCertificate:
    secretName: local-wildcard-tls
EOF

echo "==> Ensuring namespace '${NS}' and Secrets..."
for ns in "${NS}" vm-poc; do
  $KUBE create namespace "${ns}" --dry-run=client -o yaml | $KUBE apply -f - >/dev/null
done

rand_hex()    { openssl rand -hex "$1"; }
rand_urlsafe(){ python3 -c "import secrets; print(secrets.token_urlsafe($1), end='')"; }
fernet_key()  { python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode(), end="")'; }

ensure_basic_auth() {
  local name="$1" user="$2"
  local stype
  stype="$($KUBE -n "${NS}" get secret "$name" -o jsonpath='{.type}' 2>/dev/null || true)"
  if [ "${stype}" = "kubernetes.io/basic-auth" ]; then
    return 0
  fi
  local pw
  if [ -n "${stype}" ]; then
    pw="$($KUBE -n "${NS}" get secret "$name" -o jsonpath='{.data.password}' | base64 -d)"
    $KUBE -n "${NS}" delete secret "$name" >/dev/null
  else
    pw="$(rand_hex 24)"
  fi
  $KUBE -n "${NS}" create secret generic "$name" \
    --type=kubernetes.io/basic-auth \
    --from-literal=username="$user" \
    --from-literal=password="$pw" >/dev/null
  echo "    created Secret/${name} (basic-auth)"
}

ensure_secret() {
  local name="$1"; shift
  if $KUBE -n "${NS}" get secret "$name" >/dev/null 2>&1; then
    return 0
  fi
  $KUBE -n "${NS}" create secret generic "$name" "$@" >/dev/null
  echo "    created Secret/${name}"
}

ensure_basic_auth keycloak-db keycloak
ensure_basic_auth appstore-t3-db appstore_t3
ensure_basic_auth appstore-worker-db appstore_worker
ensure_basic_auth moodle-db moodle

key_of() {
  $KUBE -n "${NS}" get secret "$1" -o "jsonpath={.data.$2}" | base64 -d
}

ensure_secret keycloak-secret \
  --from-literal=admin-user=admin \
  --from-literal=admin-password="${DEMO_PASSWORD}" \
  --from-literal=demo-password="${DEMO_PASSWORD}" \
  --from-literal=bff-client-secret="$(rand_urlsafe 32)" \
  --from-literal=appstore-backend-client-secret="$(rand_urlsafe 32)"

DB_HOST="postgres-cluster-rw:5432"
ensure_secret appstore-t3 \
  --from-literal=database-url="postgresql://appstore_t3:$(key_of appstore-t3-db password)@${DB_HOST}/appstore_t3?sslmode=require" \
  --from-literal=worker-database-url="postgresql://appstore_worker:$(key_of appstore-worker-db password)@${DB_HOST}/appstore_t3?sslmode=require" \
  --from-literal=credential-encryption-key="$(fernet_key)" \
  --from-literal=results-encryption-key="$(fernet_key)" \
  --from-literal=keycloak-client-secret="$(key_of keycloak-secret appstore-backend-client-secret)" \
  --from-literal=lti13-session-secret="$(rand_urlsafe 48)" \
  --from-literal=self-service-cookie-secret="$(rand_urlsafe 24)"

ensure_secret moodle-admin \
  --from-literal=username=admin \
  --from-literal=password="${DEMO_PASSWORD}"

ensure_secret moodle-demo \
  --from-literal=password="${DEMO_PASSWORD}"

# 4. CloudNativePG operator (same version as k8s/argocd/cluster/cnpg.yaml) + PostgreSQL cluster
CNPG_VERSION="$(awk '/targetRevision:/ {print $2}' "${K8S_DIR}/argocd/cluster/cnpg.yaml")"
if ! helm --kube-context "${KUBE_CONTEXT}" -n cnpg-system status cnpg >/dev/null 2>&1; then
  echo "==> Installing CloudNativePG operator (v${CNPG_VERSION})..."
  helm --kube-context "${KUBE_CONTEXT}" upgrade --install cnpg cloudnative-pg \
    --repo https://cloudnative-pg.github.io/charts \
    --version "${CNPG_VERSION}" \
    -n cnpg-system --create-namespace --wait --timeout 5m >/dev/null
fi

echo "==> Deploying PostgreSQL via CloudNativePG (k8s/manifests/platform)..."
helm template platform "${K8S_DIR}/manifests/platform" -n "${NS}" \
  --show-only templates/postgres.yaml \
  | $KUBE -n "${NS}" apply -f - >/dev/null
$KUBE -n "${NS}" wait --for=condition=Ready cluster.postgresql.cnpg.io/postgres-cluster --timeout=180s >/dev/null
for db in keycloak appstore-t3 moodle; do
  $KUBE -n "${NS}" wait --for=jsonpath='{.status.applied}'=true "database.postgresql.cnpg.io/${db}" --timeout=60s >/dev/null
done

# 5. Platform (Keycloak + dhbw realm + demo users)
echo "==> Deploying Keycloak (k8s/manifests/platform)..."
$KUBE -n "${NS}" delete job keycloak-config keycloak-admin-url --ignore-not-found >/dev/null
PLATFORM_VALUES="$(cat <<EOF
appHost: appstore.localhost
selfServiceHost: self-service.localhost
ssoHost: sso.localhost
demoUsers: true
publicAdmin: true
EOF
)"
printf '%s\n' "${PLATFORM_VALUES}" | helm template platform "${K8S_DIR}/manifests/platform" -n "${NS}" \
  --show-only templates/keycloak-realm.yaml \
  --show-only templates/keycloak-theme.yaml \
  --show-only templates/keycloak.yaml \
  -f - | $KUBE -n "${NS}" apply --server-side --force-conflicts -f - >/dev/null
$KUBE -n "${NS}" rollout status deployment/keycloak --timeout=300s

printf '%s\n' "${PLATFORM_VALUES}" | helm template platform "${K8S_DIR}/manifests/platform" -n "${NS}" \
  --show-only templates/keycloak-config.yaml \
  -f - | $KUBE -n "${NS}" apply -f - >/dev/null
$KUBE -n "${NS}" wait --for=condition=complete job/keycloak-config --timeout=180s

# Recover if a previous helm command was interrupted in pending-* state
recover_helm_release() {
  local rel="$1"
  local status
  status="$(helm --kube-context "${KUBE_CONTEXT}" -n "${NS}" status "${rel}" -o json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("info",{}).get("status",""))' 2>/dev/null || true)"
  case "${status}" in
    pending-*|failed)
      echo "    cleaning up interrupted Helm release '${rel}' (${status})..."
      helm --kube-context "${KUBE_CONTEXT}" -n "${NS}" uninstall "${rel}" --no-hooks >/dev/null 2>&1 || true
      ;;
  esac
}

# 6. AppStore (API, Pod-Deployer, Frontend, Self-Service-UI, Migrate, Seed, RBAC, AdmissionPolicy)
echo "==> Deploying AppStore Helm chart (k8s/charts/appstore)..."
recover_helm_release appstore
$KUBE -n "${NS}" delete job appstore-t3-migrate appstore-t3-seed --ignore-not-found >/dev/null
TRAEFIK_IP="$($KUBE -n kube-system get svc traefik -o jsonpath='{.spec.clusterIP}')"
helm --kube-context "${KUBE_CONTEXT}" upgrade --install appstore "${K8S_DIR}/charts/appstore" -n "${NS}" \
  --wait --timeout 10m -f - <<EOF
host: appstore.localhost
ssoHost: sso.localhost
selfServiceHost: self-service.localhost
environment: ${NS}
images:
  tags:
    backend: dev
    workerPods: dev
    frontend: dev
    selfServiceUi: dev
api:
  replicas: 1
  hostAliases:
    - ip: ${TRAEFIK_IP}
      hostnames: [moodle.localhost]
  lti:
    platformIssuer: https://moodle.localhost
    clientId: appstore-local-lti13
    deploymentId: "1"
    jwksUrl: http://moodle-web:8080/mod/lti/certs.php
podApps:
  zone: localhost
  appDomain: apps.localhost
frontend:
  replicas: 1
  frameAncestors: https://moodle.localhost
selfServiceUi:
  enabled: true
seed:
  enabled: true
network:
  policies: false
EOF

# 7. Moodle (k8s/charts/moodle: web, cron, setup + LTI 1.3 tool & demo course)
echo "==> Deploying Moodle Helm chart (k8s/charts/moodle)..."
recover_helm_release moodle
helm --kube-context "${KUBE_CONTEXT}" upgrade --install moodle "${K8S_DIR}/charts/moodle" -n "${NS}" \
  --wait --timeout 10m -f - <<EOF
host: moodle.localhost
images:
  tags:
    moodle: dev
site:
  adminEmail: admin.demo@appstore.example
cron:
  schedule: "*/15 * * * *"
setup:
  site:
    lang: en
  demoUsers:
    - { username: dozent.demo, email: dozent.demo@appstore.example, firstName: Dozent, lastName: Demo, role: teacher }
    - { username: student1.demo, email: student1.demo@appstore.example, firstName: Student, lastName: Eins, role: student }
    - { username: student2.demo, email: student2.demo@appstore.example, firstName: Student, lastName: Zwei, role: student }
lti:
  appstoreHost: appstore.localhost
  clientId: appstore-local-lti13
  deploymentId: "1"
network:
  policies: false
EOF

echo ""
echo "=================================================================="
echo " Local Kubernetes AppStore + Moodle Stack is READY (${KUBE_CONTEXT})"
echo " Namespace:        ${NS}"
echo " AppStore UI:      https://appstore.localhost"
echo " Self-Service UI:  https://self-service.localhost"
echo " Moodle LMS:       https://moodle.localhost"
echo " Keycloak SSO:     https://sso.localhost"
echo " Demo Password:    ${DEMO_PASSWORD} (users: admin.demo, dozent.demo, student1.demo, student2.demo)"
echo "=================================================================="
