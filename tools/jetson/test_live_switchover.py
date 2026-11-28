"""Standalone 10-second verification of DirectorStream to Twitch (bandwidthtest mode).

Tests that DirectorStream can ingest camera feed, run Stage Director framing,
pipe to FFmpeg, and transmit to Twitch without errors.
"""
from __future__ import annotations

import json
import os
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

# Ensure stage-director is importable
STAGE_DIR = "/home/joseph1/stage-director"
if STAGE_DIR not in sys.path:
    sys.path.insert(0, STAGE_DIR)

from stage_director.adapter import StageFramingAdapter
from stage_director.core import BookingSnapshot
from stage_director.framing import FramingConfig
from stage_director.geometry import BoundingBox, StagePolygon
from stage_director.tracking import PerformerTracker


def get_nvr_token(ip, cfg):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    body = [{"cmd": "Login", "action": 0, "param": {"User": {"Version": "0", "userName": cfg["nvr_user"], "password": cfg["nvr_password"]}}}]
    req = urllib.request.Request(f"https://{ip}/api.cgi?cmd=Login", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    resp = json.loads(opener.open(req, timeout=5).read().decode())
    return resp[0]["value"]["Token"]["name"]


def main():
    cfg_path = "/home/joseph1/box2-stream/config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)

    nvr_ip = "10.0.0.6"
    print(f"Connecting to NVR at {nvr_ip}...")
    token = get_nvr_token(nvr_ip, cfg)
    source = f"http://{nvr_ip}/flv?port=1935&app=bcs&stream=channel{cfg['nvr_channel']}_{cfg['nvr_stream']}.bcs&token={token}"
    target = f"{cfg['twitch_server'].rstrip('/')}/{cfg['twitch_key']}?bandwidthtest=true"

    print("Opening video capture from NVR...")
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print("Failed to open NVR capture")
        sys.exit(1)

    ret, test_frame = cap.read()
    if not ret or test_frame is None:
        print("Failed to read frame")
        sys.exit(1)

    src_h, src_w = test_frame.shape[:2]
    out_w, out_h = 1280, 720
    fps = 20.0
    print(f"Camera input: {src_w}x{src_h} -> Output canvas: {out_w}x{out_h}")

    # Configure stage polygon & floor filter
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
        room_view_interval_s=45.0,
        room_view_duration_s=5.0,
        pacing_pullback_speed_threshold_px_s=300.0,
        pacing_pullback_factor=0.50,
    )
    tracker = PerformerTracker(
        stage_polygon=stage_polygon,
        loss_hold_seconds=2.5,
        allow_proximity_reacquisition=True,
        max_performer_y=float(floor_cutoff_y),
    )
    adapter = StageFramingAdapter(
        config=framing_config,
        tracker=tracker,
        allow_proximity_reacquisition=True,
    )

    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    booking = BookingSnapshot(
        booking_id="live-director", revision=1,
        slot_start_utc=now_utc - timedelta(seconds=1),
        slot_end_utc=now_utc + timedelta(hours=2),
        issued_at_utc=now_utc - timedelta(seconds=10),
        expires_at_utc=now_utc + timedelta(hours=3),
        stage_seconds=7200, privacy_class="public",
        checked_in=True, live_consent=True, tracking_consent=True, capture_verified=True,
    )
    adapter.arm(booking, now_utc)
    adapter.start_set(now_utc, time.monotonic(), host_confirmed=True)

    print("Spawning FFmpeg to Twitch in bandwidthtest mode...")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{out_w}x{out_h}",
        "-pix_fmt", "bgr24",
        "-r", str(int(fps)),
        "-i", "pipe:0",
        "-rw_timeout", "15000000",
        "-i", source,
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-b:v", "2500k",
        "-maxrate", "2500k",
        "-bufsize", "5000k",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "48000",
        "-ac", "2",
        "-f", "flv",
        "-flvflags", "no_duration_filesize",
        "-shortest",
        target,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)

    stats = {"frame": 0, "fps": 0.0, "bitrate": ""}

    def read_progress():
        for line in proc.stdout:
            try:
                line_str = line.decode("utf-8", errors="ignore").strip()
                k, _, v = line_str.partition("=")
                if k == "frame" and v.isdigit():
                    stats["frame"] = int(v)
                elif k == "fps":
                    stats["fps"] = float(v or 0)
                elif k == "bitrate":
                    stats["bitrate"] = v
            except Exception:
                pass

    threading.Thread(target=read_progress, daemon=True).start()

    print("Transmitting frames for 10 seconds...")
    t_start = time.time()
    frames_sent = 0
    try:
        while time.time() - t_start < 10.0:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            cur_mono = time.monotonic()
            cur_utc = datetime.now(timezone.utc)

            # Face detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            raw_faces = face_cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=3, minSize=(24, 24))

            candidate_boxes = []
            onstage_count = 0
            for (fx, fy, fw, fh) in raw_faces:
                bbox = BoundingBox(x=float(fx), y=float(fy), width=float(fw), height=float(fh))
                if bbox.center_y <= floor_cutoff_y and stage_polygon.contains_box(bbox):
                    candidate_boxes.append(bbox)
                    onstage_count += 1

            if adapter.tracker.state.value in ("acquiring", "ambiguous") and onstage_count == 1:
                adapter.confirm_subject(candidate_boxes[0], cur_mono)

            proposal = adapter.process_frame(candidate_boxes, cur_utc, cur_mono)

            crop = proposal.obs_crop
            if crop and proposal.camera_action == "track_face":
                x1 = max(0, crop["left"])
                y1 = max(0, crop["top"])
                x2 = min(src_w, src_w - crop["right"])
                y2 = min(src_h, src_h - crop["bottom"])
                if x2 > x1 + 10 and y2 > y1 + 10:
                    cropped = frame[y1:y2, x1:x2]
                    rendered = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
                else:
                    rendered = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
            else:
                rendered = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)

            proc.stdin.write(rendered.tobytes())
            proc.stdin.flush()
            frames_sent += 1

    finally:
        print("\nFinalizing test run...")
        cap.release()
        try:
            proc.stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    elapsed = time.time() - t_start
    print(f"Frames sent: {frames_sent} in {elapsed:.1f}s ({frames_sent / elapsed:.1f} FPS)")
    print(f"FFmpeg stats: {stats}")
    print("Test completed successfully!")


if __name__ == "__main__":
    main()
