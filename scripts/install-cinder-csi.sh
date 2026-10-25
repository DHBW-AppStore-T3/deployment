#!/usr/bin/env bash
# Install the OpenStack Cinder CSI driver on the cluster.
# Usage: bash deployment/scripts/install-cinder-csi.sh
# Prereqs: helm, kubectl, yq (or python3), ~/Downloads/clouds.yaml
set -euo pipefail

KUBECONFIG="${KUBECONFIG:-/Users/I751109/Documents/coding-projects/DHBW-AppStore/k8s-credentials/kubeconfig-ma_wwi_24sea_appstore_g3.yaml}"
CLOUDS_YAML="${CLOUDS_YAML:-$HOME/Downloads/clouds.yaml}"
CLOUD_NAME="${CLOUD_NAME:-openstack}"
CSI_NAMESPACE="cinder-csi"
HELM_RELEASE="cinder-csi"
CHART_VERSION="2.32.0"

export KUBECONFIG

echo "==> Reading credentials from $CLOUDS_YAML (cloud: $CLOUD_NAME)"

# Extract fields from clouds.yaml using only Python stdlib (no pyyaml needed).
# Works for the standard OpenStack Application Credentials format.
_py_extract() {
  python3 -I - "$CLOUDS_YAML" "$CLOUD_NAME" "$1" "$2" <<'PYEOF'
import sys, re

clouds_file, cloud_name, field, default = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

with open(clouds_file) as f:
    lines = f.readlines()

# Find the cloud block, then the auth sub-block, then the field.
# Simple line-by-line scan — sufficient for the flat OpenStack clouds.yaml format.
in_clouds = False
in_cloud = False
in_auth = False
cloud_indent = auth_indent = 0

for line in lines:
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    key_val = stripped.rstrip('\n')

    if re.match(r'^clouds\s*:', key_val):
        in_clouds = True
        continue

    if in_clouds and not in_cloud:
        m = re.match(r'^(' + re.escape(cloud_name) + r')\s*:', key_val)
        if m and indent > 0:
            in_cloud = True
            cloud_indent = indent
            continue

    if in_cloud:
        if indent <= cloud_indent and stripped and not stripped.startswith('#'):
            break  # left the cloud block
        if re.match(r'^auth\s*:', key_val):
            in_auth = True
            auth_indent = indent
            continue
        if in_auth:
            if indent <= auth_indent and stripped and not stripped.startswith('#'):
                in_auth = False
            else:
                m = re.match(r'^' + re.escape(field) + r'\s*:\s*(.+)', key_val)
                if m:
                    print(m.group(1).strip().strip('"\''))
                    sys.exit(0)
        # region_name is at cloud level, not auth level
        if field == 'region_name':
            m = re.match(r'^region_name\s*:\s*(.+)', key_val)
            if m:
                print(m.group(1).strip().strip('"\''))
                sys.exit(0)

print(default)
PYEOF
}

AUTH_URL=$(_py_extract auth_url "")
APP_CRED_ID=$(_py_extract application_credential_id "")
APP_CRED_SECRET=$(_py_extract application_credential_secret "")
REGION=$(_py_extract region_name "RegionOne")

echo "==> auth_url: $AUTH_URL  region: $REGION"

# Build cloud.conf content
if [[ -n "$APP_CRED_ID" && -n "$APP_CRED_SECRET" ]]; then
  CLOUD_CONF="[Global]
auth-url=$AUTH_URL
application-credential-id=$APP_CRED_ID
application-credential-secret=$APP_CRED_SECRET
region=$REGION
"
else
  echo "ERROR: Only application credentials are supported. Set application_credential_id + application_credential_secret in clouds.yaml."
  exit 1
fi

echo "==> Creating namespace $CSI_NAMESPACE"
kubectl create namespace "$CSI_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo "==> Creating cloud-config secret"
kubectl create secret generic cloud-config \
  --namespace="$CSI_NAMESPACE" \
  --from-literal=cloud.conf="$CLOUD_CONF" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Adding OpenStack Helm repo"
helm repo add cpo https://kubernetes.github.io/cloud-provider-openstack --force-update
helm repo update

echo "==> Installing/upgrading cinder-csi-plugin v$CHART_VERSION"
helm upgrade --install "$HELM_RELEASE" cpo/openstack-cinder-csi \
  --namespace "$CSI_NAMESPACE" \
  --version "$CHART_VERSION" \
  --set secret.enabled=true \
  --set secret.name=cloud-config \
  --wait --timeout=5m

echo "==> Applying Cinder StorageClass"
kubectl apply -f "$(dirname "$0")/../k8s/cinder/storageclass.yaml"

echo "==> Done. Verify with: kubectl get storageclasses && kubectl get pods -n $CSI_NAMESPACE"
