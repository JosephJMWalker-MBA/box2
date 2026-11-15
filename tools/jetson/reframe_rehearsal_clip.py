"""Re-frames a recorded stage rehearsal clip using updated Stage Director parameters:
- Head-and-shoulders close-up (target_face_fraction=0.33, max_zoom=3.6)
- Periodic Room View ("Breathing Wide") cadence (45s close-up / 5s wide room)
- Automatic Proximity Reacquisition on Stage Rug
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import time

import cv2
import numpy as np

# Ensure repository root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from stage_director.adapter import StageFramingAdapter
from stage_director.core import BookingSnapshot
from stage_director.framing import FramingConfig
from stage_director.geometry import BoundingBox, StagePolygon
from stage_director.tracking import PerformerTracker


def main():
    parser = argparse.ArgumentParser(description="Reframe recorded stage rehearsal")
    parser.add_argument("--input", default="/home/joseph1/stage_shadow_rehearsal.mp4", help="Input rehearsal MP4")
    parser.add_argument("--output", default="/home/joseph1/reframed_director_rehearsal.mp4", help="Output reframed MP4")
    parser.add_argument("--max-frames", type=int, default=3000, help="Maximum frames to process (3000 = 120s @ 25fps)")
    parser.add_argument("--stills-dir", default="/home/joseph1/stage-director/jetson/stills_v2", help="Directory for verification stills")
    args = parser.parse_args()

    os.makedirs(args.stills_dir, exist_ok=True)

    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        print(f"Error opening {args.input}")
        sys.exit(1)

    total_input_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Input: {args.input} ({width}x{height} @ {fps:.1f} fps, {total_input_frames} frames)")

    # Target output resolution
    out_w, out_h = 1280, 720
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.output, fourcc, fps, (out_w, out_h))

    # Stage polygon scaled to input resolution (1280x720)
    # Standing comedian head is in y in [50, 215]; floor/pets (y > 220) and offstage are excluded.
    scale_x = width / 640.0
    scale_y = height / 360.0
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
        canvas_width=width,
        canvas_height=height,
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

    now_utc = datetime(2026, 11, 15, 0, 0, 0, tzinfo=timezone.utc)
    booking = BookingSnapshot(
        booking_id="reframe-rehearsal",
        revision=1,
        slot_start_utc=now_utc - timedelta(seconds=1),
        slot_end_utc=now_utc + timedelta(seconds=3600),
        issued_at_utc=now_utc - timedelta(seconds=30),
        expires_at_utc=now_utc + timedelta(seconds=3700),
        stage_seconds=3600,
        privacy_class="public",
        checked_in=True,
        live_consent=True,
        tracking_consent=True,
        capture_verified=True,
    )
    adapter.arm(booking, now_utc)
    adapter.start_set(now_utc, 0.0, host_confirmed=True)

    print("Beginning re-framing run...")
    frame_idx = 0
    max_frames = min(args.max_frames, total_input_frames) if args.max_frames > 0 else total_input_frames

    close_up_frames = 0
    room_view_frames = 0
    reacquired_count = 0
    t_start = time.time()

    still_closeup = None
    still_room_view = None
    still_original_closeup = None

    while frame_idx < max_frames:
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        mono_t = frame_idx / fps
        cur_utc = now_utc + timedelta(seconds=mono_t)

        # Detect faces (downscale for speed)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # 1280x720 face size is ~60-80px; minSize=(40,40)
        raw_faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.10,
            minNeighbors=3,
            minSize=(35, 35),
        )

        candidate_boxes = []
        onstage_count = 0
        for (fx, fy, fw, fh) in raw_faces:
            bbox = BoundingBox(x=float(fx), y=float(fy), width=float(fw), height=float(fh))
            if stage_polygon.contains_box(bbox):
                candidate_boxes.append(bbox)
                onstage_count += 1

        if adapter.tracker.state.value in ("acquiring", "ambiguous") and onstage_count == 1:
            adapter.confirm_subject(candidate_boxes[0], mono_t)

        proposal = adapter.process_frame(
            detections=candidate_boxes,
            now_utc=cur_utc,
            monotonic_seconds=mono_t,
        )

        for ev in proposal.events:
            if ev == "camera_subject_reacquired":
                reacquired_count += 1

        # Check zoom factor
        zoom = proposal.framing["zoom_factor"] if proposal.framing else 1.0
        if zoom > 1.8:
            close_up_frames += 1
        elif zoom < 1.2 and frame_idx > 100:
            room_view_frames += 1

        # Crop and resize
        crop = proposal.obs_crop
        if crop and proposal.camera_action == "track_face":
            x1 = max(0, crop["left"])
            y1 = max(0, crop["top"])
            x2 = min(width, width - crop["right"])
            y2 = min(height, height - crop["bottom"])
            if x2 > x1 + 10 and y2 > y1 + 10:
                cropped = frame[y1:y2, x1:x2]
                rendered = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
            else:
                rendered = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
        else:
            rendered = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)

        # Save verification stills
        if zoom >= 2.5 and still_closeup is None and frame_idx > 200:
            still_closeup = rendered.copy()
            still_original_closeup = frame.copy()
            cv2.imwrite(os.path.join(args.stills_dir, "still_01_closeup_head_and_shoulders.jpg"), still_closeup)
            cv2.imwrite(os.path.join(args.stills_dir, "still_01_original_wide_reference.jpg"), still_original_closeup)

        if "periodic_room_view_started" in proposal.events or (zoom < 1.15 and frame_idx > 1100 and still_room_view is None):
            still_room_view = rendered.copy()
            cv2.imwrite(os.path.join(args.stills_dir, "still_02_periodic_room_view_establishing.jpg"), still_room_view)

        writer.write(rendered)
        frame_idx += 1

        if frame_idx % 250 == 0:
            elapsed = time.time() - t_start
            proc_fps = frame_idx / elapsed
            print(f"Processed {frame_idx}/{max_frames} frames ({proc_fps:.1f} FPS) | State: {proposal.tracking_state} | Zoom: {zoom:.2f}x")

    cap.release()
    writer.release()
    total_time = time.time() - t_start

    print(f"\nDone! Processed {frame_idx} frames in {total_time:.1f}s ({frame_idx/total_time:.1f} FPS).")
    print(f"Close-up frames (zoom > 1.8x): {close_up_frames} ({close_up_frames/frame_idx*100:.1f}%)")
    print(f"Room-view frames (zoom < 1.2x): {room_view_frames} ({room_view_frames/frame_idx*100:.1f}%)")
    print(f"Auto-reacquisitions on stage:  {reacquired_count}")
    print(f"Output saved to: {args.output}")

    # Build side-by-side comparison if we have closeup still
    if still_closeup is not None and still_original_closeup is not None:
        orig_resized = cv2.resize(still_original_closeup, (out_w // 2, out_h // 2))
        close_resized = cv2.resize(still_closeup, (out_w // 2, out_h // 2))

        # Add label bars
        cv2.putText(orig_resized, "RAW WIDE STAGE (ORIGINAL)", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(close_resized, "STAGE DIRECTOR CLOSE-UP", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        sbs = np.hstack([orig_resized, close_resized])
        sbs_path = os.path.join(args.stills_dir, "still_03_side_by_side_comparison.jpg")
        cv2.imwrite(sbs_path, sbs)
        print(f"Side-by-side comparison saved to: {sbs_path}")


if __name__ == "__main__":
    main()
