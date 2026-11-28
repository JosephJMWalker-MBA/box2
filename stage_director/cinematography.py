"""Autonomous Stand-Up Cinematography Director (P2) & Slew Concealment (#C).

Graduates Stage Director from purely digital cropping to hardware-aware stand-up cinematography:
- Autonomous 3-shot vocabulary (`ESTABLISHING_WIDE`, `MEDIUM`, `CLOSE_UP`) driven by non-metronomic
  performance signals (entrance/exit, stationary delivery vs. physical pacing, and comedic speech pauses).
- Hybrid optical + digital coordination: calibrated optical presets / `ZoomFocus` steps absorb large
  shot transitions while 4K->1080p digital framing handles immediate micro-stabilization inside generous
  stage dead-zones without constant motor chatter.
- `#C` Single-camera optical slew & autofocus concealment: bridges optical zoom travel with coordinated
  digital counter-scaling and Laplacian sharpness gating so focus hunting is never broadcast raw.
- Stage-optimized ISP policy: prevents the bright Box 2 jukebox from crushing performer facial exposure,
  and enforces exclusive PTZ ownership (`aiTrack = 0`, `PtzPatrol = 0`).

Pure Python standard library + optional NumPy.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Dict, Optional

from .framing import FramingWindow
from .geometry import BoundingBox


class ShotType(str, Enum):
    ESTABLISHING_WIDE = "wide"      # 01: Stage entrance (5-10s) & tracking recovery / exit
    MEDIUM = "medium"               # 02: Default performance framing (15-40s+), preserves hands/gestures
    CLOSE_UP = "close_up"           # 03: Stationary expressive delivery & punchlines (5-15s)


@dataclass(frozen=True)
class ShotVocabularyConfig:
    """Parameters governing non-metronomic autonomous shot selection and optical anchors."""
    # Entrance establishing wide hold (5-10s spec)
    entrance_wide_seconds: float = 6.5
    # Minimum Medium dwell before considering an expressive Close-Up (15-40s spec)
    min_medium_dwell_seconds: float = 18.0
    # Close-up duration window (5-15s spec: waits for natural comedic pause between min and max!)
    min_closeup_seconds: float = 6.0
    target_closeup_pause_exit_seconds: float = 9.5
    max_closeup_seconds: float = 14.5
    closeup_cooldown_seconds: float = 20.0
    # Stationary vs. physical movement thresholds (normalized to 3840x2160 canvas; scaled automatically)
    stationary_speed_px_s_4k: float = 110.0
    stationary_confirm_seconds: float = 4.5
    movement_pullback_speed_px_s_4k: float = 280.0
    # Target face height fraction of output frame for each shot in hybrid framing
    wide_face_fraction: float = 0.09
    medium_face_fraction: float = 0.23
    closeup_face_fraction: float = 0.32
    headroom_medium: float = 0.55
    headroom_closeup: float = 0.50
    # Reolink RLC-823A optical zoom positions (range 0..34; Preset 16 Stage Resting is pos=5)
    optical_zoom_wide_pos: int = 5
    optical_zoom_medium_pos: int = 10
    optical_zoom_closeup_pos: int = 14
    enable_live_optical_shot_moves: bool = True


@dataclass(frozen=True)
class ShotDirective:
    shot: ShotType
    reason: str
    shot_dwell_s: float
    target_face_fraction: float
    target_headroom_fraction: float
    desired_optical_zoom_pos: int
    request_optical_move: bool


class ShotDirector:
    """Non-metronomic stand-up comedy shot director."""

    def __init__(self, config: Optional[ShotVocabularyConfig] = None, canvas_width: int = 3840) -> None:
        self.config = config or ShotVocabularyConfig()
        self.canvas_width = max(320, int(canvas_width))
        self._scale = self.canvas_width / 3840.0

        self.current_shot: ShotType = ShotType.ESTABLISHING_WIDE
        self._shot_started_mono: float = 0.0
        self._last_closeup_end_mono: float = -1e9
        self._stationary_since_mono: Optional[float] = None
        self._was_performer_present: bool = False
        self._smoothed_speed_px_s: float = 0.0
        self._last_face_x: Optional[float] = None
        self._last_mono: Optional[float] = None
        self._committed_optical_pos: int = self.config.optical_zoom_wide_pos

    def reset(self, monotonic_seconds: float = 0.0) -> None:
        self.current_shot = ShotType.ESTABLISHING_WIDE
        self._shot_started_mono = monotonic_seconds
        self._stationary_since_mono = None
        self._was_performer_present = False
        self._smoothed_speed_px_s = 0.0
        self._last_face_x = None
        self._last_mono = monotonic_seconds
        self._committed_optical_pos = self.config.optical_zoom_wide_pos

    def _transition(self, new_shot: ShotType, now_mono: float, reason: str) -> str:
        if self.current_shot == ShotType.CLOSE_UP and new_shot != ShotType.CLOSE_UP:
            self._last_closeup_end_mono = now_mono
        self.current_shot = new_shot
        self._shot_started_mono = now_mono
        return reason

    def step(
        self,
        *,
        monotonic_seconds: float,
        tracking_state: str,
        face_box: Optional[BoundingBox],
        is_speaking: bool = False,
        recent_speech_age_s: float = 99.0,
        utterance_just_committed: bool = False,
    ) -> ShotDirective:
        now_m = float(monotonic_seconds)
        dt = max(0.001, now_m - self._last_mono) if self._last_mono is not None else 0.1
        self._last_mono = now_m

        performer_present = tracking_state in ("tracking", "holding") and face_box is not None
        if face_box is not None and self._last_face_x is not None:
            inst_v = abs(face_box.center_x - self._last_face_x) / dt
            self._smoothed_speed_px_s = 0.75 * self._smoothed_speed_px_s + 0.25 * inst_v
        elif not performer_present:
            self._smoothed_speed_px_s = 0.0
        self._last_face_x = face_box.center_x if face_box is not None else None

        stat_thresh = self.config.stationary_speed_px_s_4k * self._scale
        move_thresh = self.config.movement_pullback_speed_px_s_4k * self._scale

        if performer_present and self._smoothed_speed_px_s <= stat_thresh:
            if self._stationary_since_mono is None:
                self._stationary_since_mono = now_m
            stationary_dur = now_m - self._stationary_since_mono
        else:
            self._stationary_since_mono = None
            stationary_dur = 0.0

        reason = "steady"

        # 1. Stage entrance or tracking recovery -> 01 Establishing Wide
        if not performer_present or tracking_state in ("acquiring", "lost", "disabled"):
            if self.current_shot != ShotType.ESTABLISHING_WIDE:
                reason = self._transition(ShotType.ESTABLISHING_WIDE, now_m, "tracking_recovery_wide")
            else:
                self._shot_started_mono = now_m
            self._was_performer_present = False
        else:
            if not self._was_performer_present:
                self._was_performer_present = True
                reason = self._transition(ShotType.ESTABLISHING_WIDE, now_m, "stage_entrance_establishing")

            dwell = now_m - self._shot_started_mono

            if self.current_shot == ShotType.ESTABLISHING_WIDE:
                if dwell >= self.config.entrance_wide_seconds:
                    reason = self._transition(ShotType.MEDIUM, now_m, "entrance_complete_to_medium")

            elif self.current_shot == ShotType.MEDIUM:
                active_delivery = is_speaking or (recent_speech_age_s <= 2.2)
                cooldown_ok = (now_m - self._last_closeup_end_mono) >= self.config.closeup_cooldown_seconds
                if (
                    dwell >= self.config.min_medium_dwell_seconds
                    and cooldown_ok
                    and stationary_dur >= self.config.stationary_confirm_seconds
                    and active_delivery
                ):
                    reason = self._transition(ShotType.CLOSE_UP, now_m, "stationary_expressive_delivery")

            elif self.current_shot == ShotType.CLOSE_UP:
                # Immediate pullback if comedian starts pacing or gesturing broadly
                if self._smoothed_speed_px_s >= move_thresh and dwell >= 2.0:
                    reason = self._transition(ShotType.MEDIUM, now_m, "physical_movement_pullback")
                # Natural beat exit: wait for a comedic pause / sentence boundary once past target_closeup_pause_exit_seconds
                elif dwell >= self.config.target_closeup_pause_exit_seconds and (utterance_just_committed or not is_speaking):
                    reason = self._transition(ShotType.MEDIUM, now_m, "natural_beat_return_to_medium")
                elif dwell >= self.config.max_closeup_seconds:
                    reason = self._transition(ShotType.MEDIUM, now_m, "max_closeup_window_return")

        dwell_now = max(0.0, now_m - self._shot_started_mono)
        if self.current_shot == ShotType.ESTABLISHING_WIDE:
            face_frac = self.config.wide_face_fraction
            headroom = self.config.headroom_medium
            opt_pos = self.config.optical_zoom_wide_pos
        elif self.current_shot == ShotType.MEDIUM:
            face_frac = self.config.medium_face_fraction
            headroom = self.config.headroom_medium
            opt_pos = self.config.optical_zoom_medium_pos if self.config.enable_live_optical_shot_moves else self.config.optical_zoom_wide_pos
        else:
            face_frac = self.config.closeup_face_fraction
            headroom = self.config.headroom_closeup
            opt_pos = self.config.optical_zoom_closeup_pos if self.config.enable_live_optical_shot_moves else self.config.optical_zoom_wide_pos

        request_opt = bool(self.config.enable_live_optical_shot_moves and opt_pos != self._committed_optical_pos)
        if request_opt:
            self._committed_optical_pos = opt_pos

        return ShotDirective(
            shot=self.current_shot,
            reason=reason,
            shot_dwell_s=round(dwell_now, 2),
            target_face_fraction=face_frac,
            target_headroom_fraction=headroom,
            desired_optical_zoom_pos=opt_pos,
            request_optical_move=request_opt,
        )


class OpticalSlewConcealer:
    """#C Single-camera optical zoom & autofocus transition concealer.

    When `StartZoomFocus` or `ToPos` moves the physical RLC-823A lens (~1.2-2.2s motor + AF settle),
    holds/blends a crisp pre-slew digital bridge frame whenever Laplacian sharpness dips during AF
    hunting, then cross-dissolves (`0.35s`) seamlessly onto the settled optical image.
    """

    def __init__(
        self,
        min_slew_hold_s: float = 1.1,
        max_slew_conceal_s: float = 2.6,
        dissolve_out_s: float = 0.35,
        sharpness_floor: float = 24.0,
    ) -> None:
        self.min_slew_hold_s = float(min_slew_hold_s)
        self.max_slew_conceal_s = float(max_slew_conceal_s)
        self.dissolve_out_s = float(dissolve_out_s)
        self.sharpness_floor = float(sharpness_floor)

        self._slew_start_mono: Optional[float] = None
        self._settle_start_mono: Optional[float] = None
        self._bridge_canvas = None

    @property
    def is_active(self) -> bool:
        return self._slew_start_mono is not None or self._settle_start_mono is not None

    def notify_optical_move_started(self, current_rendered_canvas, now_mono: float) -> None:
        if current_rendered_canvas is not None:
            self._bridge_canvas = current_rendered_canvas.copy()
        self._slew_start_mono = float(now_mono)
        self._settle_start_mono = None

    def blend_if_concealing(self, live_rendered_canvas, focus_sharpness: float, now_mono: float):
        """Return concealed frame while lens/AF settles, or `live_rendered_canvas` when settled."""
        if self._bridge_canvas is None or live_rendered_canvas is None:
            self._slew_start_mono = None
            self._settle_start_mono = None
            return live_rendered_canvas

        if self._bridge_canvas.shape != live_rendered_canvas.shape:
            self._bridge_canvas = None
            self._slew_start_mono = None
            self._settle_start_mono = None
            return live_rendered_canvas

        if self._slew_start_mono is not None:
            elapsed = now_mono - self._slew_start_mono
            af_settled = (elapsed >= self.min_slew_hold_s) and (focus_sharpness >= self.sharpness_floor)
            timed_out = elapsed >= self.max_slew_conceal_s
            if af_settled or timed_out:
                self._slew_start_mono = None
                self._settle_start_mono = now_mono
            else:
                return self._bridge_canvas.copy()

        if self._settle_start_mono is not None:
            d_elapsed = now_mono - self._settle_start_mono
            if d_elapsed >= self.dissolve_out_s:
                self._settle_start_mono = None
                self._bridge_canvas = None
                return live_rendered_canvas
            w_live = 0.5 * (1.0 - math.cos(math.pi * (d_elapsed / self.dissolve_out_s)))
            blended = (
                self._bridge_canvas.astype("float32") * (1.0 - w_live)
                + live_rendered_canvas.astype("float32") * w_live
            ).astype("uint8")
            return blended

        return live_rendered_canvas


def build_stage_isp_payload(
    channel: int = 0,
    face_luma: float = 70.0,
    jukebox_luma: float = 190.0,
) -> Dict[str, Any]:
    """Build Reolink `SetIsp` parameter payload optimized for performer skin tones over jukebox glare."""
    # Boost DynamicRangeControl shadow lift when jukebox highlight pulls auto-exposure down
    drc_level = 185 if (face_luma < 52.0 and jukebox_luma > 160.0) else 152
    return {
        "Isp": {
            "channel": int(channel),
            "antiFlicker": "60HZ",
            "backLight": "DynamicRangeControl",
            "drc": int(drc_level),
            "exposure": "LowNoise",
            "shutter": {"min": 8, "max": 40},
            "gain": {"min": 1, "max": 58},
            "dayNight": "Color",
            "nr3d": 1,
            "whiteBalance": "Auto",
        }
    }
