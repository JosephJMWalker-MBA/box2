#!/usr/bin/env bash
# BOX2 Jetson read-only inventory: where do OBS / ffmpeg / streaming run, is the
# clock synced, and can this machine reach an OBS WebSocket?
#
# Changes nothing. Process command lines, cron lines and container commands are
# passed through a redactor because ffmpeg/gstreamer arguments routinely contain
# rtsp://user:password@camera URLs and rtmp://.../<stream key>. Redaction is
# best-effort: read the output before you share it.
#
# Usage: bash tools/jetson/inventory.sh [OBS_HOST]   (OBS_HOST e.g. the Mac mini's LAN IP)

set -u
OBS_HOST="${1:-}"
PATTERN='obs|ffmpeg|gst-launch|gstreamer|mediamtx|go2rtc|rtsp|rtmp|srt|deepstream|stream'

redact() {
  if command -v perl >/dev/null 2>&1; then
    perl -pe '
      s{\b([a-z][a-z0-9+.-]*)://\S+}{$1://<redacted>}gi;
      s{\b([\w.-]*(?:pass|pwd|pw|key|token|secret|auth|user|login)[\w.-]*\s*[=:]\s*)[^\s&"'"'"']+}{$1<redacted>}gi;
      s{(\s--?[\w-]*(?:pass|pwd|pw|key|token|secret|auth|user|login)[\w-]*\s+)\S+}{$1<redacted>}gi;
      s{\blive_[A-Za-z0-9_]{8,}}{<redacted-stream-key>}g;
    '
  else
    sed -E -e 's#([A-Za-z][A-Za-z0-9+.-]*)://[^[:space:]]+#\1://<redacted>#g' -e 's#live_[A-Za-z0-9_]{8,}#<redacted-stream-key>#g'
  fi
}

section() { printf '\n== %s\n' "$1"; }

echo "BOX2 Jetson inventory (read-only). Review before sharing; redaction is best-effort."

section "Host"
hostname
date -u '+UTC now: %Y-%m-%dT%H:%M:%SZ'
date '+Local:   %Y-%m-%dT%H:%M:%S%z %Z'
uname -srm
[ -r /etc/nv_tegra_release ] && head -n 1 /etc/nv_tegra_release
[ -r /etc/os-release ] && . /etc/os-release && echo "OS: ${PRETTY_NAME:-unknown}"

section "Clock sync (event timestamps depend on this)"
if command -v timedatectl >/dev/null 2>&1; then
  timedatectl show -p Timezone -p NTP -p NTPSynchronized 2>/dev/null || timedatectl status
fi
command -v chronyc >/dev/null 2>&1 && chronyc -n tracking 2>/dev/null | grep -E 'Reference ID|System time|Leap status'

section "Installed tools"
for tool in obs ffmpeg gst-launch-1.0 python3 docker; do
  printf '%-15s %s\n' "$tool" "$(command -v "$tool" || echo '-')"
done
command -v python3 >/dev/null 2>&1 && python3 --version
command -v ffmpeg >/dev/null 2>&1 && ffmpeg -hide_banner -version 2>/dev/null | head -n 1
command -v flatpak >/dev/null 2>&1 && flatpak list --app --columns=application,version 2>/dev/null | grep -i obs
command -v snap >/dev/null 2>&1 && snap list 2>/dev/null | grep -i obs

section "Running media processes (redacted)"
procs="$(pgrep -af "$PATTERN" 2>/dev/null | grep -v -e 'inventory\.sh' -e '^[0-9]* perl -pe' || true)"
if [ -n "$procs" ]; then printf '%s\n' "$procs" | redact; else echo "(none)"; fi

section "systemd services matching media/stream names"
systemctl list-units --type=service --all --no-pager --no-legend 2>/dev/null | grep -Ei "$PATTERN" || echo "(system: none)"
systemctl --user list-units --type=service --all --no-pager --no-legend 2>/dev/null | grep -Ei "$PATTERN" || echo "(user: none)"

section "Containers"
if command -v docker >/dev/null 2>&1; then
  if containers="$(docker ps --format '{{.Names}}  {{.Image}}  {{.Status}}' 2>/dev/null)"; then
    if [ -n "$containers" ]; then printf '%s\n' "$containers" | redact; else echo "(none running)"; fi
  else
    echo "(docker not accessible to this user; try: sudo docker ps)"
  fi
else
  echo "(docker not installed)"
fi

section "Cron lines mentioning media (redacted)"
cronlines="$(crontab -l 2>/dev/null | grep -Ei "$PATTERN" || true)"
if [ -n "$cronlines" ]; then printf '%s\n' "$cronlines" | redact; else echo "(none for $(id -un))"; fi

section "Listening TCP ports (4455 = OBS WebSocket, 1935 = RTMP, 554/8554 = RTSP)"
if command -v ss >/dev/null 2>&1; then
  ss -ltnH 2>/dev/null | awk '{print $4}' | sort -u | tr '\n' ' '; echo
fi

section "LAN addresses"
ip -4 -brief addr show scope global 2>/dev/null || hostname -I 2>/dev/null

section "OBS WebSocket reachability"
for target in 127.0.0.1 ${OBS_HOST}; do
  if timeout 3 bash -c "exec 3<>/dev/tcp/${target}/4455" 2>/dev/null; then
    echo "${target}:4455 open"
  else
    echo "${target}:4455 not reachable"
  fi
done
[ -z "$OBS_HOST" ] && echo "(pass the OBS computer's LAN IP as an argument to test it too)"

echo
echo "Done. Nothing was changed."
