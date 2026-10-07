"""Tests for the pure Kubernetes renderer (golden file + invariants)."""

import json
import os
from pathlib import Path

import pytest

from appstore_shared.k8s.render import (
    DEPLOYMENT_LABEL,
    DeploymentCtx,
    RenderSettings,
    Team,
    render,
    render_access,
    workload_refs,
)
from appstore_shared.k8s.spec import parse_spec
from tests.test_k8s_spec import VALID

GOLDEN = Path(__file__).parent / "golden" / "online_ide_3_teams.json"
DEP = DeploymentCtx(id="123e4567-e89b-12d3-a456-426614174000", course="WWI24 SEA", owner="dozent@dhbw.de")
SETTINGS = RenderSettings(
    zone="t3-k8s.example.org",
    cluster_issuer="letsencrypt",
    storage_class="local-path",
    node_selector={"appstore.dhbw/workload": "student"},
    tolerations=({"key": "appstore.dhbw/workload", "operator": "Equal", "value": "student", "effect": "NoSchedule"},),
)
TEAMS = [Team("team-a", ("alice", "bob")), Team("team-b", ("carol", "dave")), Team("team-c", ("erin", "frank"))]


def build(spec_data=VALID, teams=TEAMS, settings=SETTINGS):
    spec = parse_spec(spec_data)
    refs = workload_refs(spec, teams)
    passwords = {r.name: f"pw-{r.name}" for r in refs}
    return spec, render(spec, DEP, teams, settings, passwords), passwords


def of_kind(objs, kind):
    return [o for o in objs if o["kind"] == kind]


def test_matches_golden_file():
    _, objs, _ = build()
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(objs, indent=2, sort_keys=True) + "\n")
    assert objs == json.loads(GOLDEN.read_text())


def test_render_is_deterministic():
    assert build()[1] == build()[1]


def test_six_workloads_for_scope_user_three_for_scope_team():
    assert len(of_kind(build()[1], "StatefulSet")) == 6
    team_scope = {**VALID, "scope": "team"}
    assert len(of_kind(build(team_scope)[1], "StatefulSet")) == 3


def test_every_object_carries_deployment_label_and_namespace():
    _, objs, _ = build()
    for o in objs:
        assert o["metadata"]["labels"][DEPLOYMENT_LABEL] == DEP.id
        if o["kind"] != "Namespace":
            assert o["metadata"]["namespace"] == "dep-123e4567"


def test_namespace_enforces_restricted_pod_security():
    ns = of_kind(build()[1], "Namespace")[0]
    assert ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_pods_are_hardened_and_cannot_be_weakened_by_spec():
    for sts in of_kind(build()[1], "StatefulSet"):
        pod = sts["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
        for c in pod["containers"]:
            sc = c["securityContext"]
            assert sc["allowPrivilegeEscalation"] is False
            assert sc["capabilities"] == {"drop": ["ALL"]}
            assert sc["readOnlyRootFilesystem"] is True
        assert "hostNetwork" not in pod and "hostPID" not in pod
        assert all("hostPath" not in v for v in pod["volumes"])


def test_network_policy_denies_by_default_and_excludes_internal_ranges_for_both_families():
    pols = {p["metadata"]["name"]: p["spec"] for p in of_kind(build()[1], "NetworkPolicy")}
    assert pols["default-deny"]["policyTypes"] == ["Ingress", "Egress"]
    assert "ingress" not in pols["default-deny"] and "egress" not in pols["default-deny"]
    blocks = {
        b["to"][0]["ipBlock"]["cidr"]: b["to"][0]["ipBlock"]["except"] for b in pols["allow-egress-internet"]["egress"]
    }
    assert "169.254.0.0/16" in blocks["0.0.0.0/0"] and "10.0.0.0/8" in blocks["0.0.0.0/0"]
    assert "fc00::/7" in blocks["::/0"] and "fe80::/10" in blocks["::/0"]


def test_egress_none_has_no_internet_policy():
    names = {p["metadata"]["name"] for p in of_kind(build({**VALID, "egress": "none"})[1], "NetworkPolicy")}
    assert names == {"default-deny", "allow-ingress-controller", "allow-dns"}


def test_extra_egress_except_split_by_family():
    s = RenderSettings(zone="z", extra_egress_except=("100.64.0.0/10", "2001:db8::/32"))
    pol = next(
        p for p in of_kind(build(settings=s)[1], "NetworkPolicy") if p["metadata"]["name"] == "allow-egress-internet"
    )
    v4, v6 = (r["to"][0]["ipBlock"]["except"] for r in pol["spec"]["egress"])
    assert "100.64.0.0/10" in v4 and "100.64.0.0/10" not in v6
    assert "2001:db8::/32" in v6


def test_quota_sums_all_workloads_and_blocks_nodeports():
    hard = of_kind(build()[1], "ResourceQuota")[0]["spec"]["hard"]
    assert hard["pods"] == "6" and hard["requests.cpu"] == "3000m" and hard["requests.memory"] == "6144Mi"
    assert hard["requests.storage"] == "30720Mi" and hard["services.nodeports"] == "0"


def test_ingress_hosts_unique_and_follow_pattern():
    hosts = [i["spec"]["rules"][0]["host"] for i in of_kind(build()[1], "Ingress")]
    assert len(set(hosts)) == 6
    assert all(h.endswith("-123e4567.apps.t3-k8s.example.org") for h in hosts)
    assert all(len(h.split(".")[0]) <= 63 for h in hosts)


def test_password_secret_wired_via_secret_key_ref_not_inline():
    objs = build()[1]
    sts = of_kind(objs, "StatefulSet")[0]
    env = {e["name"]: e for e in sts["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert "value" not in env["PASSWORD"]
    assert env["PASSWORD"]["valueFrom"]["secretKeyRef"]["key"] == "password"
    assert env["TEAM"]["value"] == "team-a"


def test_access_entries_are_per_person_with_distinct_credentials():
    spec, _, pw = build()
    entries = render_access(spec, DEP, TEAMS, SETTINGS, pw)
    alice, bob = entries[0], entries[1]
    assert (alice.user, bob.user) == ("alice", "bob")
    assert alice.password != bob.password and alice.url != bob.url
    assert alice.username == "alice"
    assert alice.url == "https://team-a-alice-123e4567.apps.t3-k8s.example.org"


def test_long_names_are_shortened_to_valid_dns_labels():
    long_team = Team("T" * 80, ("u" * 80,))
    ref = workload_refs(parse_spec(VALID), [long_team])[0]
    assert len(ref.name) <= 40


def test_colliding_workload_names_rejected():
    with pytest.raises(ValueError, match="collide"):
        workload_refs(parse_spec(VALID), [Team("A b", ("x",)), Team("a-b", ("x",))])


def test_missing_password_and_vm_runtime_rejected():
    spec = parse_spec(VALID)
    with pytest.raises(ValueError, match="missing passwords"):
        render(spec, DEP, TEAMS, SETTINGS, {})
    vm = parse_spec({"apiVersion": "appstore/v2", "name": "win", "runtime": "openstack-vm"})
    with pytest.raises(ValueError, match="kubernetes"):
        render(vm, DEP, TEAMS, SETTINGS, {})


def test_file_variables_become_a_secret_mounted_as_a_single_file():
    spec = parse_spec(VALID)
    refs = workload_refs(spec, TEAMS)
    pw = {r.name: "x" for r in refs}
    objs = render(spec, DEP, TEAMS, SETTINGS, pw, files={"assignment_zip": {"team-a": b"PK\x03"}})
    secrets = [o for o in of_kind(objs, "Secret") if o["metadata"]["name"].endswith("-files")]
    assert {s["metadata"]["labels"]["appstore.dhbw/workload"] for s in secrets} == {"team-a-alice", "team-a-bob"}
    sts = next(o for o in of_kind(objs, "StatefulSet") if o["metadata"]["name"] == "team-a-alice")
    mount = next(m for m in sts["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] if m["name"] == "files")
    assert mount["mountPath"] == "/data/assignment.zip" and mount["readOnly"] is True
    others = [o for o in of_kind(objs, "StatefulSet") if o["metadata"]["name"].startswith("team-b")]
    assert all(
        "files" not in [m["name"] for m in s["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]] for s in others
    )


def test_enum_variables_reach_containers_as_env():
    spec = parse_spec(VALID)
    pw = {r.name: "x" for r in workload_refs(spec, TEAMS)}
    objs = render(spec, DEP, TEAMS, SETTINGS, pw, variable_values={"cpu_class": {"team-a": "medium"}})
    envs = {
        s["metadata"]["name"]: {e["name"]: e.get("value") for e in s["spec"]["template"]["spec"]["containers"][0]["env"]}
        for s in of_kind(objs, "StatefulSet")
    }
    assert envs["team-a-alice"]["APPSTORE_VAR_CPU_CLASS"] == "medium"
    assert envs["team-b-carol"]["APPSTORE_VAR_CPU_CLASS"] == "small"  # the declared default
