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

# Extract fields using python3 (available on macOS without extra installs)
AUTH_URL=$(python3 -c "
import yaml, sys
c = yaml.safe_load(open('$CLOUDS_YAML'))
clouds = c.get('clouds', c)
cloud = clouds['$CLOUD_NAME']
auth = cloud.get('auth', {})
# Support both application credentials and user/password
if 'auth_url' in auth:
    print(auth['auth_url'])
elif 'auth' in cloud and 'auth_url' in cloud['auth']:
    print(cloud['auth']['auth_url'])
else:
    sys.exit('Cannot find auth_url')
")

APP_CRED_ID=$(python3 -c "
import yaml, sys
c = yaml.safe_load(open('$CLOUDS_YAML'))
clouds = c.get('clouds', c)
cloud = clouds['$CLOUD_NAME']
auth = cloud.get('auth', {})
v = auth.get('application_credential_id', auth.get('application_credential_secret', ''))
print(auth.get('application_credential_id', ''))
" 2>/dev/null || echo "")

APP_CRED_SECRET=$(python3 -c "
import yaml, sys
c = yaml.safe_load(open('$CLOUDS_YAML'))
clouds = c.get('clouds', c)
cloud = clouds['$CLOUD_NAME']
auth = cloud.get('auth', {})
print(auth.get('application_credential_secret', ''))
" 2>/dev/null || echo "")

REGION=$(python3 -c "
import yaml
c = yaml.safe_load(open('$CLOUDS_YAML'))
clouds = c.get('clouds', c)
cloud = clouds['$CLOUD_NAME']
print(cloud.get('region_name', 'RegionOne'))
" 2>/dev/null || echo "RegionOne")

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
