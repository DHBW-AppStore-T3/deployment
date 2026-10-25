#!/bin/sh
# noVNC proxy: bridges WebSocket (port 8080) to VNC (VNC_HOST:VNC_PORT).
# VNC_PASSWORD is optional; if set it is passed to websockify's VNC auth.
set -e

VNC_HOST="${VNC_HOST:?VNC_HOST is required}"
VNC_PORT="${VNC_PORT:-5900}"

exec websockify --web /usr/share/novnc/ 8080 "${VNC_HOST}:${VNC_PORT}"
