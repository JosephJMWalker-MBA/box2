"""Camera framing, dead-zone, and temporal smoothing engine.

Transforms detected face bounding boxes into smooth, medium-shot OBS framing
windows (16:9 aspect ratio) with headroom and visible torso/hands.
Standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional

from .geometry import BoundingBox


@dataclass(frozen=True)
class FramingWindow:
    """A 16:9 framing / crop window within a native camera canvas."""
    center_x: float
    center_y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.center_x - self.width / 2.0

    @property
    def top(self) -> float:
        return self.center_y - self.height / 2.0

    @property
    def right(self) -> float:
        return self.center_x + self.width / 2.0

    @property
    def bottom(self) -> float:
        return self.center_y + self.height / 2.0

    def zoom_factor(self, canvas_width: float) -> float:
        """Effective digital zoom factor relative to full wide canvas."""
        if self.width <= 0:
            return 1.0
        return canvas_width / self.width

    def to_obs_crop(self, canvas_width: int, canvas_height: int) -> Dict[str, int]:
        """Convert to integer OBS scene item crop values (pixels from edge)."""
        left = max(0, int(round(self.left)))
        top = max(0, int(round(self.top)))
        right = max(0, int(round(canvas_width - self.right)))
        bottom = max(0, int(round(canvas_height - self.bottom)))

        # Guard against zero/negative visible dimensions due to boundary roundoff
        if left + right >= canvas_width:
            right = canvas_width - left - 1
        if top + bottom >= canvas_height:
            bottom = canvas_height - top - 1

        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
        }

    def to_dict(self, canvas_width: float) -> Dict[str, Any]:
        return {
            "center_x": round(self.center_x, 2),
            "center_y": round(self.center_y, 2),
            "width": int(round(self.width)),
            "height": int(round(self.height)),
            "zoom_factor": round(self.zoom_factor(canvas_width), 3),
        }


@dataclass(frozen=True)
class FramingConfig:
    """Tuning parameters for comedian camera framing and motion smoothing."""
    canvas_width: int = 3840
    canvas_height: int = 2160
    # Head-and-shoulders close-up: face height occupies ~33% of frame height (head, shoulders, mic)
    target_face_fraction: float = 0.33
    # Rule of thirds: face center positioned ~33% from top of crop
    headroom_fraction: float = 0.33
    min_zoom: float = 1.0
    max_zoom: float = 3.6
    # Dead-zone thresholds: small head swills/twitches won't cause camera jitter
    deadzone_x_px: float = 40.0
    deadzone_y_px: float = 30.0
    deadzone_zoom_px: float = 60.0
    # Time constant for exponential smoothing (seconds)
    smoothing_tau: float = 0.25
    # Maximum physical camera pan/tilt/zoom speeds (pixels per second on 4K)
    max_pan_speed_px_s: float = 1200.0
    max_tilt_speed_px_s: float = 800.0
    max_zoom_speed_px_s: float = 600.0
    # Maximum dt to apply in a single update step (clamps pauses / stalls)
    max_step_dt: float = 0.50
    # Periodic Room View ("Breathing Wide"): establishing wide view cadence
    periodic_room_view_enabled: bool = False
    room_view_interval_s: float = 45.0
    room_view_duration_s: float = 5.0
    # Pacing pull-back adaptation: widen framing during rapid walking/pacing
    pacing_pullback_speed_threshold_px_s: float = 300.0
    pacing_pullback_factor: float = 0.50
    # Optional temporal smoothing on detected face height (s) to suppress detector box-size zoom breathing
    face_size_smoothing_tau: float = 0.0


class FramingEngine:
    """Maintains a smoothed virtual camera crop window following a performer.

    Always starts from safe-wide and smoothly eases into position/zoom obeying
    strict velocity limits and smoothing filters from the very first frame.
    Supports head-and-shoulders close-ups and periodic establishing room views.
    """

    def __init__(self, config: Optional[FramingConfig] = None) -> None:
        self.config = config or FramingConfig()
        self._current_window: Optional[FramingWindow] = None
        self._last_monotonic: Optional[float] = None
        self._room_view_active: bool = False
        self._room_view_start_monotonic: Optional[float] = None
        self._last_room_view_end_monotonic: Optional[float] = None
        self._last_face_center_x: Optional[float] = None
        self._last_face_time: Optional[float] = None
        self._face_speed_x: float = 0.0
        self._smoothed_face_height: Optional[float] = None
        self._override_face_fraction: Optional[float] = None
        self._override_headroom_fraction: Optional[float] = None
        self._events: List[str] = []
        self.reset()

    def set_shot_framing(self, target_face_fraction: Optional[float] = None,
                         headroom_fraction: Optional[float] = None) -> None:
        """Dynamically adjust shot scale (Wide / Medium / Close-Up) smoothed through velocity limits."""
        self._override_face_fraction = target_face_fraction
        self._override_headroom_fraction = headroom_fraction

    def reset(self, monotonic_seconds: Optional[float] = None) -> None:
        """Reset camera framing to the default safe-wide shot with optional time anchor."""
        w = float(self.config.canvas_width)
        h = float(self.config.canvas_height)
        self._current_window = FramingWindow(
            center_x=w / 2.0,
            center_y=h / 2.0,
            width=w,
            height=h,
        )
        self._last_monotonic = monotonic_seconds
        self._room_view_active = False
        self._room_view_start_monotonic = None
        self._last_room_view_end_monotonic = monotonic_seconds
        self._last_face_center_x = None
        self._last_face_time = None
        self._face_speed_x = 0.0
        self._smoothed_face_height = None
        self._events.clear()

    @property
    def current_window(self) -> FramingWindow:
        if self._current_window is None:
            self.reset()
        assert self._current_window is not None
        return self._current_window

    def pop_events(self) -> List[str]:
        """Pop and return any camera events generated during recent updates."""
        ev = list(self._events)
        self._events.clear()
        return ev

    def compute_target_window(self, face: Optional[BoundingBox],
                              monotonic_seconds: Optional[float] = None) -> FramingWindow:
        """Calculate the desired framing window for a face, bounded by zoom and canvas."""
        canvas_w = float(self.config.canvas_width)
        canvas_h = float(self.config.canvas_height)

        if face is None:
            # Safe wide shot
            return FramingWindow(
                center_x=canvas_w / 2.0,
                center_y=canvas_h / 2.0,
                width=canvas_w,
                height=canvas_h,
            )

        # Check periodic room view establishing cadence
        if self.config.periodic_room_view_enabled and monotonic_seconds is not None:
            if self._last_room_view_end_monotonic is None:
                self._last_room_view_end_monotonic = monotonic_seconds

            if not self._room_view_active:
                if monotonic_seconds - self._last_room_view_end_monotonic >= self.config.room_view_interval_s:
                    self._room_view_active = True
                    self._room_view_start_monotonic = monotonic_seconds
                    self._events.append("periodic_room_view_started")

            if self._room_view_active:
                if monotonic_seconds - (self._room_view_start_monotonic or monotonic_seconds) >= self.config.room_view_duration_s:
                    self._room_view_active = False
                    self._room_view_start_monotonic = None
                    self._last_room_view_end_monotonic = monotonic_seconds
                    self._events.append("periodic_room_view_ended")
                else:
                    # Return safe wide shot during room view
                    return FramingWindow(
                        center_x=canvas_w / 2.0,
                        center_y=canvas_h / 2.0,
                        width=canvas_w,
                        height=canvas_h,
                    )

        # 1. Head-and-shoulders / close-up: calculate crop height based on face height and fraction
        eff_face_h = (
            self._smoothed_face_height
            if (self.config.face_size_smoothing_tau > 0.0 and self._smoothed_face_height is not None)
            else face.height
        )
        face_frac = self._override_face_fraction if self._override_face_fraction is not None else self.config.target_face_fraction
        headroom_frac = self._override_headroom_fraction if self._override_headroom_fraction is not None else self.config.headroom_fraction
        desired_h = eff_face_h / max(0.05, face_frac)
        desired_w = desired_h * (16.0 / 9.0)

        # 2. Pacing pullback adaptation: if performer is walking briskly, widen framing slightly
        if (self.config.pacing_pullback_speed_threshold_px_s > 0
                and self._face_speed_x > self.config.pacing_pullback_speed_threshold_px_s):
            excess = min(1.0, (self._face_speed_x - self.config.pacing_pullback_speed_threshold_px_s) / 600.0)
            desired_w *= (1.0 + self.config.pacing_pullback_factor * excess)
            desired_h = desired_w * (9.0 / 16.0)

        # 3. Bound zoom between min_zoom (1.0x wide) and max_zoom (e.g. 3.6x)
        min_w = canvas_w / self.config.max_zoom
        max_w = canvas_w / self.config.min_zoom
        target_w = max(min_w, min(max_w, desired_w))
        target_h = target_w * (9.0 / 16.0)

        # 4. Headroom positioning: face center at headroom_fraction from top of crop
        target_center_y = face.center_y + (0.5 - headroom_frac) * target_h
        target_center_x = face.center_x

        # 5. Canvas boundary clamping: window must never extend outside canvas
        half_w = target_w / 2.0
        half_h = target_h / 2.0
        target_center_x = max(half_w, min(canvas_w - half_w, target_center_x))
        target_center_y = max(half_h, min(canvas_h - half_h, target_center_y))

        return FramingWindow(
            center_x=target_center_x,
            center_y=target_center_y,
            width=target_w,
            height=target_h,
        )

    def update(self, face: Optional[BoundingBox], monotonic_seconds: float) -> FramingWindow:
        """Update and smooth camera framing towards the target window.

        Applies velocity limits and exponential smoothing from the very first frame,
        transitioning smoothly from safe-wide rather than instantly jumping to target.
        """
        # Estimate performer horizontal speed & smoothed face height for anti-breathing zoom stability
        if face is not None:
            dt_face = (
                max(0.001, monotonic_seconds - self._last_face_time)
                if self._last_face_time is not None
                else 0.1
            )
            if self._last_face_center_x is not None and self._last_face_time is not None:
                inst_speed = abs(face.center_x - self._last_face_center_x) / dt_face
                self._face_speed_x = 0.7 * self._face_speed_x + 0.3 * inst_speed
            if self.config.face_size_smoothing_tau > 0.0:
                if self._smoothed_face_height is None:
                    self._smoothed_face_height = face.height
                else:
                    a_sz = 1.0 - math.exp(-min(0.5, dt_face) / self.config.face_size_smoothing_tau)
                    self._smoothed_face_height += a_sz * (face.height - self._smoothed_face_height)
            self._last_face_center_x = face.center_x
            self._last_face_time = monotonic_seconds
        else:
            self._last_face_center_x = None
            self._last_face_time = None
            self._face_speed_x = 0.0
            self._smoothed_face_height = None
            self._room_view_active = False
            self._room_view_start_monotonic = None
            self._last_room_view_end_monotonic = None

        target = self.compute_target_window(face, monotonic_seconds=monotonic_seconds)
        curr = self.current_window

        if self._last_monotonic is None:
            # Time anchor uninitialized: anchor at monotonic_seconds and return safe-wide
            self._last_monotonic = monotonic_seconds
            return curr

        # Compute dt and clamp maximum step to avoid jumps on long stalls
        raw_dt = monotonic_seconds - self._last_monotonic
        dt = max(0.001, min(self.config.max_step_dt, raw_dt))
        self._last_monotonic = monotonic_seconds

        # 1. Dead-zone & Zoom hysteresis tests
        eff_target_x = target.center_x
        if abs(eff_target_x - curr.center_x) <= self.config.deadzone_x_px:
            eff_target_x = curr.center_x

        eff_target_y = target.center_y
        if abs(eff_target_y - curr.center_y) <= self.config.deadzone_y_px:
            eff_target_y = curr.center_y

        eff_target_w = target.width
        if abs(eff_target_w - curr.width) <= self.config.deadzone_zoom_px:
            eff_target_w = curr.width

        # 2. Exponential smoothing + Velocity limiting
        alpha = 1.0 - math.exp(-dt / self.config.smoothing_tau)

        raw_step_x = alpha * (eff_target_x - curr.center_x)
        max_dx = self.config.max_pan_speed_px_s * dt
        step_x = max(-max_dx, min(max_dx, raw_step_x))
        new_x = curr.center_x + step_x

        raw_step_y = alpha * (eff_target_y - curr.center_y)
        max_dy = self.config.max_tilt_speed_px_s * dt
        step_y = max(-max_dy, min(max_dy, raw_step_y))
        new_y = curr.center_y + step_y

        raw_step_w = alpha * (eff_target_w - curr.width)
        max_dw = self.config.max_zoom_speed_px_s * dt
        step_w = max(-max_dw, min(max_dw, raw_step_w))
        new_w = curr.width + step_w
        new_h = new_w * (9.0 / 16.0)

        # 3. Final safety boundary clamp
        canvas_w = float(self.config.canvas_width)
        canvas_h = float(self.config.canvas_height)
        half_w = new_w / 2.0
        half_h = new_h / 2.0
        new_x = max(half_w, min(canvas_w - half_w, new_x))
        new_y = max(half_h, min(canvas_h - half_h, new_y))

        self._current_window = FramingWindow(
            center_x=new_x,
            center_y=new_y,
            width=new_w,
            height=new_h,
        )
        return self._current_window
