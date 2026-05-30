#!/bin/bash
# T7 — Buddy web-UI dump for konfigurasjons-introspeksjon.
# Output: $OUTDIR/t7_web_ui/{root.html, status.html, config.html, ...}
#
# Tid: <10s

set -euo pipefail
OUTDIR="${1:?usage: t7_web_ui.sh <outdir>}"
mkdir -p "$OUTDIR/t7_web_ui"
echo "[T7] Web-UI dump → $OUTDIR/t7_web_ui/"

# Buddy web-UI er på http://10.5.5.1 når vi er på Tinkla WiFi
BUDDY_HOST="${BUDDY_HOST:-10.5.5.1}"

fetch() {
  local path="$1"
  local outname="$2"
  echo "  • $path → $outname"
  curl -sS --max-time 5 "http://$BUDDY_HOST$path" > "$OUTDIR/t7_web_ui/$outname" 2>&1 || echo "FAILED" > "$OUTDIR/t7_web_ui/$outname"
}

fetch "/"                      root.html
fetch "/status"                status.html
fetch "/config"                config.html
fetch "/settings"              settings.html
fetch "/can"                   can.html
fetch "/version"               version.html
fetch "/info"                  info.html
fetch "/cgi-bin/status"        cgi_status.html
fetch "/api/status"            api_status.json
fetch "/api/can"               api_can.json

echo
echo "[T7] Trying SSH-fetched buddy config files:"
python3 /tmp/buddy_ssh.py "
cat /opt/tinkla/cfg/* 2>/dev/null | head -100
echo '---'
ls /opt/tinkla/cfg/ /opt/tinkla/config/ /var/lib/tinkla* 2>/dev/null
echo '---'
cat /etc/tinklaBuddy.conf 2>/dev/null
" > "$OUTDIR/t7_web_ui/buddy_config_files.txt" 2>&1

echo "[T7] Done → $OUTDIR/t7_web_ui/"
ls -la "$OUTDIR/t7_web_ui/" | head
