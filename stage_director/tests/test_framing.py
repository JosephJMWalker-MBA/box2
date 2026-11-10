"""Unit tests for camera framing, dead-zone, and temporal smoothing."""
import unittest

from stage_director.geometry import BoundingBox
from stage_director.framing import FramingConfig, FramingEngine, FramingWindow


class FramingTests(unittest.TestCase):
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

    def test_medium_shot_aspect_and_headroom(self):
        # Standing comedian face height = 240px, centered horizontally at 1920, face center at 800
        face = BoundingBox(x=1820.0, y=680.0, width=200.0, height=240.0)
        target = self.engine.compute_target_window(face)

        # 1. 16:9 aspect ratio
        aspect = target.width / target.height
        self.assertAlmostEqual(aspect, 16.0 / 9.0, places=4)

        # 2. Medium shot framing: target height should be face_height / 0.20 = 1200px
        self.assertAlmostEqual(target.height, 1200.0, places=1)
        self.assertAlmostEqual(target.width, 1200.0 * (16.0 / 9.0), places=1)

        # 3. Headroom: face center (800) relative to crop top
        crop_top = target.top
        face_offset_from_top = face.center_y - crop_top
        # face center fraction down the crop window should be ~0.33
        self.assertAlmostEqual(face_offset_from_top / target.height, 0.33, places=2)

    def test_zoom_bounds_clamped(self):
        # Huge face (e.g. occupying 1500px height): would want a crop wider than 4K canvas
        huge_face = BoundingBox(x=1420.0, y=330.0, width=1000.0, height=1500.0)
        target_wide = self.engine.compute_target_window(huge_face)
        # Cannot zoom out wider than 1.0x (3840x2160)
        self.assertEqual(target_wide.width, 3840.0)
        self.assertEqual(target_wide.height, 2160.0)
        self.assertEqual(target_wide.zoom_factor(3840.0), 1.0)

        # Tiny face (e.g. 20px height far away): would want extreme zoom > 2.4x
        tiny_face = BoundingBox(x=1910.0, y=800.0, width=20.0, height=20.0)
        target_tight = self.engine.compute_target_window(tiny_face)
        # Cannot zoom in tighter than 2.4x (3840 / 2.4 = 1600 width)
        self.assertEqual(target_tight.width, 3840.0 / 2.4)
        self.assertEqual(target_tight.zoom_factor(3840.0), 2.4)

    def test_canvas_boundary_clamping(self):
        # Performer at far right edge of stage
        right_face = BoundingBox(x=3700.0, y=700.0, width=100.0, height=150.0)
        target = self.engine.compute_target_window(right_face)
        self.assertGreaterEqual(target.left, 0.0)
        self.assertLessEqual(target.right, 3840.0)
        self.assertGreaterEqual(target.top, 0.0)
        self.assertLessEqual(target.bottom, 2160.0)

    def test_dead_zone_suppresses_jitter(self):
        # Let framing settle on performer over 5 seconds (from 3840 wide to 1600 zoom)
        face1 = BoundingBox(x=1870.0, y=700.0, width=100.0, height=150.0)
        for i in range(1, 100):
            w1 = self.engine.update(face1, monotonic_seconds=10.0 + i * 0.05)

        # Small micro-twitch: moves only 15px in X and 10px in Y (well below 40px/30px deadzones)
        face2 = BoundingBox(x=1885.0, y=710.0, width=100.0, height=150.0)
        w2 = self.engine.update(face2, monotonic_seconds=15.05)

        # Framing center and dimensions should remain unchanged
        self.assertEqual(w1.center_x, w2.center_x)
        self.assertEqual(w1.center_y, w2.center_y)
        self.assertEqual(w1.width, w2.width)

    def test_fast_movement_rate_limited(self):
        # Performer starts at center
        face1 = BoundingBox(x=1870.0, y=700.0, width=100.0, height=150.0)
        w1 = self.engine.update(face1, monotonic_seconds=10.0)

        # Fast dash: performer leaps 1500px to the left in 0.05 seconds
        face2 = BoundingBox(x=370.0, y=700.0, width=100.0, height=150.0)
        dt = 0.05
        w2 = self.engine.update(face2, monotonic_seconds=10.0 + dt)

        # Max pan speed is 1200 px/s; in 0.05s max delta is 60 px!
        # With exponential smoothing, actual movement is <= 60 px.
        actual_delta = abs(w2.center_x - w1.center_x)
        max_allowed_delta = self.config.max_pan_speed_px_s * dt + 1.0  # slight float tolerance
        self.assertLessEqual(actual_delta, max_allowed_delta)
        # Must not have leaped to 370px!
        self.assertGreater(w2.center_x, 1500.0)

    def test_obs_crop_output(self):
        face = BoundingBox(x=1870.0, y=700.0, width=100.0, height=150.0)
        target = self.engine.compute_target_window(face)
        crops = target.to_obs_crop(3840, 2160)

        self.assertIsInstance(crops["left"], int)
        self.assertIsInstance(crops["top"], int)
        self.assertIsInstance(crops["right"], int)
        self.assertIsInstance(crops["bottom"], int)

        self.assertGreaterEqual(crops["left"], 0)
        self.assertGreaterEqual(crops["top"], 0)
        self.assertGreaterEqual(crops["right"], 0)
        self.assertGreaterEqual(crops["bottom"], 0)

        visible_w = 3840 - crops["left"] - crops["right"]
        visible_h = 2160 - crops["top"] - crops["bottom"]
        self.assertGreater(visible_w, 0)
        self.assertGreater(visible_h, 0)
        self.assertAlmostEqual(visible_w / visible_h, 16.0 / 9.0, delta=0.02)


if __name__ == "__main__":
    unittest.main()
