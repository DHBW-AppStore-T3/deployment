"""Guard: appstore-mcp may only read, and never Secrets, ConfigMaps or exec.

    python k8s/tests/check_mcp_rbac.py rendered/staging.yaml [...]
"""

import sys

import yaml

FORBIDDEN_RESOURCES = {"secrets", "configmaps", "pods/exec", "pods/attach", "pods/portforward", "*", "serviceaccounts/token"}
ALLOWED_VERBS = {"get", "list", "watch"}


def main(paths: list[str]) -> int:
    errors, seen = [], 0
    for path in paths:
        for doc in yaml.safe_load_all(open(path, encoding="utf-8")):
            if not doc or doc.get("kind") not in ("ClusterRole", "Role"):
                continue
            if not doc["metadata"]["name"].startswith("appstore-mcp-"):
                continue
            seen += 1
            for rule in doc.get("rules", []):
                if set(rule["verbs"]) - ALLOWED_VERBS:
                    errors.append(f"{path}: {doc['metadata']['name']} has verbs {rule['verbs']}")
                if FORBIDDEN_RESOURCES & set(rule.get("resources", [])):
                    errors.append(f"{path}: {doc['metadata']['name']} reads {rule['resources']}")
    print(f"checked {seen} appstore-mcp roles")
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
