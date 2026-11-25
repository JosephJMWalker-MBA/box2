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

    def test_proximity_reacquisition_enabled_single_onstage_reacquires(self):
        """When allow_proximity_reacquisition=True, single performer returning on stage auto-reacquires."""
        auto_tracker = PerformerTracker(
            self.stage,
            loss_hold_seconds=2.0,
            allow_proximity_reacquisition=True,
        )
        auto_tracker.enable()

        performer = BoundingBox(x=1900, y=800, width=120, height=150)
        auto_tracker.update([performer], monotonic_seconds=10.0)
        self.assertEqual(auto_tracker.state, TrackingState.TRACKING)

        # Extended loss (> 2.0s)
        auto_tracker.update([], monotonic_seconds=13.0)
        self.assertEqual(auto_tracker.state, TrackingState.LOST)

        # Performer reappears alone on stage (mic lowered or turned back)
        returned = BoundingBox(x=1950, y=800, width=120, height=150)
        res = auto_tracker.update([returned], monotonic_seconds=14.0)

        # Reacquires without needing manual operator confirmation!
        self.assertEqual(res.state, TrackingState.TRACKING)
        self.assertEqual(res.active_subject, returned)
        self.assertIn("camera_subject_reacquired", res.events)

    def test_proximity_reacquisition_enabled_multiple_onstage_ambiguity(self):
        """When allow_proximity_reacquisition=True, multiple candidates outside proximity stay ambiguous."""
        auto_tracker = PerformerTracker(
            self.stage,
            loss_hold_seconds=2.0,
            allow_proximity_reacquisition=True,
        )
        auto_tracker.enable()

        performer = BoundingBox(x=1000, y=800, width=120, height=150)
        auto_tracker.update([performer], monotonic_seconds=10.0)

        # Extended loss
        auto_tracker.update([], monotonic_seconds=13.0)
        self.assertEqual(auto_tracker.state, TrackingState.LOST)

        # Two strangers appear far away on stage right (x=2800 and x=3000)
        stranger1 = BoundingBox(x=2800, y=800, width=120, height=150)
        stranger2 = BoundingBox(x=3000, y=800, width=120, height=150)
        res = auto_tracker.update([stranger1, stranger2], monotonic_seconds=14.0)

        # Neither matches proximity; stays ambiguous and requires host confirmation
        self.assertEqual(res.state, TrackingState.AMBIGUOUS)
        self.assertIsNone(res.active_subject)
        self.assertIn("performer_confirmation_required", res.events)

    def test_floor_pets_and_objects_rejected_by_max_performer_y(self):
        """Objects/pets on the floor (below human standing height) are strictly ignored."""
        tracker = PerformerTracker(
            self.stage,
            max_performer_y=1200.0,  # Floor cutoff: standing human heads are <= 1200
        )
        tracker.enable()

        # Dog or pet detected on floor at y=1600 (within polygon x range, but on floor)
        dog_box = BoundingBox(x=1800.0, y=1600.0, width=100.0, height=100.0)
        res = tracker.update([dog_box], monotonic_seconds=10.0)

        # Dog must be counted as offstage and NOT acquired!
        self.assertEqual(res.state, TrackingState.ACQUIRING)
        self.assertIsNone(res.active_subject)
        self.assertEqual(res.onstage_count, 0)
        self.assertEqual(res.offstage_count, 1)

        # Standing human performer appears at y=700 (above floor cutoff)
        human_box = BoundingBox(x=1800.0, y=700.0, width=120.0, height=150.0)
        res_human = tracker.update([dog_box, human_box], monotonic_seconds=10.1)

        # Only the human is acquired!
        self.assertEqual(res_human.state, TrackingState.TRACKING)
        self.assertEqual(res_human.active_subject, human_box)
        self.assertEqual(res_human.onstage_count, 1)
        self.assertEqual(res_human.offstage_count, 1)

    def test_exclusion_boxes_reject_wall_portrait_poster(self):
        """Static portrait artwork inside exclusion zone is rejected and never tracked."""
        stage_640 = StagePolygon([(12.0, 20.0), (515.0, 20.0), (515.0, 315.0), (12.0, 315.0)])
        portrait_zone = BoundingBox(x=530.0, y=105.0, width=110.0, height=145.0)
        # Also test an exclusion zone even inside the stage polygon (e.g. door photo)
        door_photo_zone = BoundingBox(x=305.0, y=90.0, width=55.0, height=60.0)
        tracker = PerformerTracker(
            stage_640,
            exclusion_boxes=[portrait_zone, door_photo_zone],
        )
        tracker.enable()

        # Right-wall Jesus poster detection at (573, 138, 53, 53)
        poster_box = BoundingBox(x=573.0, y=138.0, width=53.0, height=53.0)
        door_box = BoundingBox(x=315.0, y=100.0, width=35.0, height=35.0)
        res = tracker.update([poster_box, door_box], monotonic_seconds=1.0)
        self.assertEqual(res.state, TrackingState.ACQUIRING)
        self.assertIsNone(res.active_subject)
        self.assertEqual(res.onstage_count, 0)
        self.assertEqual(res.offstage_count, 2)

    def test_temporal_persistence_gate_blocks_keyframe_blips_and_acquires_performer(self):
        """4-second H.264 I-frame 1-frame blips never lock, while a real performer locks in 4 frames."""
        stage_640 = StagePolygon([(12.0, 20.0), (515.0, 20.0), (515.0, 315.0), (12.0, 315.0)])
        tracker = PerformerTracker(
            stage_640,
            loss_hold_seconds=6.0,
            base_match_radius_px=85.0,
            require_confirmation_after_loss=False,
            acquisition_confirm_frames=4,
            acquisition_window_seconds=1.2,
            reacquire_confirm_frames=2,
        )
        tracker.enable()

        blip = BoundingBox(x=250.0, y=120.0, width=40.0, height=40.0)
        # Simulate 1-frame keyframe blips every 4.0 seconds over 20 seconds
        for cycle in range(5):
            t_blip = cycle * 4.0
            res_blip = tracker.update([blip], monotonic_seconds=t_blip)
            self.assertEqual(res_blip.state, TrackingState.ACQUIRING)
            self.assertIsNone(res_blip.active_subject)
            for f in range(1, 40):
                res_empty = tracker.update([], monotonic_seconds=t_blip + f * 0.1)
                self.assertEqual(res_empty.state, TrackingState.ACQUIRING)

        # Now real performer walks onto stage at t=30.0 (4 consecutive frames at 10 FPS = 0.3s)
        for i in range(3):
            r = tracker.update([BoundingBox(x=230.0 + i * 2, y=115.0, width=42.0, height=42.0)], monotonic_seconds=30.0 + i * 0.1)
            self.assertEqual(r.state, TrackingState.ACQUIRING)
        r4 = tracker.update([BoundingBox(x=236.0, y=115.0, width=42.0, height=42.0)], monotonic_seconds=30.3)
        self.assertEqual(r4.state, TrackingState.TRACKING)
        self.assertIsNotNone(r4.active_subject)

        # Performer steps off stage -> enters HOLDING; a single stray 1-frame blip does NOT reset hold timer
        r_hold = tracker.update([], monotonic_seconds=31.0)
        self.assertEqual(r_hold.state, TrackingState.HOLDING)
        r_stray = tracker.update([BoundingBox(x=236.0, y=115.0, width=42.0, height=42.0)], monotonic_seconds=34.0)
        self.assertEqual(r_stray.state, TrackingState.HOLDING)
        # At t=36.5 (> 6.0s since last confirmed 30.3s), cleanly transitions to LOST so camera returns wide
        r_lost = tracker.update([], monotonic_seconds=36.5)
        self.assertEqual(r_lost.state, TrackingState.LOST)


if __name__ == "__main__":
    unittest.main()
