"""Milestone 7: Unit and regression tests for authorization lifecycle and media gatekeeping."""
from datetime import datetime, timedelta, timezone
import unittest

from stage_director.adapter import StageFramingAdapter
from stage_director.core import (
    BookingSnapshot,
    CameraAction,
    CaptureLifecycle,
    Cue,
    Mode,
    StageDirector,
)
from stage_director.geometry import BoundingBox


class AuthorizationLifecycleTests(unittest.TestCase):
    """Verifies strict separation of capture permission, broadcast blanking, and cue timing."""

    def setUp(self) -> None:
        self.t0 = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
        self.director = StageDirector()
        self.valid_booking = BookingSnapshot(
            booking_id="valid-public-booking",
            revision=1,
            slot_start_utc=self.t0,
            slot_end_utc=self.t0 + timedelta(minutes=15),
            issued_at_utc=self.t0 - timedelta(seconds=30),
            expires_at_utc=self.t0 + timedelta(minutes=16),
            stage_seconds=60,
            privacy_class="public",
            checked_in=True,
            live_consent=True,
            tracking_consent=True,
            capture_verified=True,
        )

    def test_initial_state_is_no_input(self) -> None:
        """On boot, default state must be NO_INPUT with zero read/write permissions."""
        self.assertEqual(self.director.mode, Mode.OFF)
        self.assertEqual(self.director.capture_lifecycle, CaptureLifecycle.NO_INPUT)
        self.assertFalse(self.director.can_read_source)
        self.assertFalse(self.director.can_write_media)

    def test_arm_public_grants_preview_permission(self) -> None:
        """Arming a valid public booking transitions to ARMED_PUBLIC."""
        decision = self.director.arm(self.valid_booking, self.t0)
        self.assertEqual(decision.mode, Mode.ARMED)
        self.assertEqual(decision.camera_action, CameraAction.STAGE_WIDE)
        self.assertEqual(self.director.capture_lifecycle, CaptureLifecycle.ARMED_PUBLIC)
        self.assertTrue(self.director.can_read_source)
        self.assertTrue(self.director.can_write_media)

    def test_vision_alone_cannot_trigger_host_start(self) -> None:
        """Detections/vision cannot trigger start_set without explicit host_confirmed=True."""
        adapter = StageFramingAdapter(director=self.director)
        adapter.arm(self.valid_booking, self.t0)

        # Feed detections before host confirmation
        box = BoundingBox(1800, 750, 240, 300)
        proposal = adapter.process_frame(
            detections=[box],
            now_utc=self.t0 + timedelta(seconds=1),
            monotonic_seconds=1001.0,
        )

        # Must remain in ARMED mode with STAGE_WIDE and NO live tracking
        self.assertEqual(proposal.mode, "armed")
        self.assertEqual(proposal.camera_action, "stage_wide")
        self.assertEqual(self.director.capture_lifecycle, CaptureLifecycle.ARMED_PUBLIC)
        self.assertIsNone(proposal.cue)

    def test_countdown_does_not_advance_before_host_start(self) -> None:
        """Stage timer and cues must not advance or emit cues while awaiting host confirmation."""
        self.director.arm(self.valid_booking, self.t0)
        d1 = self.director.tick(self.t0 + timedelta(seconds=10), 1010.0)
        self.assertEqual(d1.mode, Mode.ARMED)
        self.assertIsNone(d1.remaining_seconds)
        self.assertIsNone(d1.cue)

        d2 = self.director.tick(self.t0 + timedelta(seconds=100), 1100.0)
        self.assertEqual(d2.mode, Mode.ARMED)
        self.assertIsNone(d2.remaining_seconds)
        self.assertIsNone(d2.cue)

    def test_cues_fire_exactly_once_at_tested_thresholds(self) -> None:
        """A confirmed live set emits warn_60, warn_15, and time_up exactly once."""
        booking = BookingSnapshot(
            booking_id="cue-test-booking",
            revision=1,
            slot_start_utc=self.t0,
            slot_end_utc=self.t0 + timedelta(minutes=15),
            issued_at_utc=self.t0 - timedelta(seconds=30),
            expires_at_utc=self.t0 + timedelta(minutes=16),
            stage_seconds=65,
            privacy_class="public",
            checked_in=True,
            live_consent=True,
            tracking_consent=True,
            capture_verified=True,
        )
        self.director.arm(booking, self.t0)
        start_dec = self.director.start_set(self.t0, 1000.0, host_confirmed=True)
        self.assertEqual(start_dec.mode, Mode.LIVE)
        self.assertEqual(self.director.capture_lifecycle, CaptureLifecycle.LIVE_PUBLIC)

        cues_observed = []

        # Tick 1: t=4.0s -> remaining = 61s (>60)
        d = self.director.tick(self.t0 + timedelta(seconds=4), 1004.0)
        if d.cue:
            cues_observed.append((4, d.cue))

        # Tick 2: t=6.0s -> remaining = 59s (crosses 60s boundary)
        d = self.director.tick(self.t0 + timedelta(seconds=6), 1006.0)
        if d.cue:
            cues_observed.append((6, d.cue))

        # Tick 3: t=7.0s -> remaining = 58s (must NOT re-emit warn_60)
        d = self.director.tick(self.t0 + timedelta(seconds=7), 1007.0)
        if d.cue:
            cues_observed.append((7, d.cue))

        # Tick 4: t=49.0s -> remaining = 16s (>15)
        d = self.director.tick(self.t0 + timedelta(seconds=49), 1049.0)
        if d.cue:
            cues_observed.append((49, d.cue))

        # Tick 5: t=51.0s -> remaining = 14s (crosses 15s boundary)
        d = self.director.tick(self.t0 + timedelta(seconds=51), 1051.0)
        if d.cue:
            cues_observed.append((51, d.cue))

        # Tick 6: t=52.0s -> remaining = 13s (must NOT re-emit warn_15)
        d = self.director.tick(self.t0 + timedelta(seconds=52), 1052.0)
        if d.cue:
            cues_observed.append((52, d.cue))

        # Tick 7: t=66.0s -> remaining = 0s (crosses time_up boundary)
        d = self.director.tick(self.t0 + timedelta(seconds=66), 1066.0)
        if d.cue:
            cues_observed.append((66, d.cue))

        # Verify exact sequence
        self.assertEqual(len(cues_observed), 3)
        self.assertEqual(cues_observed[0], (6, Cue.WARN_60))
        self.assertEqual(cues_observed[1], (51, Cue.WARN_15))
        self.assertEqual(cues_observed[2], (66, Cue.TIME_UP))

    def test_private_booking_fails_closed_to_stopped(self) -> None:
        """Booking with privacy_class='private' fails closed immediately."""
        private_booking = BookingSnapshot(
            booking_id="private-booking",
            revision=1,
            slot_start_utc=self.t0,
            slot_end_utc=self.t0 + timedelta(minutes=15),
            issued_at_utc=self.t0 - timedelta(seconds=30),
            expires_at_utc=self.t0 + timedelta(minutes=16),
            stage_seconds=60,
            privacy_class="private",
            checked_in=True,
            live_consent=True,
            tracking_consent=True,
            capture_verified=True,
        )
        dec = self.director.arm(private_booking, self.t0)
        self.assertEqual(dec.mode, Mode.OFF)
        self.assertEqual(dec.camera_action, CameraAction.CAPTURE_OFF)
        self.assertEqual(self.director.capture_lifecycle, CaptureLifecycle.STOPPED)
        self.assertFalse(self.director.can_read_source)
        self.assertFalse(self.director.can_write_media)

    def test_blank_output_vs_stopped_permission_separation(self) -> None:
        """BLANK_PUBLIC_OUTPUT conceals output while preserving stream; STOPPED terminates all I/O."""
        self.director.arm(self.valid_booking, self.t0)
        self.director.start_set(self.t0, 1000.0, host_confirmed=True)

        # Temporary public blanking
        b_dec = self.director.blank_output("emergency_blackout")
        self.assertEqual(self.director.capture_lifecycle, CaptureLifecycle.BLANK_PUBLIC_OUTPUT)
        # Read/write permitted to keep stream container alive
        self.assertTrue(self.director.can_read_source)
        self.assertTrue(self.director.can_write_media)

        # Restore
        r_dec = self.director.restore_output()
        self.assertEqual(self.director.capture_lifecycle, CaptureLifecycle.LIVE_PUBLIC)

        # Full stop / revoke
        s_dec = self.director.stop("consent_revoked")
        self.assertEqual(self.director.capture_lifecycle, CaptureLifecycle.STOPPED)
        # Permissions revoked immediately
        self.assertFalse(self.director.can_read_source)
        self.assertFalse(self.director.can_write_media)


if __name__ == "__main__":
    unittest.main()
