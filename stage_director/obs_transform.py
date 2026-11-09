"""OBS crop and transform proposals emitted as JSON and translated to OBS WebSocket v5.

Standard library only. Emits recommendations and translates to official OBS WebSocket
v5 SetSceneItemTransform requests; does not connect to OBS or make network calls.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Dict, List, Optional


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
    canvas_width: int = 3840,
    canvas_height: int = 2160,
    source_width: Optional[int] = None,
    source_height: Optional[int] = None,
    strategy: str = "combined",
) -> Optional[Dict[str, Any]]:
    """Translate an internal OBSProposal into an official OBS WebSocket v5 request.

    Supports three transform strategies:
      - 'combined' (default): sets boundsType='OBS_BOUNDS_SCALE_INNER' with computed scale factors.
      - 'bounds_inner': sets boundsType='OBS_BOUNDS_SCALE_INNER' with scale=(1.0, 1.0) and crop only.
      - 'explicit_scale': sets boundsType='OBS_BOUNDS_NONE' with explicit scaleX and scaleY.

    Returns None when proposal recommends capture_off.
    """
    if proposal.camera_action == "capture_off":
        return None

    src_w = float(source_width or proposal.source_resolution.get("width", canvas_width))
    src_h = float(source_height or proposal.source_resolution.get("height", canvas_height))

    if proposal.camera_action == "stage_wide" or proposal.obs_crop is None:
        crop_left = 0
        crop_top = 0
        crop_right = 0
        crop_bottom = 0
        visible_w = src_w
        visible_h = src_h
    else:
        # track_face with active crop
        crop_left = proposal.obs_crop.get("left", 0)
        crop_top = proposal.obs_crop.get("top", 0)
        crop_right = proposal.obs_crop.get("right", 0)
        crop_bottom = proposal.obs_crop.get("bottom", 0)
        visible_w = max(1.0, src_w - crop_left - crop_right)
        visible_h = max(1.0, src_h - crop_top - crop_bottom)

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
