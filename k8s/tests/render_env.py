"""Render one environment the way Argo CD does, into one manifest file.

    python k8s/tests/render_env.py <staging|prod> <out.yaml> [--helm helm]

The environment's root renders the apps-chart with k8s/environments/<env>.yaml;
each Application found there is rendered from its own path with its value
files and inline values, into its destination namespace. Remote charts
(repoURL without a path in this repository) are skipped. Needs PyYAML.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import tempfile

import yaml

K8S = pathlib.Path(__file__).resolve().parents[1]
REPO = K8S.parent


def helm(binary: str, *args: str) -> str:
    result = subprocess.run([binary, *args], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"helm {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("env", choices=["staging", "prod"])
    parser.add_argument("out")
    parser.add_argument("--helm", default="helm")
    args = parser.parse_args()

    root = helm(args.helm, "template", "root", str(K8S / "argocd" / "apps-chart"),
                "-f", str(K8S / "environments" / f"{args.env}.yaml"))
    rendered: list[str] = []
    for app in yaml.safe_load_all(root):
        if not app or app.get("kind") != "Application":
            continue
        source = app["spec"]["source"]
        if "path" not in source:
            print(f"skipped {app['metadata']['name']} (remote chart {source.get('chart')})", file=sys.stderr)
            continue
        chart = REPO / source["path"]
        helm_args = ["template", app["metadata"]["name"], str(chart),
                     "-n", app["spec"]["destination"]["namespace"]]
        for values_file in source.get("helm", {}).get("valueFiles", []):
            helm_args += ["-f", str((chart / values_file).resolve())]
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as inline:
            inline.write(source.get("helm", {}).get("values", ""))
        helm_args += ["-f", inline.name]
        print(f"rendered {app['metadata']['name']} from {source['path']}", file=sys.stderr)
        rendered.append(helm(args.helm, *helm_args))
    pathlib.Path(args.out).write_text("\n---\n".join(rendered), encoding="utf-8")


if __name__ == "__main__":
    main()
