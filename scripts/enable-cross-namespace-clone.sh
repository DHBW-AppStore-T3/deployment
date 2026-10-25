#!/usr/bin/env bash
# Let a PVC in a dep-* namespace clone the golden-image PVC of another namespace
# (kubevirt-vm apps: dataSourceRef with a namespace, backed by a ReferenceGrant per
# deployment that the pod deployer creates and removes). Idempotent.
#
#   1. k3s: feature gate CrossNamespaceVolumeDataSource on kube-apiserver and
#      kube-controller-manager, as an own drop-in next to the managed ones in
#      /etc/rancher/k3s/config.yaml.d (restarts k3s: the API is away for ~20 s,
#      running workloads keep running; staging and prod share this control plane).
#   2. cinder-csi: the same gate on the external-provisioner, and its right to read
#      ReferenceGrants. `helm upgrade` of cinder-csi resets both: run this again after it.
#
# Usage: bash scripts/enable-cross-namespace-clone.sh   (KUBECONFIG must point at the cluster)
set -euo pipefail

GATE="CrossNamespaceVolumeDataSource"
DROPIN=/host/etc/rancher/k3s/config.yaml.d/20-cross-namespace-volume-datasource.yaml
CSI_NAMESPACE="${CSI_NAMESPACE:-cinder-csi}"
CONTROLLER="${CSI_CONTROLLER:-openstack-cinder-csi-controllerplugin}"

# Not `kubectl ... | grep -q`: grep quits early, kubectl dies of SIGPIPE and pipefail calls that "off".
enabled() {
  local metrics
  metrics="$(kubectl get --raw /metrics 2>/dev/null)" || return 1
  [[ "$metrics" == *"kubernetes_feature_enabled{name=\"$GATE\",stage=\"ALPHA\"} 1"* ]]
}

if enabled; then
  echo "==> $GATE is already on in the API server"
else
  NODE="$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')"
  echo "==> Writing the k3s drop-in on $NODE and restarting k3s"
  kubectl debug "node/$NODE" -it=false --image=busybox:1.36 --profile=sysadmin -- sh -c "
    cat > $DROPIN <<YAML
# Added for kubevirt-vm: a claim in a dep-* namespace clones the golden image of another namespace.
kube-apiserver-arg:
  - \"feature-gates=$GATE=true\"
kube-controller-manager-arg:
  - \"feature-gates=$GATE=true\"
YAML
    chroot /host systemctl restart k3s"
  until enabled; do sleep 5; done
  kubectl get pods -n default -o name | grep node-debugger | xargs -r kubectl delete -n default >/dev/null
fi

echo "==> Enabling the gate on the CSI external-provisioner"
IDX="$(kubectl -n "$CSI_NAMESPACE" get deploy "$CONTROLLER" -o json | python3 -c "
import json, sys
c = json.load(sys.stdin)['spec']['template']['spec']['containers']
print(next(i for i, x in enumerate(c) if x['name'] == 'csi-provisioner'))")"
ARGS="$(kubectl -n "$CSI_NAMESPACE" get deploy "$CONTROLLER" -o jsonpath="{.spec.template.spec.containers[$IDX].args}")"
if [[ "$ARGS" != *"$GATE=true"* ]]; then
  N="$(python3 -c "
import json, sys
a = json.loads(sys.argv[1])
print(next(i for i, x in enumerate(a) if x.startswith('--feature-gates=')))" "$ARGS")"
  OLD="$(python3 -c "import json,sys;print(json.loads(sys.argv[1])[int(sys.argv[2])])" "$ARGS" "$N")"
  kubectl -n "$CSI_NAMESPACE" patch deploy "$CONTROLLER" --type json \
    -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/$IDX/args/$N\",\"value\":\"$OLD,$GATE=true\"}]"
  kubectl -n "$CSI_NAMESPACE" rollout status deploy/"$CONTROLLER" --timeout=180s
fi

echo "==> Letting the provisioner read ReferenceGrants"
if ! kubectl get clusterrole csi-provisioner-role -o jsonpath='{.rules[*].resources}' | grep -q referencegrants; then
  kubectl patch clusterrole csi-provisioner-role --type json \
    -p '[{"op":"add","path":"/rules/-","value":{"apiGroups":["gateway.networking.k8s.io"],"resources":["referencegrants"],"verbs":["get","list","watch"]}}]'
fi
echo "==> Done."
