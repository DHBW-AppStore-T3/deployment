#!/bin/bash
# Run before and after `kubectl apply -f k8s/cluster/addon-networkpolicies.yaml` (and node-netguard.yaml): everything that depends on the
# add-ons must answer the same. Uses your current kubectl context. Rollback: kubectl delete -f k8s/cluster/addon-networkpolicies.yaml

Z=t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site
echo "http: $(for h in appstore-staging sso-staging appstore sso moodle-staging; do printf '%s=%s ' $h "$(curl -s -o /dev/null -m 10 -w '%{http_code}' https://$h.$Z/)"; done)"
echo "certificates not ready: $(kubectl get certificate -A --no-headers 2>/dev/null | grep -vc True) of $(kubectl get certificate -A --no-headers 2>/dev/null | wc -l)"
echo "cnpg: $(kubectl get cluster.postgresql.cnpg.io -A --no-headers 2>/dev/null | awk '{print $1"/"$2":"$5" "$6}' | tr '\n' ';')"
echo "apiservices not available: $(kubectl get apiservices --no-headers | grep -vc True)"
echo "top nodes (metrics API): $(kubectl top nodes --no-headers 2>&1 | awk '{print $1,$3}' | head -1)"
echo "vm/vmi: $(kubectl get vm,vmi -A --no-headers 2>&1 | awk '{print $2,$4}' | tr '\n' ';')"
echo "argocd apps (not Synced/Healthy): $(kubectl -n argocd get applications --no-headers 2>/dev/null | awk '$2!="Synced" || $3!="Healthy"{print $1":"$2"/"$3}' | tr '\n' ' ')"
echo "pods not Running/Completed in add-on namespaces: $(kubectl get pods -A --no-headers 2>/dev/null | grep -E '^(cert-manager|cnpg-system|external-dns|cinder-csi|kubevirt|system-upgrade|kube-system|argocd) ' | grep -vE 'Running|Completed' | awk '{print $1"/"$2}' | tr '\n' ' ')"
# webhooks answer: server-side dry runs go through the apiserver to each add-on's webhook
kubectl create ns addon-check >/dev/null 2>&1
printf 'apiVersion: cert-manager.io/v1\nkind: Certificate\nmetadata: {name: probe, namespace: addon-check}\nspec: {secretName: probe, dnsNames: [probe.example.invalid], issuerRef: {name: x, kind: ClusterIssuer}}\n' | kubectl apply --dry-run=server -f - 2>&1 | tail -1 | cut -c1-110 | sed 's/^/cert-manager webhook: /'
printf 'apiVersion: postgresql.cnpg.io/v1\nkind: Cluster\nmetadata: {name: probe, namespace: addon-check}\nspec: {instances: 1, storage: {size: 1Gi}}\n' | kubectl apply --dry-run=server -f - 2>&1 | tail -1 | cut -c1-110 | sed 's/^/cnpg webhook: /'
printf 'apiVersion: kubevirt.io/v1\nkind: VirtualMachine\nmetadata: {name: probe, namespace: addon-check}\nspec: {runStrategy: Halted, template: {spec: {domain: {devices: {}, resources: {requests: {memory: 64Mi}}}}}}\n' | kubectl apply --dry-run=server -f - 2>&1 | tail -1 | cut -c1-110 | sed 's/^/kubevirt webhook: /'
kubectl delete ns addon-check --wait=false >/dev/null 2>&1
