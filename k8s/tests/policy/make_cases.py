"""Admission requests for the pod deployer's policy, and what it must answer.

    python make_cases.py fixtures.json cases.json placement.json

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


def binding(name, role, account):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
        "metadata": {"name": name, "namespace": DEP_NS,
                     "labels": {"appstore.dhbw/deployment-id": dep_id, "app.kubernetes.io/managed-by": "appstore"}},
        "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": role},
        "subjects": [{"kind": "ServiceAccount", "name": account, "namespace": NS}],
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
scale = {"apiVersion": "autoscaling/v1", "kind": "Scale", "metadata": {"name": sts["metadata"]["name"], "namespace": DEP_NS},
         "spec": {"replicas": 0}}
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
pod_variant("pinned to a node", lambda p: p.update(nodeName="k3s-server"))
pod_variant("priority class", lambda p: p.update(priorityClassName="system-node-critical"))
pod_variant("another scheduler", lambda p: p.update(schedulerName="my-scheduler"))
pod_variant("tolerates the control plane", lambda p: p.update(tolerations=[{"key": "node-role.kubernetes.io/control-plane", "operator": "Exists"}]))
pod_variant("host port", lambda p: c0(p)["ports"][0].update(hostPort=8080))
pod_variant("privileged init container", lambda p: p.update(initContainers=[dict(copy.deepcopy(c0(p)), name="init", securityContext={"privileged": True})]))
pod_variant("runtime class", lambda p: p.update(runtimeClassName="runc-unsafe"))
case("statefulset: other storage class", "deny",
     mutated(sts, lambda s: s["spec"]["volumeClaimTemplates"][0]["spec"].update(storageClassName="fast-hostpath")))


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
