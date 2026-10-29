"""Does the cluster really enforce what the NetworkPolicies of the student pods say?

    python k8s/tests/netcheck/netcheck.py [--blocked HOST:PORT ...] [--keep]

The chart's tests check the policies' content (k8s/tests/policy); kind's CNI enforces none of them, and
a policy is worth what the CNI of the real cluster does with it. This runs on a cluster (staging) with kubectl
and creates two namespaces of its own (netcheck-a, netcheck-b), the way the renderer's policies are:
deny all, an internet rule with the platform's exclusion list. Pods run python:3.12-slim-trixie.

  1. Isolation: no pod reaches another namespace's pod or a service the platform runs (--blocked), even though
     the target listens.
  2. Broadcast and multicast: UDP to 255.255.255.255, 224.0.0.1, a multicast group and ff02::1 reaches no pod
     of another namespace (the pods of a node share one Layer-2 segment; see k8s/cluster/node-netguard.yaml).
  3. Start-up (reported, not failed): how long a fresh pod reaches a target without an ingress policy,
     before its own policy is enforced.

Exit status 1 if (1) or (2) shows a leak. Needs kubectl with rights to create namespaces and pods.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import sys
import textwrap
import time

IMAGE = "docker.io/library/python:3.12-slim-trixie"
A, B = "netcheck-a", "netcheck-b"
V4 = ["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
      "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/3"]
V6 = ["::1/128", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2002::/16", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8"]

LISTEN = textwrap.dedent("""
    import select, socket, sys, time
    s4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s4.bind(("", 9999))
    s4.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton("239.1.2.3") + socket.inet_aton("0.0.0.0"))
    s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM); s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1); s6.bind(("::", 9999))
    t = socket.socket(); t.bind(("", 7777)); t.listen(5)
    end = time.time() + float(sys.argv[1])
    while time.time() < end:
        r, _, _ = select.select([s4, s6], [], [], 1)
        for s in r:
            d, a = s.recvfrom(200); print("GOT", d.decode(), flush=True)
""")
SEND = textwrap.dedent("""
    import socket, sys, time
    me = sys.argv[1]; ifx = socket.if_nametoindex("eth0")
    def v4(d):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1); return s, (d, 9999)
    def v6(d):
        return socket.socket(socket.AF_INET6, socket.SOCK_DGRAM), (d, 9999, 0, ifx)
    for label, (s, a) in [("limited broadcast", v4("255.255.255.255")), ("multicast 224.0.0.1", v4("224.0.0.1")),
                          ("multicast 239.1.2.3", v4("239.1.2.3")), ("IPv6 multicast ff02::1", v6("ff02::1"))]:
        for i in range(3):
            s.sendto((me + "|" + label).encode(), a); time.sleep(0.15)
""")
PROBE = textwrap.dedent("""
    import errno, socket, sys, time
    T0 = time.time(); first = {}
    targets = [t.rsplit(":", 1) for t in sys.argv[2:]]
    while time.time() - T0 < float(sys.argv[1]):
        for host, port in targets:
            fam = socket.AF_INET6 if ":" in host.strip("[]") else socket.AF_INET
            s = socket.socket(fam, socket.SOCK_STREAM); s.settimeout(0.3)
            try:
                s.connect((host.strip("[]"), int(port)))
                first.setdefault(host + ":" + port, round(time.time() - T0, 3))
            except OSError:
                pass
            finally:
                s.close()
    print("FIRST_OPEN", first, flush=True)
""")


def kubectl(*args: str, stdin: str | None = None, check: bool = True) -> str:
    r = subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"kubectl {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout


def pod(name: str, ns: str, role: str, command: list[str] | None = None) -> str:
    cmd = command or ["sleep", "900"]
    return f"""---
apiVersion: v1
kind: Pod
metadata: {{name: {name}, namespace: {ns}, labels: {{role: {role}, purpose: netcheck}}}}
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext: {{runAsNonRoot: true, runAsUser: 1000, runAsGroup: 1000, seccompProfile: {{type: RuntimeDefault}}}}
  containers:
    - name: c
      image: {IMAGE}
      command: {json.dumps(cmd)}
      resources: {{requests: {{cpu: 10m, memory: 32Mi}}, limits: {{cpu: 200m, memory: 128Mi}}}}
      securityContext: {{allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {{drop: [ALL]}}}}
"""


def manifests() -> str:
    out = ""
    for ns in (A, B):
        out += f"""---
apiVersion: v1
kind: Namespace
metadata: {{name: {ns}, labels: {{purpose: netcheck}}}}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {{name: default-deny, namespace: {ns}}}
spec: {{podSelector: {{}}, policyTypes: [Ingress, Egress]}}
"""
    out += f"""---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {{name: allow-egress-internet, namespace: {A}}}
spec:
  podSelector: {{matchLabels: {{role: internet}}}}
  policyTypes: [Egress]
  egress:
    - to: [{{ipBlock: {{cidr: 0.0.0.0/0, except: {V4!r}}}}}]
      ports: [{{protocol: TCP, port: 80}}, {{protocol: TCP, port: 443}}]
    - to: [{{ipBlock: {{cidr: "::/0", except: {V6!r}}}}}]
      ports: [{{protocol: TCP, port: 80}}, {{protocol: TCP, port: 443}}]
"""
    out += pod("listen-a", A, "none") + pod("send-internet", A, "internet") + pod("send-none", A, "none")
    out += pod("listen-b", B, "none")
    return out


def exec_py(ns: str, name: str, code: str, *args: str, timeout: int = 90) -> str:
    r = subprocess.run(["kubectl", "-n", ns, "exec", "-i", name, "--", "python3", "-", *args],
                       input=code, capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def wait_running(names: list[tuple[str, str]]) -> dict[str, tuple[str, str]]:
    ips: dict[str, tuple[str, str]] = {}
    for ns, n in names:
        for _ in range(60):
            phase = kubectl("-n", ns, "get", "pod", n, "-o", "jsonpath={.status.phase}", check=False)
            if phase == "Running":
                break
            time.sleep(3)
        else:
            sys.exit(f"pod {ns}/{n} did not start")
        addrs = kubectl("-n", ns, "get", "pod", n, "-o", "jsonpath={.status.podIPs[*].ip}").split()
        ips[n] = (next((a for a in addrs if ":" not in a), ""), next((a for a in addrs if ":" in a), ""))
    return ips


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocked", nargs="*", default=[], help="host:port a student pod must not reach (a platform service)")
    ap.add_argument("--keep", action="store_true", help="leave the namespaces (netcheck-a/b) in place")
    args = ap.parse_args()
    failures: list[str] = []
    tmp = tempfile.mkdtemp(prefix="netcheck-")
    try:
        kubectl("delete", "ns", A, B, "--ignore-not-found", "--wait=true")  # leftovers of an earlier run
        kubectl("apply", "-f", "-", stdin=manifests())
        ips = wait_running([(A, "listen-a"), (A, "send-internet"), (A, "send-none"), (B, "listen-b")])
        time.sleep(8)  # let the policies settle: this part is about steady state

        print("1. isolation (steady state)")
        targets = [f"{ips['listen-b'][1]}:7777", f"{ips['listen-b'][0]}:7777", f"{ips['listen-a'][1]}:7777",
                   *args.blocked]
        for who in ("send-internet", "send-none"):
            out = exec_py(A, who, PROBE, "6", *targets)
            leaked = "FIRST_OPEN {}" not in out
            print(f"   {who}: {'LEAK ' + out.strip() if leaked else 'nothing reachable'}")
            if leaked:
                failures.append(f"{who} reaches {out.strip()}")

        print("2. broadcast and multicast across namespaces")
        for ns, listener in ((A, "listen-a"), (B, "listen-b")):
            p = subprocess.Popen(["kubectl", "-n", ns, "exec", "-i", listener, "--", "python3", "-", "40"],
                                 stdin=subprocess.PIPE, stdout=open(f"{tmp}/{listener}.out", "w"), text=True)
            p.stdin.write(LISTEN)  # type: ignore[union-attr]
            p.stdin.close()  # type: ignore[union-attr]
        time.sleep(10)
        exec_py(A, "send-internet", SEND, "internet")
        exec_py(A, "send-none", SEND, "none")
        time.sleep(6)
        for listener in ("listen-a", "listen-b"):
            got = sorted({line.split("GOT ")[1].strip() for line in open(f"{tmp}/{listener}.out") if "GOT " in line})
            print(f"   {listener}: {'received ' + ', '.join(got) if got else 'nothing received'}")
            failures += [f"{listener} received {g}" for g in got]

        print("3. start-up window (reported only)")
        sink = ips["listen-b"]
        for i in range(3):
            kubectl("apply", "-f", "-", stdin=pod(f"fresh-{i}", A, "none",
                    ["python3", "-c", PROBE, "6", f"{sink[1]}:7777"]))
        time.sleep(25)
        for i in range(3):
            out = kubectl("-n", A, "logs", f"fresh-{i}", check=False).strip()
            print(f"   fresh-{i}: {out or 'no output'}")
    finally:
        if not args.keep:
            for ns in (A, B):
                kubectl("delete", "ns", ns, "--wait=false", check=False)
    print("\nFAILED:\n  " + "\n  ".join(failures) if failures else "\nOK: isolation holds")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
