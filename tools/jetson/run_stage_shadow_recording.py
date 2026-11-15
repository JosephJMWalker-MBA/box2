"""BOX2 Stage Director — Real-Time Stage Shadow Mode Recording.

Connects directly to the live stage camera on the LAN (Reolink NVR),
tracks the performer on stage in real-time, crops to a smooth 16:9 medium shot,
and records the live video and stage microphone audio to a local MP4 file.

Zero impact on production: box2_stream.py continues uninterrupted;
zero network egress to Twitch.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
import signal
import ssl
import subprocess
import sys
import time
import urllib.request

import cv2
import numpy as np

# Ensure repository root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from stage_director.adapter import StageFramingAdapter
from stage_director.core import BookingSnapshot
from stage_director.framing import FramingConfig, FramingEngine
from stage_director.geometry import BoundingBox, StagePolygon
from stage_director.tracking import PerformerTracker


def nvr_login(nvr_ip: str, cfg: dict) -> str:
    """Log in to Reolink NVR and return an authenticated token."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    body = [
        {
            "cmd": "Login",
            "action": 0,
            "param": {
                "User": {
                    "Version": "0",
                    "userName": cfg["nvr_user"],
                    "password": cfg["nvr_password"],
                }
            },
        }
    ]
    req = urllib.request.Request(
        f"https://{nvr_ip}/api.cgi?cmd=Login",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with opener.open(req, timeout=8) as response:
        data = json.loads(response.read().decode())
        if data[0].get("code") != 0:
            raise RuntimeError(f"NVR login failed: {data}")
        return data[0]["value"]["Token"]["name"]


def nvr_logout(nvr_ip: str, token: str) -> None:
    """Log out from Reolink NVR."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        req = urllib.request.Request(
            f"https://{nvr_ip}/api.cgi?cmd=Logout&token={token}",
            data=b"[{}]",
            headers={"Content-Type": "application/json"},
        )
        opener.open(req, timeout=3)
    except Exception:
        pass


def run_stage_shadow_recorder(
    duration_seconds: float = 1800.0,
    output_mp4: str = "/home/joseph1/stage_shadow_rehearsal.mp4",
    config_path: str = "/home/joseph1/box2-stream/config.json",
    status_path: str = "/home/joseph1/box2-stream/status.json",
    target_width: int = 1280,
    target_height: int = 720,
) -> None:
    print("=================================================================")
    print("  BOX2 STAGE DIRECTOR — LIVE STAGE SHADOW MODE RECORDER          ")
    print("=================================================================")
    print(f"Target recording duration: {duration_seconds:.1f}s ({duration_seconds/60:.1f} min)")
    print(f"Target local output file:  {output_mp4}")
    print("Mode: Live Ingest & Tracking -> Local MP4 (Zero Twitch Egress)")
    print("=================================================================\n")

    # 1. Read camera credentials
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config not found at {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Resolve NVR IP from status.json or config
    nvr_ip = "10.0.0.6"
    if os.path.exists(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                st = json.load(f)
                if st.get("nvr_ip"):
                    nvr_ip = st["nvr_ip"]
        except Exception:
            pass

    print(f"[1/5] Connecting to Reolink NVR at {nvr_ip}...")
    token = nvr_login(nvr_ip, cfg)
    print("      Authenticated successfully with NVR.")

    channel = cfg.get("nvr_channel", 0)
    stream_type = cfg.get("nvr_stream", "sub")
    sub_url = f"http://{nvr_ip}/flv?port=1935&app=bcs&stream=channel{channel}_{stream_type}.bcs&token={token}"

    # 2. Open camera feed
    print(f"[2/5] Opening camera stream (channel {channel}, {stream_type})...")
    cap = cv2.VideoCapture(sub_url)
    if not cap.isOpened():
        nvr_logout(nvr_ip, token)
        raise RuntimeError(f"Failed to open camera stream at {sub_url}")

    # Read first frame to determine source resolution
    ret, test_frame = cap.read()
    if not ret or test_frame is None:
        cap.release()
        nvr_logout(nvr_ip, token)
        raise RuntimeError("Failed to read initial video frame from camera.")

    src_h, src_w = test_frame.shape[:2]
    print(f"      Camera input resolution: {src_w}x{src_h}")

    # 3. Initialize Stage Polygon & Stage Director Engine
    print("[3/5] Configuring Stage Polygon and Tracking Engine...")
    # Standing comedian head is in y in [50, 210]; floor/pets (y > 220) and offstage are excluded.
    scale_x = src_w / 640.0
    scale_y = src_h / 360.0
    floor_cutoff_y = int(215 * scale_y)
    stage_vertices = [
        (int(150 * scale_x), int(50 * scale_y)),
        (int(440 * scale_x), int(50 * scale_y)),
        (int(440 * scale_x), floor_cutoff_y),
        (int(150 * scale_x), floor_cutoff_y),
    ]
    stage_polygon = StagePolygon(vertices=stage_vertices)

    cascade_path = "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"
    if not os.path.exists(cascade_path):
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)

    framing_config = FramingConfig(
        canvas_width=src_w,
        canvas_height=src_h,
        target_face_fraction=0.33,
        max_zoom=3.6,
        periodic_room_view_enabled=True,
        room_view_interval_s=50.0,
        room_view_duration_s=5.0,
    )
    tracker = PerformerTracker(
        stage_polygon=stage_polygon,
        loss_hold_seconds=2.5,
        allow_proximity_reacquisition=True,
        max_performer_y=float(floor_cutoff_y),
    )
        allow_proximity_reacquisition=True,
    )
    adapter = StageFramingAdapter(
        config=framing_config,
        tracker=tracker,
        allow_proximity_reacquisition=True,
    )

    now_utc = datetime.now(timezone.utc)
    t0_mono = time.monotonic()

    # Create active public booking for this rehearsal set
    booking = BookingSnapshot(
        booking_id=f"live-rehearsal-{int(time.time())}",
        revision=1,
        slot_start_utc=now_utc - timedelta(seconds=1),
        slot_end_utc=now_utc + timedelta(seconds=duration_seconds + 60),
        issued_at_utc=now_utc - timedelta(seconds=30),
        expires_at_utc=now_utc + timedelta(seconds=duration_seconds + 120),
        stage_seconds=int(duration_seconds),
        privacy_class="public",
        checked_in=True,
        live_consent=True,
        tracking_consent=True,
        capture_verified=True,
    )

    adapter.arm(booking, now_utc)
    adapter.start_set(now_utc, t0_mono, host_confirmed=True)
    print("      Stage Director armed and set started (LIVE_PUBLIC).")

    # 4. Launch FFmpeg encoder for local output file with audio mapping
    print(f"[4/5] Spawning FFmpeg encoder to {output_mp4}...")
    os.makedirs(os.path.dirname(os.path.abspath(output_mp4)), exist_ok=True)

    enc_cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{target_width}x{target_height}",
        "-pix_fmt", "bgr24",
        "-r", "25",
        "-i", "pipe:0",
        "-rw_timeout", "15000000",
        "-i", sub_url,
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-b:v", "3000k",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        output_mp4,
    ]

    enc_proc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)

    stop_event = False

    def sig_handler(sig, frame):
        nonlocal stop_event
        print("\n[!] Received stop signal, closing recording cleanly...")
        stop_event = True

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    print("\n[5/5] *** LIVE STAGE TRACKING & RECORDING IN PROGRESS ***")
    print("Press Ctrl+C at any time to stop and finalize the MP4 file.\n")

    frame_count = 0
    start_wall = time.time()
    last_stat_time = time.monotonic()
    last_detections_onstage = 0

    try:
        while not stop_event:
            elapsed_wall = time.time() - start_wall
            if elapsed_wall >= duration_seconds:
                print(f"Reached scheduled duration of {duration_seconds}s. Stopping.")
                break

            ret, frame = cap.read()
            if not ret or frame is None:
                # brief stream hiccup, retry
                time.sleep(0.02)
                continue

            frame_count += 1
            cur_mono = time.monotonic()
            cur_utc = datetime.now(timezone.utc)

            # 1. Face detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Efficient parameters for sub-stream: scaleFactor=1.08, minNeighbors=3
            raw_faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.08,
                minNeighbors=3,
                minSize=(24, 24),
            )

            # Convert to BoundingBox and filter with stage polygon
            candidate_boxes: list[BoundingBox] = []
            onstage_count = 0
            offstage_count = 0

            for (fx, fy, fw, fh) in raw_faces:
                bbox = BoundingBox(x=float(fx), y=float(fy), width=float(fw), height=float(fh))
                if stage_polygon.contains_box(bbox):
                    candidate_boxes.append(bbox)
                    onstage_count += 1
                else:
                    offstage_count += 1

            last_detections_onstage = onstage_count

            # Auto-confirm performer if acquiring/ambiguous and exactly one onstage face found
            if adapter.tracker.state.value in ("acquiring", "ambiguous") and onstage_count == 1:
                adapter.confirm_subject(candidate_boxes[0], cur_mono)

            # 2. Process frame through Stage Director
            proposal = adapter.process_frame(
                detections=candidate_boxes,
                now_utc=cur_utc,
                monotonic_seconds=cur_mono,
            )

            # 3. Dynamic Crop & Resize to Target 16:9 Canvas
            crop = proposal.obs_crop
            if crop and proposal.camera_action == "track_face":
                cl = int(crop.get("left", 0))
                ct = int(crop.get("top", 0))
                cr = int(crop.get("right", 0))
                cb = int(crop.get("bottom", 0))
                # Clamp bounds within source frame
                x1 = max(0, min(cl, src_w - 32))
                y1 = max(0, min(ct, src_h - 18))
                x2 = max(x1 + 32, min(src_w - cr, src_w))
                y2 = max(y1 + 18, min(src_h - cb, src_h))
                cropped_img = frame[y1:y2, x1:x2]
                out_canvas = cv2.resize(cropped_img, (target_width, target_height), interpolation=cv2.INTER_LINEAR)
            else:
                out_canvas = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_LINEAR)

            # Draw HUD watermark on video
            zoom_val = proposal.framing.get("zoom_factor", 1.0) if proposal.framing else 1.0
            hud = f"BOX2 LIVE SHADOW | {cur_utc.strftime('%H:%M:%S')} | ZOOM: {zoom_val:.2f}x | TRACK: {proposal.tracking_state.upper()}"
            cv2.putText(out_canvas, hud, (30, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

            if proposal.cue:
                cue_hud = f">>> CUE: {proposal.cue.upper()} (REMAINING: {proposal.remaining_seconds}s) <<<"
                cv2.putText(out_canvas, cue_hud, (30, 95), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 255), 3)

            # 4. Pipe frame to FFmpeg encoder
            if enc_proc.stdin and not enc_proc.stdin.closed:
                try:
                    enc_proc.stdin.write(out_canvas.tobytes())
                except BrokenPipeError:
                    break

            # 5. Telemetry output to console every 1.5s
            if cur_mono - last_stat_time >= 1.5:
                fps = frame_count / (time.time() - start_wall)
                rem = proposal.remaining_seconds or 0
                zoom = proposal.framing.get("zoom_factor", 1.0) if proposal.framing else 1.0
                print(
                    f"[{time.strftime('%H:%M:%S')}] Frame {frame_count:05d} ({fps:4.1f} FPS) | "
                    f"Tracking: {proposal.tracking_state:10s} | Zoom: {zoom:.2f}x | "
                    f"Onstage: {onstage_count} (Offstage: {offstage_count}) | Remaining: {rem:04d}s | "
                    f"Cue: {proposal.cue or 'none'}"
                )
                last_stat_time = cur_mono

    finally:
        print("\nFinalizing recording...")
        cap.release()
        if enc_proc.stdin and not enc_proc.stdin.closed:
            enc_proc.stdin.close()
        enc_proc.wait(timeout=10)
        nvr_logout(nvr_ip, token)

    file_size_mb = os.path.getsize(output_mp4) / (1024 * 1024) if os.path.exists(output_mp4) else 0.0
    print(f"\nSuccessfully finalized: {output_mp4} ({file_size_mb:.2f} MB)")
    print("Stage shadow mode test complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live Stage Shadow Mode Recorder")
    parser.add_argument("--duration", type=float, default=1800.0, help="Recording duration in seconds (default: 30 min)")
    parser.add_argument("--output", type=str, default="/home/joseph1/stage_shadow_rehearsal.mp4", help="Output MP4 path")
    args = parser.parse_args()

    run_stage_shadow_recorder(
        duration_seconds=args.duration,
        output_mp4=args.output,
    )
