"""Privacy and clock regression tests; standard library only."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from stage_director import BookingSnapshot, CameraAction, Cue, Mode, StageDirector


START = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)


def booking(**changes):
    data = dict(
        booking_id="synthetic-id-01", revision=1,
        slot_start_utc=START,
        slot_end_utc=START + timedelta(minutes=10),
        issued_at_utc=START - timedelta(seconds=10),
        expires_at_utc=START + timedelta(minutes=11),
        stage_seconds=600, privacy_class="public", checked_in=True,
        live_consent=True, tracking_consent=True, capture_verified=True,
    )
    data.update(changes)
    return BookingSnapshot(**data)


class StageDirectorTests(unittest.TestCase):
    def setUp(self):
        self.d = StageDirector()

    def arm_and_start(self, at=START, mono=100):
        self.assertEqual(self.d.arm(booking(), at).mode, Mode.ARMED)
        self.assertEqual(
            self.d.start_set(at, mono, host_confirmed=True).mode, Mode.LIVE
        )

    def test_default_fails_closed(self):
        decision = self.d.tick(START, 100)
        self.assertEqual(decision.camera_action, CameraAction.CAPTURE_OFF)
        self.assertIsNone(decision.cue)

    def test_schedule_does_not_start_performance(self):
        result = self.d.arm(booking(), START)
        self.assertEqual(result.mode, Mode.ARMED)
        self.assertEqual(result.camera_action, CameraAction.STAGE_WIDE)
        self.assertIsNone(self.d.tick(START + timedelta(seconds=5), 105).cue)
        self.assertEqual(self.d.mode, Mode.ARMED)

    def test_manual_confirmation_required(self):
        self.d.arm(booking(), START)
        self.assertEqual(self.d.start_set(START, 100).mode, Mode.ARMED)
        self.assertEqual(self.d.mode, Mode.ARMED)

    def test_private_cannot_arm(self):
        result = self.d.arm(booking(privacy_class="private"), START)
        self.assertEqual(result.camera_action, CameraAction.CAPTURE_OFF)

    def test_each_missing_grant_fails_closed(self):
        for field in ("checked_in", "live_consent", "tracking_consent",
                      "capture_verified"):
            with self.subTest(field=field):
                d = StageDirector()
                result = d.arm(booking(**{field: False}), START)
                self.assertEqual(result.mode, Mode.OFF)

    def test_stale_snapshot_cannot_arm(self):
        b = booking(expires_at_utc=START - timedelta(seconds=1))
        self.assertEqual(self.d.arm(b, START).mode, Mode.OFF)

    def test_future_snapshot_cannot_arm(self):
        b = booking(issued_at_utc=START + timedelta(seconds=1))
        self.assertEqual(self.d.arm(b, START).mode, Mode.OFF)

    def test_no_start_before_slot(self):
        early = START - timedelta(seconds=2)
        self.d.arm(booking(), early)
        result = self.d.start_set(early, 100, host_confirmed=True)
        self.assertEqual(result.mode, Mode.ARMED)

    def test_once_each_warning_and_time_up(self):
        self.arm_and_start()
        self.assertIsNone(
            self.d.tick(START + timedelta(seconds=539), 639).cue
        )
        self.assertEqual(
            self.d.tick(START + timedelta(seconds=541), 641).cue, Cue.WARN_60
        )
        self.assertIsNone(
            self.d.tick(START + timedelta(seconds=542), 642).cue
        )
        self.assertEqual(
            self.d.tick(START + timedelta(seconds=586), 686).cue, Cue.WARN_15
        )
        self.assertEqual(
            self.d.tick(START + timedelta(seconds=600), 700).cue, Cue.TIME_UP
        )
        # A slot that has ended is no longer authorized to capture.
        later = self.d.tick(START + timedelta(seconds=601), 701)
        self.assertEqual(later.camera_action, CameraAction.CAPTURE_OFF)
        self.assertIsNone(later.cue)

    def test_late_set_ends_at_booking_deadline(self):
        late = START + timedelta(seconds=580)
        self.arm_and_start(late, mono=900)
        self.assertEqual(self.d.tick(late, 900).remaining_seconds, 20)
        self.assertEqual(
            self.d.tick(START + timedelta(seconds=586), 906).cue,
            Cue.WARN_15
        )
        self.assertEqual(
            self.d.tick(START + timedelta(seconds=600), 920).cue,
            Cue.TIME_UP
        )

    def test_no_replay_when_very_late_start(self):
        late = START + timedelta(seconds=590)
        self.arm_and_start(late, mono=100)
        self.assertIsNone(self.d.tick(late, 100).cue)

    def test_large_jump_emits_only_urgent_cue(self):
        self.arm_and_start()
        decision = self.d.tick(START + timedelta(seconds=599), 699)
        self.assertEqual(decision.cue, Cue.WARN_15)

    def test_stop_disables_every_output(self):
        self.arm_and_start()
        self.d.stop()
        decision = self.d.tick(START + timedelta(seconds=541), 641)
        self.assertEqual(decision.camera_action, CameraAction.CAPTURE_OFF)
        self.assertIsNone(decision.cue)

    def test_revoked_grant_during_live_is_fail_closed(self):
        self.arm_and_start()
        new = replace(booking(), revision=2, live_consent=False)
        decision = self.d.refresh(new, START + timedelta(seconds=30))
        self.assertEqual(decision.camera_action, CameraAction.CAPTURE_OFF)
        self.assertEqual(self.d.mode, Mode.OFF)

    def test_old_revision_is_rejected(self):
        self.d.arm(replace(booking(), revision=3), START)
        self.assertEqual(
            self.d.refresh(booking(), START).reason,
            "booking_revision_rollback",
        )

    def test_changed_identity_is_rejected(self):
        self.arm_and_start()
        other = replace(booking(), booking_id="different-id", revision=2)
        self.assertEqual(self.d.refresh(other, START).mode, Mode.OFF)

    def test_replacing_active_set_is_forbidden(self):
        self.arm_and_start()
        decision = self.d.arm(booking(), START + timedelta(seconds=2))
        self.assertEqual(decision.mode, Mode.OFF)

    def test_monotonic_regression_fails_closed(self):
        self.arm_and_start()
        self.d.tick(START + timedelta(seconds=50), 150)
        self.assertEqual(
            self.d.tick(START + timedelta(seconds=51), 149).mode, Mode.OFF
        )

    def test_invalid_utc_rejected(self):
        with self.assertRaises(ValueError):
            booking(slot_start_utc=START.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            self.d.arm(booking(), START.replace(tzinfo=None))

    def test_timer_does_not_require_clip_permission(self):
        # Clip/archival permission is intentionally absent from this contract.
        self.arm_and_start()
        self.assertEqual(self.d.mode, Mode.LIVE)


if __name__ == "__main__":
    unittest.main()
