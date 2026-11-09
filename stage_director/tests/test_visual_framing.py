"""Automated unit and regression tests for Milestone 4: Visual Framing and OBS Transform Strategies."""
import json
import os
import tempfile
import unittest

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from stage_director.geometry import BoundingBox
from stage_director.framing import FramingConfig, FramingEngine
from stage_director.obs_transform import (
    OBSProposal,
    translate_to_obs_request,
    create_transform_backup,
    restore_transform_request,
)
from stage_director.obs_disposable_env import (
    setup_disposable_obs_environment,
    verify_production_isolation,
)


@unittest.skipUnless(HAS_PIL, "Pillow required for visual framing image tests")
class VisualFramingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_PIL:
            return
        from stage_director.test_pattern import generate_synthetic_stage_test_pattern
        cls.fixtures_dir = "stage_director/fixtures"
        os.makedirs(cls.fixtures_dir, exist_ok=True)
        cls.pattern_path = os.path.join(cls.fixtures_dir, "synthetic_stage_4k.png")
        if not os.path.exists(cls.pattern_path):
            generate_synthetic_stage_test_pattern(output_path=cls.pattern_path)

    def test_synthetic_4k_test_pattern_attributes(self):
        """Synthetic test pattern must be exact 3840x2160 native 16:9 RGB PNG."""
        with Image.open(self.pattern_path) as im:
            self.assertEqual(im.size, (3840, 2160))
            self.assertEqual(im.mode, "RGB")
            aspect = im.size[0] / im.size[1]
            self.assertAlmostEqual(aspect, 16.0 / 9.0, places=4)

    def test_transform_strategy_comparison(self):
        """Test and compare Strategies A, B, and C against a 1920x1080 canvas."""
        from stage_director.visual_test_harness import run_visual_comparison
        res = run_visual_comparison(fixtures_dir=self.fixtures_dir, canvas_w=1920, canvas_h=1080)

        # 1. Canvas dimensions
        self.assertEqual(res["source_resolution"], (3840, 2160))
        self.assertEqual(res["canvas_resolution"], (1920, 1080))

        # 2. Strategy A (Bounds Inner, Crop Only)
        strat_a = res["strategies"]["strategy_a"]
        self.assertEqual(strat_a["boundsType"], "OBS_BOUNDS_SCALE_INNER")
        self.assertEqual(strat_a["drawn_size"], (1920, 1080))
        self.assertEqual(strat_a["canvas_fill_percent"], 100.0)
        self.assertFalse(strat_a["letterboxed_or_clipped"])
        self.assertAlmostEqual(strat_a["aspect_ratio"], 16.0 / 9.0, places=3)
        self.assertEqual(strat_a["input_scale"], (1.0, 1.0))  # Scale is clean 1.0; libobs handles scaling

        # 3. Strategy B (Explicit Scale, No Bounds)
        strat_b = res["strategies"]["strategy_b"]
        self.assertEqual(strat_b["boundsType"], "OBS_BOUNDS_NONE")
        self.assertEqual(strat_b["drawn_size"], (1920, 1080))
        self.assertEqual(strat_b["canvas_fill_percent"], 100.0)
        self.assertFalse(strat_b["letterboxed_or_clipped"])

        # 4. Strategy C (Combined Scale + Bounds)
        strat_c = res["strategies"]["strategy_c"]
        self.assertEqual(strat_c["boundsType"], "OBS_BOUNDS_SCALE_INNER")
        self.assertEqual(strat_c["drawn_size"], (1920, 1080))
        self.assertEqual(strat_c["canvas_fill_percent"], 100.0)
        self.assertFalse(strat_c["letterboxed_or_clipped"])

        # 5. Rollback fidelity: restoring transform must restore bit-for-bit exact wide frame
        self.assertTrue(res["rollback_verified_exact"], "Rollback did not produce bit-for-bit identical image")

        # 6. Performer Centering: Performer center error on 1080p canvas must be within 1.0 pixel
        framing_eval = res["performer_framing_evaluation"]
        self.assertLess(abs(framing_eval["center_error_px"]), 1.0)


class DisposableOBSEnvironmentTests(unittest.TestCase):
    def test_disposable_obs_environment_isolation(self):
        """Disposable profile/collection creation must never modify live production Diag.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Seed mock production Diag.json
            mock_scenes = os.path.join(tmpdir, "basic", "scenes")
            os.makedirs(mock_scenes, exist_ok=True)
            mock_diag = os.path.join(mock_scenes, "Diag.json")
            with open(mock_diag, "w", encoding="utf-8") as f:
                json.dump({"name": "Diag", "sources": []}, f)

            paths = setup_disposable_obs_environment(base_dir=tmpdir)
            self.assertTrue(os.path.exists(paths["profile_ini"]))
            self.assertTrue(os.path.exists(paths["scene_json"]))

            ok, issues = verify_production_isolation(obs_dir=tmpdir)
            self.assertTrue(ok, f"Production isolation violated: {issues}")

            # Verify Diag.json was not modified
            with open(mock_diag, "r", encoding="utf-8") as f:
                d = json.load(f)
                self.assertEqual(d["name"], "Diag")


if __name__ == "__main__":
    unittest.main()
