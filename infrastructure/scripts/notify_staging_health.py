#!/usr/bin/env python3
"""
Staging Deployment Health-Check & Discord Notification (Hermes Integration).
Wird im Anschluss an deployment/staging.yml ausgeführt.
Prüft die System-Health der Staging-VM und meldet das Ergebnis nach Discord.
"""

import os
import sys
import json
import urllib.request
import urllib.error
import ssl

def check_vm_health(vm_ip: str) -> tuple[str, str]:
    """Prüft die Erreichbarkeit der Staging-VM über HTTP/HTTPS Endpoints."""
    if not vm_ip:
        return "UNBEKANNT", "Keine VM-IP übergeben"

    # IPv6-Adressen brauchen eckige Klammern in URLs
    host = f"[{vm_ip}]" if ":" in vm_ip else vm_ip

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    endpoints = [
        f"http://{host}/",
        f"https://{host}/",
        f"http://{host}:8000/api/v1/health",
    ]

    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Hermes-HealthCheck/1.0"})
            with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                if response.status in (200, 204, 301, 302):
                    return "GUT", f"{url} → {response.status}"
        except Exception:
            continue

    return "SCHLECHT", "Kein HTTP/HTTPS-Endpoint auf der VM erreichbar"

def send_discord_notification(webhook_url: str, message: dict) -> bool:
    """Sendet ein formatiertes JSON-Payload an den Discord-Webhook."""
    if not webhook_url:
        print("[Hermes Notification] Kein DISCORD_WEBHOOK_URL gesetzt — Benachrichtigung wird nur geloggt.")
        return False
        
    try:
        data = json.dumps(message).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Hermes-Agent/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as exc:
        print(f"[Hermes Notification] Fehler beim Senden an Discord: {exc}")
        return False

def main():
    vm_ip = os.getenv("VM_IP", "").strip()
    job_status = os.getenv("JOB_STATUS", "unknown").lower()
    github_sha = os.getenv("GITHUB_SHA", "unknown")[:7]
    github_ref = os.getenv("GITHUB_REF", "dev")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    
    print(f"=== Hermes Staging Health Check ===")
    print(f"Job-Status: {job_status} | VM-IP: {vm_ip} | Commit: {github_sha} | Ref: {github_ref}")
    
    if job_status == "success":
        health_status, health_detail = check_vm_health(vm_ip)
    else:
        health_status = "SCHLECHT"
        health_detail = f"Staging Deployment Job fehlgeschlagen mit Status: {job_status}"
        
    health_icon = "✅" if health_status == "GUT" else "⚠️"
    color = 0x2ecc71 if health_status == "GUT" else 0xe74c3c
    
    embed = {
        "title": f"🚀 Feature fertig & deployed! (Staging)",
        "description": f"Das automatische Staging-Deployment für **{github_ref}** wurde abgeschlossen.",
        "color": color,
        "fields": [
            {"name": "System Health", "value": f"{health_icon} **{health_status}** ({health_detail})", "inline": False},
            {"name": "Branch / Event", "value": f"`{github_ref}`", "inline": True},
            {"name": "Commit", "value": f"`{github_sha}`", "inline": True},
            {"name": "Staging VM IP", "value": f"`{vm_ip or 'N/A'}`", "inline": True},
        ],
        "footer": {
            "text": "Hermes Harness Engineering • Push auf main bleibt rein menschlich + Test Coverage Gate"
        }
    }
    
    discord_payload = {
        "username": "Hermes Agent",
        "avatar_url": "https://raw.githubusercontent.com/DHBW-AppStore-T3/.github/main/docs/img/hermes.png",
        "embeds": [embed]
    }
    
    print(f"\n--- Hermes Discord Meldung ---")
    print(f"Status: Feature fertig & deployed!")
    print(f"System Health: {health_status} ({health_detail})")
    print(f"Commit: {github_sha} | Branch: {github_ref}")
    
    sent = send_discord_notification(webhook_url, discord_payload)
    if sent:
        print("✅ Discord-Meldung erfolgreich abgesetzt.")
    else:
        print("ℹ️ Discord-Meldung lokal protokolliert.")
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
