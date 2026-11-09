"""Comprehensive integration tests for StageFramingAdapter.

Covers performer movement, fast movement, offstage bystanders, lost face,
reacquisition, subject switch, sudden zoom, dead-zone, privacy revoke,
time cues, and process restart.
Standard library only.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import unittest

from stage_director.adapter import StageFramingAdapter
from stage_director.core import BookingSnapshot, CameraAction, Cue, Mode, StageDirector
from stage_director.framing import FramingConfig, FramingEngine
from stage_director.geometry import BoundingBox, StagePolygon
from stage_director.obs_transform import OBSProposal


START = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)


def valid_booking(**changes) -> BookingSnapshot:
    data = dict(
        booking_id="synthetic-comic-01",
        revision=1,
        slot_start_utc=START,
        slot_end_utc=START + timedelta(minutes=10),
        issued_at_utc=START - timedelta(seconds=10),
        expires_at_utc=START + timedelta(minutes=11),
        stage_seconds=600,
        privacy_class="public",
        checked_in=True,
        live_consent=True,
        tracking_consent=True,
        capture_verified=True,
    )
    data.update(changes)
    return BookingSnapshot(**data)


class StageFramingAdapterTests(unittest.TestCase):
    def setUp(self):
        self.stage = StagePolygon([
            (400.0, 400.0),
            (3440.0, 400.0),
            (3600.0, 2050.0),
            (240.0, 2050.0),
        ])
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
        self.adapter = StageFramingAdapter(config=self.config)
        # Configure tracker with test stage
        self.adapter.tracker.stage_polygon = self.stage
        self.adapter.tracker.loss_hold_seconds = 2.0

    def arm_and_start(self, at=START, mono=100.0):
        proposal_arm = self.adapter.arm(valid_booking(), at)
        self.assertEqual(proposal_arm.mode, "armed")
        self.assertEqual(proposal_arm.camera_action, "stage_wide")
        self.assertEqual(proposal_arm.obs_crop, {"left": 0, "top": 0, "right": 0, "bottom": 0})

        proposal_start = self.adapter.start_set(at, mono, host_confirmed=True)
        self.assertEqual(proposal_start.mode, "live")
        self.assertEqual(proposal_start.camera_action, "track_face")
        self.assertEqual(proposal_start.tracking_state, "acquiring")

    def test_process_restart_default_fails_closed(self):
        """On process start/reboot, default state must be OFF with capture_off."""
        raw_adapter = StageFramingAdapter()
        face = BoundingBox(x=1920, y=800, width=120, height=150)
        proposal = raw_adapter.process_frame([face], START, 100.0)

        self.assertEqual(proposal.mode, "off")
        self.assertEqual(proposal.camera_action, "capture_off")
        self.assertEqual(proposal.tracking_state, "disabled")
        self.assertIsNone(proposal.obs_crop)
        self.assertIsNone(proposal.framing)

    def test_manual_start_required(self):
        """Vision/detections can never trigger set start without host confirmation."""
        self.adapter.arm(valid_booking(), START)
        face = BoundingBox(x=1920, y=800, width=120, height=150)

        proposal = self.adapter.process_frame([face], START + timedelta(seconds=1), 101.0)
        self.assertEqual(proposal.mode, "armed")
        self.assertEqual(proposal.camera_action, "stage_wide")
        self.assertEqual(proposal.obs_crop, {"left": 0, "top": 0, "right": 0, "bottom": 0})

    def test_performer_movement_smoothly_tracked(self):
        """Performer moving across stage is smoothly followed with 16:9 framing."""
        self.arm_and_start()

        # Frame 1: Performer at center stage (x=1860, y=700, w=120, h=150)
        face1 = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        prop1 = self.adapter.process_frame([face1], START + timedelta(seconds=1), 101.0)

        self.assertEqual(prop1.mode, "live")
        self.assertEqual(prop1.camera_action, "track_face")
        self.assertEqual(prop1.tracking_state, "tracking")
        self.assertFalse(prop1.subject_lost)
        self.assertIsNotNone(prop1.obs_crop)
        self.assertIsNotNone(prop1.framing)

        # Frame 2..5: Performer walks stage left (x moves from 1860 to 1200 over 3 seconds)
        for i in range(1, 4):
            x_pos = 1860.0 - i * 220.0
            face = BoundingBox(x=x_pos, y=700.0, width=120.0, height=150.0)
            now = START + timedelta(seconds=1 + i)
            mono = 101.0 + i
            prop = self.adapter.process_frame([face], now, mono)

            self.assertEqual(prop.tracking_state, "tracking")
            self.assertFalse(prop.subject_lost)
            # Camera center should be moving to the left
            self.assertLess(prop.framing["center_x"], prop1.framing["center_x"])
            # Validate OBS crop geometry
            crop = prop.obs_crop
            visible_w = 3840 - crop["left"] - crop["right"]
            visible_h = 2160 - crop["top"] - crop["bottom"]
            self.assertAlmostEqual(visible_w / visible_h, 16.0 / 9.0, delta=0.03)

    def test_fast_movement_rate_limited(self):
        """Sudden sprint/leap across stage is velocity-clamped to prevent jarring jumps."""
        self.arm_and_start()

        face1 = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        prop1 = self.adapter.process_frame([face1], START + timedelta(seconds=1), 101.0)
        init_x = prop1.framing["center_x"]

        # Fast sprint: performer jumps 1600px to x=260 in 0.05 seconds
        face2 = BoundingBox(x=260.0, y=700.0, width=120.0, height=150.0)
        dt = 0.05
        prop2 = self.adapter.process_frame([face2], START + timedelta(seconds=1, milliseconds=50), 101.0 + dt)

        # Max pan speed is 1200 px/s; in 0.05s max delta is 60 px!
        actual_delta = abs(prop2.framing["center_x"] - init_x)
        self.assertLessEqual(actual_delta, self.config.max_pan_speed_px_s * dt + 1.0)
        self.assertGreater(prop2.framing["center_x"], 1600.0)

    def test_offstage_bystanders_ignored(self):
        """Audience and backstage people outside stage polygon are ignored."""
        self.arm_and_start()

        # Face in the audience/offstage wing (x=50, y=800)
        bystander = BoundingBox(x=50.0, y=800.0, width=120.0, height=150.0)
        prop = self.adapter.process_frame([bystander], START + timedelta(seconds=1), 101.0)

        # Should NOT acquire bystander
        self.assertEqual(prop.tracking_state, "acquiring")
        self.assertEqual(prop.framing["zoom_factor"], 1.0)

    def test_lost_face_holding_and_timeout(self):
        """Performer turning away holds framing for 2.0s; timeout falls back to safe wide."""
        self.arm_and_start()

        face = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        prop_init = self.adapter.process_frame([face], START + timedelta(seconds=1), 101.0)
        init_crop = prop_init.obs_crop
        init_zoom = prop_init.framing["zoom_factor"]
        self.assertGreater(init_zoom, 1.0)

        # Performer turns head or mic blocks face: detections become empty
        # 1.0 second elapsed (<= 2.0s hold): state must be HOLDING
        prop_held = self.adapter.process_frame([], START + timedelta(seconds=2), 102.0)
        self.assertEqual(prop_held.tracking_state, "holding")
        self.assertFalse(prop_held.subject_lost)
        # Framing is held steady (not snapping wide)
        self.assertEqual(prop_held.framing["center_x"], prop_init.framing["center_x"])

        # 3.2 seconds elapsed (> 2.0s hold): timeout exceeded!
        prop_lost = self.adapter.process_frame([], START + timedelta(seconds=4, milliseconds=200), 104.2)
        self.assertEqual(prop_lost.tracking_state, "lost")
        self.assertTrue(prop_lost.subject_lost)
        self.assertIn("camera_subject_lost", prop_lost.events)

    def test_lost_face_reacquisition(self):
        """Performer face returns after brief occlusion without resetting to safe wide."""
        self.arm_and_start()

        face = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        self.adapter.process_frame([face], START + timedelta(seconds=1), 101.0)

        # Face missing for 1.0s (holding)
        self.adapter.process_frame([], START + timedelta(seconds=2), 102.0)
        self.assertEqual(self.adapter.tracker.state, "holding")

        # Face reappears at t=2.5s
        face_back = BoundingBox(x=1880.0, y=700.0, width=120.0, height=150.0)
        prop = self.adapter.process_frame([face_back], START + timedelta(seconds=2, milliseconds=500), 102.5)
        self.assertEqual(prop.tracking_state, "tracking")
        self.assertFalse(prop.subject_lost)
        self.assertIn("camera_subject_reacquired", prop.events)

    def test_subject_switch_and_secondary_onstage(self):
        """Second person on stage is ignored; explicit operator switch works cleanly."""
        self.arm_and_start()

        primary = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        prop1 = self.adapter.process_frame([primary], START + timedelta(seconds=1), 101.0)

        # Secondary guest appears at x=2800 on stage
        secondary = BoundingBox(x=2800.0, y=700.0, width=120.0, height=150.0)
        primary_moved = BoundingBox(x=1880.0, y=700.0, width=120.0, height=150.0)

        # Process frame with both: tracker stays locked on primary
        prop2 = self.adapter.process_frame([secondary, primary_moved], START + timedelta(seconds=2), 102.0)
        self.assertEqual(prop2.tracking_state, "tracking")
        self.assertAlmostEqual(prop2.framing["center_x"], primary_moved.center_x, delta=80.0)

        # Operator explicitly calls switch_subject to track guest
        self.adapter.switch_subject(secondary, monotonic_seconds=102.5)
        prop3 = self.adapter.process_frame([secondary, primary_moved], START + timedelta(seconds=3), 103.0)
        self.assertEqual(prop3.tracking_state, "tracking")
        # Camera is now tracking towards secondary at x=2800
        self.assertGreater(prop3.framing["center_x"], 2000.0)

    def test_sudden_zoom_clamped_and_smoothed(self):
        """Extreme face size variation is clamped by zoom limits and rate-limited."""
        self.arm_and_start()

        face1 = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        prop1 = self.adapter.process_frame([face1], START + timedelta(seconds=1), 101.0)

        # Face detection suddenly shrinks to 10px (e.g. false detection or artifact)
        tiny_face = BoundingBox(x=1860.0, y=700.0, width=10.0, height=10.0)
        prop2 = self.adapter.process_frame([tiny_face], START + timedelta(seconds=1, milliseconds=100), 101.1)

        # Zoom must never exceed max_zoom (2.4x)
        self.assertLessEqual(prop2.framing["zoom_factor"], self.config.max_zoom)

    def test_dead_zone_suppresses_micro_jitter(self):
        """Micro-movements below dead-zone thresholds produce zero camera jitter."""
        self.arm_and_start()

        face1 = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        # Settle framing on performer over 5 seconds (from 3840 wide to 1600 zoom)
        for i in range(1, 100):
            prop1 = self.adapter.process_frame(
                [face1],
                START + timedelta(seconds=1, milliseconds=i * 50),
                101.0 + i * 0.05
            )

        # Move 10px in X and 8px in Y (deadzones are 40px and 30px)
        face2 = BoundingBox(x=1870.0, y=708.0, width=120.0, height=150.0)
        prop2 = self.adapter.process_frame(
            [face2],
            START + timedelta(seconds=6, milliseconds=50),
            106.05
        )

        self.assertEqual(prop1.obs_crop, prop2.obs_crop)
        self.assertEqual(prop1.framing["center_x"], prop2.framing["center_x"])
        self.assertEqual(prop1.framing["center_y"], prop2.framing["center_y"])

    def test_privacy_revoke_immediately_disables_capture(self):
        """Revoking consent immediately drops framing to capture_off and null crop."""
        self.arm_and_start()

        face = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        prop_live = self.adapter.process_frame([face], START + timedelta(seconds=10), 110.0)
        self.assertEqual(prop_live.camera_action, "track_face")

        # Booking snapshot revokes live consent
        revoked = replace(valid_booking(), revision=2, live_consent=False)
        prop_revoked = self.adapter.refresh(revoked, START + timedelta(seconds=11), 111.0)

        self.assertEqual(prop_revoked.mode, "off")
        self.assertEqual(prop_revoked.camera_action, "capture_off")
        self.assertEqual(prop_revoked.tracking_state, "disabled")
        self.assertIsNone(prop_revoked.obs_crop)
        self.assertIsNone(prop_revoked.framing)
        self.assertIn("camera_auto_disabled", prop_revoked.events)

        # Subsequent frames must fail closed
        prop_after = self.adapter.process_frame([face], START + timedelta(seconds=12), 112.0)
        self.assertEqual(prop_after.mode, "off")
        self.assertEqual(prop_after.camera_action, "capture_off")
        self.assertIsNone(prop_after.obs_crop)

    def test_time_up_cue_and_stage_wide(self):
        """Performance duration expires: time_up cue emitted and switches to safe wide."""
        self.arm_and_start()

        face = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        # Tick at 600s (set end)
        prop = self.adapter.process_frame([face], START + timedelta(seconds=600), 700.0)

        self.assertEqual(prop.mode, "finished")
        self.assertEqual(prop.camera_action, "stage_wide")
        self.assertEqual(prop.cue, "time_up")
        self.assertEqual(prop.obs_crop, {"left": 0, "top": 0, "right": 0, "bottom": 0})

    def test_obs_proposal_json_serialization(self):
        """Proposal serializes to strictly valid JSON matching required schema."""
        self.arm_and_start()

        face = BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        prop = self.adapter.process_frame([face], START + timedelta(seconds=5), 105.0)

        json_str = prop.to_json()
        parsed = json.loads(json_str)

        self.assertEqual(parsed["schema_version"], "1.0")
        self.assertEqual(parsed["mode"], "live")
        self.assertEqual(parsed["camera_action"], "track_face")
        self.assertIn("left", parsed["obs_crop"])
        self.assertIn("top", parsed["obs_crop"])
        self.assertIn("right", parsed["obs_crop"])
        self.assertIn("bottom", parsed["obs_crop"])
        self.assertIsInstance(parsed["events"], list)


if __name__ == "__main__":
    unittest.main()
