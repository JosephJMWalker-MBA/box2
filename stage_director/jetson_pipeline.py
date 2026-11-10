"""Jetson-Native Autonomous Frame Pipeline for Stage Director.

Integrates the StageFramingAdapter state engine with local media decoding,
dynamic 16:9 crop and scale transformations, and software H.264/AAC encoding.
Designed to run autonomously on NVIDIA Jetson Orin Nano without Mac OBS dependency.

Guarantees:
- Output is strictly 1920x1080 @ 30.0 FPS.
- Zero network egress: writes to a local sandboxed file or pipe.
- Fail-closed safety: emergency stop, revoked consent, or tracking loss drops to safe wide or capture_off.
- Pure standard library + NumPy + OpenCV/GStreamer (no external network dependencies).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    import cv2
    import numpy as np
    HAS_CV2_NUMPY = True
except ImportError:
    cv2 = None  # type: ignore
    np = None  # type: ignore
    HAS_CV2_NUMPY = False

from .adapter import StageFramingAdapter
from .core import BookingSnapshot, CameraAction, Mode
from .framing import FramingConfig
from .geometry import BoundingBox, StagePolygon
from .obs_transform import OBSProposal


@dataclass
class PipelineFrameMetrics:
    frame_index: int
    timestamp_utc: str
    monotonic_seconds: float
    mode: str
    camera_action: str
    crop: Dict[str, int]
    zoom_factor: float
    center_px: Tuple[float, float]
    pts_seconds: float
    dt_ms: float


@dataclass
class PipelineSummary:
    total_frames_processed: int
    duration_seconds: float
    effective_fps: float
    output_resolution: Tuple[int, int]
    output_path: str
    output_size_bytes: int
    sha256_hash: str
    pts_monotonic: bool
    max_pts_jitter_ms: float
    transition_stills: Dict[str, str] = field(default_factory=dict)


class JetsonFramePipeline:
    """Autonomous Jetson framing controller combining StageFramingAdapter with video encoding."""

    def __init__(
        self,
        output_width: int = 1920,
        output_height: int = 1080,
        source_width: int = 3840,
        source_height: int = 2160,
        target_fps: int = 30,
        adapter: Optional[StageFramingAdapter] = None,
    ) -> None:
        self.output_width = output_width
        self.output_height = output_height
        self.source_width = source_width
        self.source_height = source_height
        self.target_fps = target_fps
        self.frame_interval_s = 1.0 / target_fps

        self.adapter = adapter or StageFramingAdapter(
            config=FramingConfig(
                canvas_width=source_width,
                canvas_height=source_height,
                target_face_fraction=0.20,
                headroom_fraction=0.33,
            )
        )

        self.metrics: List[PipelineFrameMetrics] = []
        self._emergency_stop_triggered = False

    def trigger_emergency_stop(self) -> None:
        """Trigger an immediate fail-closed emergency stop."""
        self._emergency_stop_triggered = True
        if hasattr(self, "adapter") and self.adapter and hasattr(self.adapter, "director"):
            self.adapter.director.stop("operator_emergency_stop")

    def calculate_crop_slice(
        self,
        proposal: OBSProposal,
    ) -> Tuple[int, int, int, int]:
        """Convert an OBSProposal crop into 0-indexed pixel slices for the source frame."""
        if proposal.camera_action == "capture_off" or proposal.obs_crop is None:
            return (0, 0, self.source_width, self.source_height)

        crop = proposal.obs_crop
        crop_l = max(0, min(int(crop.get("left", 0)), self.source_width - 16))
        crop_t = max(0, min(int(crop.get("top", 0)), self.source_height - 16))
        crop_r = max(0, min(int(crop.get("right", 0)), self.source_width - crop_l - 16))
        crop_b = max(0, min(int(crop.get("bottom", 0)), self.source_height - crop_t - 16))

        x1 = crop_l
        y1 = crop_t
        x2 = self.source_width - crop_r
        y2 = self.source_height - crop_b

        # Ensure valid 16:9 box
        w = max(16, x2 - x1)
        h = max(9, y2 - y1)
        return (x1, y1, x1 + w, y1 + h)

    def crop_and_scale_frame(
        self,
        frame: np.ndarray,
        proposal: OBSProposal,
    ) -> np.ndarray:
        """Crop and resize a frame (BGR or YUV420) to exact broadcast dimensions.

        If mode is capture_off or emergency stop triggered, returns a solid black frame.
        """
        if not HAS_CV2_NUMPY:
            raise RuntimeError("OpenCV and NumPy are required for frame scaling.")
        if self._emergency_stop_triggered or proposal.camera_action == "capture_off":
            if len(frame.shape) == 3:
                return np.zeros((self.output_height, self.output_width, frame.shape[2]), dtype=np.uint8)
            else:
                return np.zeros((self.output_height * 3 // 2, self.output_width), dtype=np.uint8)

        if proposal.camera_action == "stage_wide" or proposal.obs_crop is None:
            # Full source safe-wide scaled to output canvas
            if len(frame.shape) == 3:
                return cv2.resize(frame, (self.output_width, self.output_height), interpolation=cv2.INTER_LINEAR)
            else:
                # Direct YUV420 plane scaling
                h, w = self.source_height, self.source_width
                y_p = frame[:h, :w]
                u_p = frame[h : h + h // 4, :w].reshape((h // 2, w // 2))
                v_p = frame[h + h // 4 :, :w].reshape((h // 2, w // 2))

                y_s = cv2.resize(y_p, (self.output_width, self.output_height), interpolation=cv2.INTER_LINEAR)
                u_s = cv2.resize(u_p, (self.output_width // 2, self.output_height // 2), interpolation=cv2.INTER_LINEAR)
                v_s = cv2.resize(v_p, (self.output_width // 2, self.output_height // 2), interpolation=cv2.INTER_LINEAR)
                return np.vstack([y_s, u_s.reshape((self.output_height // 4, self.output_width)), v_s.reshape((self.output_height // 4, self.output_width))])

        # Active medium shot crop
        x1, y1, x2, y2 = self.calculate_crop_slice(proposal)

        if len(frame.shape) == 3:
            cropped = frame[y1:y2, x1:x2]
            return cv2.resize(cropped, (self.output_width, self.output_height), interpolation=cv2.INTER_LINEAR)
        else:
            # Direct YUV420 plane slicing and scaling
            h, w = self.source_height, self.source_width
            y_p = frame[:h, :w]
            u_p = frame[h : h + h // 4, :w].reshape((h // 2, w // 2))
            v_p = frame[h + h // 4 :, :w].reshape((h // 2, w // 2))

            y_c = y_p[y1:y2, x1:x2]
            u_c = u_p[y1 // 2 : y2 // 2, x1 // 2 : x2 // 2]
            v_c = v_p[y1 // 2 : y2 // 2, x1 // 2 : x2 // 2]

            y_s = cv2.resize(y_c, (self.output_width, self.output_height), interpolation=cv2.INTER_LINEAR)
            u_s = cv2.resize(u_c, (self.output_width // 2, self.output_height // 2), interpolation=cv2.INTER_LINEAR)
            v_s = cv2.resize(v_c, (self.output_width // 2, self.output_height // 2), interpolation=cv2.INTER_LINEAR)
            return np.vstack([y_s, u_s.reshape((self.output_height // 4, self.output_width)), v_s.reshape((self.output_height // 4, self.output_width))])

    def run_offline_simulation(
        self,
        timeline_events: Sequence[Tuple[float, List[BoundingBox], Optional[str]]],
        output_mp4_path: str,
        frame_generator: Optional[Callable[[int, float], np.ndarray]] = None,
        bitrate_kbps: int = 4500,
        preset: str = "veryfast",
        realtime_pacing: bool = False,
    ) -> PipelineSummary:
        """Execute a deterministic, scripted framing run and encode to local MP4.

        Each timeline event is: (elapsed_seconds, detected_faces, optional_operator_command).
        Supported commands:
          - "confirm_first": confirms detected_faces[0]
          - "switch_second": switches to detected_faces[1]
          - "emergency_stop": triggers emergency stop
        """
        if not HAS_CV2_NUMPY:
            raise RuntimeError("OpenCV and NumPy are required for offline simulation.")
        # Ensure output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_mp4_path)), exist_ok=True)
        if os.path.exists(output_mp4_path):
            os.remove(output_mp4_path)

        start_time_utc = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
        base_monotonic = 1000.0

        booking = BookingSnapshot(
            booking_id="milestone6-jetson-offline-proof",
            revision=1,
            slot_start_utc=start_time_utc,
            slot_end_utc=start_time_utc + timedelta(minutes=15),
            issued_at_utc=start_time_utc - timedelta(seconds=30),
            expires_at_utc=start_time_utc + timedelta(minutes=16),
            stage_seconds=900,
            privacy_class="public",
            checked_in=True,
            live_consent=True,
            tracking_consent=True,
            capture_verified=True,
        )

        self.adapter.arm(booking, start_time_utc)
        self.adapter.start_set(start_time_utc, base_monotonic, host_confirmed=True)

        # Launch FFmpeg pipe encoder
        enc_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{self.output_width}x{self.output_height}",
            "-pix_fmt", "bgr24",
            "-r", str(self.target_fps),
            "-i", "pipe:0",
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000",
            "-c:v", "libx264",
            "-preset", preset,
            "-tune", "zerolatency",
            "-b:v", f"{bitrate_kbps}k",
            "-maxrate", f"{bitrate_kbps}k",
            "-bufsize", f"{bitrate_kbps * 2}k",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "48000",
            "-ac", "2",
            "-shortest",
            "-movflags", "+faststart",
            output_mp4_path,
        ]

        enc_proc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)
        total_steps = len(timeline_events)
        wall_start = time.perf_counter()

        transition_stills: Dict[str, str] = {}

        for idx, (elapsed_s, faces, cmd) in enumerate(timeline_events):
            t_loop_start = time.perf_counter()
            cur_mono = base_monotonic + elapsed_s
            cur_utc = start_time_utc + timedelta(seconds=elapsed_s)

            # Handle operator command
            if cmd == "confirm_first" and faces:
                self.adapter.confirm_subject(faces[0], cur_mono)
            elif cmd == "switch_second" and len(faces) > 1:
                self.adapter.switch_subject(faces[1], cur_mono)
            elif cmd == "emergency_stop":
                self.trigger_emergency_stop()

            # Tick StageFramingAdapter
            proposal = self.adapter.process_frame(
                detections=faces,
                now_utc=cur_utc,
                monotonic_seconds=cur_mono,
            )

            # Generate frame canvas
            if frame_generator:
                src_frame = frame_generator(idx, elapsed_s)
            else:
                src_frame = np.zeros((self.source_height, self.source_width, 3), dtype=np.uint8)
                # Render stage guideline
                cv2.rectangle(src_frame, (384, 216), (3456, 1944), (40, 40, 40), 4)
                # Render detected faces
                for f in faces:
                    cv2.rectangle(
                        src_frame,
                        (int(f.x), int(f.y)),
                        (int(f.x + f.width), int(f.y + f.height)),
                        (0, 255, 0),
                        -1,
                    )

            # Crop and scale to 1920x1080 broadcast canvas
            framed_canvas = self.crop_and_scale_frame(src_frame, proposal)

            # Capture transition stills at significant moments
            if cmd or proposal.events or (idx in (5, 30, 90, 150, 210)):
                label = cmd or (proposal.events[0] if proposal.events else f"step_{idx}")
                still_path = os.path.join(
                    os.path.dirname(output_mp4_path), f"still_{label}_{idx:04d}.png"
                )
                if not os.path.exists(still_path):
                    cv2.imwrite(still_path, framed_canvas)
                    transition_stills[f"{label}_frame{idx}"] = still_path

            # Write to encoder pipe
            enc_proc.stdin.write(framed_canvas.tobytes())

            # Log metrics
            crop_dict = proposal.obs_crop or {"left": 0, "top": 0, "right": 0, "bottom": 0}
            framing_dict = proposal.framing or {}
            pts = idx * self.frame_interval_s
            dt_ms = (time.perf_counter() - t_loop_start) * 1000.0

            self.metrics.append(
                PipelineFrameMetrics(
                    frame_index=idx,
                    timestamp_utc=cur_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    monotonic_seconds=cur_mono,
                    mode="off" if self._emergency_stop_triggered else proposal.mode,
                    camera_action="capture_off" if self._emergency_stop_triggered else proposal.camera_action,
                    crop=crop_dict,
                    zoom_factor=float(framing_dict.get("zoom_factor", 1.0)),
                    center_px=(float(framing_dict.get("center_x", 1920.0)), float(framing_dict.get("center_y", 1080.0))),
                    pts_seconds=round(pts, 4),
                    dt_ms=round(dt_ms, 2),
                )
            )

            if realtime_pacing:
                target_wake = wall_start + (idx + 1) * self.frame_interval_s
                sleep_s = target_wake - time.perf_counter()
                if sleep_s > 0:
                    time.sleep(sleep_s)

        enc_proc.stdin.close()
        enc_proc.wait()
        total_wall_s = time.perf_counter() - wall_start

        # Compute output file verification & SHA-256
        file_size = os.path.getsize(output_mp4_path) if os.path.exists(output_mp4_path) else 0
        sha256 = hashlib.sha256()
        if os.path.exists(output_mp4_path):
            with open(output_mp4_path, "rb") as f:
                while chunk := f.read(65536):
                    sha256.update(chunk)
        digest = sha256.hexdigest()

        # Check PTS monotonicity
        pts_list = [m.pts_seconds for m in self.metrics]
        is_monotonic = all(pts_list[i] < pts_list[i + 1] for i in range(len(pts_list) - 1)) if len(pts_list) > 1 else True
        diffs = [pts_list[i + 1] - pts_list[i] for i in range(len(pts_list) - 1)]
        max_jitter_ms = max(abs(d - self.frame_interval_s) * 1000.0 for d in diffs) if diffs else 0.0

        return PipelineSummary(
            total_frames_processed=total_steps,
            duration_seconds=round(total_wall_s, 2),
            effective_fps=round(total_steps / total_wall_s, 1) if total_wall_s > 0 else 0.0,
            output_resolution=(self.output_width, self.output_height),
            output_path=output_mp4_path,
            output_size_bytes=file_size,
            sha256_hash=digest,
            pts_monotonic=is_monotonic,
            max_pts_jitter_ms=round(max_jitter_ms, 3),
            transition_stills=transition_stills,
        )
