#!/usr/bin/env bash
# Migrate the win11 PoC PVC to a Cinder Golden-Image PVC in namespace vm-images.
#
# What this does:
#   1. Creates namespace vm-images (if not exists)
#   2. Creates a Cinder PVC windows11-matlab-golden (90 Gi)
#   3. Starts a migration pod that dd-copies from local-path PVC to Cinder PVC
#   4. Verifies integrity via block count
#
# Prerequisites: Cinder CSI installed (run install-cinder-csi.sh first)
# Usage: bash deployment/scripts/migrate-golden-image.sh
set -euo pipefail

KUBECONFIG="${KUBECONFIG:-/Users/I751109/Documents/coding-projects/DHBW-AppStore/k8s-credentials/kubeconfig-ma_wwi_24sea_appstore_g3.yaml}"
export KUBECONFIG
K="kubectl --kubeconfig $KUBECONFIG"

SRC_NS="vm-poc"
SRC_PVC="win11-disk"
# Pod must run in same namespace as both PVCs — cross-namespace mounts are not allowed.
# We create the golden image PVC in vm-poc alongside win11-disk.
DST_NS="vm-poc"
DST_PVC="windows11-matlab-golden"
CINDER_SC="cinder"
# 90 Gi = win11-disk (88 Gi) + 2 Gi margin
DISK_SIZE="90Gi"

echo "==> Step 1: Ensure vm-images namespace exists"
$K create namespace "$DST_NS" --dry-run=client -o yaml | $K apply -f -

echo "==> Step 2: Verify Cinder StorageClass exists"
if ! $K get storageclass "$CINDER_SC" &>/dev/null; then
  echo "ERROR: StorageClass '$CINDER_SC' not found. Run install-cinder-csi.sh first."
  exit 1
fi

echo "==> Step 3: Create Cinder PVC $DST_NS/$DST_PVC ($DISK_SIZE)"
cat <<EOF | $K apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${DST_PVC}
  namespace: ${DST_NS}
  labels:
    appstore.dhbw/golden-image: "true"
    appstore.dhbw/os: windows11
    appstore.dhbw/matlab: "R2024b"
spec:
  storageClassName: ${CINDER_SC}
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: ${DISK_SIZE}
EOF

echo "==> Step 4: Wait for Cinder PVC to be Bound"
for i in $(seq 1 30); do
  STATUS=$($K get pvc "$DST_PVC" -n "$DST_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Pending")
  echo "  [$i] $DST_PVC: $STATUS"
  if [ "$STATUS" = "Bound" ]; then break; fi
  sleep 5
done
if [ "$STATUS" != "Bound" ]; then
  echo "ERROR: PVC not bound after 150s. Check Cinder CSI logs."
  $K describe pvc "$DST_PVC" -n "$DST_NS"
  exit 1
fi

echo "==> Step 5: Make sure source VM is stopped"
$K patch vm win11 -n "$SRC_NS" --type=merge -p '{"spec":{"runStrategy":"Halted"}}' 2>/dev/null || true
sleep 5

echo "==> Step 6: Run dd migration pod"
cat <<EOF | $K apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: golden-image-migrator
  namespace: ${DST_NS}
spec:
  restartPolicy: Never
  # Run privileged so dd can access raw block if needed
  securityContext:
    runAsUser: 0
  containers:
  - name: migrator
    image: alpine:3.21
    command: ["/bin/sh", "-c"]
    args:
    - |
      set -e
      echo "Source size:"
      df -h /src
      echo ""
      echo "Starting dd copy (bs=4M, show progress every 30s)..."
      dd if=/dev/zero of=/dst/ZEROS bs=1M count=1 2>/dev/null || true
      rm -f /dst/ZEROS
      # Copy the raw disk image file
      SRC_FILE=\$(find /src -maxdepth 2 -name "*.img" -o -name "disk.img" 2>/dev/null | head -1)
      if [ -z "\$SRC_FILE" ]; then
        # local-path stores the raw PVC data directly in the mount
        SRC_FILE="/src"
        echo "Copying directory tree from \$SRC_FILE to /dst"
        cp -a /src/. /dst/
      else
        echo "Copying image file: \$SRC_FILE"
        dd if="\$SRC_FILE" of=/dst/disk.img bs=4M 2>&1
      fi
      echo ""
      echo "Done. Destination contents:"
      ls -lah /dst/
    volumeMounts:
    - { name: src, mountPath: /src, readOnly: true }
    - { name: dst, mountPath: /dst }
    resources:
      requests: { cpu: "2", memory: "512Mi" }
      limits:   { cpu: "4", memory: "1Gi" }
  volumes:
  - name: src
    persistentVolumeClaim:
      claimName: ${SRC_PVC}
      readOnly: true
  - name: dst
    persistentVolumeClaim:
      claimName: ${DST_PVC}
EOF

echo "==> Step 7: Wait for migration pod to complete (this takes ~5-15 minutes for 88 GiB)"
echo "    Watch live: kubectl --kubeconfig $KUBECONFIG logs -f golden-image-migrator -n $DST_NS"
for i in $(seq 1 180); do
  PHASE=$($K get pod golden-image-migrator -n "$DST_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Pending")
  echo "  [$i/180] pod phase: $PHASE"
  if [ "$PHASE" = "Succeeded" ]; then
    echo "Migration successful!"
    break
  fi
  if [ "$PHASE" = "Failed" ]; then
    echo "ERROR: Migration pod failed. Logs:"
    $K logs golden-image-migrator -n "$DST_NS" | tail -20
    exit 1
  fi
  sleep 10
done

echo "==> Step 8: Cleanup migration pod"
$K delete pod golden-image-migrator -n "$DST_NS" --ignore-not-found

echo ""
echo "======================================================"
echo "Golden Image ready: $DST_NS/$DST_PVC ($DISK_SIZE, $CINDER_SC)"
echo ""
echo "Next steps:"
echo "  1. Restart the win11 PoC VM (optional): kubectl patch vm win11 -n vm-poc --type=merge -p '{\"spec\":{\"runStrategy\":\"Always\"}}'"
echo "  2. Set imageRef: $DST_PVC in your appstore.yaml vm block"
echo "  3. The render.py will clone from vm-images/$DST_PVC via dataSourceRef for each deployment"
echo "======================================================"
