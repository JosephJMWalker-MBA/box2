"""Performer tracking engine with stage-only area and subject-loss hold.

Strictly spatial tracking only: NO biometric face recognition, embeddings,
enrollment, or identity profiles.
Standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence

from .geometry import BoundingBox, StagePolygon


class TrackingState(str, Enum):
    DISABLED = "disabled"
    ACQUIRING = "acquiring"
    TRACKING = "tracking"
    HOLDING = "holding"
    LOST = "lost"


@dataclass(frozen=True)
class TrackingResult:
    """Outcome of a single tracking update frame."""
    state: TrackingState
    active_subject: Optional[BoundingBox]
    events: List[str]
    onstage_count: int
    offstage_count: int


class PerformerTracker:
    """Tracks a single primary stage performer while ignoring bystanders.

    - Excludes faces outside the stage polygon.
    - Locks onto the confirmed performer; secondary people on stage are ignored.
    - Temporarily holds framing during brief occlusions / head turns.
    - Smoothly transitions to safe wide only after a subject-loss timeout.
    """

    def __init__(self, stage_polygon: Optional[StagePolygon] = None,
                 loss_hold_seconds: float = 2.0) -> None:
        self.stage_polygon = stage_polygon or StagePolygon.default_stage()
        self.loss_hold_seconds = loss_hold_seconds

        self.state: TrackingState = TrackingState.DISABLED
        self.active_subject: Optional[BoundingBox] = None
        self._last_seen_monotonic: Optional[float] = None
        self._held_subject: Optional[BoundingBox] = None

    def enable(self) -> None:
        """Enable tracking (transitions from DISABLED to ACQUIRING)."""
        if self.state == TrackingState.DISABLED:
            self.state = TrackingState.ACQUIRING
            self.active_subject = None
            self._held_subject = None
            self._last_seen_monotonic = None

    def disable(self) -> None:
        """Disable tracking immediately (fail-closed / stop)."""
        self.state = TrackingState.DISABLED
        self.active_subject = None
        self._held_subject = None
        self._last_seen_monotonic = None

    def confirm_subject(self, box: Optional[BoundingBox] = None,
                        monotonic_seconds: float = 0.0) -> None:
        """Operator explicitly confirms or locks the performer."""
        if box is not None and self.stage_polygon.contains_box(box):
            self.active_subject = box
            self._held_subject = box
            self._last_seen_monotonic = monotonic_seconds
            self.state = TrackingState.TRACKING
        else:
            self.enable()

    def switch_subject(self, box: BoundingBox, monotonic_seconds: float) -> bool:
        """Operator explicitly switches the tracked subject to a new performer.

        Returns True if the box is inside the stage polygon and switch succeeded.
        """
        if not self.stage_polygon.contains_box(box):
            return False
        self.active_subject = box
        self._held_subject = box
        self._last_seen_monotonic = monotonic_seconds
        self.state = TrackingState.TRACKING
        return True

    def update(self, detections: Sequence[BoundingBox],
               monotonic_seconds: float) -> TrackingResult:
        """Process candidate face detections for the current frame."""
        if self.state == TrackingState.DISABLED:
            return TrackingResult(
                state=TrackingState.DISABLED,
                active_subject=None,
                events=[],
                onstage_count=0,
                offstage_count=len(detections),
            )

        events: List[str] = []

        # 1. Filter out offstage bystanders using the stage polygon
        onstage_boxes: List[BoundingBox] = []
        offstage_count = 0
        for box in detections:
            if self.stage_polygon.contains_box(box):
                onstage_boxes.append(box)
            else:
                offstage_count += 1

        onstage_count = len(onstage_boxes)

        # 2. Case A: Onstage candidate(s) detected
        if onstage_boxes:
            if self.active_subject is None:
                # No active track: acquire best candidate (largest face on stage)
                chosen = max(onstage_boxes, key=lambda b: b.area)
                self.active_subject = chosen
                self._held_subject = chosen
                self._last_seen_monotonic = monotonic_seconds
                self.state = TrackingState.TRACKING
                events.append("camera_subject_acquired")
            else:
                # Match candidate closest to current active subject position
                anchor = self._held_subject or self.active_subject
                matched = min(onstage_boxes, key=lambda b: b.distance_to(anchor))
                self.active_subject = matched
                self._held_subject = matched
                self._last_seen_monotonic = monotonic_seconds

                if self.state in (TrackingState.HOLDING, TrackingState.LOST):
                    events.append("camera_subject_reacquired")
                self.state = TrackingState.TRACKING

            return TrackingResult(
                state=self.state,
                active_subject=self.active_subject,
                events=events,
                onstage_count=onstage_count,
                offstage_count=offstage_count,
            )

        # 3. Case B: NO onstage candidate detected (lost face / turned head / off stage)
        if self._last_seen_monotonic is not None:
            time_lost = monotonic_seconds - self._last_seen_monotonic
            if time_lost <= self.loss_hold_seconds:
                # Temporary loss: hold framing steady
                self.state = TrackingState.HOLDING
                # Subject remains held for framing reference
                return TrackingResult(
                    state=TrackingState.HOLDING,
                    active_subject=self._held_subject,
                    events=[],
                    onstage_count=0,
                    offstage_count=offstage_count,
                )
            else:
                # Timeout exceeded: transition to LOST
                if self.state == TrackingState.HOLDING:
                    events.append("camera_subject_lost")
                self.state = TrackingState.LOST
                self.active_subject = None
                return TrackingResult(
                    state=TrackingState.LOST,
                    active_subject=None,
                    events=events,
                    onstage_count=0,
                    offstage_count=offstage_count,
                )

        # Never seen anyone yet
        self.state = TrackingState.ACQUIRING
        return TrackingResult(
            state=TrackingState.ACQUIRING,
            active_subject=None,
            events=[],
            onstage_count=0,
            offstage_count=offstage_count,
        )
