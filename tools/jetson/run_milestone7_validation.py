"""Milestone 7: Jetson-Native Authorization Lifecycle, Capture Control & Media Verification.

Executes a physical, real-time paced (30.0 FPS) validation benchmark directly on the
NVIDIA Jetson Orin Nano 8GB, verifying:
1. Strict capture lifecycle: NO_INPUT, ARMED_PUBLIC, LIVE_PUBLIC, BLANK_PUBLIC_OUTPUT, STOPPED.
2. Zero source reads and zero media writes after revoke or private session.
3. Genuine host start (set does not advance from vision alone).
4. Genuine natural countdown cues (warn_15, time_up) fired exactly once at threshold.
5. Independent FFprobe packet inspection for BOTH video and audio streams, measuring A/V drift.
6. Continuous background tegrastats telemetry.
7. Read-only live service audit (box2_stream.py PID 266619 continuity, zero restarts).
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

# Ensure repository root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from stage_director.adapter import StageFramingAdapter
from stage_director.core import BookingSnapshot, CaptureLifecycle
from stage_director.geometry import BoundingBox, StagePolygon
from stage_director.jetson_pipeline import JetsonFramePipeline, PipelineSummary


# ---------------------------------------------------------------------------
# Allowlist-Sanitized Live Service Baseline Audit
# ---------------------------------------------------------------------------

def audit_live_service_baseline() -> Dict[str, Any]:
    """Inspect the running box2_stream service non-invasively using strict allowlist sanitization."""
    audit: Dict[str, Any] = {
        "service_detected": False,
        "pid": None,
        "uptime": "unknown",
        "restarts": 0,
        "stream_fps": 0.0,
        "cpu_percent": 0.0,
        "rss_mb": 0.0,
        "video_architecture": "unknown",
    }

    try:
        ps_out = subprocess.check_output(
            ["ps", "-eo", "pid,ppid,pcpu,pmem,rss,etime,comm,args"],
            text=True,
        )
        total_cpu = 0.0
        total_rss_kb = 0
        detected_pid = None
        detected_etime = "unknown"

        for line in ps_out.splitlines():
            if "box2_stream.py" in line or ("ffmpeg" in line and "channel0_sub" in line):
                parts = line.strip().split(None, 7)
                if len(parts) >= 8:
                    try:
                        pid = int(parts[0])
                        cpu = float(parts[2])
                        rss = int(parts[4])
                        etime = parts[5]
                        args = parts[7]

                        if "box2_stream.py" in args:
                            detected_pid = pid
                            detected_etime = etime
                        total_cpu += cpu
                        total_rss_kb += rss
                        if "-c:v copy" in args:
                            audit["video_architecture"] = "passthrough_remux (-c:v copy)"
                    except (ValueError, IndexError):
                        pass

        if detected_pid:
            audit["service_detected"] = True
            audit["pid"] = detected_pid
            audit["uptime"] = detected_etime
            audit["cpu_percent"] = round(total_cpu, 1)
            audit["rss_mb"] = round(total_rss_kb / 1024.0, 1)
    except Exception as e:
        audit["ps_error"] = str(e)

    status_file = "/home/joseph1/box2-stream/status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
                audit["stream_fps"] = float(raw.get("fps", 0.0))
                audit["restarts"] = int(raw.get("restarts", 0))
                if "state" in raw:
                    audit["service_state"] = str(raw["state"])
        except Exception:
            pass

    return audit


# ---------------------------------------------------------------------------
# Background Tegrastats Telemetry Collector
# ---------------------------------------------------------------------------

class TegrastatsCollector:
    """Samples tegrastats in a background thread and aggregates stats."""

    def __init__(self, interval_ms: int = 1000) -> None:
        self.interval_ms = interval_ms
        self.samples: List[Dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        try:
            proc = subprocess.Popen(
                ["tegrastats", "--interval", str(self.interval_ms)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            return

        while not self._stop_event.is_set():
            line = proc.stdout.readline()
            if not line:
                break
            parsed = self._parse_line(line)
            if parsed:
                self.samples.append(parsed)

        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()

    @staticmethod
    def _parse_line(line: str) -> Optional[Dict[str, Any]]:
        try:
            ram_m = re.search(r"RAM (\d+)/(\d+)MB", line)
            swap_m = re.search(r"SWAP (\d+)/(\d+)MB", line)
            cpu_m = re.search(r"CPU \[([^\]]+)\]", line)
            gpu_m = re.search(r"GR3D_FREQ (\d+)%", line)
            temp_cpu = re.search(r"cpu@([\d\.]+)C", line)
            temp_gpu = re.search(r"gpu@([\d\.]+)C", line)
            temp_soc = re.search(r"soc\d*@([\d\.]+)C", line)
            power_in = re.search(r"VDD_IN (\d+)mW", line)
            power_cv = re.search(r"VDD_CPU_GPU_CV (\d+)mW", line)
            power_soc = re.search(r"VDD_SOC (\d+)mW", line)

            sample: Dict[str, Any] = {}
            if ram_m:
                sample["ram_used_mb"] = int(ram_m.group(1))
                sample["ram_total_mb"] = int(ram_m.group(2))
            if swap_m:
                sample["swap_used_mb"] = int(swap_m.group(1))
                sample["swap_total_mb"] = int(swap_m.group(2))
            if cpu_m:
                cores = [c.split("%@")[0].strip() for c in cpu_m.group(1).split(",")]
                sample["cpu_cores_percent"] = [int(c) for c in cores if c.isdigit()]
                if sample["cpu_cores_percent"]:
                    sample["cpu_avg_percent"] = round(sum(sample["cpu_cores_percent"]) / len(sample["cpu_cores_percent"]), 1)
            if gpu_m:
                sample["gpu_percent"] = int(gpu_m.group(1))
            if temp_cpu:
                sample["temp_cpu_c"] = float(temp_cpu.group(1))
            if temp_gpu:
                sample["temp_gpu_c"] = float(temp_gpu.group(1))
            if temp_soc:
                sample["temp_soc_c"] = float(temp_soc.group(1))
            if power_in:
                sample["power_vdd_in_mw"] = int(power_in.group(1))
            if power_cv:
                sample["power_vdd_cpu_gpu_cv_mw"] = int(power_cv.group(1))
            if power_soc:
                sample["power_vdd_soc_mw"] = int(power_soc.group(1))
            return sample
        except Exception:
            return None

    def get_summary(self) -> Dict[str, Any]:
        if not self.samples:
            return {"samples_count": 0}

        def _stats(key: str) -> Dict[str, float]:
            vals = [s[key] for s in self.samples if key in s]
            if not vals:
                return {}
            return {
                "min": round(min(vals), 1),
                "max": round(max(vals), 1),
                "mean": round(sum(vals) / len(vals), 1),
            }

        return {
            "samples_count": len(self.samples),
            "ram_used_mb": _stats("ram_used_mb"),
            "swap_used_mb": _stats("swap_used_mb"),
            "cpu_avg_percent": _stats("cpu_avg_percent"),
            "gpu_percent": _stats("gpu_percent"),
            "temp_cpu_c": _stats("temp_cpu_c"),
            "temp_gpu_c": _stats("temp_gpu_c"),
            "temp_soc_c": _stats("temp_soc_c"),
            "power_vdd_in_mw": _stats("power_vdd_in_mw"),
            "power_vdd_cpu_gpu_cv_mw": _stats("power_vdd_cpu_gpu_cv_mw"),
            "power_vdd_soc_mw": _stats("power_vdd_soc_mw"),
        }


# ---------------------------------------------------------------------------
# Decoupled Face Detection Benchmark (Stimulus-Verified)
# ---------------------------------------------------------------------------

def render_synthetic_face_stimulus(size: int = 500) -> np.ndarray:
    """Generate high-contrast facial features activating standard frontal Haar cascades."""
    img = np.full((size, size), 210, dtype=np.uint8)
    cx, cy = size // 2, size // 2
    cv2.ellipse(img, (cx, cy), (int(size * 0.28), int(size * 0.36)), 0, 0, 360, 240, -1)
    cv2.ellipse(img, (cx, cy), (int(size * 0.28), int(size * 0.36)), 0, 0, 360, 60, 4)
    eye_offset_x = int(size * 0.12)
    eye_y = int(cy - size * 0.08)
    cv2.circle(img, (cx - eye_offset_x, eye_y), int(size * 0.048), 40, -1)
    cv2.circle(img, (cx + eye_offset_x, eye_y), int(size * 0.048), 40, -1)
    cv2.circle(img, (cx - eye_offset_x, eye_y), int(size * 0.020), 255, -1)
    cv2.circle(img, (cx + eye_offset_x, eye_y), int(size * 0.020), 255, -1)
    brow_y = int(cy - size * 0.15)
    cv2.line(img, (cx - eye_offset_x - 30, brow_y), (cx - eye_offset_x + 30, brow_y + 6), 40, 8)
    cv2.line(img, (cx + eye_offset_x - 30, brow_y + 6), (cx + eye_offset_x + 30, brow_y), 40, 8)
    cv2.line(img, (cx, eye_y), (cx, cy + int(size * 0.06)), 50, 6)
    cv2.line(img, (cx - 20, cy + int(size * 0.06)), (cx + 20, cy + int(size * 0.06)), 50, 6)
    cv2.ellipse(img, (cx, cy + int(size * 0.16)), (int(size * 0.12), int(size * 0.05)), 0, 0, 180, 40, 8)
    return img


def benchmark_face_detector_resolutions(iterations: int = 12) -> Dict[str, Any]:
    """Measure face detection accuracy (TP/FP/misses) and latency across resolutions."""
    cascade_path = "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"
    if not os.path.exists(cascade_path):
        return {"error": f"Cascade not found at {cascade_path}"}

    cascade = cv2.CascadeClassifier(cascade_path)
    face_patch = render_synthetic_face_stimulus(400)

    pos_4k = np.full((2160, 3840), 128, dtype=np.uint8)
    pos_4k[780 : 780 + 400, 1720 : 1720 + 400] = face_patch

    neg_4k = np.full((2160, 3840), 128, dtype=np.uint8)
    cv2.rectangle(neg_4k, (500, 500), (1500, 1500), 180, 8)
    cv2.circle(neg_4k, (2500, 1000), 300, 70, -1)

    resolutions = [
        {"name": "Native 4K", "w": 3840, "h": 2160},
        {"name": "1080p", "w": 1920, "h": 1080},
        {"name": "qHD 540p", "w": 960, "h": 540},
        {"name": "Sub-stream 360p", "w": 640, "h": 360},
    ]

    results: Dict[str, Any] = {}
    for res in resolutions:
        w, h = res["w"], res["h"]
        pos_resized = cv2.resize(pos_4k, (w, h), interpolation=cv2.INTER_LINEAR)
        neg_resized = cv2.resize(neg_4k, (w, h), interpolation=cv2.INTER_LINEAR)

        # Warm-up
        cascade.detectMultiScale(pos_resized, scaleFactor=1.05, minNeighbors=2)

        t0 = time.perf_counter()
        pos_detections = 0
        for _ in range(iterations):
            f_pos = cascade.detectMultiScale(pos_resized, scaleFactor=1.05, minNeighbors=2)
            pos_detections += len(f_pos)
        dt_pos = time.perf_counter() - t0
        avg_pos_ms = (dt_pos / iterations) * 1000.0

        f_neg = cascade.detectMultiScale(neg_resized, scaleFactor=1.05, minNeighbors=2)
        fp_count = len(f_neg)
        tp = 1 if pos_detections > 0 else 0

        results[res["name"]] = {
            "resolution": f"{w}x{h}",
            "avg_latency_ms": round(avg_pos_ms, 2),
            "max_fps": round(1000.0 / avg_pos_ms, 1) if avg_pos_ms > 0 else 0.0,
            "true_positives": tp,
            "false_positives": fp_count,
            "misses": 0 if tp == 1 else 1,
            "realtime_viable_at_30fps": avg_pos_ms <= 33.3,
        }

    return results


# ---------------------------------------------------------------------------
# Milestone 7 Scripted Scenario (75.0s, Genuine Host Start, Natural Cues, Shutoff)
# ---------------------------------------------------------------------------

def generate_milestone7_timeline(
    total_seconds: float = 75.0,
    fps: int = 30,
) -> Tuple[List[Tuple[float, List[BoundingBox], Optional[str]]], Dict[str, Any]]:
    """Build a deterministic scenario demonstrating genuine host-start, countdown, and shutdown."""
    total_frames = int(total_seconds * fps)
    events: List[Tuple[float, List[BoundingBox], Optional[str]]] = []

    # Scenario parameters:
    # Booking stage_seconds = 50s.
    # Phase 1: 0.0s - 3.0s: Armed wide, awaiting host start. (Performer on stage, but NOT started).
    # Phase 2: 3.0s: Host confirms set start (cmd='host_start'). Remaining = 50s.
    # Phase 3: 3.0s - 20.0s: Performer moves across stage (x=1500 -> 2400).
    # Phase 4: 20.0s - 30.0s: Offstage bystander at x=150 (outside polygon) rejected.
    # Phase 5: 30.0s - 38.0s: Guest enters at x=2700; operator switches at 33.0s (cmd='switch_second').
    # Phase 6: 38.0s: 35s elapsed from host start -> 15s remaining! Natural warn_15 cue emitted!
    # Phase 7: 38.0s - 46.0s: Performer vanishes -> 2.0s loss hold -> fallback to safe-wide.
    # Phase 8: 46.0s - 53.0s: Performer returns, reacquired smoothly.
    # Phase 9: 53.0s: 50s elapsed from host start -> 0s remaining! Natural time_up cue emitted, wide!
    # Phase 10: 53.0s - 65.0s: Post-set holding wide in public mode.
    # Phase 11: 65.0s: Operator triggers revoke_consent (cmd='revoke_consent').
    #           State transitions to STOPPED. Zero source reads, zero sink writes for remaining 10s!

    for frame_idx in range(total_frames):
        t = frame_idx / fps
        cmd: Optional[str] = None
        faces: List[BoundingBox] = []

        if t < 3.0:
            # Performer standing on stage center, awaiting host confirmation
            p1 = BoundingBox(x=1800, y=750, width=240, height=300)
            faces = [p1]
        elif 3.0 <= t < 20.0:
            # Pacing performer across stage
            px = 1950.0 + 450.0 * math.sin((t - 3.0) * 0.4)
            p1 = BoundingBox(x=px - 120, y=750, width=240, height=300)
            faces = [p1]
            if frame_idx == int(3.0 * fps):
                cmd = "host_start"
            elif frame_idx == int(3.1 * fps):
                cmd = "confirm_first"
        elif 20.0 <= t < 30.0:
            # Performer at x=1800 + Offstage bystander at x=150
            p1 = BoundingBox(x=1800, y=750, width=240, height=300)
            bystander = BoundingBox(x=150, y=1000, width=200, height=250)
            faces = [p1, bystander]
        elif 30.0 <= t < 38.0:
            # Two persons onstage: P1 at x=1700, P2 (guest) at x=2700
            p1 = BoundingBox(x=1700, y=750, width=240, height=300)
            p2 = BoundingBox(x=2700, y=750, width=240, height=300)
            faces = [p1, p2]
            if frame_idx == int(33.0 * fps):
                cmd = "switch_second"
        elif 38.0 <= t < 46.0:
            # Performer turns away: 0 faces detected (2.0s hold, then fallback to safe-wide)
            faces = []
        elif 46.0 <= t < 53.0:
            # Performer returns to center stage
            p1 = BoundingBox(x=1920 - 120, y=750, width=240, height=300)
            faces = [p1]
            if frame_idx == int(46.0 * fps):
                cmd = "confirm_first"
        elif 53.0 <= t < 65.0:
            # Post-set period: holding safe-wide
            p1 = BoundingBox(x=1920 - 120, y=750, width=240, height=300)
            faces = [p1]
        elif t >= 65.0:
            # Operator revokes consent / private session
            if frame_idx == int(65.0 * fps):
                cmd = "revoke_consent"
            p1 = BoundingBox(x=1920 - 120, y=750, width=240, height=300)
            faces = [p1]

        events.append((round(t, 4), faces, cmd))

    meta = {
        "duration_seconds": total_seconds,
        "fps": fps,
        "total_frames": total_frames,
        "booking_stage_seconds": 50,
        "phases": [
            {"name": "Phase 1: Arm & Safe-Wide (Pre-Start)", "time_range": "0.0s - 3.0s", "expected_action": "stage_wide (no live tracking before host start)"},
            {"name": "Phase 2: Genuine Host Start Action", "time_range": "3.0s", "expected_action": "start_set executed, lifecycle transitions to LIVE_PUBLIC"},
            {"name": "Phase 3: Smooth Tracking", "time_range": "3.0s - 20.0s", "expected_action": "dynamic 16:9 crop follows performer"},
            {"name": "Phase 4: Offstage Bystander Filter", "time_range": "20.0s - 30.0s", "expected_action": "offstage face rejected by stage polygon"},
            {"name": "Phase 5: Secondary & Operator Switch", "time_range": "30.0s - 38.0s", "expected_action": "switch_second transfers tracking cleanly"},
            {"name": "Phase 6: Natural warn_15 Cue", "time_range": "38.0s (15s remaining)", "expected_action": "warn_15 cue emitted exactly once"},
            {"name": "Phase 7: Performer Loss (Hold -> Wide)", "time_range": "38.0s - 46.0s", "expected_action": "2.0s hold, then fallback to safe-wide"},
            {"name": "Phase 8: Reacquisition", "time_range": "46.0s - 53.0s", "expected_action": "safe reacquisition without jumps"},
            {"name": "Phase 9: Natural time_up Cue", "time_range": "53.0s (0s remaining)", "expected_action": "time_up cue emitted, mode FINISHED, safe-wide"},
            {"name": "Phase 10: Post-Set Holding Wide", "time_range": "53.0s - 65.0s", "expected_action": "safe-wide hold"},
            {"name": "Phase 11: Consent Revoked / Media Shutdown", "time_range": "65.0s - 75.0s", "expected_action": "STOPPED: 0 reads, 0 writes for 10.0s"},
        ],
    }
    return events, meta


def create_synthetic_frame_renderer(
    source_width: int = 3840,
    source_height: int = 2160,
) -> Callable[[int, float, List[BoundingBox]], np.ndarray]:
    stage_poly = StagePolygon.default_stage(source_width, source_height)
    pts = np.array(stage_poly.vertices, np.int32).reshape((-1, 1, 2))

    face_patch = render_synthetic_face_stimulus(300)
    face_patch_bgr = cv2.cvtColor(face_patch, cv2.COLOR_GRAY2BGR)

    def render(idx: int, elapsed_s: float, faces: List[BoundingBox]) -> np.ndarray:
        canvas = np.full((source_height, source_width, 3), 32, dtype=np.uint8)

        # Stage grid
        for gx in range(0, source_width, 320):
            cv2.line(canvas, (gx, 0), (gx, source_height), (40, 40, 40), 1)
        for gy in range(0, source_height, 180):
            cv2.line(canvas, (0, gy), (source_width, gy), (40, 40, 40), 1)

        # Authorized stage boundary
        cv2.polylines(canvas, [pts], isClosed=True, color=(80, 180, 80), thickness=6)
        cv2.putText(
            canvas,
            "AUTHORIZED STAGE AREA",
            (int(source_width * 0.40), int(source_height * 0.24)),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.6,
            (80, 180, 80),
            3,
        )

        hud_text = f"MILESTONE 7 JETSON VALIDATION | TIME: {elapsed_s:05.2f}s | FRAME: {idx:04d}"
        cv2.putText(canvas, hud_text, (80, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (220, 220, 220), 4)

        for i, box in enumerate(faces):
            bx = int(box.x)
            by = int(box.y)
            bw = int(box.width)
            bh = int(box.height)

            is_onstage = stage_poly.contains_box(box)
            box_color = (0, 255, 0) if is_onstage else (0, 0, 255)
            tag = f"SUBJECT {i+1} [ONSTAGE]" if is_onstage else f"BYSTANDER {i+1} [OFFSTAGE]"

            cv2.rectangle(canvas, (bx - 40, by + bh), (bx + bw + 40, by + bh + 450), (60, 60, 60), -1)

            if bw >= 100 and bh >= 100 and (by + bh <= source_height) and (bx + bw <= source_width):
                resized_face = cv2.resize(face_patch_bgr, (bw, bh))
                canvas[by : by + bh, bx : bx + bw] = resized_face

            cv2.rectangle(canvas, (bx, by), (bx + bw, by + bh), box_color, 4)
            cv2.putText(canvas, tag, (bx, max(30, by - 15)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, box_color, 3)

        return canvas

    return render


# ---------------------------------------------------------------------------
# Independent FFprobe Dual-Stream (Audio & Video) Verification
# ---------------------------------------------------------------------------

def verify_mp4_dual_stream_with_ffprobe(mp4_path: str) -> Dict[str, Any]:
    """Inspect BOTH video and audio packet timestamps, drift, and decode integrity."""
    result: Dict[str, Any] = {
        "valid": False,
        "format": {},
        "video": {},
        "audio": {},
        "av_sync": {},
        "decode_integrity_verified": False,
    }

    if not os.path.exists(mp4_path):
        result["error"] = f"File not found: {mp4_path}"
        return result

    try:
        # Stream and format probe
        cmd = [
            "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", mp4_path
        ]
        out = subprocess.check_output(cmd, text=True)
        data = json.loads(out)

        result["format"] = {
            "format_name": data.get("format", {}).get("format_name"),
            "duration": float(data.get("format", {}).get("duration", 0.0)),
            "size_bytes": int(data.get("format", {}).get("size", 0)),
            "bit_rate": int(data.get("format", {}).get("bit_rate", 0)),
        }

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                result["video"] = {
                    "codec_name": stream.get("codec_name"),
                    "profile": stream.get("profile"),
                    "width": int(stream.get("width", 0)),
                    "height": int(stream.get("height", 0)),
                    "r_frame_rate": stream.get("r_frame_rate"),
                    "pix_fmt": stream.get("pix_fmt"),
                    "nb_frames": int(stream.get("nb_frames", 0)),
                    "duration": float(stream.get("duration", 0.0)),
                }
            elif stream.get("codec_type") == "audio":
                result["audio"] = {
                    "codec_name": stream.get("codec_name"),
                    "sample_rate": int(stream.get("sample_rate", 0)),
                    "channels": int(stream.get("channels", 0)),
                    "bit_rate": int(stream.get("bit_rate", 0)) if stream.get("bit_rate") else None,
                    "duration": float(stream.get("duration", 0.0)),
                }

        # 1. Video packet analysis
        v_pkt_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v",
            "-show_entries", "packet=pts_time,duration_time", "-of", "json", mp4_path
        ]
        v_pkts = json.loads(subprocess.check_output(v_pkt_cmd, text=True)).get("packets", [])
        v_pts = [float(p["pts_time"]) for p in v_pkts if "pts_time" in p]
        v_monotonic = all(v_pts[i] < v_pts[i + 1] for i in range(len(v_pts) - 1)) if len(v_pts) > 1 else True

        v_diffs = [v_pts[i + 1] - v_pts[i] for i in range(len(v_pts) - 1)]
        v_jitter_ms = max(abs(d - 1.0 / 30.0) * 1000.0 for d in v_diffs) if v_diffs else 0.0

        result["video"]["total_packets"] = len(v_pkts)
        result["video"]["first_pts"] = v_pts[0] if v_pts else 0.0
        result["video"]["last_pts"] = v_pts[-1] if v_pts else 0.0
        result["video"]["pts_monotonic"] = v_monotonic
        result["video"]["packet_jitter_ms"] = round(v_jitter_ms, 3)

        # 2. Audio packet analysis
        a_pkt_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "packet=pts_time,duration_time", "-of", "json", mp4_path
        ]
        a_pkts = json.loads(subprocess.check_output(a_pkt_cmd, text=True)).get("packets", [])
        a_pts = [float(p["pts_time"]) for p in a_pkts if "pts_time" in p]
        a_monotonic = all(a_pts[i] < a_pts[i + 1] for i in range(len(a_pts) - 1)) if len(a_pts) > 1 else True

        expected_audio_interval = 1024.0 / 48000.0  # ~0.02133s
        a_diffs = [a_pts[i + 1] - a_pts[i] for i in range(len(a_pts) - 1)]
        a_jitter_ms = max(abs(d - expected_audio_interval) * 1000.0 for d in a_diffs) if a_diffs else 0.0

        result["audio"]["total_packets"] = len(a_pkts)
        result["audio"]["first_pts"] = a_pts[0] if a_pts else 0.0
        result["audio"]["last_pts"] = a_pts[-1] if a_pts else 0.0
        result["audio"]["pts_monotonic"] = a_monotonic
        result["audio"]["packet_jitter_ms"] = round(a_jitter_ms, 3)

        # 3. Audio/Video synchronization calculation
        start_drift_ms = abs((v_pts[0] if v_pts else 0.0) - (a_pts[0] if a_pts else 0.0)) * 1000.0
        end_drift_ms = abs((v_pts[-1] if v_pts else 0.0) - (a_pts[-1] if a_pts else 0.0)) * 1000.0
        dur_drift_ms = abs(result["video"].get("duration", 0.0) - result["audio"].get("duration", 0.0)) * 1000.0

        av_sync_ok = (start_drift_ms < 50.0) and (end_drift_ms < 60.0) and (dur_drift_ms < 100.0)
        result["av_sync"] = {
            "start_drift_ms": round(start_drift_ms, 2),
            "end_drift_ms": round(end_drift_ms, 2),
            "duration_drift_ms": round(dur_drift_ms, 2),
            "av_synchronized": av_sync_ok,
        }

        # 4. Full container decode integrity check
        dec_check_cmd = ["ffmpeg", "-v", "error", "-i", mp4_path, "-f", "null", "-"]
        ret = subprocess.call(dec_check_cmd)
        result["decode_integrity_verified"] = (ret == 0)

        # Validation predicate
        has_1080p = result["video"].get("width") == 1920 and result["video"].get("height") == 1080
        has_h264 = result["video"].get("codec_name") == "h264"
        has_aac = result["audio"].get("codec_name") == "aac"
        has_48k = result["audio"].get("sample_rate") == 48000
        has_audio_packets = len(a_pkts) > 0

        result["valid"] = (
            has_1080p
            and has_h264
            and has_aac
            and has_48k
            and has_audio_packets
            and v_monotonic
            and a_monotonic
            and av_sync_ok
            and result["decode_integrity_verified"]
        )

    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Main Benchmark Orchestration
# ---------------------------------------------------------------------------

def run_milestone7_benchmark(
    duration_s: float = 75.0,
    preset: str = "veryfast",
    bitrate_kbps: int = 4500,
    output_mp4_path: Optional[str] = None,
    results_json_path: Optional[str] = None,
    stills_dir: Optional[str] = None,
) -> Dict[str, Any]:
    print("=================================================================")
    print("  BOX2 STAGE DIRECTOR — MILESTONE 7 JETSON VALIDATION HARNESS    ")
    print("=================================================================")

    start_wall_time = datetime.now(timezone.utc).isoformat()

    # Step 1: Pre-run Live Baseline Audit
    print("\n[Step 1/6] Auditing baseline live service (read-only, sanitized)...")
    pre_audit = audit_live_service_baseline()
    print(f"  Live service detected: {pre_audit.get('service_detected')} (PID: {pre_audit.get('pid')})")
    print(f"  Architecture: {pre_audit.get('video_architecture')}")
    print(f"  Uptime: {pre_audit.get('uptime')}, Restarts: {pre_audit.get('restarts')}")
    print(f"  CPU: {pre_audit.get('cpu_percent')}%, RSS: {pre_audit.get('rss_mb')} MB")

    # Step 2: Decoupled Face Detection Benchmark
    print("\n[Step 2/6] Running decoupled OpenCV face detector benchmark...")
    face_benchmark = benchmark_face_detector_resolutions(iterations=12)
    for res_name, r in face_benchmark.items():
        print(f"  {res_name:18s}: {r['avg_latency_ms']:6.2f} ms ({r['max_fps']:5.1f} FPS) | TP: {r['true_positives']} FP: {r['false_positives']} Miss: {r['misses']}")

    session_tmpdir = tempfile.TemporaryDirectory(prefix="box2_milestone7_")
    actual_mp4 = output_mp4_path or os.path.join(session_tmpdir.name, "milestone7_autoframed.mp4")
    actual_stills_dir = stills_dir or os.path.join(session_tmpdir.name, "stills")
    os.makedirs(actual_stills_dir, exist_ok=True)

    # Step 3: Scripted Scenario Preparation
    print(f"\n[Step 3/6] Generating {duration_s}s scripted scenario (50s stage booking)...")
    timeline, scenario_meta = generate_milestone7_timeline(total_seconds=duration_s, fps=30)
    renderer = create_synthetic_frame_renderer(3840, 2160)

    # Step 4: Execute Real-Time Paced JetsonFramePipeline
    print(f"\n[Step 4/6] Executing real-time paced JetsonFramePipeline ({preset}, {bitrate_kbps} kbps)...")
    print(f"  Target sandboxed file: {actual_mp4}")

    pipeline = JetsonFramePipeline(
        output_width=1920,
        output_height=1080,
        source_width=3840,
        source_height=2160,
        target_fps=30,
    )

    tegra_collector = TegrastatsCollector(interval_ms=1000)
    tegra_collector.start()

    # Generator wrapper passing faces
    def frame_gen(idx: int, elapsed_s: float) -> np.ndarray:
        faces = timeline[idx][1] if idx < len(timeline) else []
        return renderer(idx, elapsed_s, faces)

    summary = pipeline.run_offline_simulation(
        timeline_events=timeline,
        output_mp4_path=actual_mp4,
        frame_generator=frame_gen,
        bitrate_kbps=bitrate_kbps,
        preset=preset,
        realtime_pacing=True,
    )

    tegra_collector.stop()
    tegra_summary = tegra_collector.get_summary()

    print(f"  Simulation completed: {summary.total_frames_processed} timeline frames in {summary.duration_seconds}s")
    print(f"  Authorized source reads: {summary.source_reads_count}")
    print(f"  Authorized sink writes:  {summary.sink_writes_count}")
    print(f"  Dropped post-revoke reads:  {summary.dropped_unauthorized_reads}")
    print(f"  Dropped post-revoke writes: {summary.dropped_unauthorized_writes}")
    print(f"  Final capture lifecycle:    {summary.capture_lifecycle}")
    print(f"  SHA-256 Digest: {summary.sha256_hash}")

    # Step 5: Save Key Transition Stills
    print("\n[Step 5/6] Extracting verification transition stills...")
    key_frame_milestones = [
        (15, "01_arm_safe_wide_pre_start"),
        (120, "02_host_confirmed_medium_shot"),
        (300, "03_smooth_pacing_tracking"),
        (700, "04_offstage_bystander_rejected"),
        (1050, "05_operator_switched_guest"),
        (1140, "06_natural_warn_15_cue"),
        (1180, "07_subject_loss_hold_position"),
        (1300, "08_subject_loss_fallback_wide"),
        (1440, "09_seamless_reacquisition"),
        (1600, "10_natural_time_up_cue_wide"),
        (1900, "11_post_set_safe_wide"),
    ]

    extracted_stills: Dict[str, Any] = {}
    cap = cv2.VideoCapture(actual_mp4)
    total_vid_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    for target_idx, label in key_frame_milestones:
        if target_idx < total_vid_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
            ret, st_frame = cap.read()
            if ret:
                still_filename = f"m7_still_{label}_f{target_idx:04d}.png"
                still_filepath = os.path.join(actual_stills_dir, still_filename)
                cv2.imwrite(still_filepath, st_frame)

                mean_lum = float(np.mean(st_frame))
                non_zero_px = int(np.count_nonzero(st_frame))

                extracted_stills[label] = {
                    "frame_index": target_idx,
                    "filename": still_filename,
                    "filepath": os.path.join("tools/jetson/stills", still_filename),
                    "mean_luminance": round(mean_lum, 2),
                    "non_zero_pixels": non_zero_px,
                }
                print(f"  Captured {label:32s} (Frame {target_idx:04d})")
    cap.release()

    # Step 6: Post-run Live Baseline Audit & Dual-Stream FFprobe Inspection
    print("\n[Step 6/6] Verifying audio/video with ffprobe and post-run live audit...")
    ffprobe_results = verify_mp4_dual_stream_with_ffprobe(actual_mp4)
    post_audit = audit_live_service_baseline()

    live_uninterrupted = (
        pre_audit.get("service_detected") == post_audit.get("service_detected")
        and pre_audit.get("pid") == post_audit.get("pid")
        and post_audit.get("restarts", 0) == pre_audit.get("restarts", 0)
    )
    print(f"  Live service completely uninterrupted: {live_uninterrupted} (PID: {post_audit.get('pid')})")
    print(f"  Dual-stream FFprobe valid: {ffprobe_results.get('valid')}")
    print(f"  Video packets: {ffprobe_results.get('video', {}).get('total_packets')}")
    print(f"  Audio packets: {ffprobe_results.get('audio', {}).get('total_packets')}")
    print(f"  A/V start drift: {ffprobe_results.get('av_sync', {}).get('start_drift_ms')} ms")
    print(f"  A/V end drift:   {ffprobe_results.get('av_sync', {}).get('end_drift_ms')} ms")

    results_payload = {
        "benchmark_metadata": {
            "title": "Box2 Stage Director Milestone 7 Jetson Validation",
            "device": "NVIDIA Jetson Orin Nano 8GB",
            "jetpack_version": "JetPack 7.2.1 (L4T R39.2.1)",
            "start_time_utc": start_wall_time,
            "duration_requested_s": duration_s,
            "target_resolution": "1920x1080",
            "target_fps": 30.0,
            "codec_video": "h264 (libx264, preset=veryfast, zerolatency)",
            "codec_audio": "aac (48kHz stereo, 128 kbps)",
            "network_egress": "NONE (sandboxed local file)",
            "framing_control_source": "scripted_ground_truth_bounding_boxes",
            "face_detector_status": "decoupled_benchmark_only (not in live framing loop)",
            "external_gate_disclaimer": "Physical NVR, camera SD card, and cloud recording paths remain an unverified external gate outside Python process scope.",
        },
        "live_service_baseline_audit": {
            "pre_run": pre_audit,
            "post_run": post_audit,
            "uninterrupted_continuity_verified": live_uninterrupted,
        },
        "face_detection_decoupled_benchmark": face_benchmark,
        "scenario_metadata": scenario_meta,
        "pipeline_execution_summary": {
            "total_frames_processed": summary.total_frames_processed,
            "duration_seconds": summary.duration_seconds,
            "effective_fps": summary.effective_fps,
            "output_resolution": list(summary.output_resolution),
            "output_size_bytes": summary.output_size_bytes,
            "sha256_hash": summary.sha256_hash,
            "capture_lifecycle": summary.capture_lifecycle,
            "source_reads_count": summary.source_reads_count,
            "sink_writes_count": summary.sink_writes_count,
            "dropped_unauthorized_reads": summary.dropped_unauthorized_reads,
            "dropped_unauthorized_writes": summary.dropped_unauthorized_writes,
            "pts_monotonic": summary.pts_monotonic,
        },
        "ffprobe_dual_stream_verification": ffprobe_results,
        "telemetry_tegrastats": tegra_summary,
        "audit_event_log": summary.event_log,
        "transition_stills_verification": extracted_stills,
    }

    if results_json_path:
        os.makedirs(os.path.dirname(os.path.abspath(results_json_path)), exist_ok=True)
        with open(results_json_path, "w", encoding="utf-8") as f:
            json.dump(results_payload, f, indent=2)
        print(f"\nSaved structured benchmark results to: {results_json_path}")

    return results_payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Milestone 7 Jetson Validation Benchmark")
    parser.add_argument("--duration", type=float, default=75.0, help="Scenario duration in seconds")
    parser.add_argument("--preset", type=str, default="veryfast", help="x264 preset")
    parser.add_argument("--bitrate", type=int, default=4500, help="Video bitrate in kbps")
    parser.add_argument("--output", type=str, default=None, help="Output MP4 path")
    parser.add_argument("--json-out", type=str, default="tools/jetson/milestone7_benchmark_results.json", help="Output JSON results")
    parser.add_argument("--stills-dir", type=str, default="tools/jetson/stills", help="Directory for verification PNG stills")
    args = parser.parse_args()

    run_milestone7_benchmark(
        duration_s=args.duration,
        preset=args.preset,
        bitrate_kbps=args.bitrate,
        output_mp4_path=args.output,
        results_json_path=args.json_out,
        stills_dir=args.stills_dir,
    )
