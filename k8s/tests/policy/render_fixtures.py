"""Render the fixtures of the admission policy tests with the backend's renderer.

The objects the pod deployer applies come from app/k8s/render.py (backend and
worker). Rerun this whenever the renderer changes, from a backend checkout:

    cd backend && PYTHONPATH=. python ../deployment/k8s/tests/policy/render_fixtures.py \
        ../deployment/k8s/tests/policy/fixtures.json

The settings match k8s/environments/staging.yaml (zone, egress exceptions) and
placement-values.yaml (student nodes).
"""

import json
import sys
import uuid

from app.k8s.render import DeploymentCtx, Member, RenderSettings, Team, render
from app.k8s.spec import parse_spec

ZONE = "t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site"
EXTRA = ("10.42.0.0/16", "fd00:42::/48", "fd00:43::/48", "2001:7c0:1b20:c913:1::10d/128")
DIGEST = "sha256:" + "a" * 64
SPEC = {
    "apiVersion": "appstore/v2",
    "name": "online-ide",
    "runtime": "kubernetes",
    "scope": "user",
    "workload": {
        "containers": [
            {
                "name": "ide",
                "image": f"ghcr.io/dhbw-appstore-t3/apps/online-ide@{DIGEST}",
                "expose": {"port": 8080, "path": "/"},
                "resources": {"cpu": "1", "memory": "1Gi", "requests": {"cpu": "100m", "memory": "256Mi"}},
                "env": [{"name": "PASSWORD", "from": "generated-password"}],
                "writablePaths": ["/tmp"],
            }
        ],
        "storage": {"size": "5Gi", "mountPath": "/home/coder"},
    },
    "network": {"internet": {"allowed": True, "default": True}, "podNetwork": {"allowed": True, "default": False}},
    "variables": [{"name": "assignment", "type": "file", "scope": "team", "mountPath": "/data/assignment.zip"}],
    "access": [
        {"type": "url", "template": "https://{workload}-{deployment}.{domain}"},
        {"type": "password", "from": "generated-password", "username": "{user}"},
    ],
}
PLACEMENT = {
    "node_selector": {"appstore.dhbw/workload": "student"},
    "tolerations": ({"key": "appstore.dhbw/workload", "operator": "Equal", "value": "student", "effect": "NoSchedule"},),
}

dep = DeploymentCtx(id="12345678-aaaa-bbbb-cccc-1234567890ab", owner="0f0f0f0f-0000-4000-8000-000000000001")
teams = [Team("Team-1", (Member(str(uuid.UUID(int=1)), "alice"), Member(str(uuid.UUID(int=2)), "bob")))]
spec = parse_spec(SPEC)
networked = parse_spec({**SPEC, "network": {"internet": {"allowed": True}, "podNetwork": {"allowed": True, "default": True}}})
passwords = {"team-1-alice": "pw1", "team-1-bob": "pw2"}
base = dict(zone=ZONE, app_domain_override=ZONE, ingress_class="traefik", ingress_namespace="kube-system",
            extra_egress_except=EXTRA, environment="appstore-staging",
            ingress_pod_labels={"app.kubernetes.io/name": "traefik"})
fixtures = {
    "deployment": {"id": dep.id, "namespace": dep.namespace},
    "default": render(spec, dep, teams, RenderSettings(**base), passwords, files={"assignment": {"Team-1": b"zip"}}),
    "placement": render(spec, dep, teams, RenderSettings(**base, **PLACEMENT), passwords),
    # The same app with the pods allowed to talk to each other and no internet.
    "networked": render(networked, dep, teams, RenderSettings(**base), passwords),
}
with open(sys.argv[1], "w", encoding="utf-8") as out:
    json.dump(fixtures, out, indent=1)
    out.write("\n")
print(f"{len(fixtures['default'])} + {len(fixtures['placement'])} + {len(fixtures['networked'])} objects")
