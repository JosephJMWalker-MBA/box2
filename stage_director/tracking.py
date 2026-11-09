"""Performer tracking engine with stage-only area, spatial gating, and subject-loss hold.

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
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class TrackingResult:
    """Outcome of a single tracking update frame."""
    state: TrackingState
    active_subject: Optional[BoundingBox]
    events: List[str]
    onstage_count: int
    offstage_count: int


class PerformerTracker:
    """Tracks a single primary stage performer while ignoring bystanders and preventing subject stealing.

    - Excludes faces outside the stage polygon.
    - Locks onto the confirmed performer; secondary people on stage are ignored.
    - Gated spatial matching: rejects implausible jumps (distance scaled to elapsed time)
      and area inconsistencies to prevent latching onto a bystander when performer vanishes.
    - Temporarily holds framing during brief occlusions / head turns.
    - Smoothly transitions to safe wide only after a subject-loss timeout.
    - Disallows automatic reacquisition after extended loss (>2s); physical proximity is NOT
      identity proof. Host confirmation is strictly required by default.
    - Requires unambiguous candidate or explicit host selection during initial acquisition.
    """

    def __init__(self, stage_polygon: Optional[StagePolygon] = None,
                 loss_hold_seconds: float = 2.0,
                 min_confidence: float = 0.50,
                 base_match_radius_px: float = 400.0,
                 max_performer_speed_px_s: float = 1500.0,
                 max_area_ratio: float = 3.0,
                 require_confirmation_after_loss: bool = True,
                 allow_proximity_reacquisition: bool = False) -> None:
        self.stage_polygon = stage_polygon or StagePolygon.default_stage()
        self.loss_hold_seconds = loss_hold_seconds
        self.min_confidence = min_confidence
        self.base_match_radius_px = base_match_radius_px
        self.max_performer_speed_px_s = max_performer_speed_px_s
        self.max_area_ratio = max_area_ratio
        self.require_confirmation_after_loss = require_confirmation_after_loss
        self.allow_proximity_reacquisition = allow_proximity_reacquisition

        self.state: TrackingState = TrackingState.DISABLED
        self.active_subject: Optional[BoundingBox] = None
        self._last_seen_monotonic: Optional[float] = None
        self._held_subject: Optional[BoundingBox] = None

    def enable(self) -> None:
        """Enable tracking (transitions from DISABLED/AMBIGUOUS to ACQUIRING)."""
        if self.state in (TrackingState.DISABLED, TrackingState.AMBIGUOUS):
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
                        monotonic_seconds: float = 0.0) -> bool:
        """Operator explicitly confirms or locks the performer.

        Returns True if performer was successfully confirmed or enabled.
        """
        if self.state == TrackingState.DISABLED:
            return False

        if box is not None:
            if not self.stage_polygon.contains_box(box):
                return False
            self.active_subject = box
            self._held_subject = box
            self._last_seen_monotonic = monotonic_seconds
            self.state = TrackingState.TRACKING
            return True

        # While in AMBIGUOUS or LOST, an explicit onstage bounding box is mandatory.
        # Passing box=None must be rejected to prevent clearing ambiguity without
        # identifying the performer.
        if self.state in (TrackingState.AMBIGUOUS, TrackingState.LOST):
            return False

        self.enable()
        return True

    def switch_subject(self, box: BoundingBox, monotonic_seconds: float) -> bool:
        """Operator explicitly switches the tracked subject to a new performer.

        Returns True if the box is inside the stage polygon and switch succeeded.
        """
        if self.state == TrackingState.DISABLED:
            return False
        if not self.stage_polygon.contains_box(box):
            return False
        self.active_subject = box
        self._held_subject = box
        self._last_seen_monotonic = monotonic_seconds
        self.state = TrackingState.TRACKING
        return True

    def _is_plausible_match(self, candidate: BoundingBox, anchor: BoundingBox,
                            dt: float) -> bool:
        """Gated spatial matching: check if candidate is a plausible continuation of anchor."""
        # 1. Distance gate scaled by elapsed time
        max_dist = self.base_match_radius_px + self.max_performer_speed_px_s * dt
        dist = candidate.distance_to(anchor)
        if dist > max_dist:
            return False

        # 2. Area consistency gate (prevent sudden 3x+ size jump in fraction of a second)
        ratio = max(candidate.area / anchor.area, anchor.area / candidate.area)
        if ratio > self.max_area_ratio:
            return False

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

        # 1. Filter out offstage bystanders and low-confidence detections
        onstage_boxes: List[BoundingBox] = []
        offstage_count = 0
        for box in detections:
            if box.confidence < self.min_confidence:
                continue
            if self.stage_polygon.contains_box(box):
                onstage_boxes.append(box)
            else:
                offstage_count += 1

        onstage_count = len(onstage_boxes)

        # 2. Case A: Active performer is currently tracked (or holding within loss_hold_seconds)
        if self.active_subject is not None or self.state == TrackingState.HOLDING:
            anchor = self._held_subject or self.active_subject
            assert anchor is not None
            dt = max(0.001, monotonic_seconds - (self._last_seen_monotonic or monotonic_seconds))

            # Filter onstage boxes to only plausible matches for this performer
            plausible_matches = [
                b for b in onstage_boxes
                if self._is_plausible_match(b, anchor, dt)
            ]

            if plausible_matches:
                # Match closest plausible box
                matched = min(plausible_matches, key=lambda b: b.distance_to(anchor))
                self.active_subject = matched
                self._held_subject = matched
                self._last_seen_monotonic = monotonic_seconds

                if self.state in (TrackingState.HOLDING, TrackingState.LOST, TrackingState.AMBIGUOUS):
                    events.append("camera_subject_reacquired")
                self.state = TrackingState.TRACKING

                return TrackingResult(
                    state=self.state,
                    active_subject=self.active_subject,
                    events=events,
                    onstage_count=onstage_count,
                    offstage_count=offstage_count,
                )

            # No plausible candidate matches active subject (performer vanished, occluded, or jumped)
            if self._last_seen_monotonic is not None:
                time_lost = monotonic_seconds - self._last_seen_monotonic
                if time_lost <= self.loss_hold_seconds:
                    self.state = TrackingState.HOLDING
                    # Keep held subject for framing reference, do NOT latch onto bystanders
                    return TrackingResult(
                        state=TrackingState.HOLDING,
                        active_subject=self._held_subject,
                        events=[],
                        onstage_count=onstage_count,
                        offstage_count=offstage_count,
                    )
                else:
                    if self.state == TrackingState.HOLDING:
                        events.append("camera_subject_lost")
                    self.state = TrackingState.LOST
                    self.active_subject = None
                    return TrackingResult(
                        state=TrackingState.LOST,
                        active_subject=None,
                        events=events,
                        onstage_count=onstage_count,
                        offstage_count=offstage_count,
                    )

        # 3. Case B: No active performer (state is ACQUIRING, LOST, or AMBIGUOUS)
        if onstage_boxes:
            # Subcase B1: Recovering after extended loss (>2s)
            if self.state in (TrackingState.LOST, TrackingState.AMBIGUOUS):
                if self.require_confirmation_after_loss:
                    # Optional proximity auto-reacquisition (off by default)
                    if self.allow_proximity_reacquisition and self._held_subject is not None:
                        reacquire_radius = self.base_match_radius_px * 1.5
                        matches = [
                            b for b in onstage_boxes
                            if b.distance_to(self._held_subject) <= reacquire_radius
                        ]
                        if len(matches) == 1 and len(onstage_boxes) == 1:
                            chosen = matches[0]
                            self.active_subject = chosen
                            self._held_subject = chosen
                            self._last_seen_monotonic = monotonic_seconds
                            self.state = TrackingState.TRACKING
                            events.append("camera_subject_reacquired")
                            return TrackingResult(
                                state=self.state,
                                active_subject=self.active_subject,
                                events=events,
                                onstage_count=onstage_count,
                                offstage_count=offstage_count,
                            )

                    # Default policy: Proximity is NOT proof of identity after extended loss.
                    # Must require explicit host confirmation rather than silently tracking someone.
                    self.state = TrackingState.AMBIGUOUS
                    events.append("performer_confirmation_required")
                    return TrackingResult(
                        state=TrackingState.AMBIGUOUS,
                        active_subject=None,
                        events=events,
                        onstage_count=onstage_count,
                        offstage_count=offstage_count,
                    )

            # Subcase B2: Initial acquisition (state is ACQUIRING)
            if len(onstage_boxes) > 1:
                # Ambiguous initial state: multiple people on stage at start!
                # Do NOT pick largest face; require host confirmation.
                self.state = TrackingState.AMBIGUOUS
                events.append("performer_confirmation_required")
                return TrackingResult(
                    state=TrackingState.AMBIGUOUS,
                    active_subject=None,
                    events=events,
                    onstage_count=onstage_count,
                    offstage_count=offstage_count,
                )

            # Exactly one unambiguous performer on stage
            chosen = onstage_boxes[0]
            self.active_subject = chosen
            self._held_subject = chosen
            self._last_seen_monotonic = monotonic_seconds
            self.state = TrackingState.TRACKING
            events.append("camera_subject_acquired")
            return TrackingResult(
                state=self.state,
                active_subject=self.active_subject,
                events=events,
                onstage_count=onstage_count,
                offstage_count=offstage_count,
            )

        # No onstage boxes detected
        if self.state not in (TrackingState.LOST, TrackingState.AMBIGUOUS):
            self.state = TrackingState.ACQUIRING

        return TrackingResult(
            state=self.state,
            active_subject=None,
            events=[],
            onstage_count=0,
            offstage_count=offstage_count,
        )
