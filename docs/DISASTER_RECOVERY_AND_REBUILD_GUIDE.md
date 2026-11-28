# BOX 2 Disaster Recovery & Rebuild Runbook

This runbook provides complete, step-by-step instructions to rebuild the entire BOX 2 Stage Director live broadcast system from scratch on a brand new or freshly wiped NVIDIA Jetson Orin Nano.

---

## 1. GitHub Repository & Branch

All production code, AI models, geometric framing algorithms, dual-camera wall overlays, resilience hardening, and systemd service templates are tracked and backed up in GitHub:

- **Repository**: [`https://github.com/JosephJMWalker-MBA/box2`](https://github.com/JosephJMWalker-MBA/box2)
- **Production Branch**: `feature/stage-director-antigravity-kickoff`
- **Pull Request**: [PR #9: Stage Director Kickoff](https://github.com/JosephJMWalker-MBA/box2/pull/9)

---

## 2. System Architecture & Prerequisites

### Hardware
- **Edge Computer**: NVIDIA Jetson Orin Nano (Ubuntu 22.04 / 24.04 with JetPack 5.x/6.x)
- **NVR**: Reolink NVR (IP: `10.0.0.6`, Hardware MAC: `ec:71:db:bb:69:56`)
  - **Channel 0**: Stage PTZ Camera (`RLC-823A`)
  - **Channel 1**: Parking Lot Outdoor Camera (`RLC-811A`)
- **Network**: Jetson and NVR connected to the same LAN / Wi-Fi subnet.

### Core Software Packages
- Python 3.10+ (tested on Python 3.12.3)
- FFmpeg with x264 and AAC support
- OpenCV with Python bindings (`python3-opencv`)
- Pillow (`python3-pil`)
- NumPy (`python3-numpy`)

---

## 3. Disaster Recovery: 4-Step Fresh Rebuild

If the Jetson is completely wiped, re-imaged, or replaced tomorrow:

### Step 1: Clone the Repository
```bash
git clone https://github.com/JosephJMWalker-MBA/box2.git
cd box2
git checkout feature/stage-director-antigravity-kickoff
```

### Step 2: Run the One-Step Automated Installer
```bash
./tools/jetson/install_service.sh
```
This script automatically:
1. Installs all required OS packages via `apt-get` (`ffmpeg`, `python3-opencv`, `python3-pil`, `python3-numpy`).
2. Creates `~/box2-stream/` runtime directory.
3. Deploys `box2_stream.py` and default `ticker.json`.
4. Generates a fresh `config.json` template with `chmod 600`.
5. Installs the systemd user service `~/.config/systemd/user/box2-stream.service`.
6. Enables systemd lingering (`loginctl enable-linger $USER`) so the stream runs 24/7 autonomously even after disconnecting SSH.

### Step 3: Enter Your Credentials in `config.json`
Edit `~/box2-stream/config.json`:
```bash
nano ~/box2-stream/config.json
```
Fill in your Twitch stream key and NVR password:
```json
{
  "nvr_mac": "ec:71:db:bb:69:56",
  "nvr_user": "OBS",
  "nvr_password": "<YOUR_NVR_PASSWORD>",
  "nvr_channel": 0,
  "nvr_stream": "sub",
  "twitch_server": "rtmp://live.twitch.tv/app",
  "twitch_key": "live_XXXXXXXXX_YOUR_TWITCH_KEY",
  "scheduled_refresh_hours": 3,
  "headroom_fraction": 0.50
}
```

### Step 4: Start the Service
```bash
systemctl --user start box2-stream.service
```

---

## 4. Verification & Daily Operations

### Check Live Status
```bash
~/box2-stream/box2_stream.py status
```
Expected output:
```json
{
  "state": "live",
  "since": "2026-11-18 00:56:32",
  "restarts": 0,
  "nvr_ip": "10.0.0.6",
  "fps": 30.0,
  "bitrate": "2650.0kbits/s",
  "mode": "director",
  "next_scheduled_refresh": "2026-11-18 03:00:00 AM"
}
```

### View Real-Time Streaming Logs
```bash
journalctl --user -u box2-stream.service -f
```

### Hot-Updating Sponsor & Ticker Messages
Edit `~/box2-stream/ticker.json`:
- Messages, ads, sponsor names, and scroll speed hot-reload automatically within 2 seconds without restarting or dropping the live stream.

### Running Test Suite
```bash
cd ~/stage-director
PYTHONPATH=. pytest tests
```
All 96 test suite cases should pass in under 3 seconds.
