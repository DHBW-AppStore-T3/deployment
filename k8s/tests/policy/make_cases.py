"""Admission requests for the pod deployer's policy, and what it must answer.

    python make_cases.py fixtures.json cases.json placement.json grants.json vm.json

fixtures.json holds what the renderer produces (render_fixtures.py); every
request the pod deployer really sends with it must be allowed, every variant
an attacker controlling the pod deployer could send must be denied. Pure
Python (no backend needed), run by CI before the policy check.
"""

import copy
import json
import sys
import uuid

NS = "appstore-staging"
ENV = "appstore-staging"
SA = f"system:serviceaccount:{NS}:appstore-t3-pod-deployer"
ZONE = "t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site"
DEPLOYER_ROLE = f"appstore-t3-{NS}-deployer"
READER_ROLE = f"appstore-t3-{NS}-reader"
VNC_PROXY_ROLE = f"appstore-t3-{NS}-vnc-proxy"
DIGEST = "sha256:" + "a" * 64

GROUPS = {
    "Namespace": ("", "v1", "namespaces"),
    "Secret": ("", "v1", "secrets"),
    "Service": ("", "v1", "services"),
    "ResourceQuota": ("", "v1", "resourcequotas"),
    "LimitRange": ("", "v1", "limitranges"),
    "PersistentVolumeClaim": ("", "v1", "persistentvolumeclaims"),
    "Pod": ("", "v1", "pods"),
    "StatefulSet": ("apps", "v1", "statefulsets"),
    "Ingress": ("networking.k8s.io", "v1", "ingresses"),
    "NetworkPolicy": ("networking.k8s.io", "v1", "networkpolicies"),
    "RoleBinding": ("rbac.authorization.k8s.io", "v1", "rolebindings"),
    "ServiceAccount": ("", "v1", "serviceaccounts"),
    "Deployment": ("apps", "v1", "deployments"),
    "VirtualMachine": ("kubevirt.io", "v1", "virtualmachines"),
    "VirtualMachineInstance": ("kubevirt.io", "v1", "virtualmachineinstances"),
    "ReferenceGrant": ("gateway.networking.k8s.io", "v1beta1", "referencegrants"),
}

fixtures = json.load(open(sys.argv[1], encoding="utf-8"))
dep_id = fixtures["deployment"]["id"]
DEP_NS = fixtures["deployment"]["namespace"]
objects = fixtures["default"]
cases = []
ns_obj = objects[0]


def case(name, expect, obj=None, operation="CREATE", old=None, namespace=None, ns_object=None,
         kind=None, sub="", user=SA):
    target = obj if obj is not None else old
    kind = kind or target["kind"]
    group, version, resource = GROUPS[kind]
    meta = target.get("metadata", {})
    if kind == "Namespace":
        namespace_, ns_object_ = "", None
    else:
        namespace_ = namespace if namespace is not None else meta.get("namespace", DEP_NS)
        ns_object_ = ns_object if ns_object is not None else (ns_obj if namespace_ == DEP_NS else None)
    cases.append({
        "name": name, "expect": expect, "operation": operation, "group": group, "version": version,
        "kind": kind, "resource": resource, "subResource": sub, "namespace": namespace_,
        "name_": meta.get("name", ""), "username": user, "object": obj, "oldObject": old,
        "namespaceObject": ns_object_,
    })


def mutated(obj, fn):
    out = copy.deepcopy(obj)
    fn(out)
    return out


def binding(name, role, account, account_ns=None):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
        "metadata": {"name": name, "namespace": DEP_NS,
                     "labels": {"appstore.dhbw/deployment-id": dep_id, "app.kubernetes.io/managed-by": "appstore"}},
        "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": role},
        "subjects": [{"kind": "ServiceAccount", "name": account, "namespace": account_ns or NS}],
    }


# ---------------------------------------------------------------- allowed
case("namespace create", "allow", ns_obj)
case("namespace re-apply", "allow", ns_obj, "UPDATE", old=ns_obj)
case("namespace delete", "allow", None, "DELETE", old=ns_obj)
for obj in objects[1:]:
    case(f"{obj['kind']} {obj['metadata']['name']} create", "allow", obj)
    case(f"{obj['kind']} {obj['metadata']['name']} re-apply", "allow", obj, "UPDATE", old=obj)
deployer_rb = binding("appstore-deployer", DEPLOYER_ROLE, "appstore-t3-pod-deployer")
reader_rb = binding("appstore-api-reader", READER_ROLE, "appstore-t3-api")
case("deployer role binding", "allow", deployer_rb)
# kubevirt-vm namespaces: the noVNC proxy's own account and its role.
proxy_sa = {"apiVersion": "v1", "kind": "ServiceAccount",
            "metadata": {"name": "vnc-proxy", "namespace": DEP_NS,
                         "labels": {"appstore.dhbw/deployment-id": dep_id, "app.kubernetes.io/managed-by": "appstore"}}}
case("vnc-proxy service account", "allow", proxy_sa)
case("vnc-proxy service account, re-apply", "allow", proxy_sa, "UPDATE", old=proxy_sa)
case("vnc-proxy role binding", "allow", binding("appstore-vnc-proxy", VNC_PROXY_ROLE, "vnc-proxy", DEP_NS))
case("any other service account", "deny", mutated(proxy_sa, lambda s: s["metadata"].update(name="admin")))
case("service account with a pull secret", "deny", mutated(proxy_sa, lambda s: s.update(imagePullSecrets=[{"name": "x"}])))
case("vnc-proxy role bound to a foreign account", "deny", binding("appstore-vnc-proxy", VNC_PROXY_ROLE, "vnc-proxy", "kube-system"))
case("vnc-proxy role bound to another account", "deny", binding("appstore-vnc-proxy", VNC_PROXY_ROLE, "default", DEP_NS))
case("vnc-proxy role bound to the pod deployer", "deny", binding("appstore-vnc-proxy", VNC_PROXY_ROLE, "appstore-t3-pod-deployer"))
case("reader role binding", "allow", reader_rb)
sts = next(o for o in objects if o["kind"] == "StatefulSet")
ingress = next(o for o in objects if o["kind"] == "Ingress")
service = next(o for o in objects if o["kind"] == "Service")
secret = next(o for o in objects if o["kind"] == "Secret")
quota = next(o for o in objects if o["kind"] == "ResourceQuota")
netpols = [o for o in objects if o["kind"] == "NetworkPolicy"]
internet = next(o for o in netpols if o["metadata"]["name"] == "allow-egress-internet")
ingress_np = next(o for o in netpols if o["metadata"]["name"] == "allow-ingress-controller")
dns_np = next(o for o in netpols if o["metadata"]["name"] == "allow-dns")
# kube-apiserver defaults the pod template before admission; the policy sees this form.
defaulted = mutated(sts, lambda s: s["spec"]["template"]["spec"].update(schedulerName="default-scheduler"))
case("statefulset as kube-apiserver defaults it", "allow", defaulted)
case("statefulset as kube-apiserver defaults it, re-apply", "allow", defaulted, "UPDATE", old=defaulted)
# A Scale to 0 as kube-apiserver passes it: replicas is omitempty in autoscaling/v1.
scale = {"apiVersion": "autoscaling/v1", "kind": "Scale", "metadata": {"name": sts["metadata"]["name"], "namespace": DEP_NS},
         "spec": {}}
case("scale to 0", "allow", scale, "UPDATE", old=mutated(scale, lambda s: s["spec"].update(replicas=1)), kind="StatefulSet", sub="scale")
case("scale to 1", "allow", mutated(scale, lambda s: s["spec"].update(replicas=1)), "UPDATE", old=scale, kind="StatefulSet", sub="scale")
pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "team-1-alice-0", "namespace": DEP_NS}, "spec": sts["spec"]["template"]["spec"]}
case("restart: delete the pod", "allow", None, "DELETE", old=pod)
pvc = {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "data-team-1-alice-0", "namespace": DEP_NS}, "spec": {}}
case("reset: delete the claim", "allow", None, "DELETE", old=pvc)
privileged_pod = mutated(pod, lambda p: p["spec"]["containers"][0]["securityContext"].update(privileged=True))
case("another identity is not matched (statefulset controller)", "allow", privileged_pod,
     user="system:serviceaccount:kube-system:statefulset-controller")

# ---------------------------------------------------------------- where
for bad_name in ("kube-system", "appstore-prod", "dep-xyz", "dep-1234567", "dep-12345678x"):
    case(f"namespace named {bad_name}", "deny", mutated(ns_obj, lambda n, b=bad_name: n["metadata"].update(name=b)))
for label in ("pod-security.kubernetes.io/enforce", "appstore.dhbw/environment", "app.kubernetes.io/managed-by", "appstore.dhbw/deployment-id"):
    case(f"namespace without {label}", "deny", mutated(ns_obj, lambda n, k=label: n["metadata"]["labels"].pop(k)))
case("namespace privileged", "deny", mutated(ns_obj, lambda n: n["metadata"]["labels"].update({"pod-security.kubernetes.io/enforce": "privileged"})))
case("namespace old pod security version", "deny", mutated(ns_obj, lambda n: n["metadata"]["labels"].update({"pod-security.kubernetes.io/enforce-version": "v1.0"})))
case("namespace of the other environment", "deny", mutated(ns_obj, lambda n: n["metadata"]["labels"].update({"appstore.dhbw/environment": "appstore-prod"})))
prod_ns = mutated(ns_obj, lambda n: n["metadata"]["labels"].update({"appstore.dhbw/environment": "appstore-prod"}))
case("take over the other environment's namespace", "deny", ns_obj, "UPDATE", old=prod_ns)
case("delete the other environment's namespace", "deny", None, "DELETE", old=prod_ns)
unmanaged = mutated(ns_obj, lambda n: n["metadata"].update(labels={"kubernetes.io/metadata.name": DEP_NS}))
case("delete a dep-* namespace someone else created", "deny", None, "DELETE", old=unmanaged)
other_dep = mutated(ns_obj, lambda n: n["metadata"]["labels"].update({"appstore.dhbw/deployment-id": str(uuid.uuid4())}))
case("hand a namespace to another deployment", "deny", ns_obj, "UPDATE", old=other_dep)
case("secret in the other environment's namespace", "deny", secret, ns_object=prod_ns)
case("secret in the platform namespace", "deny", mutated(secret, lambda s: s["metadata"].update(namespace=NS)), namespace=NS,
     ns_object={"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS, "labels": {"kubernetes.io/metadata.name": NS}}})

# ---------------------------------------------------------------- what
case("delete the quota", "deny", None, "DELETE", old=quota)
case("delete a network policy", "deny", None, "DELETE", old=internet)
case("delete a secret", "deny", None, "DELETE", old=secret)
case("delete the statefulset", "deny", None, "DELETE", old=sts)
case("bind cluster-admin", "deny", mutated(deployer_rb, lambda b: b["roleRef"].update(name="cluster-admin")))
case("bind the deployer role to another account", "deny", mutated(deployer_rb, lambda b: b["subjects"][0].update(name="default")))
case("bind the reader role to the pod deployer", "deny", mutated(reader_rb, lambda b: b["subjects"][0].update(name="appstore-t3-pod-deployer")))
case("bind to two subjects", "deny", mutated(deployer_rb, lambda b: b["subjects"].append(dict(b["subjects"][0], name="appstore-t3-api"))))
case("bind to a user", "deny", mutated(deployer_rb, lambda b: b["subjects"][0].update(kind="User", name="eve")))
case("bind as Role", "deny", mutated(deployer_rb, lambda b: b["roleRef"].update(kind="Role")))
case("service account token secret", "deny", mutated(secret, lambda s: s.update(type="kubernetes.io/service-account-token")))
for svc_type in ("NodePort", "LoadBalancer"):
    case(f"service {svc_type}", "deny", mutated(service, lambda s, t=svc_type: s["spec"].update(type=t)))
case("service external IPs", "deny", mutated(service, lambda s: s["spec"].update(externalIPs=["192.0.2.1"])))
case("service ExternalName", "deny", mutated(service, lambda s: s["spec"].update(type="ExternalName", externalName="evil.example")))
case("quota with node ports", "deny", mutated(quota, lambda q: q["spec"]["hard"].update({"services.nodeports": "5"})))
case("quota without a pod cap", "deny", mutated(quota, lambda q: q["spec"]["hard"].pop("pods")))
case("quota above the workload limit", "deny", mutated(quota, lambda q: q["spec"]["hard"].update(pods="1000")))
case("quota with a quantity suffix", "deny", mutated(quota, lambda q: q["spec"]["hard"].update(pods="1k")))
case("quota with many claims", "deny", mutated(quota, lambda q: q["spec"]["hard"].update(persistentvolumeclaims="500")))
case("scale to 5", "deny", mutated(scale, lambda s: s["spec"].update(replicas=5)), "UPDATE", old=scale, kind="StatefulSet", sub="scale")
case("statefulset with 5 replicas", "deny", mutated(sts, lambda s: s["spec"].update(replicas=5)))


# ---------------------------------------------------------------- pods
def pod_variant(name, fn):
    case(f"statefulset: {name}", "deny", mutated(sts, lambda s: fn(s["spec"]["template"]["spec"])))


c0 = lambda p: p["containers"][0]  # noqa: E731
pod_variant("privileged container", lambda p: c0(p)["securityContext"].update(privileged=True))
pod_variant("privilege escalation", lambda p: c0(p)["securityContext"].update(allowPrivilegeEscalation=True))
pod_variant("container may run as root", lambda p: c0(p)["securityContext"].update(runAsNonRoot=False))
pod_variant("pod may run as root", lambda p: p["securityContext"].pop("runAsNonRoot"))
pod_variant("added capability", lambda p: c0(p)["securityContext"]["capabilities"].update(add=["NET_ADMIN"]))
pod_variant("host network", lambda p: p.update(hostNetwork=True))
pod_variant("host PID", lambda p: p.update(hostPID=True))
pod_variant("host path volume", lambda p: p["volumes"].append({"name": "root", "hostPath": {"path": "/"}}))
pod_variant("emptyDir without a size limit", lambda p: p["volumes"].append({"name": "big", "emptyDir": {}}))
pod_variant("projected service account token", lambda p: p["volumes"].append({"name": "tok", "projected": {"sources": [{"serviceAccountToken": {"path": "t"}}]}}))
pod_variant("service account token mounted", lambda p: p.update(automountServiceAccountToken=True))
pod_variant("service account token default", lambda p: p.pop("automountServiceAccountToken"))
pod_variant("service account", lambda p: p.update(serviceAccountName="appstore-t3-pod-deployer"))
pod_variant("image from docker.io", lambda p: c0(p).update(image=f"docker.io/evil/img@{DIGEST}"))
pod_variant("image by tag", lambda p: c0(p).update(image="ghcr.io/dhbw-appstore-t3/apps/online-ide:latest"))
pod_variant("lookalike registry", lambda p: c0(p).update(image=f"ghcr.io/dhbw-appstore-t3-evil/img@{DIGEST}"))
pod_variant("a platform image, not an app's", lambda p: c0(p).update(image=f"ghcr.io/dhbw-appstore-t3/backend@{DIGEST}"))
pod_variant("cpu above the ceiling", lambda p: c0(p)["resources"]["limits"].update(cpu="64"))
pod_variant("memory above the ceiling", lambda p: c0(p)["resources"]["limits"].update(memory="512Gi"))
pod_variant("no limits", lambda p: c0(p)["resources"].pop("limits"))
pod_variant("no cpu limit", lambda p: c0(p)["resources"]["limits"].pop("cpu"))
pod_variant("pinned to a node", lambda p: p.update(nodeName="k3s-server"))
pod_variant("priority class", lambda p: p.update(priorityClassName="system-node-critical"))
pod_variant("another scheduler", lambda p: p.update(schedulerName="my-scheduler"))
pod_variant("tolerates the control plane", lambda p: p.update(tolerations=[{"key": "node-role.kubernetes.io/control-plane", "operator": "Exists"}]))
pod_variant("host port", lambda p: c0(p)["ports"][0].update(hostPort=8080))
pod_variant("privileged init container", lambda p: p.update(initContainers=[dict(copy.deepcopy(c0(p)), name="init", securityContext={"privileged": True})]))
pod_variant("runtime class", lambda p: p.update(runtimeClassName="runc-unsafe"))
case("statefulset: other storage class", "deny",
     mutated(sts, lambda s: s["spec"]["volumeClaimTemplates"][0]["spec"].update(storageClassName="fast-hostpath")))
case("statefulset: volume above the ceiling", "deny",
     mutated(sts, lambda s: s["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"].update(storage="10Ti")))
case("statefulset: volume without a size", "deny",
     mutated(sts, lambda s: s["spec"]["volumeClaimTemplates"][0]["spec"].pop("resources")))


# ---------------------------------------------------------------- ingress
def ingress_variant(name, fn):
    case(f"ingress: {name}", "deny", mutated(ingress, fn))


host_of = lambda i: i["spec"]["rules"][0]  # noqa: E731
ingress_variant("the platform's own host", lambda i: host_of(i).update(host=f"appstore.{ZONE}"))
ingress_variant("keycloak's host", lambda i: host_of(i).update(host=f"sso.{ZONE}"))
ingress_variant("another deployment's host", lambda i: host_of(i).update(host=f"team-1-alice-deadbeef.{ZONE}"))
ingress_variant("a host outside the zone", lambda i: host_of(i).update(host="evil.example.org"))
ingress_variant("a two-label prefix", lambda i: host_of(i).update(host=f"a.b-12345678.{ZONE}"))
ingress_variant("wildcard host", lambda i: host_of(i).update(host=f"*.{ZONE}"))
ingress_variant("no host (all hosts)", lambda i: host_of(i).pop("host"))
ingress_variant("backtick in the path", lambda i: host_of(i)["http"]["paths"][0].update(path="/x`) || HostRegexp(`.+`) || PathPrefix(`/"))
ingress_variant("regex path type", lambda i: host_of(i)["http"]["paths"][0].update(pathType="ImplementationSpecific"))
ingress_variant("default backend", lambda i: i["spec"].update(defaultBackend={"service": {"name": "x", "port": {"number": 80}}}))
ingress_variant("resource backend", lambda i: host_of(i)["http"]["paths"][0].update(backend={"resource": {"apiGroup": "x", "kind": "y", "name": "z"}}))
ingress_variant("tls for the platform's host", lambda i: i["spec"]["tls"][0]["hosts"].append(f"appstore.{ZONE}"))
ingress_variant("another ingress class", lambda i: i["spec"].update(ingressClassName="nginx"))
ingress_variant("traefik router priority", lambda i: i["metadata"].update(annotations={"traefik.ingress.kubernetes.io/router.priority": "100000"}))
ingress_variant("traefik middlewares", lambda i: i["metadata"].update(annotations={"traefik.ingress.kubernetes.io/router.middlewares": "kube-system-x@kubernetescrd"}))
case("ingress: a second plain path is fine", "allow",
     mutated(ingress, lambda i: host_of(i)["http"]["paths"].append(dict(copy.deepcopy(host_of(i)["http"]["paths"][0]), path="/ide/"))))


# ---------------------------------------------------------------- network policies
def np_variant(base, name, fn):
    case(f"network policy: {name}", "deny", mutated(base, fn))


np_variant(internet, "selects some pods only", lambda n: n["spec"].update(podSelector={"matchLabels": {"a": "b"}}))
np_variant(ingress_np, "ingress from everywhere", lambda n: n["spec"]["ingress"][0].pop("from"))
np_variant(ingress_np, "ingress from an empty peer list", lambda n: n["spec"]["ingress"][0].update({"from": []}))
np_variant(ingress_np, "ingress from an address block", lambda n: n["spec"]["ingress"][0].update({"from": [{"ipBlock": {"cidr": "0.0.0.0/0"}}]}))
np_variant(ingress_np, "ingress from another namespace", lambda n: n["spec"]["ingress"][0]["from"][0].update(namespaceSelector={"matchLabels": {"kubernetes.io/metadata.name": "appstore-staging"}}))
np_variant(internet, "egress everywhere", lambda n: n["spec"]["egress"][0].pop("to"))
np_variant(internet, "egress without except", lambda n: n["spec"]["egress"][0]["to"][0]["ipBlock"].pop("except"))
np_variant(internet, "egress reaches the metadata service", lambda n: n["spec"]["egress"][0]["to"][0]["ipBlock"]["except"].remove("169.254.0.0/16"))
np_variant(internet, "egress reaches the node", lambda n: n["spec"]["egress"][1]["to"][0]["ipBlock"]["except"].remove("2001:7c0:1b20:c913:1::10d/128"))
np_variant(internet, "egress to a private range", lambda n: n["spec"]["egress"][0]["to"][0].update(ipBlock={"cidr": "10.0.0.0/8"}))
# allow-intra-namespace (issue .github#11): the one podSelector shape that is accepted.
def intra(**over):
    spec = {"podSelector": {}, "policyTypes": ["Ingress", "Egress"],
            "ingress": [{"from": [{"podSelector": {}}], "ports": [{"protocol": "TCP", "port": 8080}]}],
            "egress": [{"to": [{"podSelector": {}}], "ports": [{"protocol": "TCP", "port": 8080}]}]}
    spec.update(over)
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": dict(copy.deepcopy(dns_np["metadata"]), name="allow-intra-namespace"), "spec": spec}


intra_np = intra()
case("network policy: allow-intra-namespace create", "allow", intra_np)
case("network policy: allow-intra-namespace re-apply", "allow", intra_np, "UPDATE", old=intra_np)
case("network policy: allow-intra-namespace, protocol defaulted away", "allow",
     mutated(intra_np, lambda n: [n["spec"][d][0]["ports"][0].pop("protocol") for d in ("ingress", "egress")]))
np_variant(intra_np, "podSelector peer in another policy (ingress)", lambda n: n["metadata"].update(name="allow-pods"))
np_variant(intra_np, "podSelector peer in the dns policy name", lambda n: n["metadata"].update(name="allow-dns"))
np_variant(intra_np, "intra-namespace non-empty podSelector (ingress)", lambda n: n["spec"]["ingress"][0]["from"][0].update(podSelector={"matchLabels": {"a": "b"}}))
np_variant(intra_np, "intra-namespace non-empty podSelector (egress)", lambda n: n["spec"]["egress"][0]["to"][0].update(podSelector={"matchLabels": {"a": "b"}}))
np_variant(intra_np, "intra-namespace empty matchExpressions podSelector", lambda n: n["spec"]["egress"][0]["to"][0].update(podSelector={"matchExpressions": []}))
np_variant(intra_np, "intra-namespace podSelector + namespaceSelector (ingress)", lambda n: n["spec"]["ingress"][0]["from"][0].update(namespaceSelector={}))
np_variant(intra_np, "intra-namespace podSelector + namespaceSelector (egress)", lambda n: n["spec"]["egress"][0]["to"][0].update(namespaceSelector={}))
np_variant(intra_np, "intra-namespace podSelector + ipBlock (ingress)", lambda n: n["spec"]["ingress"][0]["from"][0].update(ipBlock={"cidr": "0.0.0.0/0"}))
np_variant(intra_np, "intra-namespace podSelector + ipBlock (egress)", lambda n: n["spec"]["egress"][0]["to"][0].update(ipBlock={"cidr": "10.0.0.0/8"}))
np_variant(intra_np, "intra-namespace UDP (ingress)", lambda n: n["spec"]["ingress"][0]["ports"][0].update(protocol="UDP"))
np_variant(intra_np, "intra-namespace SCTP (egress)", lambda n: n["spec"]["egress"][0]["ports"][0].update(protocol="SCTP"))
np_variant(intra_np, "intra-namespace TCP and UDP (egress)", lambda n: n["spec"]["egress"][0]["ports"].append({"protocol": "UDP", "port": 53}))
np_variant(intra_np, "intra-namespace TCP without a port (ingress)", lambda n: n["spec"]["ingress"][0].update(ports=[{"protocol": "TCP"}]))
np_variant(intra_np, "intra-namespace empty port entry (egress)", lambda n: n["spec"]["egress"][0].update(ports=[{}]))
np_variant(intra_np, "intra-namespace port range (ingress)", lambda n: n["spec"]["ingress"][0]["ports"][0].update(port=1, endPort=65535))
np_variant(intra_np, "intra-namespace port range (egress)", lambda n: n["spec"]["egress"][0]["ports"][0].update(endPort=9000))
np_variant(intra_np, "intra-namespace named port (egress)", lambda n: n["spec"]["egress"][0]["ports"][0].update(port="http"))
np_variant(intra_np, "intra-namespace two rules, one bad (ingress)", lambda n: n["spec"]["ingress"].append({"from": [{"podSelector": {}}], "ports": [{"protocol": "UDP", "port": 53}]}))
np_variant(intra_np, "intra-namespace two rules, one without ports (egress)", lambda n: n["spec"]["egress"].append({"to": [{"podSelector": {}}]}))
case("network policy: allow-intra-namespace, two good rules", "allow", mutated(intra_np, lambda n: [n["spec"][d].append(copy.deepcopy(n["spec"][d][0])) or n["spec"][d][1]["ports"][0].update(port=9090) for d in ("ingress", "egress")]))
np_variant(intra_np, "intra-namespace without ports (ingress)", lambda n: n["spec"]["ingress"][0].pop("ports"))
np_variant(intra_np, "intra-namespace empty ports (egress)", lambda n: n["spec"]["egress"][0].update(ports=[]))
np_variant(intra_np, "intra-namespace extra peer (ingress)", lambda n: n["spec"]["ingress"][0]["from"].append({"ipBlock": {"cidr": "0.0.0.0/0"}}))
np_variant(intra_np, "intra-namespace extra namespaceSelector peer (egress)", lambda n: n["spec"]["egress"][0]["to"].append({"namespaceSelector": {}}))
np_variant(intra_np, "intra-namespace second podSelector peer (egress)", lambda n: n["spec"]["egress"][0]["to"].append({"podSelector": {}}))
np_variant(intra_np, "intra-namespace selects some pods only", lambda n: n["spec"].update(podSelector={"matchLabels": {"a": "b"}}))
np_variant(intra_np, "intra-namespace peer-less ingress rule", lambda n: n["spec"]["ingress"][0].pop("from"))
np_variant(intra_np, "intra-namespace peer-less egress rule", lambda n: n["spec"]["egress"][0].pop("to"))

np_variant(dns_np, "egress to all of kube-system", lambda n: n["spec"]["egress"][0]["to"][0].pop("podSelector"))
np_variant(dns_np, "egress to postgres", lambda n: n["spec"]["egress"][0]["to"][0].update(namespaceSelector={"matchLabels": {"kubernetes.io/metadata.name": NS}}, podSelector={"matchLabels": {"cnpg.io/cluster": "postgres-cluster"}}))

json.dump(cases, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
print(f"{len(cases)} cases")

# ---------------------------------------------------------------- student node placement
cases.clear()
placed = next(o for o in fixtures["placement"] if o["kind"] == "StatefulSet")


def placement(name, expect, fn):
    obj = copy.deepcopy(placed)
    fn(obj["spec"]["template"]["spec"])
    case(f"placement: {name}", expect, obj)


placement("as rendered", "allow", lambda p: None)
placement("toleration without operator (defaults to Equal)", "allow", lambda p: p["tolerations"][0].pop("operator"))
placement("no node selector", "deny", lambda p: p.pop("nodeSelector"))
placement("other node selector", "deny", lambda p: p.update(nodeSelector={"node-role.kubernetes.io/control-plane": "true"}))
placement("extra toleration", "deny", lambda p: p["tolerations"].append({"key": "node-role.kubernetes.io/control-plane", "operator": "Exists"}))
placement("toleration with Exists", "deny", lambda p: p["tolerations"][0].update(operator="Exists"))
placement("toleration seconds", "deny", lambda p: p["tolerations"][0].update(tolerationSeconds=10))
json.dump(cases, open(sys.argv[3], "w", encoding="utf-8"), indent=1)
print(f"{len(cases)} placement cases")

# ---------------------------------------------------------------- clone grants (own policy)
cases.clear()
IMAGE_NS = "vm-poc"
GRANT_NAME = f"clone-{DEP_NS}"


def grant(**over):
    obj = {
        "apiVersion": "gateway.networking.k8s.io/v1beta1", "kind": "ReferenceGrant",
        "metadata": {"name": GRANT_NAME, "namespace": IMAGE_NS},
        "spec": {"from": [{"group": "", "kind": "PersistentVolumeClaim", "namespace": DEP_NS}],
                 "to": [{"group": "", "kind": "PersistentVolumeClaim", "name": "windows11-matlab-golden"}]},
    }
    for key, value in over.items():
        obj["spec"][key] = value
    return obj


def grant_case(name, expect, obj=None, operation="CREATE", old=None, **kw):
    case(f"grant: {name}", expect, obj, operation, old=old, namespace=kw.pop("namespace", IMAGE_NS), **kw)


good = grant()
grant_case("create", "allow", good)
grant_case("re-apply", "allow", good, "UPDATE", old=good)
grant_case("delete", "allow", None, "DELETE", old=good)
grant_case("another identity is not matched", "allow", grant(to=[{"group": "", "kind": "Secret", "name": "x"}]),
           user="system:serviceaccount:kube-system:somebody")
grant_case("in the platform namespace", "deny", mutated(good, lambda g: g["metadata"].update(namespace=NS)), namespace=NS)
grant_case("in kube-system", "deny", mutated(good, lambda g: g["metadata"].update(namespace="kube-system")), namespace="kube-system")
grant_case("not named after its namespace", "deny", mutated(good, lambda g: g["metadata"].update(name="clone-dep-00000000")))
grant_case("badly named", "deny", mutated(good, lambda g: g["metadata"].update(name="all")))
grant_case("for a namespace outside dep-*", "deny", mutated(good, lambda g: (g["metadata"].update(name="clone-kube-system"), g["spec"]["from"][0].update(namespace="kube-system"))))
grant_case("for two namespaces", "deny", grant(**{"from": good["spec"]["from"] + [{"group": "", "kind": "PersistentVolumeClaim", "namespace": "dep-deadbeef"}]}))
grant_case("from Secrets", "deny", grant(**{"from": [{"group": "", "kind": "Secret", "namespace": DEP_NS}]}))
grant_case("to Secrets", "deny", grant(to=[{"group": "", "kind": "Secret", "name": "x"}]))
grant_case("to two kinds", "deny", grant(to=good["spec"]["to"] + [{"group": "", "kind": "Secret", "name": "x"}]))
grant_case("to every claim", "deny", grant(to=[{"group": "", "kind": "PersistentVolumeClaim"}]))
grant_case("delete a foreign grant", "deny", None, "DELETE", old=mutated(good, lambda g: g["metadata"].update(name="keep-me")))
json.dump(cases, open(sys.argv[4], "w", encoding="utf-8"), indent=1)
print(f"{len(cases)} grant cases")

# ---------------------------------------------------------------- kubevirt-vm namespace (own cases)
# Hand-written from app/k8s/render.py::render_vm of the backend (fixtures.json
# holds pod renders only): what the platform really creates in a VM namespace,
# and every way a misused token could abuse the privileged namespace.
cases.clear()
vm_ns = mutated(ns_obj, lambda n: n["metadata"]["labels"].update({
    "pod-security.kubernetes.io/enforce": "privileged", "appstore.dhbw/vm-namespace": "true"}))
ROLE = "appstore.dhbw/role"
PREFIX = "ghcr.io/dhbw-appstore-t3/novnc-proxy"
base_labels = {"appstore.dhbw/deployment-id": dep_id, "app.kubernetes.io/managed-by": "appstore"}


def vm_case(name, expect, obj=None, operation="CREATE", old=None, **kw):
    kind = kw.pop("kind", None)
    case(name, expect, obj, operation, old=old, ns_object=vm_ns, kind=kind, **kw)


def vm_meta(name):
    return {"name": name, "namespace": DEP_NS, "labels": dict(base_labels)}


vm_pvc = {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": vm_meta("win-disk"),
          "spec": {"storageClassName": "cinder", "accessModes": ["ReadWriteOnce"],
                   "resources": {"requests": {"storage": "80Gi"}},
                   "dataSourceRef": {"apiGroup": "", "kind": "PersistentVolumeClaim",
                                     "name": "windows11-matlab-golden", "namespace": "vm-poc"}}}
virtual_machine = {
    "apiVersion": "kubevirt.io/v1", "kind": "VirtualMachine", "metadata": vm_meta("win"),
    "spec": {"runStrategy": "Always", "template": {
        "metadata": {"labels": {"vm.kubevirt.io/name": "win", ROLE: "vm"}},
        "spec": {
            "domain": {
                "cpu": {"cores": 4}, "memory": {"guest": "8Gi"},
                "devices": {"disks": [{"name": "root", "disk": {"bus": "sata"}}],
                            "interfaces": [{"name": "default", "masquerade": {}, "model": "e1000e"}],
                            "inputs": [{"name": "tablet", "type": "tablet", "bus": "usb"}], "tpm": {}},
                "features": {"hyperv": {}, "acpi": {}},
                "firmware": {"bootloader": {"efi": {"secureBoot": False}}}},
            "networks": [{"name": "default", "pod": {}}],
            "volumes": [{"name": "root", "persistentVolumeClaim": {"claimName": "win-disk"}}]}}},
}
proxy_deploy = {
    "apiVersion": "apps/v1", "kind": "Deployment", "metadata": vm_meta("win-novnc"),
    "spec": {"replicas": 1,
             "selector": {"matchLabels": {"appstore.dhbw/workload": "win-novnc"}},
             "template": {"metadata": {"labels": {ROLE: "vnc-proxy"}}, "spec": {
                 "serviceAccountName": "vnc-proxy", "automountServiceAccountToken": True, "enableServiceLinks": False,
                 "schedulerName": "default-scheduler",
                 "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000,
                                     "seccompProfile": {"type": "RuntimeDefault"}},
                 "containers": [{
                     "name": "novnc", "image": f"{PREFIX}:latest",
                     "ports": [{"name": "http", "containerPort": 8080, "protocol": "TCP"}],
                     "env": [{"name": "VM_NAME", "value": "win"}],
                     "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                         "runAsNonRoot": True, "capabilities": {"drop": ["ALL"]},
                                         "seccompProfile": {"type": "RuntimeDefault"}},
                     "resources": {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"cpu": "200m", "memory": "128Mi"}},
                     "readinessProbe": {"tcpSocket": {"port": "http"}}}]}}},
}


def vm_netpol(name, spec):
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": vm_meta(name), "spec": spec}


VMSEL = {"matchLabels": {ROLE: "vm"}}
PROXYSEL = {"matchLabels": {ROLE: "vnc-proxy"}}
vm_nps = {
    "default-deny": vm_netpol("default-deny", {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}),
    "allow-ingress-controller": vm_netpol("allow-ingress-controller", {
        "podSelector": PROXYSEL, "policyTypes": ["Ingress"],
        "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
                     "ports": [{"protocol": "TCP", "port": 8080}]}]}),
    "allow-dns": vm_netpol("allow-dns", {"podSelector": {}, "policyTypes": ["Egress"], "egress": [{
        "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
        "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}]}),
    "allow-vnc-proxy-to-apiserver": vm_netpol("allow-vnc-proxy-to-apiserver", {
        "podSelector": PROXYSEL, "policyTypes": ["Egress"],
        "egress": [{"to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}, {"ipBlock": {"cidr": "::/0"}}],
                    "ports": [{"protocol": "TCP", "port": 443}, {"protocol": "TCP", "port": 6443}]}]}),
    "allow-egress-internet": vm_netpol("allow-egress-internet", {
        "podSelector": VMSEL, "policyTypes": ["Egress"],
        "egress": copy.deepcopy(internet["spec"]["egress"])}),
    "allow-intra-namespace": vm_netpol("allow-intra-namespace", {
        "podSelector": VMSEL, "policyTypes": ["Ingress", "Egress"],
        "ingress": [{"from": [{"podSelector": VMSEL}]}], "egress": [{"to": [{"podSelector": VMSEL}]}]}),
}
# The ingress controller's namespace is what podApps.ingressNamespace says (see the pod cases).
vm_nps["allow-ingress-controller"]["spec"]["ingress"][0]["from"] = copy.deepcopy(ingress_np["spec"]["ingress"][0]["from"])

vm_case("vm namespace create", "allow", vm_ns)
vm_case("vm namespace re-apply", "allow", vm_ns, "UPDATE", old=vm_ns)
for obj in (vm_pvc, virtual_machine, proxy_deploy, proxy_sa, secret, service, ingress, *vm_nps.values()):
    label = f"{obj['kind']} {obj['metadata']['name']}"
    vm_case(f"vm: {label} create", "allow", obj)
    vm_case(f"vm: {label} re-apply", "allow", obj, "UPDATE", old=obj)
vm_case("vm: the proxy as the API server defaults it (tag :v1, digest)", "allow",
        mutated(proxy_deploy, lambda d: d["spec"]["template"]["spec"]["containers"][0].update(image=f"{PREFIX}@{DIGEST}")))
PINNED = "sha256:" + "0123456789abcdef" * 4
vm_case("vm: the proxy pinned by digest (K8S_VNC_PROXY_IMAGE)", "allow",
        mutated(proxy_deploy, lambda d: d["spec"]["template"]["spec"]["containers"][0].update(image=f"{PREFIX}@{PINNED}")))
vm_case("vm: the proxy pinned by digest, rolled over from :latest", "allow",
        mutated(proxy_deploy, lambda d: d["spec"]["template"]["spec"]["containers"][0].update(image=f"{PREFIX}@{PINNED}")),
        "UPDATE", old=proxy_deploy)
vm_case("vm: lookalike image pinned by digest", "deny",
        mutated(proxy_deploy, lambda d: d["spec"]["template"]["spec"]["containers"][0].update(image=f"{PREFIX}-evil@{PINNED}")))
vm_case("vm: the proxy scaled to 0", "allow", mutated(proxy_deploy, lambda d: d["spec"].update(replicas=0)))
vm_case("vm: the bound claim, re-applied", "allow", mutated(vm_pvc, lambda c: c["spec"].update(volumeName="pvc-1234")), "UPDATE", old=vm_pvc)
vm_case("vm: claim without a clone source", "allow", mutated(vm_pvc, lambda c: c["spec"].pop("dataSourceRef")))
vm_case("vm: VM with defaults KubeVirt adds (sockets/threads 1, machine type)", "allow",
        mutated(virtual_machine, lambda v: (v["spec"]["template"]["spec"]["domain"]["cpu"].update(sockets=1, threads=1),
                                            v["spec"]["template"]["spec"]["domain"].update(machine={"type": "q35"}))))
vm_case("vm: halt the VM (runStrategy)", "allow", mutated(virtual_machine, lambda v: v["spec"].update(runStrategy="Halted")), "UPDATE", old=virtual_machine)
vm_case("vm: delete the VM", "allow", None, "DELETE", old=virtual_machine)
vm_case("vm: delete the claim (reset)", "allow", None, "DELETE", old=vm_pvc)
vm_case("vm: the VM's own pod is not matched", "allow",
        mutated(pod, lambda p: p["spec"]["containers"][0]["securityContext"].update(privileged=True)),
        user="system:serviceaccount:kube-system:replicaset-controller")


def proxy_variant(name, fn):
    vm_case(f"vm deployment: {name}", "deny", mutated(proxy_deploy, lambda d: fn(d["spec"]["template"]["spec"])))


pc = lambda p: p["containers"][0]  # noqa: E731
proxy_variant("privileged container", lambda p: pc(p)["securityContext"].update(privileged=True))
proxy_variant("hostPath volume", lambda p: p.update(volumes=[{"name": "root", "hostPath": {"path": "/"}}]))
proxy_variant("secret volume", lambda p: p.update(volumes=[{"name": "s", "secret": {"secretName": "x"}}]))
proxy_variant("emptyDir without a limit", lambda p: p.update(volumes=[{"name": "e", "emptyDir": {}}]))
proxy_variant("hostNetwork", lambda p: p.update(hostNetwork=True))
proxy_variant("hostPID", lambda p: p.update(hostPID=True))
proxy_variant("hostIPC", lambda p: p.update(hostIPC=True))
proxy_variant("wrong service account", lambda p: p.update(serviceAccountName="appstore-t3-pod-deployer"))
proxy_variant("default service account", lambda p: p.pop("serviceAccountName"))
proxy_variant("image outside the prefix", lambda p: pc(p).update(image=f"docker.io/evil/img@{DIGEST}"))
proxy_variant("another platform image", lambda p: pc(p).update(image="ghcr.io/dhbw-appstore-t3/backend:latest"))
proxy_variant("lookalike image", lambda p: pc(p).update(image=f"{PREFIX}-evil:latest"))
proxy_variant("added capability", lambda p: pc(p)["securityContext"].update(capabilities={"drop": ["ALL"], "add": ["SYS_ADMIN"]}))
proxy_variant("capabilities not dropped", lambda p: pc(p)["securityContext"].pop("capabilities"))
proxy_variant("host port", lambda p: pc(p)["ports"][0].update(hostPort=80))
proxy_variant("privilege escalation", lambda p: pc(p)["securityContext"].update(allowPrivilegeEscalation=True))
proxy_variant("may run as root (container)", lambda p: pc(p)["securityContext"].update(runAsNonRoot=False))
proxy_variant("may run as root (pod)", lambda p: p["securityContext"].update(runAsNonRoot=False))
proxy_variant("writable root file system", lambda p: pc(p)["securityContext"].update(readOnlyRootFilesystem=False))
proxy_variant("second container", lambda p: p["containers"].append(dict(copy.deepcopy(pc(p)), name="two")))
proxy_variant("privileged init container", lambda p: p.update(initContainers=[dict(copy.deepcopy(pc(p)), name="init", securityContext={"privileged": True})]))
proxy_variant("pinned to a node", lambda p: p.update(nodeName="k3s-server"))
proxy_variant("priority class", lambda p: p.update(priorityClassName="system-node-critical"))
proxy_variant("runtime class", lambda p: p.update(runtimeClassName="x"))
proxy_variant("no limits", lambda p: pc(p)["resources"].pop("limits"))
proxy_variant("cpu above the ceiling", lambda p: pc(p)["resources"]["limits"].update(cpu="64"))
vm_case("vm deployment: 2 replicas", "deny", mutated(proxy_deploy, lambda d: d["spec"].update(replicas=2)))
vm_case("vm deployment: 100 replicas", "deny", mutated(proxy_deploy, lambda d: d["spec"].update(replicas=100)))
case("deployment in an ordinary app namespace", "deny", proxy_deploy)
vm_case("vm deployment: delete", "deny", None, "DELETE", old=proxy_deploy)


def vm_variant(name, fn):
    vm_case(f"vm: VirtualMachine {name}", "deny", mutated(virtual_machine, lambda v: fn(v["spec"]["template"]["spec"], v)))


vm_variant("with a host disk", lambda s, v: (s["volumes"].append({"name": "h", "hostDisk": {"path": "/x", "type": "Disk"}}),
                                             s["domain"]["devices"]["disks"].append({"name": "h", "disk": {"bus": "sata"}})))
vm_variant("with a container disk", lambda s, v: s["volumes"].append({"name": "c", "containerDisk": {"image": "evil/img"}}))
vm_variant("with cloud-init (no cloud)", lambda s, v: s["volumes"].append({"name": "ci", "cloudInitNoCloud": {"userData": "x"}}))
vm_variant("with cloud-init (config drive)", lambda s, v: s["volumes"].append({"name": "ci", "cloudInitConfigDrive": {"userData": "x"}}))
vm_variant("with a secret volume", lambda s, v: s["volumes"].append({"name": "sec", "secret": {"secretName": "x"}}))
vm_variant("with a config map volume", lambda s, v: s["volumes"].append({"name": "cm", "configMap": {"name": "x"}}))
vm_variant("with a service account volume", lambda s, v: s["volumes"].append({"name": "sa", "serviceAccount": {"serviceAccountName": "x"}}))
vm_variant("with a data volume", lambda s, v: s["volumes"].append({"name": "dv", "dataVolume": {"name": "x"}}))
vm_variant("claim volume that is also a host disk", lambda s, v: s["volumes"][0].update(hostDisk={"path": "/x", "type": "Disk"}))
vm_variant("with host devices", lambda s, v: s["domain"]["devices"].update(hostDevices=[{"name": "d", "deviceName": "x/y"}]))
vm_variant("with a GPU", lambda s, v: s["domain"]["devices"].update(gpus=[{"name": "g", "deviceName": "nvidia.com/x"}]))
vm_variant("with a file system share", lambda s, v: s["domain"]["devices"].update(filesystems=[{"name": "f", "virtiofs": {}}]))
vm_variant("with a virtio disk bus", lambda s, v: s["domain"]["devices"]["disks"][0]["disk"].update(bus="virtio"))
vm_variant("with a LUN", lambda s, v: (s["domain"]["devices"]["disks"][0].pop("disk"), s["domain"]["devices"]["disks"][0].update(lun={"bus": "sata"})))
vm_variant("with a bridge interface", lambda s, v: (s["domain"]["devices"]["interfaces"][0].pop("masquerade"), s["domain"]["devices"]["interfaces"][0].update(bridge={})))
vm_variant("with an SR-IOV interface", lambda s, v: s["domain"]["devices"]["interfaces"][0].update(sriov={}))
vm_variant("with a multus network", lambda s, v: s["networks"].append({"name": "m", "multus": {"networkName": "x"}}))
vm_variant("with a keyboard input", lambda s, v: s["domain"]["devices"]["inputs"][0].update(type="keyboard"))
vm_variant("64 cores", lambda s, v: s["domain"]["cpu"].update(cores=64))
vm_variant("4 sockets", lambda s, v: s["domain"]["cpu"].update(sockets=4))
vm_variant("without a core count", lambda s, v: s["domain"]["cpu"].pop("cores"))
vm_variant("dedicated CPUs", lambda s, v: s["domain"]["cpu"].update(dedicatedCpuPlacement=True))
vm_variant("128Gi of memory", lambda s, v: s["domain"]["memory"].update(guest="128Gi"))
vm_variant("without guest memory", lambda s, v: s["domain"].pop("memory"))
vm_variant("huge pages", lambda s, v: s["domain"]["memory"].update(hugepages={"pageSize": "2Mi"}))
vm_variant("a memory request above the ceiling", lambda s, v: s["domain"].update(resources={"requests": {"memory": "256Gi"}}))
vm_variant("a cpu limit above the ceiling", lambda s, v: s["domain"].update(resources={"limits": {"cpu": "64"}}))
vm_variant("kernel boot from an image", lambda s, v: s["domain"]["firmware"].update(kernelBoot={"container": {"image": "evil/img"}}))
vm_variant("tolerating the control plane", lambda s, v: s.update(tolerations=[{"key": "node-role.kubernetes.io/control-plane", "operator": "Exists"}]))
vm_variant("with a node selector", lambda s, v: s.update(nodeSelector={"a": "b"}))
vm_variant("with a priority class", lambda s, v: s.update(priorityClassName="system-node-critical"))
vm_variant("with access credentials", lambda s, v: s.update(accessCredentials=[{"sshPublicKey": {}}]))
vm_variant("with a hook sidecar", lambda s, v: v["spec"]["template"]["metadata"].update(annotations={"hooks.kubevirt.io/hookSidecars": '[{"image":"evil"}]'}))
vm_variant("with data volume templates", lambda s, v: v["spec"].update(dataVolumeTemplates=[{"metadata": {"name": "x"}}]))
vm_variant("with an instance type", lambda s, v: v["spec"].update(instancetype={"name": "huge"}))
case("vm: VirtualMachine in an ordinary app namespace", "deny", virtual_machine)
vmi = {"apiVersion": "kubevirt.io/v1", "kind": "VirtualMachineInstance", "metadata": vm_meta("win"),
       "spec": copy.deepcopy(virtual_machine["spec"]["template"]["spec"])}
vm_case("vm: VirtualMachineInstance create", "deny", vmi)
vm_case("vm: VirtualMachineInstance update", "deny", vmi, "UPDATE", old=vmi)
vm_case("vm: VirtualMachineInstance delete", "deny", None, "DELETE", old=vmi)

# claims
vm_case("vm: claim of 500Gi", "deny", mutated(vm_pvc, lambda c: c["spec"]["resources"]["requests"].update(storage="500Gi")))
vm_case("vm: claim without a size", "deny", mutated(vm_pvc, lambda c: c["spec"].pop("resources")))
vm_case("vm: claim of another storage class", "deny", mutated(vm_pvc, lambda c: c["spec"].update(storageClassName="local-path")))
vm_case("vm: claim without a storage class", "deny", mutated(vm_pvc, lambda c: c["spec"].pop("storageClassName")))
vm_case("vm: claim cloned from kube-system", "deny", mutated(vm_pvc, lambda c: c["spec"]["dataSourceRef"].update(namespace="kube-system")))
vm_case("vm: claim cloned from the platform namespace", "deny", mutated(vm_pvc, lambda c: c["spec"]["dataSourceRef"].update(namespace=NS)))
vm_case("vm: claim cloned from a snapshot", "deny", mutated(vm_pvc, lambda c: c["spec"]["dataSourceRef"].update(kind="VolumeSnapshot", apiGroup="snapshot.storage.k8s.io")))
vm_case("vm: claim cloned from a secret", "deny", mutated(vm_pvc, lambda c: c["spec"]["dataSourceRef"].update(kind="Secret")))
vm_case("vm: claim cloned from a claim of the own namespace (no namespace)", "deny", mutated(vm_pvc, lambda c: c["spec"]["dataSourceRef"].pop("namespace")))
vm_case("vm: claim from another API group", "deny", mutated(vm_pvc, lambda c: c["spec"]["dataSourceRef"].update(apiGroup="evil.example")))
vm_case("vm: claim with a dataSource from another group", "deny", mutated(vm_pvc, lambda c: c["spec"].update(dataSource={"kind": "VolumeSnapshot", "apiGroup": "snapshot.storage.k8s.io", "name": "x"})))
vm_case("vm: claim bound to a chosen volume", "deny", mutated(vm_pvc, lambda c: c["spec"].update(volumeName="pv-of-someone-else")))
vm_case("vm: claim with a selector", "deny", mutated(vm_pvc, lambda c: c["spec"].update(selector={"matchLabels": {"a": "b"}})))
vm_case("vm: claim ReadWriteMany", "deny", mutated(vm_pvc, lambda c: c["spec"].update(accessModes=["ReadWriteMany"])))

# network policies


def vm_np_variant(name, base, fn):
    vm_case(f"vm network policy: {name}", "deny", mutated(vm_nps[base], fn))


vm_np_variant("ingress from everywhere", "allow-ingress-controller", lambda n: n["spec"]["ingress"][0].pop("from"))
vm_np_variant("ingress from 0.0.0.0/0", "allow-ingress-controller", lambda n: n["spec"]["ingress"][0].update({"from": [{"ipBlock": {"cidr": "0.0.0.0/0"}}]}))
vm_np_variant("ingress from every pod of the namespace", "allow-ingress-controller", lambda n: n["spec"]["ingress"][0].update({"from": [{"podSelector": {}}]}))
vm_np_variant("ingress rule open to all peers", "default-deny", lambda n: n["spec"].update(ingress=[{}]))
vm_np_variant("ingress from 0.0.0.0/0 on a policy selecting the VMs", "allow-intra-namespace", lambda n: n["spec"]["ingress"].append({"from": [{"ipBlock": {"cidr": "0.0.0.0/0"}}]}))
vm_np_variant("selects other pods", "allow-dns", lambda n: n["spec"].update(podSelector={"matchLabels": {"app": "x"}}))
vm_np_variant("selects by expression", "allow-dns", lambda n: n["spec"].update(podSelector={"matchExpressions": [{"key": ROLE, "operator": "Exists"}]}))
vm_np_variant("selects a role and more", "allow-dns", lambda n: n["spec"].update(podSelector={"matchLabels": {ROLE: "vm", "a": "b"}}))
vm_np_variant("egress everywhere", "allow-egress-internet", lambda n: n["spec"]["egress"][0].pop("to"))
vm_np_variant("egress to a private range", "allow-egress-internet", lambda n: n["spec"]["egress"][0]["to"][0]["ipBlock"].pop("except"))
vm_np_variant("egress to the metadata service", "allow-egress-internet", lambda n: n["spec"]["egress"][0]["to"][0]["ipBlock"]["except"].remove("169.254.0.0/16"))
vm_np_variant("apiserver rule on every port", "allow-vnc-proxy-to-apiserver", lambda n: n["spec"]["egress"][0].pop("ports"))
vm_np_variant("apiserver rule with port 22", "allow-vnc-proxy-to-apiserver", lambda n: n["spec"]["egress"][0]["ports"].append({"protocol": "TCP", "port": 22}))
vm_np_variant("apiserver rule with UDP", "allow-vnc-proxy-to-apiserver", lambda n: n["spec"]["egress"][0]["ports"][0].update(protocol="UDP"))
vm_np_variant("apiserver rule with a port range", "allow-vnc-proxy-to-apiserver", lambda n: n["spec"]["egress"][0]["ports"][0].update(port=1, endPort=65535))
vm_np_variant("apiserver rule for every pod", "allow-vnc-proxy-to-apiserver", lambda n: n["spec"].update(podSelector={}))
vm_np_variant("apiserver rule for the VMs", "allow-vnc-proxy-to-apiserver", lambda n: n["spec"].update(podSelector=VMSEL))
vm_np_variant("apiserver rule to a namespace", "allow-vnc-proxy-to-apiserver", lambda n: n["spec"]["egress"][0]["to"].append({"namespaceSelector": {}}))
vm_np_variant("apiserver-like rule under another name", "allow-vnc-proxy-to-apiserver", lambda n: n["metadata"].update(name="allow-anything"))
vm_np_variant("intra-namespace for every pod", "allow-intra-namespace", lambda n: n["spec"].update(podSelector={}))
vm_np_variant("intra-namespace towards every pod (egress)", "allow-intra-namespace", lambda n: n["spec"]["egress"][0]["to"][0].update(podSelector={}))
vm_np_variant("intra-namespace towards the proxies (egress)", "allow-intra-namespace", lambda n: n["spec"]["egress"][0]["to"][0].update(podSelector=PROXYSEL))
vm_np_variant("intra-namespace plus a namespace selector", "allow-intra-namespace", lambda n: n["spec"]["egress"][0]["to"][0].update(namespaceSelector={}))
vm_np_variant("intra-namespace plus an address block", "allow-intra-namespace", lambda n: n["spec"]["egress"][0]["to"].append({"ipBlock": {"cidr": "0.0.0.0/0"}}))
vm_np_variant("VM peer rule under another name", "allow-intra-namespace", lambda n: n["metadata"].update(name="allow-vms"))
vm_np_variant("egress to kube-system as a whole", "allow-dns", lambda n: n["spec"]["egress"][0]["to"][0].pop("podSelector"))
vm_case("vm network policy: delete", "deny", None, "DELETE", old=vm_nps["allow-dns"])

json.dump(cases, open(sys.argv[5], "w", encoding="utf-8"), indent=1)
print(f"{len(cases)} vm cases")
