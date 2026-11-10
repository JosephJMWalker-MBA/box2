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
        from stage_director.obs_disposable_env import get_production_obs_config_dir

        with tempfile.TemporaryDirectory() as prod_dir, tempfile.TemporaryDirectory() as test_dir:
            # Seed mock production Diag.json
            mock_scenes = os.path.join(prod_dir, "basic", "scenes")
            os.makedirs(mock_scenes, exist_ok=True)
            mock_diag = os.path.join(mock_scenes, "Diag.json")
            with open(mock_diag, "w", encoding="utf-8") as f:
                json.dump({"name": "Diag", "sources": []}, f)

            # Setup in dedicated isolated test_dir
            paths = setup_disposable_obs_environment(base_dir=test_dir)
            self.assertTrue(os.path.exists(paths["profile_ini"]))
            self.assertTrue(os.path.exists(paths["scene_json"]))

            # Verify production dir was completely untouched
            ok, issues = verify_production_isolation(obs_dir=prod_dir)
            self.assertTrue(ok, f"Production isolation violated: {issues}")

            with open(mock_diag, "r", encoding="utf-8") as f:
                d = json.load(f)
                self.assertEqual(d["name"], "Diag")

            # Verify safety guard blocks writing to production root
            with self.assertRaises(RuntimeError):
                setup_disposable_obs_environment(base_dir=get_production_obs_config_dir())

            # Verify safety guard blocks writing to subdirectories of production root
            with self.assertRaises(RuntimeError):
                setup_disposable_obs_environment(
                    base_dir=os.path.join(get_production_obs_config_dir(), "basic", "scenes")
                )

    def test_production_symlink_escape_blocked(self):
        """Symlinks pointing into production OBS directories must be rejected by realpath guard."""
        from stage_director.obs_disposable_env import get_production_obs_config_dir
        with tempfile.TemporaryDirectory() as temp_dir:
            symlink_to_prod = os.path.join(temp_dir, "fake_obs_link")
            try:
                os.symlink(get_production_obs_config_dir(), symlink_to_prod)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks not supported in this environment")

            with self.assertRaises(RuntimeError):
                setup_disposable_obs_environment(base_dir=symlink_to_prod)

    def test_overwrite_safeguard_fails_if_either_target_exists(self):
        """setup_disposable_obs_environment must fail before writes if either test file exists when overwrite=False."""
        from stage_director.obs_disposable_env import (
            DISPOSABLE_PROFILE_NAME,
            DISPOSABLE_SCENE_COLLECTION_NAME,
        )

        with tempfile.TemporaryDirectory() as test_dir:
            profiles_dir = os.path.join(test_dir, "basic", "profiles", DISPOSABLE_PROFILE_NAME)
            scenes_dir = os.path.join(test_dir, "basic", "scenes")
            profile_ini_path = os.path.join(profiles_dir, "basic.ini")
            scene_json_path = os.path.join(scenes_dir, f"{DISPOSABLE_SCENE_COLLECTION_NAME}.json")

            # Case 1: Only profile_ini exists
            os.makedirs(profiles_dir, exist_ok=True)
            with open(profile_ini_path, "w") as f:
                f.write("existing profile content")

            with self.assertRaises(FileExistsError):
                setup_disposable_obs_environment(base_dir=test_dir, overwrite=False)
            # Verify scene_json was NOT written
            self.assertFalse(os.path.exists(scene_json_path))

            # Case 2: Only scene_json exists
            os.remove(profile_ini_path)
            os.makedirs(scenes_dir, exist_ok=True)
            with open(scene_json_path, "w") as f:
                f.write("{}")

            with self.assertRaises(FileExistsError):
                setup_disposable_obs_environment(base_dir=test_dir, overwrite=False)
            # Verify profile_ini was NOT written
            self.assertFalse(os.path.exists(profile_ini_path))

            # Case 3: Overwrite=True succeeds and replaces both
            paths = setup_disposable_obs_environment(base_dir=test_dir, overwrite=True)
            self.assertTrue(os.path.exists(paths["profile_ini"]))
            self.assertTrue(os.path.exists(paths["scene_json"]))
            with open(paths["profile_ini"], "r") as f:
                self.assertIn("[General]", f.read())


if __name__ == "__main__":
    unittest.main()
