"""OBS crop and transform proposals emitted as JSON and translated to OBS WebSocket v5.

Standard library only. Emits recommendations and translates to official OBS WebSocket
v5 SetSceneItemTransform requests; does not connect to OBS or make network calls.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from typing import Any, Dict, List, Optional

VALID_STRATEGIES = frozenset({"bounds_inner", "explicit_scale", "combined"})


@dataclass(frozen=True)
class OBSProposal:
    """A single internal OBS crop and scene item transform proposal."""
    schema_version: str
    timestamp_utc: str
    monotonic_seconds: float
    mode: str
    camera_action: str
    tracking_state: str
    subject_lost: bool
    source_resolution: Dict[str, int]
    obs_crop: Optional[Dict[str, int]]
    framing: Optional[Dict[str, Any]]
    events: List[str]
    cue: Optional[str] = None
    remaining_seconds: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class OBSSceneItemTransform:
    """Official OBS WebSocket v5 sceneItemTransform object matching libobs C++ types."""
    cropLeft: int
    cropTop: int
    cropRight: int
    cropBottom: int
    positionX: float = 0.0
    positionY: float = 0.0
    scaleX: float = 1.0
    scaleY: float = 1.0
    rotation: float = 0.0
    alignment: int = 5  # OBS_ALIGN_TOP | OBS_ALIGN_LEFT = 1 | 4 = 5
    boundsType: str = "OBS_BOUNDS_SCALE_INNER"
    boundsAlignment: int = 0
    boundsWidth: float = 3840.0
    boundsHeight: float = 2160.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def translate_to_obs_request(
    proposal: OBSProposal,
    scene_name: str,
    scene_item_id: int,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    source_width: Optional[int] = None,
    source_height: Optional[int] = None,
    strategy: str = "bounds_inner",
) -> Optional[Dict[str, Any]]:
    """Translate an internal OBSProposal into an official OBS WebSocket v5 request.

    Supports three transform strategies:
      - 'bounds_inner' (default): sets boundsType='OBS_BOUNDS_SCALE_INNER' with scale=(1.0, 1.0) and crop only.
      - 'combined': sets boundsType='OBS_BOUNDS_SCALE_INNER' with computed scale factors.
      - 'explicit_scale': sets boundsType='OBS_BOUNDS_NONE' with explicit scaleX and scaleY.

    Returns None when proposal recommends capture_off.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Invalid strategy '{strategy}'. Must be one of {sorted(VALID_STRATEGIES)}")

    if proposal.camera_action == "capture_off":
        return None

    if not math.isfinite(canvas_width) or not math.isfinite(canvas_height) or canvas_width <= 0 or canvas_height <= 0:
        raise ValueError(f"Invalid canvas dimensions: {canvas_width}x{canvas_height}. Must be finite positive values.")

    src_w = float(source_width or proposal.source_resolution.get("width", canvas_width))
    src_h = float(source_height or proposal.source_resolution.get("height", canvas_height))

    if not math.isfinite(src_w) or not math.isfinite(src_h) or src_w <= 0 or src_h <= 0:
        raise ValueError(f"Invalid source dimensions: {src_w}x{src_h}. Must be finite positive values.")

    if proposal.camera_action == "stage_wide" or proposal.obs_crop is None:
        crop_left = 0
        crop_top = 0
        crop_right = 0
        crop_bottom = 0
        visible_w = src_w
        visible_h = src_h
    else:
        # Validate crop parameters
        for k in ("left", "top", "right", "bottom"):
            val = proposal.obs_crop.get(k)
            if val is None or not isinstance(val, (int, float)) or not math.isfinite(val) or val < 0:
                raise ValueError(f"Invalid crop dimension '{k}': {val}. Must be a finite non-negative number.")

        crop_left = int(proposal.obs_crop.get("left", 0))
        crop_top = int(proposal.obs_crop.get("top", 0))
        crop_right = int(proposal.obs_crop.get("right", 0))
        crop_bottom = int(proposal.obs_crop.get("bottom", 0))

        if crop_left + crop_right >= src_w:
            raise ValueError(
                f"Horizontal crops ({crop_left} + {crop_right} = {crop_left + crop_right}) "
                f"equal or exceed source width ({src_w})"
            )
        if crop_top + crop_bottom >= src_h:
            raise ValueError(
                f"Vertical crops ({crop_top} + {crop_bottom} = {crop_top + crop_bottom}) "
                f"equal or exceed source height ({src_h})"
            )

        visible_w = src_w - crop_left - crop_right
        visible_h = src_h - crop_top - crop_bottom

    if strategy == "bounds_inner":
        # Strategy (a): OBS_BOUNDS_SCALE_INNER with crop only; scale is 1.0
        scale_x = 1.0
        scale_y = 1.0
        bounds_type = "OBS_BOUNDS_SCALE_INNER"
        bounds_w = float(canvas_width)
        bounds_h = float(canvas_height)
    elif strategy == "explicit_scale":
        # Strategy (b): explicit scale with bounds NONE
        scale_x = round(float(canvas_width) / visible_w, 4)
        scale_y = round(float(canvas_height) / visible_h, 4)
        bounds_type = "OBS_BOUNDS_NONE"
        bounds_w = 0.0
        bounds_h = 0.0
    else:
        # Strategy (c): combined scale + bounds SCALE_INNER (default)
        scale_x = round(float(canvas_width) / visible_w, 4)
        scale_y = round(float(canvas_height) / visible_h, 4)
        bounds_type = "OBS_BOUNDS_SCALE_INNER"
        bounds_w = float(canvas_width)
        bounds_h = float(canvas_height)

    transform = OBSSceneItemTransform(
        cropLeft=crop_left,
        cropTop=crop_top,
        cropRight=crop_right,
        cropBottom=crop_bottom,
        positionX=0.0,
        positionY=0.0,
        scaleX=scale_x,
        scaleY=scale_y,
        rotation=0.0,
        alignment=5,
        boundsType=bounds_type,
        boundsAlignment=0,
        boundsWidth=bounds_w,
        boundsHeight=bounds_h,
    )

    return {
        "requestType": "SetSceneItemTransform",
        "requestData": {
            "sceneName": scene_name,
            "sceneItemId": scene_item_id,
            "sceneItemTransform": transform.to_dict(),
        },
    }


def create_transform_backup(transform_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Create a validated copy of an existing scene item transform for later rollback."""
    keys = (
        "cropLeft", "cropTop", "cropRight", "cropBottom",
        "positionX", "positionY", "scaleX", "scaleY",
        "rotation", "alignment", "boundsType", "boundsAlignment",
        "boundsWidth", "boundsHeight",
    )
    return {k: transform_dict[k] for k in keys if k in transform_dict}


def restore_transform_request(scene_name: str, scene_item_id: int,
                              backup: Dict[str, Any]) -> Dict[str, Any]:
    """Build a SetSceneItemTransform request to restore the backup transform."""
    return {
        "requestType": "SetSceneItemTransform",
        "requestData": {
            "sceneName": scene_name,
            "sceneItemId": scene_item_id,
            "sceneItemTransform": dict(backup),
        },
    }
