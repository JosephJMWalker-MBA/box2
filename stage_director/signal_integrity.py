"""Stage Director Signal Integrity Layer (#I) & Audio Source Authority (P1).

Establishes four guarantees before performance interpretation, transcription, or broadcast:
1. Provenance: Explicit room-to-camera and room-to-microphone authority (fail-closed; never
   substitutes another room's microphone if the stage mic disconnects).
2. Quality: Laplacian focus sharpness, performer-face vs. jukebox luminance balance, and
   speech SNR / noise-floor tracking.
3. Synchronization: Audio-to-video PTS alignment and ASR pipeline latency bounds.
4. Continuity: Real-time dropout, stall, and interruption telemetry for downstream analysis.

Pure Python standard library + optional NumPy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    np = None  # type: ignore
    HAS_NUMPY = False

from .geometry import BoundingBox


@dataclass(frozen=True)
class AudioAuthorityPolicy:
    """Explicit room-bound audio provenance rules for Box 2 Stage (P1)."""
    room_id: str = "box2_stage"
    # Preferred dedicated USB/XLR/wireless stage receiver match substring in /proc/asound/cards
    preferred_usb_alsa_match: Optional[str] = "StageMic"
    # Pinned NVR hardware MAC + strict single channel index (CH 0 = Box 2 Stage RLC-823A)
    authorized_nvr_mac: str = "ec:71:db:bb:69:56"
    authorized_nvr_channel: int = 0
    expected_osd_name: str = "Camera1"
    # Explicitly forbidden NVR channels (Parking Lot, Lesson Rooms, Recording Booth, Reception Desk)
    forbidden_nvr_channels: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
    # Fail-closed timeout when zero valid stage audio frames arrive
    mic_stall_timeout_s: float = 2.5


@dataclass(frozen=True)
class ProvenanceVerdict:
    authorized: bool
    fail_closed: bool
    source_kind: str        # "usb_stage_mic" | "nvr_stage_ch0" | "unverified"
    source_id: str
    status_code: str        # "AUTHORIZED" | "STAGE_MIC_INTERRUPTED" | "WRONG_ROOM_REJECTED"
    reason: str


@dataclass(frozen=True)
class VisualQualityReport:
    focus_sharpness: float
    is_sharp: bool
    face_luma: float
    jukebox_luma: float
    exposure_balanced: bool
    underexposed_face: bool


@dataclass
class SignalIntegritySnapshot:
    timestamp_epoch: float
    room_id: str
    status_code: str                    # "HEALTHY" | "STAGE_MIC_INTERRUPTED" | "VIDEO_STALLED" | "DEGRADED_QUALITY"
    camera_verified: bool
    camera_source_id: str
    mic_verified: bool
    mic_fail_closed_active: bool
    mic_source_id: str
    pre_mix_speech_isolated: bool
    focus_sharpness: float
    is_sharp: bool
    face_luma: float
    jukebox_luma: float
    exposure_balanced: bool
    speech_rms_dbfs: float
    noise_floor_dbfs: float
    speech_snr_db: float
    av_drift_ms: float
    asr_lag_ms: float
    sync_ok: bool
    mic_interruption_count: int
    video_stall_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def discover_authorized_usb_mic(alsa_cards_text: str, match_substring: Optional[str]) -> Optional[Tuple[int, str]]:
    """Parse `/proc/asound/cards` text for a dedicated USB stage microphone receiver.

    Ignores built-in Jetson HDA / Tegra APE buses so motherboard headers are never mistaken
    for a stage microphone.
    """
    if not alsa_cards_text:
        return None
    needle = (match_substring or "").strip().lower()
    for line in alsa_cards_text.splitlines():
        s = line.strip()
        if not s or not s[0].isdigit():
            continue
        low = s.lower()
        if "tegra" in low or "ape" in low or "hda" in low:
            continue
        card_idx_str = s.split()[0]
        if not card_idx_str.isdigit():
            continue
        if ("usb" in low and not needle) or (needle and needle in low):
            return int(card_idx_str), s
    return None


def verify_audio_provenance(
    policy: AudioAuthorityPolicy,
    *,
    source_kind: str,
    source_id: str,
    nvr_mac: Optional[str] = None,
    nvr_channel: Optional[int] = None,
    osd_name: Optional[str] = None,
    last_audio_age_s: float = 0.0,
) -> ProvenanceVerdict:
    """Enforce P1 fail-closed audio source authority for Box 2 Stage."""
    # 1. Dedicated local USB stage receiver explicitly matched
    if source_kind == "usb_stage_mic":
        if last_audio_age_s > policy.mic_stall_timeout_s:
            return ProvenanceVerdict(
                authorized=False,
                fail_closed=True,
                source_kind=source_kind,
                source_id=source_id,
                status_code="STAGE_MIC_INTERRUPTED",
                reason=f"usb_stage_mic_stalled_{last_audio_age_s:.1f}s",
            )
        return ProvenanceVerdict(
            authorized=True,
            fail_closed=False,
            source_kind="usb_stage_mic",
            source_id=source_id,
            status_code="AUTHORIZED",
            reason="verified_usb_stage_receiver",
        )

    # 2. Pinned NVR stage channel (CH 0 ONLY on verified NVR MAC)
    if source_kind == "nvr_channel":
        mac_norm = (nvr_mac or "").strip().lower()
        expected_mac = policy.authorized_nvr_mac.strip().lower()
        if expected_mac and mac_norm != expected_mac:
            return ProvenanceVerdict(
                authorized=False,
                fail_closed=True,
                source_kind=source_kind,
                source_id=source_id,
                status_code="WRONG_ROOM_REJECTED",
                reason=f"nvr_mac_mismatch:{mac_norm or 'missing'}",
            )
        if nvr_channel is None or int(nvr_channel) != int(policy.authorized_nvr_channel) or int(nvr_channel) in policy.forbidden_nvr_channels:
            return ProvenanceVerdict(
                authorized=False,
                fail_closed=True,
                source_kind=source_kind,
                source_id=source_id,
                status_code="WRONG_ROOM_REJECTED",
                reason=f"forbidden_nvr_channel:{nvr_channel}",
            )
        if osd_name and policy.expected_osd_name and osd_name.strip().lower() != policy.expected_osd_name.strip().lower():
            # Reject if NVR channel wiring was swapped to another room (e.g. "reception 1" or "parking lot center")
            return ProvenanceVerdict(
                authorized=False,
                fail_closed=True,
                source_kind=source_kind,
                source_id=source_id,
                status_code="WRONG_ROOM_REJECTED",
                reason=f"osd_room_mismatch:{osd_name}",
            )
        if last_audio_age_s > policy.mic_stall_timeout_s:
            return ProvenanceVerdict(
                authorized=False,
                fail_closed=True,
                source_kind="nvr_stage_ch0",
                source_id=source_id,
                status_code="STAGE_MIC_INTERRUPTED",
                reason=f"nvr_ch0_audio_stalled_{last_audio_age_s:.1f}s",
            )
        return ProvenanceVerdict(
            authorized=True,
            fail_closed=False,
            source_kind="nvr_stage_ch0",
            source_id=source_id,
            status_code="AUTHORIZED",
            reason="verified_nvr_ch0_stage_mic",
        )

    # 3. Any other source (desktop PipeWire default, browser, unknown) -> strictly rejected
    return ProvenanceVerdict(
        authorized=False,
        fail_closed=True,
        source_kind=source_kind,
        source_id=source_id,
        status_code="WRONG_ROOM_REJECTED",
        reason=f"unauthorized_source_kind:{source_kind}",
    )


def measure_visual_quality(
    gray_frame: "np.ndarray",
    face_box: Optional[BoundingBox] = None,
    sharpness_threshold: float = 28.0,
) -> VisualQualityReport:
    """Compute Laplacian focus sharpness and performer-face vs. jukebox luminance on a 2D grayscale frame."""
    if not HAS_NUMPY or gray_frame is None or gray_frame.size == 0:
        return VisualQualityReport(0.0, False, 0.0, 0.0, True, False)

    h, w = gray_frame.shape[:2]
    # Evaluate sharpness inside stage performer zone (or active face+torso ROI) so dark walls don't dilute variance
    if face_box is not None:
        x1 = max(1, int(face_box.x - face_box.width * 0.5))
        y1 = max(1, int(face_box.y - face_box.height * 0.3))
        x2 = min(w - 1, int(face_box.right + face_box.width * 0.5))
        y2 = min(h - 1, int(face_box.bottom + face_box.height * 1.5))
    else:
        x1, y1 = max(1, int(w * 0.12)), max(1, int(h * 0.14))
        x2, y2 = min(w - 1, int(w * 0.68)), min(h - 1, int(h * 0.82))

    roi = gray_frame[y1:y2, x1:x2].astype(np.float32) if (x2 > x1 + 4 and y2 > y1 + 4) else gray_frame.astype(np.float32)
    # Discrete 3x3 4-neighbor Laplacian without requiring OpenCV in pure-NumPy environments
    if roi.shape[0] >= 3 and roi.shape[1] >= 3:
        center = roi[1:-1, 1:-1]
        lap = (-4.0 * center) + roi[:-2, 1:-1] + roi[2:, 1:-1] + roi[1:-1, :-2] + roi[1:-1, 2:]
        sharpness = float(np.var(lap))
    else:
        sharpness = 0.0

    if face_box is not None:
        fx1 = max(0, int(face_box.x))
        fy1 = max(0, int(face_box.y))
        fx2 = min(w, int(face_box.right))
        fy2 = min(h, int(face_box.bottom))
        face_patch = gray_frame[fy1:fy2, fx1:fx2]
        face_luma = float(np.mean(face_patch)) if face_patch.size > 0 else float(np.mean(roi))
    else:
        # Center-left stage performer zone
        stage_patch = gray_frame[int(h * 0.22):int(h * 0.68), int(w * 0.18):int(w * 0.58)]
        face_luma = float(np.mean(stage_patch)) if stage_patch.size > 0 else float(np.mean(roi))

    # Right-side jukebox zone (~x=0.72..0.88, y=0.45..0.90 on wide stage preset)
    jb_patch = gray_frame[int(h * 0.45):int(h * 0.90), int(w * 0.72):int(w * 0.88)]
    jukebox_luma = float(np.mean(jb_patch)) if jb_patch.size > 0 else 0.0

    underexposed_face = bool(face_luma < 44.0 and jukebox_luma > 165.0)
    exposure_balanced = not underexposed_face and (32.0 <= face_luma <= 215.0)

    return VisualQualityReport(
        focus_sharpness=round(sharpness, 2),
        is_sharp=bool(sharpness >= sharpness_threshold),
        face_luma=round(face_luma, 1),
        jukebox_luma=round(jukebox_luma, 1),
        exposure_balanced=exposure_balanced,
        underexposed_face=underexposed_face,
    )


class SignalIntegrityMonitor:
    """Continuous #I Signal Integrity validator and telemetry logger."""

    def __init__(
        self,
        policy: Optional[AudioAuthorityPolicy] = None,
        integrity_log_path: Optional[Path] = None,
        max_av_drift_ms: float = 120.0,
    ) -> None:
        self.policy = policy or AudioAuthorityPolicy()
        self.integrity_log_path = Path(integrity_log_path) if integrity_log_path else None
        self.max_av_drift_ms = float(max_av_drift_ms)

        self._noise_floor_dbfs: float = -58.0
        self._speech_rms_dbfs: float = -90.0
        self._mic_interruption_count: int = 0
        self._video_stall_count: int = 0
        self._was_mic_authorized: bool = True
        self._was_video_fresh: bool = True
        self._last_visual = VisualQualityReport(0.0, True, 90.0, 90.0, True, False)
        self._last_snapshot: Optional[SignalIntegritySnapshot] = None
        self._last_log_mono: float = 0.0

    def update_speech_rms(self, raw_pre_mix_dbfs: float, is_onstage: bool) -> None:
        val = float(raw_pre_mix_dbfs)
        self._speech_rms_dbfs = val
        # Track ambient stage noise floor slowly during quiet gaps
        if val < self._noise_floor_dbfs + 4.0:
            self._noise_floor_dbfs = 0.96 * self._noise_floor_dbfs + 0.04 * max(-80.0, val)
        elif not is_onstage and val < -38.0:
            self._noise_floor_dbfs = 0.99 * self._noise_floor_dbfs + 0.01 * val

    def evaluate(
        self,
        *,
        now_epoch: float,
        now_mono: float,
        camera_verified: bool,
        camera_source_id: str,
        video_fresh: bool,
        audio_verdict: ProvenanceVerdict,
        visual_report: Optional[VisualQualityReport] = None,
        av_drift_ms: float = 0.0,
        asr_lag_ms: float = 0.0,
        pre_mix_speech_isolated: bool = True,
    ) -> SignalIntegritySnapshot:
        if visual_report is not None:
            self._last_visual = visual_report

        if not audio_verdict.authorized and self._was_mic_authorized:
            self._mic_interruption_count += 1
        self._was_mic_authorized = audio_verdict.authorized

        if not video_fresh and self._was_video_fresh:
            self._video_stall_count += 1
        self._was_video_fresh = video_fresh

        sync_ok = abs(float(av_drift_ms)) <= self.max_av_drift_ms
        snr_db = max(0.0, self._speech_rms_dbfs - self._noise_floor_dbfs)

        if not audio_verdict.authorized:
            status_code = audio_verdict.status_code
        elif not camera_verified or not video_fresh:
            status_code = "VIDEO_STALLED"
        elif not self._last_visual.is_sharp or not sync_ok:
            status_code = "DEGRADED_QUALITY"
        else:
            status_code = "HEALTHY"

        snap = SignalIntegritySnapshot(
            timestamp_epoch=round(float(now_epoch), 3),
            room_id=self.policy.room_id,
            status_code=status_code,
            camera_verified=bool(camera_verified),
            camera_source_id=camera_source_id,
            mic_verified=bool(audio_verdict.authorized),
            mic_fail_closed_active=bool(audio_verdict.fail_closed),
            mic_source_id=audio_verdict.source_id,
            pre_mix_speech_isolated=bool(pre_mix_speech_isolated),
            focus_sharpness=self._last_visual.focus_sharpness,
            is_sharp=self._last_visual.is_sharp,
            face_luma=self._last_visual.face_luma,
            jukebox_luma=self._last_visual.jukebox_luma,
            exposure_balanced=self._last_visual.exposure_balanced,
            speech_rms_dbfs=round(self._speech_rms_dbfs, 1),
            noise_floor_dbfs=round(self._noise_floor_dbfs, 1),
            speech_snr_db=round(snr_db, 1),
            av_drift_ms=round(float(av_drift_ms), 1),
            asr_lag_ms=round(float(asr_lag_ms), 1),
            sync_ok=sync_ok,
            mic_interruption_count=self._mic_interruption_count,
            video_stall_count=self._video_stall_count,
        )
        self._last_snapshot = snap

        # Persist periodic telemetry (every 15s or immediately on fault transitions)
        if self.integrity_log_path is not None and (
            (now_mono - self._last_log_mono >= 15.0) or status_code != "HEALTHY"
        ):
            if now_mono - self._last_log_mono >= 2.0:
                self._last_log_mono = now_mono
                try:
                    self.integrity_log_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.integrity_log_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(snap.to_dict()) + "\n")
                except Exception:
                    pass

        return snap
