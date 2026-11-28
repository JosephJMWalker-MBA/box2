#!/usr/bin/env bash
# ==============================================================================
# BOX 2 Stream — Headless Spotify Premium Connect Speaker ("BOX 2 Stream")
# Routes 320 kbps Spotify Connect audio directly into PipeWire `box2_dj_bus`
# ==============================================================================
set -euo pipefail

BIN_DIR="${HOME}/box2-stream/bin"
CFG_DIR="${HOME}/.config/go-librespot"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

mkdir -p "${BIN_DIR}" "${CFG_DIR}" "${SYSTEMD_USER_DIR}"
chmod 700 "${CFG_DIR}"

if [ ! -x "${BIN_DIR}/go-librespot" ]; then
    echo "Downloading official go-librespot linux_arm64 binary..."
    python3 - << 'PY'
import json, os, tarfile, tempfile, urllib.request
req = urllib.request.Request(
    "https://api.github.com/repos/devgianlu/go-librespot/releases/latest",
    headers={"User-Agent": "box2-stream"},
)
data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
asset = next(a for a in data["assets"] if a["name"] == "go-librespot_linux_arm64.tar.gz")
with tempfile.TemporaryDirectory() as tmp:
    tgz = os.path.join(tmp, "gl.tar.gz")
    urllib.request.urlretrieve(asset["browser_download_url"], tgz)
    with tarfile.open(tgz) as tf:
        tf.extract("go-librespot", path=os.path.expanduser("~/box2-stream/bin"))
os.chmod(os.path.expanduser("~/box2-stream/bin/go-librespot"), 0o755)
PY
fi

cat > "${CFG_DIR}/config.yml" << 'YAML'
device_name: "BOX 2 Stream"
device_type: speaker
audio_backend: pulseaudio
bitrate: 320
crossfade_duration: 3000
normalisation_disabled: false
initial_volume: 100
ignore_last_volume: true
external_volume: true
zeroconf_enabled: true
zeroconf_backend: avahi
credentials:
  type: zeroconf
  zeroconf:
    persist_credentials: true
server:
  enabled: true
  address: 127.0.0.1
  port: 3678
YAML
chmod 600 "${CFG_DIR}/config.yml"

cat > "${SYSTEMD_USER_DIR}/box2-spotify-connect.service" << 'UNIT'
[Unit]
Description=BOX 2 Spotify Connect Speaker (go-librespot -> box2_dj_bus)
After=network-online.target pipewire.service pipewire-pulse.service
Wants=network-online.target

[Service]
Environment=PULSE_SERVER=unix:%t/pulse/native
Environment=PULSE_SINK=box2_dj_bus
ExecStartPre=/usr/bin/python3 -c "import sys; sys.path.insert(0, '%h/box2-stream'); import box2_radio; box2_radio.ensure_pipewire_dj_bus()"
ExecStart=%h/box2-stream/bin/go-librespot --config_dir %h/.config/go-librespot
Restart=always
RestartSec=4

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now box2-spotify-connect.service
echo "BOX 2 Stream Spotify Connect speaker active (select 'BOX 2 Stream' in Spotify app)!"
