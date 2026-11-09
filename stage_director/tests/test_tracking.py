"""Unit tests for performer tracking, stage filtering, and loss holding."""
import unittest

from stage_director.geometry import BoundingBox, StagePolygon
from stage_director.tracking import PerformerTracker, TrackingState


class TrackingTests(unittest.TestCase):
    def setUp(self):
        # Stage polygon roughly 400..3400 horizontally, 400..2000 vertically
        self.stage = StagePolygon([
            (400.0, 400.0),
            (3400.0, 400.0),
            (3600.0, 2000.0),
            (200.0, 2000.0),
        ])
        self.tracker = PerformerTracker(self.stage, loss_hold_seconds=2.0)

    def test_disabled_by_default(self):
        box = BoundingBox(x=1900, y=800, width=120, height=150)
        res = self.tracker.update([box], monotonic_seconds=10.0)
        self.assertEqual(res.state, TrackingState.DISABLED)
        self.assertIsNone(res.active_subject)
        self.assertEqual(res.events, [])

    def test_acquire_and_track_performer(self):
        self.tracker.enable()
        box = BoundingBox(x=1900, y=800, width=120, height=150)
        res = self.tracker.update([box], monotonic_seconds=10.0)
        self.assertEqual(res.state, TrackingState.TRACKING)
        self.assertEqual(res.active_subject, box)
        self.assertIn("camera_subject_acquired", res.events)

        # Performer moves slightly to the right
        box2 = BoundingBox(x=1950, y=800, width=120, height=150)
        res2 = self.tracker.update([box2], monotonic_seconds=10.1)
        self.assertEqual(res2.state, TrackingState.TRACKING)
        self.assertEqual(res2.active_subject, box2)

    def test_offstage_bystanders_ignored(self):
        self.tracker.enable()
        # Bystander outside stage polygon (e.g. x=50, offstage left)
        bystander = BoundingBox(x=50, y=800, width=120, height=150)
        res = self.tracker.update([bystander], monotonic_seconds=10.0)
        self.assertEqual(res.state, TrackingState.ACQUIRING)
        self.assertIsNone(res.active_subject)
        self.assertEqual(res.offstage_count, 1)
        self.assertEqual(res.onstage_count, 0)

    def test_subject_loss_hold_then_lost(self):
        self.tracker.enable()
        performer = BoundingBox(x=1900, y=800, width=120, height=150)
        self.tracker.update([performer], monotonic_seconds=10.0)

        # Face disappears (e.g. turned head, microphone blocking, or stepped off)
        # At t=11.0s (1.0 second elapsed, <= 2.0s hold limit)
        res_held = self.tracker.update([], monotonic_seconds=11.0)
        self.assertEqual(res_held.state, TrackingState.HOLDING)
        self.assertEqual(res_held.active_subject, performer)
        self.assertEqual(res_held.events, [])

        # At t=12.1s (> 2.0s hold limit exceeded)
        res_lost = self.tracker.update([], monotonic_seconds=12.1)
        self.assertEqual(res_lost.state, TrackingState.LOST)
        self.assertIsNone(res_lost.active_subject)
        self.assertIn("camera_subject_lost", res_lost.events)

    def test_reacquisition_after_brief_hold(self):
        self.tracker.enable()
        performer = BoundingBox(x=1900, y=800, width=120, height=150)
        self.tracker.update([performer], monotonic_seconds=10.0)

        # Face disappears for 1 second
        self.tracker.update([], monotonic_seconds=11.0)
        self.assertEqual(self.tracker.state, TrackingState.HOLDING)

        # Face reappears at t=11.5s
        performer_returned = BoundingBox(x=1920, y=800, width=120, height=150)
        res = self.tracker.update([performer_returned], monotonic_seconds=11.5)
        self.assertEqual(res.state, TrackingState.TRACKING)
        self.assertEqual(res.active_subject, performer_returned)
        self.assertIn("camera_subject_reacquired", res.events)

    def test_secondary_person_onstage_ignored(self):
        self.tracker.enable()
        primary = BoundingBox(x=1900, y=800, width=120, height=150)
        self.tracker.update([primary], monotonic_seconds=10.0)

        # Second person appears on stage far to the right (x=2800)
        secondary = BoundingBox(x=2800, y=800, width=120, height=150)
        primary_moved = BoundingBox(x=1920, y=800, width=120, height=150)

        # Both onstage: tracker must match the closest box to primary
        res = self.tracker.update([secondary, primary_moved], monotonic_seconds=10.1)
        self.assertEqual(res.state, TrackingState.TRACKING)
        self.assertEqual(res.active_subject, primary_moved)

    def test_manual_subject_switch(self):
        self.tracker.enable()
        primary = BoundingBox(x=1900, y=800, width=120, height=150)
        self.tracker.update([primary], monotonic_seconds=10.0)

        # Host or guest on stage
        guest = BoundingBox(x=2800, y=800, width=120, height=150)
        # Operator confirms switch to guest
        switched = self.tracker.switch_subject(guest, monotonic_seconds=10.5)
        self.assertTrue(switched)
        self.assertEqual(self.tracker.active_subject, guest)

        # Attempting to switch to an offstage position fails
        offstage = BoundingBox(x=50, y=800, width=120, height=150)
        self.assertFalse(self.tracker.switch_subject(offstage, monotonic_seconds=10.6))
        # Active subject remains guest
        self.assertEqual(self.tracker.active_subject, guest)


if __name__ == "__main__":
    unittest.main()
