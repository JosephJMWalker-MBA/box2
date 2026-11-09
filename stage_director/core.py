"""Offline-first Box2 Stage Director decision logic.

This module cannot access a camera, OBS, a speaker, a website, or the network.
It only emits recommendations for a future, separately authorized adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from math import ceil
from typing import Optional


class Mode(str, Enum):
    OFF = "off"
    ARMED = "armed"
    LIVE = "live"
    FINISHED = "finished"


class CameraAction(str, Enum):
    CAPTURE_OFF = "capture_off"
    STAGE_WIDE = "stage_wide"
    TRACK_FACE = "track_face"


class Cue(str, Enum):
    WARN_60 = "warn_60"
    WARN_15 = "warn_15"
    TIME_UP = "time_up"


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")


@dataclass(frozen=True)
class BookingSnapshot:
    """Synthetic or authenticated *minimal* booking data; never include PII.

    capture_verified means the operator has independently verified all capture
    and recording permissions/states, not merely hidden the source in OBS.
    """
    booking_id: str
    revision: int
    slot_start_utc: datetime
    slot_end_utc: datetime
    issued_at_utc: datetime
    expires_at_utc: datetime
    stage_seconds: int
    privacy_class: str
    checked_in: bool
    live_consent: bool
    tracking_consent: bool
    capture_verified: bool

    def __post_init__(self) -> None:
        for label in ("slot_start_utc", "slot_end_utc", "issued_at_utc",
                      "expires_at_utc"):
            _require_utc(getattr(self, label), label)
        if not self.booking_id or len(self.booking_id) > 128:
            raise ValueError("booking_id must be a nonempty opaque ID")
        if self.revision < 1 or self.stage_seconds <= 0:
            raise ValueError("revision and stage_seconds must be positive")
        if self.slot_end_utc <= self.slot_start_utc:
            raise ValueError("slot end must be later than slot start")
        if self.expires_at_utc <= self.issued_at_utc:
            raise ValueError("snapshot expiry must follow issuance")


@dataclass(frozen=True)
class Decision:
    mode: Mode
    camera_action: CameraAction
    cue: Optional[Cue] = None
    remaining_seconds: Optional[int] = None
    reason: str = ""


class StageDirector:
    """Manual-armed, fail-closed timer with deterministic decisions.

    A future adapter must ALSO independently enforce device-level privacy and
    consent. A Decision is NOT proof that a physical camera was disabled.
    """

    def __init__(self) -> None:
        self._booking: Optional[BookingSnapshot] = None
        self.mode = Mode.OFF
        self._started_monotonic: Optional[float] = None
        self._last_monotonic: Optional[float] = None
        self._previous_remaining: Optional[float] = None

    def stop(self, reason: str = "operator_stop") -> Decision:
        self._booking = None
        self.mode = Mode.OFF
        self._started_monotonic = None
        self._last_monotonic = None
        self._previous_remaining = None
        return Decision(Mode.OFF, CameraAction.CAPTURE_OFF, reason=reason)

    @staticmethod
    def _authorization_error(booking: BookingSnapshot, now_utc: datetime) -> str:
        _require_utc(now_utc, "now_utc")
        if not (booking.issued_at_utc <= now_utc < booking.expires_at_utc):
            return "booking_snapshot_stale_or_not_yet_valid"
        if booking.privacy_class != "public":
            return "private_or_unknown_privacy_class"
        if not booking.checked_in:
            return "performer_not_checked_in"
        if not (booking.live_consent and booking.tracking_consent
                and booking.capture_verified):
            return "consent_or_capture_verification_missing"
        if now_utc >= booking.slot_end_utc:
            return "slot_has_ended"
        return ""

    def arm(self, booking: BookingSnapshot, now_utc: datetime) -> Decision:
        """Loading a schedule does not start a set or move a camera."""
        if self.mode == Mode.LIVE:
            return self.stop("cannot_replace_active_set")
        error = self._authorization_error(booking, now_utc)
        if error:
            return self.stop(error)
        self.stop()
        self._booking = booking
        self.mode = Mode.ARMED
        return Decision(Mode.ARMED, CameraAction.STAGE_WIDE,
                        reason="awaiting_host_confirmed_start")

    def refresh(self, booking: BookingSnapshot, now_utc: datetime) -> Decision:
        """Treat identity changes, rollback, or revoked rights as a stop."""
        if self._booking is None:
            return self.arm(booking, now_utc)
        if booking.booking_id != self._booking.booking_id:
            return self.stop("booking_changed")
        if booking.revision < self._booking.revision:
            return self.stop("booking_revision_rollback")
        error = self._authorization_error(booking, now_utc)
        if error:
            return self.stop(error)
        self._booking = booking
        return self._current_decision("snapshot_refreshed")

    def start_set(self, now_utc: datetime, monotonic_seconds: float,
                  *, host_confirmed: bool = False) -> Decision:
        """An explicit host action is mandatory; vision is never the trigger."""
        if not host_confirmed or self.mode != Mode.ARMED or self._booking is None:
            return self._current_decision("manual_start_required")
        error = self._authorization_error(self._booking, now_utc)
        if error:
            return self.stop(error)
        if now_utc < self._booking.slot_start_utc:
            return self._current_decision("slot_not_started")
        self.mode = Mode.LIVE
        self._started_monotonic = monotonic_seconds
        self._last_monotonic = monotonic_seconds
        self._previous_remaining = min(
            float(self._booking.stage_seconds),
            (self._booking.slot_end_utc - now_utc).total_seconds(),
        )
        return Decision(Mode.LIVE, CameraAction.TRACK_FACE,
                        remaining_seconds=ceil(self._previous_remaining),
                        reason="host_confirmed_set_start")

    def tick(self, now_utc: datetime, monotonic_seconds: float) -> Decision:
        _require_utc(now_utc, "now_utc")
        if self._booking is None or self.mode == Mode.OFF:
            return Decision(Mode.OFF, CameraAction.CAPTURE_OFF,
                            reason="not_armed")
        error = self._authorization_error(self._booking, now_utc)
        # A confirmed live set must emit its end cue at the slot boundary.
        # After that one cue, the following tick fails closed as expired.
        if error and not (error == "slot_has_ended" and self.mode == Mode.LIVE):
            return self.stop(error)
        if self.mode != Mode.LIVE:
            return self._current_decision("waiting_or_finished")
        if self._last_monotonic is None or self._started_monotonic is None:
            return self.stop("missing_timer_anchor")
        if monotonic_seconds < self._last_monotonic:
            return self.stop("monotonic_clock_regressed")
        self._last_monotonic = monotonic_seconds
        remaining = max(0.0, min(
            self._booking.stage_seconds -
            (monotonic_seconds - self._started_monotonic),
            (self._booking.slot_end_utc - now_utc).total_seconds(),
        ))
        previous = self._previous_remaining
        self._previous_remaining = remaining
        if remaining <= 0:
            self.mode = Mode.FINISHED
            return Decision(Mode.FINISHED, CameraAction.STAGE_WIDE,
                            Cue.TIME_UP, remaining_seconds=0)
        # On a delayed tick, emit only the most urgent cue; never replay cues.
        if previous is not None and previous > 15 >= remaining:
            cue = Cue.WARN_15
        elif previous is not None and previous > 60 >= remaining:
            cue = Cue.WARN_60
        else:
            cue = None
        return Decision(Mode.LIVE, CameraAction.TRACK_FACE,
                        cue, remaining_seconds=ceil(remaining))

    def _current_decision(self, reason: str) -> Decision:
        if self.mode == Mode.OFF:
            return Decision(Mode.OFF, CameraAction.CAPTURE_OFF, reason=reason)
        action = (CameraAction.TRACK_FACE if self.mode == Mode.LIVE
                  else CameraAction.STAGE_WIDE)
        remaining = (ceil(self._previous_remaining)
                     if self.mode == Mode.LIVE and
                     self._previous_remaining is not None else None)
        return Decision(self.mode, action, remaining_seconds=remaining,
                        reason=reason)
