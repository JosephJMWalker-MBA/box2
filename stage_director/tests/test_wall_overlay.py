"""Unit tests for WallOverlay subtle painted branding and dynamic fading."""
import json
import os
import tempfile
import unittest

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

try:
    from tools.jetson.box2_stream import WallOverlay
except ImportError:
    try:
        import sys
        sys.path.insert(0, "/home/joseph1/box2-stream")
        from box2_stream import WallOverlay
    except ImportError:
        WallOverlay = None

if WallOverlay is None:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "OpenCV, NumPy, and PIL required for WallOverlay tests")
class WallOverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmp_dir.name, "ticker.json")
        with open(self.config_path, "w") as f:
            json.dump({
                "title": "BOX 2",
                "wall_overlay": {
                    "enabled": True,
                    "lines": ["PARKING LOT", "CENTER"],
                    "x": 210,
                    "y": 170,
                    "font_size": 32,
                    "letter_spacing": 6,
                    "max_opacity": 0.55,
                    "fade_speed": 0.10,
                    "color": [220, 222, 225],
                    "style": "stacked",
                }
            }, f)
        self.overlay = WallOverlay(config_path=self.config_path, base_w=1280, base_h=720)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_initialization_and_precomputation(self):
        self.assertTrue(self.overlay.enabled)
        self.assertEqual(self.overlay.lines, ["PARKING LOT", "CENTER"])
        self.assertEqual(self.overlay.max_opacity, 0.55)
        self.assertIsNotNone(self.overlay.alpha_mask_roi)
        self.assertIsNotNone(self.overlay.color_bgr)
        self.assertGreater(self.overlay.roi_x2, self.overlay.roi_x1)
        self.assertGreater(self.overlay.roi_y2, self.overlay.roi_y1)

    def test_fade_out_when_performer_framed(self):
        # Start at max opacity on empty stage
        self.overlay.current_opacity = 0.55
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        
        # When performer is framed, opacity fades toward 0
        for _ in range(6):
            self.overlay.draw(frame, is_performer_framed=True)
            
        self.assertLess(self.overlay.current_opacity, 0.05)
        self.assertGreaterEqual(self.overlay.current_opacity, 0.0)

    def test_fade_in_when_stage_empty(self):
        # Start at 0 opacity (performer just left)
        self.overlay.current_opacity = 0.0
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        
        # When performer leaves, opacity fades back in to max_opacity
        for _ in range(7):
            self.overlay.draw(frame, is_performer_framed=False)
            
        self.assertAlmostEqual(self.overlay.current_opacity, 0.55, places=2)

    def test_blending_affects_roi_and_preserves_black_background(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.overlay.current_opacity = 0.55
        self.overlay.draw(frame, is_performer_framed=False)
        
        # Inside ROI, some pixels should now have color
        roi = frame[self.overlay.roi_y1:self.overlay.roi_y2, self.overlay.roi_x1:self.overlay.roi_x2]
        self.assertGreater(roi.max(), 50)
        
        # Outside ROI, frame should remain untouched
        outside = frame[0:100, 0:100]
        self.assertEqual(outside.max(), 0)

    def test_hot_reload_config(self):
        # Update config to disable overlay
        with open(self.config_path, "w") as f:
            json.dump({
                "title": "BOX 2",
                "wall_overlay": {
                    "enabled": False,
                }
            }, f)
        self.overlay.last_check = 0  # force check interval
        self.overlay.reload_if_needed(force=True)
        self.assertFalse(self.overlay.enabled)


if __name__ == "__main__":
    unittest.main()
