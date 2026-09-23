#!/usr/bin/env python3
"""
Staging & Prod Discord Notification — zwei Embeds, SSH-basierter Health-Check.

Schritt 1: Postet "Staging deployed" mit Container-Status (via SSH auf die VM).
Schritt 2: Postet Prod-Status (via SSH, selbe VM, nur read-only container_list).

GitHub Actions hat kein IPv6 — alle Checks laufen daher via SSH auf die VM selbst,
nicht direkt vom Runner aus. Der SSH-Key liegt unter ~/.ssh/openstack-key im CI.
"""

import json
import os
import subprocess
import sys
import urllib.request

AVATAR_URL = "https://raw.githubusercontent.com/DHBW-AppStore-T3/.github/main/docs/img/hermes.png"


def ssh_run(vm_ip: str, cmd: str) -> tuple[bool, str]:
    """Führt einen Befehl via SSH auf der VM aus. Gibt (ok, output) zurück."""
    result = subprocess.run(
        [
            "ssh", "-i", os.path.expanduser("~/.ssh/openstack-key"),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"ubuntu@{vm_ip}",
            cmd,
        ],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def get_container_status(vm_ip: str) -> tuple[str, list[dict]]:
    """Liest Container-Status via SSH. Gibt (summary, fields) zurück."""
    ok, output = ssh_run(
        vm_ip,
        "sudo docker ps --format '{{.Names}}\t{{.Status}}' 2>/dev/null"
    )
    if not ok:
        return "UNBEKANNT", [{"name": "SSH", "value": f"⚠️ Verbindung fehlgeschlagen\n```{output[:200]}```", "inline": False}]

    lines = [l for l in output.splitlines() if l.strip()]
    fields = []
    all_up = True
    for line in lines:
        parts = line.split("\t", 1)
        name = parts[0] if parts else "?"
        status = parts[1] if len(parts) > 1 else "?"
        ok_container = "Up" in status and "unhealthy" not in status.lower()
        if not ok_container:
            all_up = False
        icon = "✅" if ok_container else "⚠️"
        fields.append({"name": f"{icon} {name}", "value": f"`{status}`", "inline": True})

    summary = "GUT" if all_up else "PROBLEME"
    return summary, fields


def send(webhook_url: str, payload: dict) -> bool:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Hermes-CI/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status in (200, 204)
    except Exception as exc:
        print(f"Discord-Fehler: {exc}")
        return False


def main() -> int:
    vm_ip      = os.getenv("VM_IP", "").strip()
    job_status = os.getenv("JOB_STATUS", "unknown").lower()
    sha        = os.getenv("GITHUB_SHA", "unknown")[:7]
    ref        = os.getenv("GITHUB_REF_NAME", os.getenv("GITHUB_REF", "dev"))
    webhook    = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    if not webhook:
        print("Kein DISCORD_WEBHOOK_URL gesetzt — nur Logging.")

    deploy_ok = job_status == "success"
    deploy_icon = "🚀" if deploy_ok else "❌"

    # --- Embed 1: Staging ---
    print(f"=== Staging Health Check (SSH) ===")
    if deploy_ok and vm_ip:
        summary, container_fields = get_container_status(vm_ip)
        color = 0x2ecc71 if summary == "GUT" else 0xe74c3c
        health_line = f"✅ Alle Container Up" if summary == "GUT" else f"⚠️ Probleme erkannt"
    else:
        container_fields = []
        color = 0xe74c3c
        health_line = f"❌ Deploy fehlgeschlagen ({job_status})"

    staging_embed = {
        "title": f"{deploy_icon} Staging deployed — `{ref}` @ `{sha}`",
        "description": health_line,
        "color": color,
        "fields": container_fields or [
            {"name": "VM IP", "value": f"`{vm_ip or 'N/A'}`", "inline": True}
        ],
        "footer": {"text": "Schritt 1 von 2 · Container-Status via SSH"}
    }

    # --- Embed 2: Prod ---
    print(f"=== Prod Health Check (SSH) ===")
    if vm_ip:
        prod_summary, prod_fields = get_container_status(vm_ip)
        prod_color = 0x2ecc71 if prod_summary == "GUT" else 0xe74c3c
        prod_line = "✅ Prod läuft stabil" if prod_summary == "GUT" else "⚠️ Prod hat Probleme"
    else:
        prod_fields = [{"name": "VM IP", "value": "`N/A`", "inline": True}]
        prod_color = 0x95a5a6
        prod_line = "Keine VM-IP — Prod-Check übersprungen"

    prod_embed = {
        "title": f"🏭 Prod-Status",
        "description": prod_line,
        "color": prod_color,
        "fields": prod_fields,
        "footer": {"text": "Schritt 2 von 2 · Container-Status via SSH"}
    }

    payload = {
        "username": "Hermes Agent",
        "avatar_url": AVATAR_URL,
        "embeds": [staging_embed, prod_embed],
    }

    for name, embed in [("Staging", staging_embed), ("Prod", prod_embed)]:
        print(f"\n--- {name} ---")
        print(f"  Status: {embed['description']}")
        for f in embed["fields"]:
            print(f"  {f['name']}: {f['value']}")

    sent = send(webhook, payload)
    print(f"\n{'✅ Discord gesendet' if sent else 'ℹ️ Nur geloggt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
