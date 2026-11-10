"""Standalone fixture validator for OBS WebSocket v5 SetSceneItemTransform requests.

Validates:
  - Official OBS WebSocket v5 schema compatibility (camelCase fields, sceneItemTransform).
  - Crop-to-scale calculations ensuring the cropped region fills the canvas.
  - 16:9 aspect ratio integrity across wide, medium, and boundary camera positions.
  - Safe-stop handling (capture_off translates to None).

Offline only; no network or live OBS WebSocket connections.
Run: python3 -m stage_director.obs_request_fixture
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from .geometry import BoundingBox
from .framing import FramingConfig, FramingEngine
from .obs_transform import (
    OBSProposal,
    OBSSceneItemTransform,
    translate_to_obs_request,
    create_transform_backup,
    restore_transform_request,
)


def validate_obs_transform_request(
    request: Dict[str, Any],
    canvas_width: int = 3840,
    canvas_height: int = 2160,
) -> Tuple[bool, List[str]]:
    """Validate that an OBS WebSocket request strictly matches official v5 specs."""
    errors: List[str] = []

    if request.get("requestType") != "SetSceneItemTransform":
        errors.append(f"Expected requestType 'SetSceneItemTransform', got {request.get('requestType')}")

    data = request.get("requestData", {})
    if not data.get("sceneName"):
        errors.append("Missing sceneName in requestData")
    if not isinstance(data.get("sceneItemId"), int):
        errors.append(f"sceneItemId must be integer, got {data.get('sceneItemId')}")

    transform = data.get("sceneItemTransform", {})
    required_keys = (
        "cropLeft", "cropTop", "cropRight", "cropBottom",
        "positionX", "positionY", "scaleX", "scaleY",
        "alignment", "boundsType", "boundsWidth", "boundsHeight",
    )
    for key in required_keys:
        if key not in transform:
            errors.append(f"Missing required transform field: {key}")

    # Integer crops
    for crop_key in ("cropLeft", "cropTop", "cropRight", "cropBottom"):
        val = transform.get(crop_key)
        if not isinstance(val, int) or val < 0:
            errors.append(f"{crop_key} must be a non-negative integer, got {val}")

    crop_l = transform.get("cropLeft", 0)
    crop_r = transform.get("cropRight", 0)
    crop_t = transform.get("cropTop", 0)
    crop_b = transform.get("cropBottom", 0)

    vis_w = canvas_width - crop_l - crop_r
    vis_h = canvas_height - crop_t - crop_b

    if vis_w <= 0 or vis_h <= 0:
        errors.append(f"Crops exceed source dimensions: vis_w={vis_w}, vis_h={vis_h}")
    else:
        # Check aspect ratio of visible area
        aspect = vis_w / vis_h
        if abs(aspect - (16.0 / 9.0)) > 0.05:
            errors.append(f"Visible aspect ratio {aspect:.4f} diverges from 16:9")

        # Check that bounds or scaling fills canvas
        bounds_type = transform.get("boundsType", "OBS_BOUNDS_NONE")
        if bounds_type == "OBS_BOUNDS_SCALE_INNER":
            bounds_w = transform.get("boundsWidth", 0.0)
            bounds_h = transform.get("boundsHeight", 0.0)
            if abs(bounds_w - canvas_width) > 2.0:
                errors.append(f"Bounds width {bounds_w:.1f} does not match canvas {canvas_width}")
            if abs(bounds_h - canvas_height) > 2.0:
                errors.append(f"Bounds height {bounds_h:.1f} does not match canvas {canvas_height}")
        else:
            scale_x = transform.get("scaleX", 1.0)
            scale_y = transform.get("scaleY", 1.0)
            scaled_w = vis_w * scale_x
            scaled_h = vis_h * scale_y

            if abs(scaled_w - canvas_width) > 2.0:
                errors.append(f"Scaled width {scaled_w:.1f} does not fill canvas {canvas_width}")
            if abs(scaled_h - canvas_height) > 2.0:
                errors.append(f"Scaled height {scaled_h:.1f} does not fill canvas {canvas_height}")

    return (len(errors) == 0, errors)


def run_fixtures() -> bool:
    """Generate and validate fixtures for wide, medium, boundary, and stop states."""
    config = FramingConfig()
    engine = FramingEngine(config)
    all_ok = True

    fixtures: List[Tuple[str, Optional[BoundingBox]]] = [
        ("stage_wide_full_frame", None),
        ("center_medium_shot", BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)),
        ("stage_left_boundary", BoundingBox(x=450.0, y=700.0, width=120.0, height=150.0)),
        ("stage_right_boundary", BoundingBox(x=3250.0, y=700.0, width=120.0, height=150.0)),
        ("stage_top_headroom_boundary", BoundingBox(x=1860.0, y=250.0, width=120.0, height=150.0)),
    ]

    print("=== OBS WEBSOCKET v5 TRANSFORM FIXTURE VALIDATOR ===")
    print("Canvas: 3840x2160 (4K 16:9) | Offline Schema Check")
    print()

    for name, face_box in fixtures:
        engine.reset(monotonic_seconds=10.0)
        # Settle framing towards target over several steps
        for step in range(1, 40):
            window = engine.update(face_box, monotonic_seconds=10.0 + step * 0.1)

        action = "stage_wide" if face_box is None else "track_face"
        proposal = OBSProposal(
            schema_version="1.0",
            timestamp_utc="2026-11-09T22:00:00Z",
            monotonic_seconds=14.0,
            mode="live",
            camera_action=action,
            tracking_state="stage_wide" if face_box is None else "tracking",
            subject_lost=False,
            source_resolution={"width": 3840, "height": 2160},
            obs_crop=window.to_obs_crop(3840, 2160),
            framing=window.to_dict(3840),
            events=[],
        )

        obs_req = translate_to_obs_request(
            proposal=proposal,
            scene_name="PERFORMER LIVE",
            scene_item_id=10,
            canvas_width=3840,
            canvas_height=2160,
        )

        assert obs_req is not None
        valid, errors = validate_obs_transform_request(obs_req, 3840, 2160)
        status = "PASS" if valid else "FAIL"
        if not valid:
            all_ok = False

        crop = obs_req["requestData"]["sceneItemTransform"]
        print(f"[{status}] Fixture: {name}")
        print(f"  crop: Left={crop['cropLeft']}, Top={crop['cropTop']}, Right={crop['cropRight']}, Bottom={crop['cropBottom']}")
        print(f"  scale: ({crop['scaleX']}, {crop['scaleY']}) | bounds: {crop['boundsWidth']}x{crop['boundsHeight']} ({crop['boundsType']})")
        if errors:
            for err in errors:
                print(f"  ERROR: {err}")
        print()

    # Capture OFF fixture (must translate to None, preventing inadvertent broadcast/framing)
    off_proposal = OBSProposal(
        schema_version="1.0",
        timestamp_utc="2026-11-09T22:00:00Z",
        monotonic_seconds=15.0,
        mode="off",
        camera_action="capture_off",
        tracking_state="disabled",
        subject_lost=False,
        source_resolution={"width": 3840, "height": 2160},
        obs_crop=None,
        framing=None,
        events=["camera_auto_disabled"],
    )
    off_req = translate_to_obs_request(off_proposal, "PERFORMER LIVE", 10)
    if off_req is None:
        print("[PASS] Fixture: capture_off_returns_none (verified fail-closed)")
    else:
        print("[FAIL] Fixture: capture_off did not return None!")
        all_ok = False

    # Backup & restore test
    original_sample = {
        "cropLeft": 0, "cropTop": 0, "cropRight": 0, "cropBottom": 0,
        "positionX": 0.0, "positionY": 0.0, "scaleX": 1.0, "scaleY": 1.0,
        "boundsType": "OBS_BOUNDS_NONE", "boundsWidth": 0.0, "boundsHeight": 0.0,
        "alignment": 5,
    }
    backup = create_transform_backup(original_sample)
    restore_req = restore_transform_request("PERFORMER LIVE", 10, backup)
    if restore_req.get("requestData", {}).get("sceneItemTransform") == original_sample:
        print("[PASS] Fixture: backup_and_restore_fidelity")
    else:
        print("[FAIL] Fixture: backup and restore fidelity mismatch")
        all_ok = False

    print()
    print(f"Validation complete: {'ALL FIXTURES PASSED' if all_ok else 'FIXTURE FAILURES DETECTED'}")
    return all_ok


if __name__ == "__main__":
    success = run_fixtures()
    exit(0 if success else 1)
