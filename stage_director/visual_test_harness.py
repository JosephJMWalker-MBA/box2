"""Isolated Visual Framing Test Harness for Stage Director.

Simulates the libobs compositor and transform pipeline at 1920x1080 canvas resolution
using synthetic 4K (3840x2160) calibration imagery. Evaluates and compares:
  Strategy (a): bounds SCALE_INNER with crop only (scale = 1.0)
  Strategy (b): explicit scale with bounds NONE
  Strategy (c): combined scale + bounds SCALE_INNER

Measures:
  - 16:9 canvas coverage (fill %)
  - Aspect ratio preservation (circle eccentricity and aspect ratio error)
  - Performer centering and headroom placement (33% guideline)
  - Rollback fidelity after transform restoration
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageChops

from .geometry import BoundingBox
from .framing import FramingConfig, FramingEngine
from .obs_transform import (
    OBSProposal,
    OBSSceneItemTransform,
    translate_to_obs_request,
    create_transform_backup,
    restore_transform_request,
)
from .test_pattern import generate_synthetic_stage_test_pattern


class VisualFramingRenderer:
    """Simulates libobs scene-item transform calculations and renders to a canvas."""

    def __init__(self, source_image_path: str, canvas_width: int = 1920, canvas_height: int = 1080):
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.source_image_path = source_image_path

        if not os.path.exists(source_image_path):
            generate_synthetic_stage_test_pattern(output_path=source_image_path)

        self.source_image = Image.open(source_image_path).convert("RGB")
        self.src_width, self.src_height = self.source_image.size

    def render_transform(
        self,
        transform: Dict[str, Any],
        strategy_label: str = "custom",
    ) -> Tuple[Image.Image, Dict[str, Any]]:
        """Simulate libobs item rendering given an OBS transform dictionary.

        Follows libobs/obs-scene.c calculate_bounds_data and matrix4_scale3f logic.
        """
        crop_l = int(transform.get("cropLeft", 0))
        crop_t = int(transform.get("cropTop", 0))
        crop_r = int(transform.get("cropRight", 0))
        crop_b = int(transform.get("cropBottom", 0))

        vis_w = max(2, self.src_width - crop_l - crop_r)
        vis_h = max(2, self.src_height - crop_t - crop_b)

        # 1. Crop source region
        cropped = self.source_image.crop((crop_l, crop_t, crop_l + vis_w, crop_t + vis_h))

        # 2. Compute libobs scale and output dimensions
        bounds_type = transform.get("boundsType", "OBS_BOUNDS_NONE")
        scale_x = float(transform.get("scaleX", 1.0))
        scale_y = float(transform.get("scaleY", 1.0))
        bounds_w = float(transform.get("boundsWidth", 0.0))
        bounds_h = float(transform.get("boundsHeight", 0.0))

        if bounds_type == "OBS_BOUNDS_SCALE_INNER" and bounds_w > 0 and bounds_h > 0:
            # libobs/obs-scene.c lines 455-475
            width = float(vis_w) * abs(scale_x)
            height = float(vis_h) * abs(scale_y)
            item_aspect = width / height
            bounds_aspect = bounds_w / bounds_h
            use_width = (bounds_aspect < item_aspect)
            mul = (bounds_w / width) if use_width else (bounds_h / height)
            effective_scale_x = scale_x * mul
            effective_scale_y = scale_y * mul
        else:
            # OBS_BOUNDS_NONE: use scale directly (obs-scene.c line 651)
            effective_scale_x = scale_x
            effective_scale_y = scale_y

        draw_w = int(round(vis_w * effective_scale_x))
        draw_h = int(round(vis_h * effective_scale_y))

        # 3. Resample cropped source using bicubic interpolation (matching libobs)
        resampled = cropped.resize((max(1, draw_w), max(1, draw_h)), Image.Resampling.BICUBIC)

        # 4. Composite onto canvas
        canvas = Image.new("RGB", (self.canvas_width, self.canvas_height), color=(0, 0, 0))
        pos_x = int(round(float(transform.get("positionX", 0.0))))
        pos_y = int(round(float(transform.get("positionY", 0.0))))
        canvas.paste(resampled, (pos_x, pos_y))

        # 5. Calculate validation metrics
        aspect_ratio = draw_w / max(1.0, float(draw_h))
        target_aspect = self.canvas_width / float(self.canvas_height)
        aspect_error = abs(aspect_ratio - target_aspect) / target_aspect
        canvas_coverage = (min(draw_w, self.canvas_width) * min(draw_h, self.canvas_height)) / float(self.canvas_width * self.canvas_height)

        metrics = {
            "strategy": strategy_label,
            "boundsType": bounds_type,
            "crop": {"left": crop_l, "top": crop_t, "right": crop_r, "bottom": crop_b},
            "visible_size": (vis_w, vis_h),
            "input_scale": (scale_x, scale_y),
            "effective_scale": (effective_scale_x, effective_scale_y),
            "drawn_size": (draw_w, draw_h),
            "canvas_fill_percent": round(canvas_coverage * 100.0, 3),
            "aspect_ratio": round(aspect_ratio, 5),
            "aspect_error_percent": round(aspect_error * 100.0, 4),
            "letterboxed_or_clipped": (draw_w != self.canvas_width or draw_h != self.canvas_height),
        }

        return canvas, metrics


def run_visual_comparison(
    fixtures_dir: str = "stage_director/fixtures",
    canvas_w: int = 1920,
    canvas_h: int = 1080,
) -> Dict[str, Any]:
    """Execute visual framing tests across Strategies A, B, and C and record metrics."""
    os.makedirs(fixtures_dir, exist_ok=True)
    pattern_path = os.path.join(fixtures_dir, "synthetic_stage_4k.png")
    renderer = VisualFramingRenderer(pattern_path, canvas_width=canvas_w, canvas_height=canvas_h)

    # 1. Base Framing Engine setup (4K native source, 16:9)
    config = FramingConfig(canvas_width=3840, canvas_height=2160)
    engine = FramingEngine(config)

    # Performer center target: Face x=1800, y=750, w=240, h=300 (Center: 1920, 900)
    face_target = BoundingBox(x=1800.0, y=750.0, width=240.0, height=300.0)

    # Proposals:
    # A. Initial Safe-Wide (zoom = 1.0)
    wide_prop = OBSProposal(
        schema_version="1.0",
        timestamp_utc="2026-11-09T22:00:00Z",
        monotonic_seconds=0.0,
        mode="armed",
        camera_action="stage_wide",
        tracking_state="disabled",
        subject_lost=False,
        source_resolution={"width": 3840, "height": 2160},
        obs_crop={"left": 0, "top": 0, "right": 0, "bottom": 0},
        framing={"center_x": 1920.0, "center_y": 1080.0, "width": 3840, "height": 2160, "zoom_factor": 1.0},
        events=[],
    )
    # B. Active Medium Shot (zoom target)
    target_win = engine.compute_target_window(face_target)
    med_crop = target_win.to_obs_crop(3840, 2160)
    med_prop = OBSProposal(
        schema_version="1.0",
        timestamp_utc="2026-11-09T22:00:05Z",
        monotonic_seconds=5.0,
        mode="live",
        camera_action="track_face",
        tracking_state="tracking",
        subject_lost=False,
        source_resolution={"width": 3840, "height": 2160},
        obs_crop=med_crop,
        framing=target_win.to_dict(3840),
        events=[],
    )

    results: Dict[str, Any] = {
        "source_resolution": (renderer.src_width, renderer.src_height),
        "canvas_resolution": (canvas_w, canvas_h),
        "strategies": {},
    }

    # 2. Render Initial Safe-Wide Full Frame
    req_wide = translate_to_obs_request(wide_prop, "Test Scene", 1, canvas_w, canvas_h, strategy="combined")
    assert req_wide is not None
    backup_transform = create_transform_backup(req_wide["requestData"]["sceneItemTransform"])
    wide_img, wide_metrics = renderer.render_transform(backup_transform, strategy_label="wide_reference")
    wide_img_path = os.path.join(fixtures_dir, "rendered_stage_wide_1080p.png")
    wide_img.save(wide_img_path)
    results["strategies"]["wide_reference"] = wide_metrics

    # 3. Strategy (a): bounds SCALE_INNER with crop only (scale = 1.0, 1.0)
    req_a = translate_to_obs_request(med_prop, "Test Scene", 1, canvas_w, canvas_h, strategy="bounds_inner")
    assert req_a is not None
    trans_a = req_a["requestData"]["sceneItemTransform"]
    img_a, metrics_a = renderer.render_transform(trans_a, strategy_label="Strategy A (Bounds Inner, Crop Only)")
    img_a_path = os.path.join(fixtures_dir, "rendered_medium_shot_strategy_a_1080p.png")
    img_a.save(img_a_path)
    results["strategies"]["strategy_a"] = metrics_a

    # 4. Strategy (b): explicit scale with bounds NONE
    req_b = translate_to_obs_request(med_prop, "Test Scene", 1, canvas_w, canvas_h, strategy="explicit_scale")
    assert req_b is not None
    trans_b = req_b["requestData"]["sceneItemTransform"]
    img_b, metrics_b = renderer.render_transform(trans_b, strategy_label="Strategy B (Explicit Scale, No Bounds)")
    img_b_path = os.path.join(fixtures_dir, "rendered_medium_shot_strategy_b_1080p.png")
    img_b.save(img_b_path)
    results["strategies"]["strategy_b"] = metrics_b

    # 5. Strategy (c): combined scale + bounds SCALE_INNER
    req_c = translate_to_obs_request(med_prop, "Test Scene", 1, canvas_w, canvas_h, strategy="combined")
    assert req_c is not None
    trans_c = req_c["requestData"]["sceneItemTransform"]
    img_c, metrics_c = renderer.render_transform(trans_c, strategy_label="Strategy C (Combined Scale + Bounds)")
    img_c_path = os.path.join(fixtures_dir, "rendered_medium_shot_strategy_c_1080p.png")
    img_c.save(img_c_path)
    results["strategies"]["strategy_c"] = metrics_c

    # 6. Test Rollback Restoration: restore the original backup transform
    restore_req = restore_transform_request("Test Scene", 1, backup_transform)
    restored_trans = restore_req["requestData"]["sceneItemTransform"]
    restored_img, restored_metrics = renderer.render_transform(restored_trans, strategy_label="restored_rollback")
    restored_img_path = os.path.join(fixtures_dir, "rendered_restored_wide_1080p.png")
    restored_img.save(restored_img_path)
    results["strategies"]["restored_rollback"] = restored_metrics

    # 7. Rollback pixel fidelity comparison
    diff = ImageChops.difference(wide_img, restored_img)
    diff_bbox = diff.getbbox()
    rollback_identical = (diff_bbox is None)
    results["rollback_verified_exact"] = rollback_identical

    # 8. Measure performer framing on Strategy A:
    # Target headroom in OBS canvas (33% from top): 1080 * 0.3333 = 360px
    # Target center in OBS canvas: 1920 / 2 = 960px
    vis_w = metrics_a["visible_size"][0]
    eff_scale = metrics_a["effective_scale"][0]
    face_top_crop_rel = (face_target.y - metrics_a["crop"]["top"])
    face_cx_crop_rel = (face_target.center[0] - metrics_a["crop"]["left"])

    rendered_face_top = face_top_crop_rel * eff_scale
    rendered_face_cx = face_cx_crop_rel * eff_scale

    target_headroom_y = canvas_h * (1.0 / 3.0)
    target_center_x = canvas_w / 2.0

    headroom_error_px = round(rendered_face_top - target_headroom_y, 2)
    center_error_px = round(rendered_face_cx - target_center_x, 2)

    results["performer_framing_evaluation"] = {
        "rendered_face_top_y": round(rendered_face_top, 1),
        "target_headroom_y": round(target_headroom_y, 1),
        "headroom_error_px": headroom_error_px,
        "rendered_face_center_x": round(rendered_face_cx, 1),
        "target_center_x": round(target_center_x, 1),
        "center_error_px": center_error_px,
    }

    return results


if __name__ == "__main__":
    res = run_visual_comparison()
    print("=== VISUAL FRAMING COMPARISON RESULTS ===")
    print(json.dumps(res, indent=2))
