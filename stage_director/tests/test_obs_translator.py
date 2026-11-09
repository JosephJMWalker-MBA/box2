"""Failing regression tests for P1 Finding 3: OBS WebSocket v5 Transform Translator."""
import unittest

from stage_director.obs_transform import (
    OBSProposal,
    translate_to_obs_request,
    create_transform_backup,
    restore_transform_request,
)


class OBSTranslatorTests(unittest.TestCase):
    def test_translate_to_obs_request_schema(self):
        """Translates an internal OBSProposal into official OBS WebSocket v5 SetSceneItemTransform."""
        proposal = OBSProposal(
            schema_version="1.0",
            timestamp_utc="2026-11-09T22:00:00Z",
            monotonic_seconds=1000.0,
            mode="live",
            camera_action="track_face",
            tracking_state="tracking",
            subject_lost=False,
            source_resolution={"width": 3840, "height": 2160},
            obs_crop={"left": 1120, "top": 478, "right": 1120, "bottom": 782},
            framing={"center_x": 1920.0, "center_y": 928.0, "width": 1600, "height": 900, "zoom_factor": 2.4},
            events=[],
        )

        request = translate_to_obs_request(
            proposal=proposal,
            scene_name="PERFORMER LIVE",
            scene_item_id=42,
            canvas_width=3840,
            canvas_height=2160,
        )

        self.assertIsNotNone(request)
        self.assertEqual(request["requestType"], "SetSceneItemTransform")
        data = request["requestData"]
        self.assertEqual(data["sceneName"], "PERFORMER LIVE")
        self.assertEqual(data["sceneItemId"], 42)

        transform = data["sceneItemTransform"]
        # Official OBS WebSocket v5 field names (camelCase)
        self.assertEqual(transform["cropLeft"], 1120)
        self.assertEqual(transform["cropTop"], 478)
        self.assertEqual(transform["cropRight"], 1120)
        self.assertEqual(transform["cropBottom"], 782)
        self.assertEqual(transform["positionX"], 0.0)
        self.assertEqual(transform["positionY"], 0.0)
        self.assertEqual(transform["alignment"], 5)  # OBS_ALIGN_TOP | OBS_ALIGN_LEFT
        self.assertEqual(transform["boundsType"], "OBS_BOUNDS_SCALE_INNER")
        self.assertEqual(transform["boundsWidth"], 3840.0)
        self.assertEqual(transform["boundsHeight"], 2160.0)
        # Default strategy (bounds_inner) leaves scale at 1.0; OBS bounds handles scaling
        self.assertEqual(transform["scaleX"], 1.0)
        self.assertEqual(transform["scaleY"], 1.0)

        # Combined strategy explicitly sets scale factors
        req_comb = translate_to_obs_request(
            proposal=proposal,
            scene_name="PERFORMER LIVE",
            scene_item_id=42,
            canvas_width=3840,
            canvas_height=2160,
            strategy="combined",
        )
        assert req_comb is not None
        trans_comb = req_comb["requestData"]["sceneItemTransform"]
        self.assertAlmostEqual(trans_comb["scaleX"], 2.4, places=2)
        self.assertAlmostEqual(trans_comb["scaleY"], 2.4, places=2)

        # Explicit scale strategy sets OBS_BOUNDS_NONE
        req_exp = translate_to_obs_request(
            proposal=proposal,
            scene_name="PERFORMER LIVE",
            scene_item_id=42,
            canvas_width=3840,
            canvas_height=2160,
            strategy="explicit_scale",
        )
        assert req_exp is not None
        trans_exp = req_exp["requestData"]["sceneItemTransform"]
        self.assertEqual(trans_exp["boundsType"], "OBS_BOUNDS_NONE")
        self.assertAlmostEqual(trans_exp["scaleX"], 2.4, places=2)

    def test_backup_and_restore(self):
        """Transform backup and restore request creation."""
        original = {
            "cropLeft": 0, "cropTop": 0, "cropRight": 0, "cropBottom": 0,
            "positionX": 100.0, "positionY": 50.0, "scaleX": 1.0, "scaleY": 1.0,
            "boundsType": "OBS_BOUNDS_NONE", "boundsWidth": 0.0, "boundsHeight": 0.0,
            "alignment": 5, "rotation": 0.0,
        }
        backup = create_transform_backup(original)
        restore_req = restore_transform_request("PERFORMER LIVE", 42, backup)
        self.assertEqual(restore_req["requestType"], "SetSceneItemTransform")
        self.assertEqual(restore_req["requestData"]["sceneItemTransform"]["positionX"], 100.0)

    def test_invalid_strategy_rejected(self):
        """translate_to_obs_request must raise ValueError on unknown strategies."""
        proposal = OBSProposal(
            schema_version="1.0",
            timestamp_utc="2026-11-09T22:00:00Z",
            monotonic_seconds=1000.0,
            mode="live",
            camera_action="track_face",
            tracking_state="tracking",
            subject_lost=False,
            source_resolution={"width": 3840, "height": 2160},
            obs_crop={"left": 100, "top": 100, "right": 100, "bottom": 100},
            framing={"center_x": 1920.0, "center_y": 1080.0, "width": 3640, "height": 1960, "zoom_factor": 1.05},
            events=[],
        )
        with self.assertRaises(ValueError) as ctx:
            translate_to_obs_request(proposal, "TestScene", 1, strategy="unknown_strategy")
        self.assertIn("Invalid strategy", str(ctx.exception))

    def test_invalid_crop_dimensions_rejected(self):
        """translate_to_obs_request must reject non-finite, negative, or excessive crops."""
        base_kwargs = dict(
            schema_version="1.0",
            timestamp_utc="2026-11-09T22:00:00Z",
            monotonic_seconds=1000.0,
            mode="live",
            camera_action="track_face",
            tracking_state="tracking",
            subject_lost=False,
            source_resolution={"width": 3840, "height": 2160},
            framing={},
            events=[],
        )

        # Negative crop
        prop_neg = OBSProposal(obs_crop={"left": -10, "top": 0, "right": 0, "bottom": 0}, **base_kwargs)
        with self.assertRaises(ValueError):
            translate_to_obs_request(prop_neg, "TestScene", 1)

        # NaN crop
        prop_nan = OBSProposal(obs_crop={"left": float("nan"), "top": 0, "right": 0, "bottom": 0}, **base_kwargs)
        with self.assertRaises(ValueError):
            translate_to_obs_request(prop_nan, "TestScene", 1)

        # Crop exceeding source width
        prop_excess_w = OBSProposal(obs_crop={"left": 2000, "top": 0, "right": 2000, "bottom": 0}, **base_kwargs)
        with self.assertRaises(ValueError):
            translate_to_obs_request(prop_excess_w, "TestScene", 1, source_width=3840, source_height=2160)

        # Crop exceeding source height
        prop_excess_h = OBSProposal(obs_crop={"left": 0, "top": 1200, "right": 0, "bottom": 1200}, **base_kwargs)
        with self.assertRaises(ValueError):
            translate_to_obs_request(prop_excess_h, "TestScene", 1, source_width=3840, source_height=2160)

    def test_invalid_canvas_and_source_dimensions_rejected(self):
        """translate_to_obs_request must reject zero, negative, or non-finite canvas/source dims."""
        proposal = OBSProposal(
            schema_version="1.0",
            timestamp_utc="2026-11-09T22:00:00Z",
            monotonic_seconds=1000.0,
            mode="live",
            camera_action="track_face",
            tracking_state="tracking",
            subject_lost=False,
            source_resolution={"width": 3840, "height": 2160},
            obs_crop={"left": 100, "top": 100, "right": 100, "bottom": 100},
            framing={},
            events=[],
        )
        with self.assertRaises(ValueError):
            translate_to_obs_request(proposal, "TestScene", 1, canvas_width=0)
        with self.assertRaises(ValueError):
            translate_to_obs_request(proposal, "TestScene", 1, canvas_height=-1080)
        with self.assertRaises(ValueError):
            translate_to_obs_request(proposal, "TestScene", 1, source_width=float("inf"))



if __name__ == "__main__":
    unittest.main()
