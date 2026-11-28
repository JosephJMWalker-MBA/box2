"""Failing regression tests for the three P1 review findings:

1. PerformerTracker subject stealing when current performer disappears while another person is on stage.
2. FramingEngine first frame bypassing rate limits and zoom caps from safe-wide.
3. Accurate offline OBS WebSocket v5 SetSceneItemTransform translator.
"""
from datetime import datetime, timedelta, timezone
import unittest

from stage_director.core import BookingSnapshot, CameraAction, Mode, StageDirector
from stage_director.geometry import BoundingBox, StagePolygon
from stage_director.framing import FramingConfig, FramingEngine
from stage_director.tracking import PerformerTracker, TrackingState
from stage_director.adapter import StageFramingAdapter
from stage_director.obs_transform import OBSProposal


class TrackingHardeningTests(unittest.TestCase):
    def setUp(self):
        self.stage = StagePolygon([
            (400.0, 400.0),
            (3440.0, 400.0),
            (3600.0, 2050.0),
            (240.0, 2050.0),
        ])
        self.tracker = PerformerTracker(self.stage, loss_hold_seconds=2.0)

    def test_performer_disappears_does_not_steal_bystander(self):
        """When performer A disappears, tracker must HOLD for A and NOT latch onto B."""
        self.tracker.enable()
        # Performer A at center stage
        perf_a = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        res1 = self.tracker.update([perf_a], monotonic_seconds=10.0)
        self.assertEqual(res1.state, TrackingState.TRACKING)
        self.assertEqual(res1.active_subject, perf_a)

        # 0.1s later: A is occluded / steps away. Guest B is at x=2800 (1000px away).
        guest_b = BoundingBox(x=2800.0, y=800.0, width=120.0, height=150.0)
        res2 = self.tracker.update([guest_b], monotonic_seconds=10.1)

        # MUST NOT latch onto guest B as performer A!
        self.assertNotEqual(res2.active_subject, guest_b,
                            "Tracker incorrectly stole guest B when performer A vanished!")
        self.assertEqual(res2.state, TrackingState.HOLDING)

    def test_implausible_jump_rejected(self):
        """A single subject teleporting 1500px in 0.05s must be rejected as implausible."""
        self.tracker.enable()
        perf = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        self.tracker.update([perf], monotonic_seconds=10.0)

        # Implausible jump: 1500px away in 0.05s
        jumped = BoundingBox(x=300.0, y=800.0, width=120.0, height=150.0)
        res = self.tracker.update([jumped], monotonic_seconds=10.05)

        self.assertNotEqual(res.active_subject, jumped)
        self.assertEqual(res.state, TrackingState.HOLDING)

    def test_size_inconsistency_rejected(self):
        """A candidate with a 5x area change in 0.05s must be rejected."""
        self.tracker.enable()
        perf = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        self.tracker.update([perf], monotonic_seconds=10.0)

        # Sudden massive box (e.g. false detection artifact 5x area)
        massive = BoundingBox(x=1800.0, y=800.0, width=300.0, height=300.0)
        res = self.tracker.update([massive], monotonic_seconds=10.05)
        self.assertNotEqual(res.active_subject, massive)

    def test_extended_loss_requires_confirmation_policy(self):
        """After prolonged loss (>2s), tracker must not silently auto-acquire stranger B."""
        self.tracker.enable()
        perf_a = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        self.tracker.update([perf_a], monotonic_seconds=10.0)

        # Prolonged absence: 3 seconds pass with no detections
        self.tracker.update([], monotonic_seconds=13.0)
        self.assertEqual(self.tracker.state, TrackingState.LOST)

        # Now stranger B appears far away (x=2800).
        stranger_b = BoundingBox(x=2800.0, y=800.0, width=120.0, height=150.0)
        res = self.tracker.update([stranger_b], monotonic_seconds=13.5)

        # Tracker must require host confirmation or enter ambiguous state, NOT silently track stranger B
        self.assertIn(res.state, (TrackingState.AMBIGUOUS, TrackingState.LOST))
        self.assertNotEqual(res.active_subject, stranger_b)

    def test_near_position_reacquisition_after_extended_loss_requires_confirmation(self):
        """Person appearing in performer's previous position after extended loss must NOT auto-acquire."""
        self.tracker.enable()
        perf_a = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        self.tracker.update([perf_a], monotonic_seconds=10.0)

        # 3 seconds of no detections (>2s loss hold limit)
        self.tracker.update([], monotonic_seconds=13.0)
        self.assertEqual(self.tracker.state, TrackingState.LOST)

        # Person B steps directly into A's former position with matching size
        person_b = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        res = self.tracker.update([person_b], monotonic_seconds=13.5)

        # Proximity is NOT proof of identity after extended loss; must require host confirmation
        self.assertEqual(res.state, TrackingState.AMBIGUOUS)
        self.assertIsNone(res.active_subject)
        self.assertIn("performer_confirmation_required", res.events)

        # Explicit host confirmation then locks and tracks person B
        confirmed = self.tracker.confirm_subject(person_b, monotonic_seconds=14.0)
        self.assertTrue(confirmed)
        self.assertEqual(self.tracker.active_subject, person_b)
        self.assertEqual(self.tracker.state, TrackingState.TRACKING)

    def test_ambiguous_no_box_confirm_rejected_and_does_not_auto_acquire_stranger(self):
        """Confirming without a specific box while ambiguous must be rejected and not auto-acquire stranger."""
        self.tracker.enable()
        perf_a = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        self.tracker.update([perf_a], monotonic_seconds=10.0)
        self.assertEqual(self.tracker.state, TrackingState.TRACKING)

        # Performer A lost for > 2 seconds
        self.tracker.update([], monotonic_seconds=13.0)
        self.assertEqual(self.tracker.state, TrackingState.LOST)

        # Stranger B appears near A's prior position -> enters AMBIGUOUS
        person_b = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        res1 = self.tracker.update([person_b], monotonic_seconds=13.5)
        self.assertEqual(res1.state, TrackingState.AMBIGUOUS)
        self.assertIsNone(res1.active_subject)

        # Operator calls confirm_subject(None) without a specific box
        confirmed = self.tracker.confirm_subject(None, monotonic_seconds=14.0)
        self.assertFalse(confirmed, "confirm_subject(None) must fail when ambiguous")
        self.assertEqual(self.tracker.state, TrackingState.AMBIGUOUS)
        self.assertIsNone(self.tracker.active_subject)

        # Next frame with stranger B still present: B must NOT be auto-acquired!
        res2 = self.tracker.update([person_b], monotonic_seconds=14.5)
        self.assertEqual(res2.state, TrackingState.AMBIGUOUS)
        self.assertIsNone(res2.active_subject)
        self.assertIn("performer_confirmation_required", res2.events)

        # Only explicit confirmation with B's box locks onto B
        confirmed_b = self.tracker.confirm_subject(person_b, monotonic_seconds=15.0)
        self.assertTrue(confirmed_b)
        self.assertEqual(self.tracker.state, TrackingState.TRACKING)
        self.assertEqual(self.tracker.active_subject, person_b)

    def test_multiple_onstage_faces_initial_acquisition_is_ambiguous(self):
        """When multiple faces appear onstage on initial frame, do NOT pick largest; require confirmation."""
        self.tracker.enable()
        face_a = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)
        face_b = BoundingBox(x=2400.0, y=800.0, width=140.0, height=170.0)  # Larger face

        # Initial frame with two candidates
        res = self.tracker.update([face_a, face_b], monotonic_seconds=10.0)

        # Ambiguous! Must NOT auto-acquire face_b simply because it's larger
        self.assertEqual(res.state, TrackingState.AMBIGUOUS)
        self.assertIsNone(res.active_subject)
        self.assertIn("performer_confirmation_required", res.events)

        # Host explicitly selects face_a
        self.tracker.confirm_subject(face_a, monotonic_seconds=10.5)
        self.assertEqual(self.tracker.active_subject, face_a)
        self.assertEqual(self.tracker.state, TrackingState.TRACKING)

    def test_adapter_confirm_and_switch_rejected_when_not_live(self):
        """Adapter confirm_subject and switch_subject must fail closed unless LIVE."""
        adapter = StageFramingAdapter()
        face = BoundingBox(x=1800.0, y=800.0, width=120.0, height=150.0)

        # In OFF mode
        self.assertFalse(adapter.confirm_subject(face, 10.0))
        self.assertFalse(adapter.switch_subject(face, 10.0))
        self.assertEqual(adapter.tracker.state, TrackingState.DISABLED)

        # In ARMED mode
        now = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)
        booking = BookingSnapshot(
            booking_id="test-booking", revision=1,
            slot_start_utc=now, slot_end_utc=now + timedelta(minutes=10),
            issued_at_utc=now - timedelta(seconds=10),
            expires_at_utc=now + timedelta(minutes=11),
            stage_seconds=600, privacy_class="public", checked_in=True,
            live_consent=True, tracking_consent=True, capture_verified=True,
        )
        adapter.arm(booking, now)
        self.assertFalse(adapter.confirm_subject(face, 10.0))
        self.assertFalse(adapter.switch_subject(face, 10.0))
        self.assertEqual(adapter.tracker.state, TrackingState.DISABLED)

        # Now start set (LIVE mode)
        adapter.start_set(now, 100.0, host_confirmed=True)
        self.assertTrue(adapter.confirm_subject(face, 100.0))
        self.assertEqual(adapter.tracker.state, TrackingState.TRACKING)


class FramingHardeningTests(unittest.TestCase):
    def setUp(self):
        self.config = FramingConfig(
            canvas_width=3840,
            canvas_height=2160,
            target_face_fraction=0.20,
            headroom_fraction=0.33,
            min_zoom=1.0,
            max_zoom=2.4,
            deadzone_x_px=40.0,
            deadzone_y_px=30.0,
            deadzone_zoom_px=60.0,
            smoothing_tau=0.25,
            max_pan_speed_px_s=1200.0,
            max_tilt_speed_px_s=800.0,
            max_zoom_speed_px_s=600.0,
        )
        self.engine = FramingEngine(self.config)

    def test_first_frame_obeys_rate_limits_from_safe_wide(self):
        """First tracking frame must NOT instantly jump from 1.0x wide to 2.4x zoom."""
        face = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        # Target for this face is max_zoom 2.4x (width = 3840 / 2.4 = 1600)
        # In a 0.05s initial tick, max zoom width change is max_zoom_speed * dt = 600 * 0.05 = 30px!
        dt = 0.05
        # Framing is initialized at safe-wide (3840x2160) at t=10.0
        self.engine.reset(monotonic_seconds=10.0)

        window = self.engine.update(face, monotonic_seconds=10.0 + dt)

        # Must NOT be 1600 immediately!
        self.assertGreater(window.width, 3500.0,
                           f"First frame jumped immediately to width {window.width} (zoom {window.zoom_factor(3840):.2f}x)!")
        max_allowed_dw = self.config.max_zoom_speed_px_s * dt + 5.0
        actual_dw = 3840.0 - window.width
        self.assertLessEqual(actual_dw, max_allowed_dw)

    def test_irregular_cadence_clamped(self):
        """Irregular large time step (e.g. 5 seconds) must not cause unbounded leap."""
        self.engine.reset(monotonic_seconds=10.0)
        face = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)

        # 5 seconds elapse on a stalled frame
        window = self.engine.update(face, monotonic_seconds=15.0)

        # Velocity / dt capping should prevent teleportation
        # Width shouldn't jump all the way instantaneously
        self.assertGreater(window.width, 1600.0)

    def test_zoom_hysteresis(self):
        """Small noise in face box height (within deadzone) must produce zero zoom change."""
        self.engine.reset(monotonic_seconds=10.0)
        # Face producing intermediate zoom (~1.6x, target width = 2400px)
        face1 = BoundingBox(x=1860.0, y=700.0, width=200.0, height=270.0)
        # Let framing settle completely over 6 seconds (enters deadzone around 2400)
        for i in range(1, 120):
            w = self.engine.update(face1, monotonic_seconds=10.0 + i * 0.05)
        settled_width = w.width
        self.assertLessEqual(abs(settled_width - 2400.0), self.config.deadzone_zoom_px)

        # Small ~1% face size fluctuation: height changes from 270 to 273 (width change ~26px < 60px deadzone)
        face2 = BoundingBox(x=1860.0, y=700.0, width=200.0, height=273.0)
        w2 = self.engine.update(face2, monotonic_seconds=16.05)
        self.assertEqual(w2.width, settled_width)


if __name__ == "__main__":
    unittest.main()
