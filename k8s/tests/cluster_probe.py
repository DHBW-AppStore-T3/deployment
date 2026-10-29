"""RBAC and admission policy of the chart against a real API server (kind in CI).

    python k8s/tests/cluster_probe.py <rendered staging manifests> k8s/tests/policy/fixtures.json

Installs only the chart's RBAC and admission policy (and the namespace they
live in), then acts as the pod deployer and as the API with kubectl --as:
what app/k8s/kube.py really does must work, what an attacker in control of
either account would try must be refused. Needs kubectl with cluster-admin
(impersonation) and PyYAML.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import time

import yaml

NS = "appstore-staging"
DEPLOYER = f"system:serviceaccount:{NS}:appstore-t3-pod-deployer"
API = f"system:serviceaccount:{NS}:appstore-t3-api"
ZONE = "t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site"
failures: list[str] = []


def kubectl(*args: str, stdin: str | None = None, user: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["kubectl", *args] + (["--as", user] if user else [])
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True)


def expect(name: str, ok: bool, result: subprocess.CompletedProcess) -> None:
    passed = (result.returncode == 0) == ok
    status = "ok  " if passed else "FAIL"
    print(f"{status} {'allowed' if result.returncode == 0 else 'refused'}  {name}")
    if not passed:
        failures.append(name)
        print("     ", (result.stderr or result.stdout).strip()[:400])


def apply(obj: dict, user: str = DEPLOYER) -> subprocess.CompletedProcess:
    return kubectl("apply", "--server-side", "--field-manager=appstore", "--force-conflicts", "-f", "-",
                   stdin=json.dumps(obj), user=user)


def main() -> None:
    manifests = [d for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")) if d]
    fixtures = json.load(open(sys.argv[2], encoding="utf-8"))
    dep_ns = fixtures["deployment"]["namespace"]
    objects = fixtures["default"]

    # The chart's identities, RBAC and policy; nothing else of it.
    wanted = {"ServiceAccount", "ClusterRole", "ClusterRoleBinding",
              "ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"}
    kubectl("create", "namespace", NS)
    for doc in manifests:
        if doc["kind"] in wanted and doc["metadata"].get("labels", {}).get("app.kubernetes.io/part-of") == "appstore-t3":
            if doc["kind"] == "ServiceAccount":
                doc["metadata"]["namespace"] = NS
            result = kubectl("apply", "-f", "-", stdin=json.dumps(doc))
            if result.returncode != 0:
                sys.exit(f"cannot install {doc['kind']} {doc['metadata']['name']}: {result.stderr}")

    namespace = objects[0]
    # The policy takes effect asynchronously: wait until a dry run of a
    # forbidden namespace is refused (a dry run passes admission too).
    probe = copy.deepcopy(namespace)
    probe["metadata"]["name"] = "not-a-dep-namespace"
    deadline = time.time() + 90
    while kubectl("apply", "--server-side", "--dry-run=server", "--field-manager=appstore", "-f", "-",
                  stdin=json.dumps(probe), user=DEPLOYER).returncode == 0:
        if time.time() > deadline:
            sys.exit("the admission policy did not take effect")
        time.sleep(2)
    role_bindings = [
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
         "metadata": {"name": name, "namespace": dep_ns,
                      "labels": {"appstore.dhbw/deployment-id": fixtures["deployment"]["id"],
                                 "app.kubernetes.io/managed-by": "appstore"}},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": f"appstore-t3-{NS}-{role}"},
         "subjects": [{"kind": "ServiceAccount", "name": account, "namespace": NS}]}
        for name, role, account in (("appstore-deployer", "deployer", "appstore-t3-pod-deployer"),
                                    ("appstore-api-reader", "reader", "appstore-t3-api"))
    ]

    # --- what the pod deployer does (pod_tasks.deploy_application)
    expect("deployer creates its namespace (server-side apply)", True, apply(namespace))
    for rb in role_bindings:
        expect(f"deployer binds {rb['metadata']['name']}", True, apply(rb))
    for obj in objects[1:]:
        expect(f"deployer applies {obj['kind']} {obj['metadata']['name']}", True, apply(obj))
    for obj in objects[1:3]:
        expect(f"deployer re-applies {obj['kind']} {obj['metadata']['name']}", True, apply(obj))
    sts = next(o for o in objects if o["kind"] == "StatefulSet")
    name = sts["metadata"]["name"]
    expect("deployer scales to 0", True,
           kubectl("scale", "statefulset", name, "-n", dep_ns, "--replicas=0", user=DEPLOYER))
    expect("deployer scales to 1", True,
           kubectl("scale", "statefulset", name, "-n", dep_ns, "--replicas=1", user=DEPLOYER))
    expect("deployer lists pods, claims and events", True,
           kubectl("get", "pods,pvc,events,statefulsets", "-n", dep_ns, user=DEPLOYER))
    expect("deployer deletes claims of a workload", True,
           kubectl("delete", "pvc", "-n", dep_ns, "-l", f"appstore.dhbw/workload={name}", user=DEPLOYER))

    # --- what the API does (k8s_status, k8s_orphans)
    expect("API lists namespaces", True, kubectl("get", "namespaces", user=API))
    expect("API reads the workloads", True, kubectl("get", "statefulsets,pods,pvc,events", "-n", dep_ns, user=API))
    expect("API cannot read secrets", False, kubectl("get", "secrets", "-n", dep_ns, user=API))
    expect("API cannot change workloads", False,
           kubectl("scale", "statefulset", name, "-n", dep_ns, "--replicas=0", user=API))

    # --- refused: RBAC
    expect("deployer cannot read secrets", False, kubectl("get", "secrets", "-n", dep_ns, user=DEPLOYER))
    expect("deployer cannot touch the platform namespace", False,
           kubectl("get", "secrets", "-n", NS, user=DEPLOYER))
    expect("deployer cannot exec into pods", False,
           kubectl("auth", "can-i", "create", "pods/exec", "-n", dep_ns, user=DEPLOYER))
    expect("deployer cannot create pods directly", False,
           kubectl("auth", "can-i", "create", "pods", "-n", dep_ns, user=DEPLOYER))
    expect("deployer cannot create cluster roles", False,
           kubectl("auth", "can-i", "create", "clusterroles", user=DEPLOYER))

    # --- refused: admission policy
    other = copy.deepcopy(namespace)
    other["metadata"]["name"] = "kube-evil"
    expect("deployer cannot create other namespaces", False, apply(other))
    prod = copy.deepcopy(namespace)
    prod["metadata"]["name"] = "dep-0badc0de"
    prod["metadata"]["labels"]["appstore.dhbw/environment"] = "appstore-prod"
    expect("deployer cannot create another installation's namespace", False, apply(prod))
    admin = copy.deepcopy(role_bindings[0])
    admin["roleRef"]["name"] = "cluster-admin"
    expect("deployer cannot bind cluster-admin", False, apply(admin))
    privileged = copy.deepcopy(sts)
    privileged["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"] = True
    expect("deployer cannot run privileged pods", False, apply(privileged))
    hijack = copy.deepcopy(next(o for o in objects if o["kind"] == "Ingress"))
    hijack["spec"]["rules"][0]["host"] = f"appstore.{ZONE}"
    hijack["spec"]["tls"][0]["hosts"] = [f"appstore.{ZONE}"]
    expect("deployer cannot route the platform's host", False, apply(hijack))
    quota = next(o for o in objects if o["kind"] == "ResourceQuota")
    expect("deployer cannot delete the quota", False,
           kubectl("delete", "resourcequota", quota["metadata"]["name"], "-n", dep_ns, user=DEPLOYER))

    # --- the controller's pods pass Pod Security "restricted" of the namespace
    deadline = time.time() + 60
    while time.time() < deadline:
        pods = kubectl("get", "pods", "-n", dep_ns, "-o", "name")
        if pods.stdout.strip():
            break
        time.sleep(2)
    expect("the StatefulSet controller's pods pass Pod Security restricted", True,
           subprocess.CompletedProcess([], 0 if pods.stdout.strip() else 1, "", kubectl("get", "events", "-n", dep_ns).stdout))

    # --- destroy
    expect("deployer deletes its namespace", True, kubectl("delete", "namespace", dep_ns, "--wait=false", user=DEPLOYER))

    print(f"\n{len(failures)} failed" if failures else "\nall probes passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
