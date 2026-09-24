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

def check_vm_health(vm_ip: str, app_hostname: str = "") -> tuple[str, str]:
    """Prüft die Erreichbarkeit der Staging-VM über HTTP/HTTPS Endpoints.

    Real bug found live: this always checked the bare IP, never
    APP_HOSTNAME. Caddy's site block is keyed on {$APP_HOSTNAME}
    specifically (see caddy/Caddyfile's own header comment — ACME issues
    certs for domains, never bare IPs), so an IP-only HTTPS request has
    no matching site/cert to answer it. Every staging deploy reported
    SCHLECHT for this reason alone, regardless of whether staging was
    actually healthy — confirmed by cross-checking against
    docker-compose.staging.yml (backend's healthcheck path is
    /health, not /api/v1/health, and backend:8000 is never published to
    the host at all — only reachable inside the Docker network via
    Caddy's reverse_proxy, so the old :8000 endpoint here could never
    have succeeded either).
    """
    if not vm_ip:
        return "UNBEKANNT", "Keine VM-IP übergeben"

    # IPv6-Adressen brauchen eckige Klammern in URLs
    ip_host = f"[{vm_ip}]" if ":" in vm_ip else vm_ip

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    endpoints = []
    if app_hostname:
        # The real, ACME-certified, Caddy-routed path — checked first.
        endpoints.append(f"https://{app_hostname}/api/v1/health")
        endpoints.append(f"https://{app_hostname}/")
    # IP fallbacks kept for when APP_HOSTNAME couldn't be read (e.g. the
    # .env fetch step failed) — won't succeed against Caddy's real TLS
    # config, but at least confirms whether the host answers HTTP at all.
    endpoints.append(f"http://{ip_host}/")
    endpoints.append(f"https://{ip_host}/")

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
    app_hostname = os.getenv("APP_HOSTNAME", "").strip()
    job_status = os.getenv("JOB_STATUS", "unknown").lower()
    github_sha = os.getenv("GITHUB_SHA", "unknown")[:7]
    github_ref = os.getenv("GITHUB_REF", "dev")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    print(f"=== Hermes Staging Health Check ===")
    print(f"Job-Status: {job_status} | VM-IP: {vm_ip} | APP_HOSTNAME: {app_hostname or '(not read)'} | Commit: {github_sha} | Ref: {github_ref}")

    if job_status == "success":
        health_status, health_detail = check_vm_health(vm_ip, app_hostname)
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
