#!/usr/bin/env bash
# ==============================================================================
# BOX 2 Stream Box — Jetson Orin Nano One-Step Installer & Recovery Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${HOME}/box2-stream"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

echo "=== BOX 2 Stream Box Installer ==="

# 1. Ensure required system packages are present
echo "[1/6] Verifying system dependencies..."
MISSING_PKGS=()
for pkg in ffmpeg python3 python3-pip; do
    if ! command -v "$pkg" >/dev/null 2>&1; then
        MISSING_PKGS+=("$pkg")
    fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "Installing missing system packages: ${MISSING_PKGS[*]}..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq "${MISSING_PKGS[@]}" python3-opencv python3-pil python3-numpy
fi

# 2. Setup target runtime directory and Stage Director package
echo "[2/6] Setting up runtime directories at ${TARGET_DIR} and ${HOME}/stage-director..."
mkdir -p "${TARGET_DIR}" "${HOME}/stage-director/stage_director"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
if [ -d "${REPO_ROOT}/stage_director" ]; then
    cp -r "${REPO_ROOT}/stage_director/"* "${HOME}/stage-director/stage_director/"
fi

# 3. Deploy main streaming script
echo "[3/6] Deploying box2_stream.py..."
cp "${SCRIPT_DIR}/box2_stream.py" "${TARGET_DIR}/box2_stream.py"
chmod +x "${TARGET_DIR}/box2_stream.py"

# Deploy ticker configuration if not already customized
if [ ! -f "${TARGET_DIR}/ticker.json" ]; then
    echo "Installing default ticker.json..."
    cp "${SCRIPT_DIR}/ticker.json.example" "${TARGET_DIR}/ticker.json"
fi

# Setup config.json template if not present
if [ ! -f "${TARGET_DIR}/config.json" ]; then
    echo "Creating ~/box2-stream/config.json template..."
    cp "${SCRIPT_DIR}/config.json.example" "${TARGET_DIR}/config.json"
    chmod 600 "${TARGET_DIR}/config.json"
    echo ""
    echo "⚠️  ACTION REQUIRED: Edit ${TARGET_DIR}/config.json and set your Twitch key and NVR password:"
    echo "    nano ${TARGET_DIR}/config.json"
    echo ""
fi

# 4. Install systemd user service
echo "[4/6] Installing systemd user service..."
mkdir -p "${SYSTEMD_USER_DIR}"
cp "${SCRIPT_DIR}/box2-stream.service" "${SYSTEMD_USER_DIR}/box2-stream.service"

# 5. Enable systemd user lingering (runs 24/7 without active SSH session)
echo "[5/6] Enabling systemd user lingering for 24/7 autonomous streaming..."
loginctl enable-linger "${USER}" || true

# 6. Reload and enable service
echo "[6/6] Reloading systemd and enabling box2-stream.service..."
systemctl --user daemon-reload
systemctl --user enable box2-stream.service

echo ""
echo "=== Installation Complete! ==="
echo "To start streaming:"
echo "    systemctl --user start box2-stream.service"
echo ""
echo "To check live status:"
echo "    ${TARGET_DIR}/box2_stream.py status"
echo ""
echo "To view live logs:"
echo "    journalctl --user -u box2-stream.service -f"
