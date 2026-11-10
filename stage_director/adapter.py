"""Consented-video-only Stage Framing Adapter.

An isolated adapter integrating StageDirector authorization with performer
tracking and smooth OBS crop proposal generation.
Standard library only. Does NOT connect to cameras, OBS, or network services.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .core import BookingSnapshot, CameraAction, Decision, Mode, StageDirector
from .framing import FramingConfig, FramingEngine, FramingWindow
from .geometry import BoundingBox, StagePolygon
from .obs_transform import OBSProposal
from .tracking import PerformerTracker, TrackingState


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StageFramingAdapter:
    """Combines stage timer authorization with virtual camera framing proposals."""

    def __init__(self,
                 director: Optional[StageDirector] = None,
                 tracker: Optional[PerformerTracker] = None,
                 framing_engine: Optional[FramingEngine] = None,
                 config: Optional[FramingConfig] = None) -> None:
        self.config = config or FramingConfig()
        self.director = director or StageDirector()
        self.tracker = tracker or PerformerTracker(
            stage_polygon=StagePolygon.default_stage(
                self.config.canvas_width, self.config.canvas_height
            ),
            loss_hold_seconds=2.0,
        )
        self.framing = framing_engine or FramingEngine(self.config)
        self._was_active = False

    def arm(self, booking: BookingSnapshot, now_utc: datetime) -> OBSProposal:
        """Arm a consented set; defaults camera to safe wide shot."""
        decision = self.director.arm(booking, now_utc)
        self.tracker.disable()
        self.framing.reset(monotonic_seconds=0.0)
        self._was_active = False
        return self._make_proposal(
            decision=decision,
            tracking_state=TrackingState.DISABLED,
            subject_lost=False,
            events=[],
            now_utc=now_utc,
            monotonic_seconds=0.0,
        )

    def start_set(self, now_utc: datetime, monotonic_seconds: float,
                  *, host_confirmed: bool = False) -> OBSProposal:
        """Host explicitly confirms and starts the set."""
        decision = self.director.start_set(
            now_utc, monotonic_seconds, host_confirmed=host_confirmed
        )
        if decision.mode == Mode.LIVE:
            self.tracker.enable()
            self.framing.reset(monotonic_seconds=monotonic_seconds)
            self._was_active = True
            return self._make_proposal(
                decision=decision,
                tracking_state=TrackingState.ACQUIRING,
                subject_lost=False,
                events=["performance_started"],
                now_utc=now_utc,
                monotonic_seconds=monotonic_seconds,
            )
        return self._make_proposal(
            decision=decision,
            tracking_state=TrackingState.DISABLED,
            subject_lost=False,
            events=[],
            now_utc=now_utc,
            monotonic_seconds=monotonic_seconds,
        )

    def stop(self, reason: str = "operator_stop",
             now_utc: Optional[datetime] = None,
             monotonic_seconds: float = 0.0) -> OBSProposal:
        """Stop performance immediately; fails closed to capture_off."""
        decision = self.director.stop(reason)
        self.tracker.disable()
        self.framing.reset(monotonic_seconds=monotonic_seconds)
        events = ["camera_auto_disabled"] if self._was_active else []
        self._was_active = False
        now = now_utc or datetime.now(timezone.utc)
        return self._make_proposal(
            decision=decision,
            tracking_state=TrackingState.DISABLED,
            subject_lost=False,
            events=events,
            now_utc=now,
            monotonic_seconds=monotonic_seconds,
        )

    def refresh(self, booking: BookingSnapshot, now_utc: datetime,
                monotonic_seconds: float = 0.0) -> OBSProposal:
        """Refresh booking snapshot; revoking consent immediately drops capture."""
        decision = self.director.refresh(booking, now_utc)
        if decision.camera_action == CameraAction.CAPTURE_OFF:
            self.tracker.disable()
            self.framing.reset(monotonic_seconds=monotonic_seconds)
            events = ["camera_auto_disabled"] if self._was_active else []
            self._was_active = False
            return self._make_proposal(
                decision=decision,
                tracking_state=TrackingState.DISABLED,
                subject_lost=False,
                events=events,
                now_utc=now_utc,
                monotonic_seconds=monotonic_seconds,
            )
        return self._make_proposal(
            decision=decision,
            tracking_state=self.tracker.state,
            subject_lost=(self.tracker.state == TrackingState.LOST),
            events=[],
            now_utc=now_utc,
            monotonic_seconds=monotonic_seconds,
        )

    def confirm_subject(self, box: Optional[BoundingBox] = None,
                        monotonic_seconds: float = 0.0) -> bool:
        """Explicitly lock or confirm the stage performer.

        Only permitted when an authorized LIVE set is active; fails closed otherwise.
        """
        if self.director.mode != Mode.LIVE:
            return False
        return self.tracker.confirm_subject(box, monotonic_seconds)

    def switch_subject(self, box: BoundingBox, monotonic_seconds: float) -> bool:
        """Explicitly switch tracking to another onstage performer.

        Only permitted when an authorized LIVE set is active; fails closed otherwise.
        """
        if self.director.mode != Mode.LIVE:
            return False
        return self.tracker.switch_subject(box, monotonic_seconds)

    def process_frame(self, detections: Sequence[BoundingBox],
                      now_utc: datetime, monotonic_seconds: float) -> OBSProposal:
        """Process one video frame of synthetic face detections."""
        decision = self.director.tick(now_utc, monotonic_seconds)

        # 1. Privacy / Fail-closed: capture off
        if decision.camera_action == CameraAction.CAPTURE_OFF:
            self.tracker.disable()
            self.framing.reset()
            events = ["camera_auto_disabled"] if self._was_active else []
            self._was_active = False
            return self._make_proposal(
                decision=decision,
                tracking_state=TrackingState.DISABLED,
                subject_lost=False,
                events=events,
                now_utc=now_utc,
                monotonic_seconds=monotonic_seconds,
            )

        # 2. Finished or safe wide
        if decision.camera_action == CameraAction.STAGE_WIDE:
            self.tracker.disable()
            self.framing.reset()
            self._was_active = False
            return self._make_proposal(
                decision=decision,
                tracking_state=TrackingState.DISABLED,
                subject_lost=False,
                events=[],
                now_utc=now_utc,
                monotonic_seconds=monotonic_seconds,
            )

        # 3. Active tracking mode (LIVE + TRACK_FACE)
        self._was_active = True
        track_res = self.tracker.update(detections, monotonic_seconds)

        # Update framing window
        if track_res.state in (TrackingState.TRACKING, TrackingState.HOLDING):
            window = self.framing.update(track_res.active_subject, monotonic_seconds)
            subject_lost = False
        else:
            # Face is lost, ambiguous, or acquiring: smoothly transition towards safe wide
            window = self.framing.update(None, monotonic_seconds)
            subject_lost = (track_res.state == TrackingState.LOST)

        return self._make_proposal(
            decision=decision,
            tracking_state=track_res.state,
            subject_lost=subject_lost,
            events=track_res.events,
            now_utc=now_utc,
            monotonic_seconds=monotonic_seconds,
            window=window,
        )

    def _make_proposal(self, decision: Decision, tracking_state: TrackingState,
                       subject_lost: bool, events: List[str],
                       now_utc: datetime, monotonic_seconds: float,
                       window: Optional[FramingWindow] = None) -> OBSProposal:
        w = self.config.canvas_width
        h = self.config.canvas_height

        if decision.camera_action == CameraAction.CAPTURE_OFF:
            obs_crop = None
            framing_dict = None
        elif decision.camera_action == CameraAction.STAGE_WIDE:
            obs_crop = {"left": 0, "top": 0, "right": 0, "bottom": 0}
            framing_dict = {
                "center_x": round(w / 2.0, 2),
                "center_y": round(h / 2.0, 2),
                "width": w,
                "height": h,
                "zoom_factor": 1.0,
            }
        else:
            # TRACK_FACE
            active_win = window or self.framing.current_window
            obs_crop = active_win.to_obs_crop(w, h)
            framing_dict = active_win.to_dict(w)

        return OBSProposal(
            schema_version="1.0",
            timestamp_utc=_utc_iso(now_utc),
            monotonic_seconds=round(monotonic_seconds, 3),
            mode=decision.mode.value,
            camera_action=decision.camera_action.value,
            tracking_state=tracking_state.value,
            subject_lost=subject_lost,
            source_resolution={"width": w, "height": h},
            obs_crop=obs_crop,
            framing=framing_dict,
            events=events,
            cue=decision.cue.value if decision.cue else None,
            remaining_seconds=decision.remaining_seconds,
            reason=decision.reason,
        )
