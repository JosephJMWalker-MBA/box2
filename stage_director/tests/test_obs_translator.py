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
        # Scaled to fill output canvas
        self.assertAlmostEqual(transform["scaleX"], 2.4, places=2)
        self.assertAlmostEqual(transform["scaleY"], 2.4, places=2)

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


if __name__ == "__main__":
    unittest.main()
