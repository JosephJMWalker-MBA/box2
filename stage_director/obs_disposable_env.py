"""Disposable OBS Profile and Scene Collection Generator for Stage Director.

Safely generates an isolated, disposable test profile and scene collection in the user's
OBS Studio configuration directory:
  - Profile: StageDirector_Test
  - Scene Collection: StageDirector_Test.json
  - Target Canvas: 1920x1080 @ 30 FPS
  - Test Source: Synthetic 4K Calibration image (fixtures/synthetic_stage_4k.png)
  - Zero RTSP, zero microphones, zero external network streams, zero stream keys.
  - Production Diag.json and user.ini remain completely untouched.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple


DISPOSABLE_PROFILE_NAME = "StageDirector_Test"
DISPOSABLE_SCENE_COLLECTION_NAME = "StageDirector_Test"
DEFAULT_ISOLATED_CONFIG_ROOT = os.path.expanduser("~/.box2_obs_isolated_test")


def get_isolated_obs_config_dir() -> str:
    """Return the dedicated, isolated OBS test configuration root directory.

    Defaults to ~/.box2_obs_isolated_test, completely separate from production OBS.
    Can be overridden via BOX2_OBS_CONFIG_ROOT environment variable.
    """
    return os.environ.get("BOX2_OBS_CONFIG_ROOT", DEFAULT_ISOLATED_CONFIG_ROOT)


def get_production_obs_config_dir() -> str:
    """Return the user's live production OBS Studio configuration directory (read-only)."""
    return os.path.expanduser("~/Library/Application Support/obs-studio")


def setup_disposable_obs_environment(
    base_dir: Optional[str] = None,
    synthetic_image_path: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, str]:
    """Create isolated disposable OBS profile and scene collection files.

    Guarantees:
      - Defaults to a dedicated isolated root (~/.box2_obs_isolated_test), anchored outside production.
      - Refuses to write into production OBS directory or any of its subdirectories/descendants.
      - Resolves symlinks via os.path.realpath to prevent escape.
      - Fails before any directory creation or writes if either test file exists unless overwrite=True.
    """
    obs_dir = base_dir or get_isolated_obs_config_dir()

    # Safety guard: Prevent accidental collision with production OBS directory or any descendant
    target_real = os.path.realpath(os.path.abspath(obs_dir))
    prod_real = os.path.realpath(os.path.abspath(get_production_obs_config_dir()))

    is_in_production = False
    try:
        common = os.path.commonpath([target_real, prod_real])
        if common == prod_real:
            is_in_production = True
    except ValueError:
        is_in_production = False

    if is_in_production:
        raise RuntimeError(
            f"Isolation safety violation: Refusing to create test artifacts in live production "
            f"OBS configuration directory tree ({prod_real}). Target: {target_real}. "
            f"Use a path anchored outside the entire production OBS tree."
        )

    profiles_dir = os.path.join(obs_dir, "basic", "profiles", DISPOSABLE_PROFILE_NAME)
    scenes_dir = os.path.join(obs_dir, "basic", "scenes")

    profile_ini_path = os.path.join(profiles_dir, "basic.ini")
    scene_json_path = os.path.join(scenes_dir, f"{DISPOSABLE_SCENE_COLLECTION_NAME}.json")

    # Safeguard against accidental overwrite: fail before writing if either exists
    if not overwrite:
        existing = [p for p in (profile_ini_path, scene_json_path) if os.path.exists(p)]
        if existing:
            raise FileExistsError(
                f"Refusing to overwrite existing disposable OBS test files when overwrite=False: {existing}"
            )

    os.makedirs(profiles_dir, exist_ok=True)
    os.makedirs(scenes_dir, exist_ok=True)

    test_image = synthetic_image_path or os.path.abspath("stage_director/fixtures/synthetic_stage_4k.png")

    # 1. Profile basic.ini: 1920x1080 canvas, 30 FPS, no stream keys, no audio inputs
    profile_ini_path = os.path.join(profiles_dir, "basic.ini")
    profile_ini_content = f"""[General]
Name={DISPOSABLE_PROFILE_NAME}

[Video]
BaseCX=1920
BaseCY=1080
OutputCX=1920
OutputCY=1080
FPSCommon=30
FPSType=0
FPSInt=30
FPSNum=30
FPSDen=1
ScaleType=bicubic
ColorFormat=NV12
ColorSpace=709
ColorRange=Partial

[Audio]
MonitoringDeviceId=default
MonitoringDeviceName=Default
SampleRate=48000
ChannelSetup=Stereo

[Stream1]
EnableMultitrackVideo=false

[Output]
Mode=Simple
"""
    with open(profile_ini_path, "w", encoding="utf-8") as f:
        f.write(profile_ini_content)

    # 2. Scene Collection JSON: StageDirector_Test.json
    scene_json_path = os.path.join(scenes_dir, f"{DISPOSABLE_SCENE_COLLECTION_NAME}.json")
    scene_collection: Dict[str, Any] = {
        "name": DISPOSABLE_SCENE_COLLECTION_NAME,
        "current_scene": "Stage Director Test Scene",
        "current_program_scene": "Stage Director Test Scene",
        "scene_order": [{"name": "Stage Director Test Scene"}],
        "sources": [
            {
                "name": "Synthetic 4K Calibration Source",
                "uuid": "4c85ef92-0b1a-4d7a-8b83-938210928374",
                "id": "image_source",
                "versioned_id": "image_source",
                "settings": {
                    "file": test_image,
                    "unload": False,
                    "linear_alpha": True,
                },
                "mixers": 0,
                "sync": 0,
                "flags": 0,
                "volume": 0.0,
                "balance": 0.5,
                "enabled": True,
                "muted": True,
                "deinterlace_mode": 0,
                "deinterlace_field_order": 0,
                "monitoring_type": 0,
                "private_settings": {},
            },
            {
                "name": "Stage Director Test Scene",
                "uuid": "1e8432a9-98a7-4712-bf91-a83716d93e11",
                "id": "scene",
                "versioned_id": "scene",
                "settings": {
                    "id_counter": 1,
                    "custom_size": False,
                    "items": [
                        {
                            "name": "Synthetic 4K Calibration Source",
                            "source_uuid": "4c85ef92-0b1a-4d7a-8b83-938210928374",
                            "visible": True,
                            "locked": False,
                            "rot": 0.0,
                            "scale_ref": {"x": 1920.0, "y": 1080.0},
                            "align": 5,
                            "bounds_type": 2,  # OBS_BOUNDS_SCALE_INNER
                            "bounds_align": 0,
                            "bounds_crop": False,
                            "crop_left": 0,
                            "crop_top": 0,
                            "crop_right": 0,
                            "crop_bottom": 0,
                            "id": 1,
                            "group_item_backup": False,
                            "pos": {"x": 0.0, "y": 0.0},
                            "pos_rel": {"x": -1.7777777910232544, "y": -1.0},
                            "scale": {"x": 1.0, "y": 1.0},
                            "scale_rel": {"x": 1.0, "y": 1.0},
                            "bounds": {"x": 1920.0, "y": 1080.0},
                            "bounds_rel": {"x": 3.555555582046509, "y": 2.0},
                            "scale_filter": "bicubic",
                            "blend_method": "default",
                            "blend_type": "normal",
                            "show_transition": {"duration": 0},
                            "hide_transition": {"duration": 0},
                            "private_settings": {},
                        }
                    ],
                },
                "mixers": 0,
                "sync": 0,
                "flags": 0,
                "volume": 1.0,
                "balance": 0.5,
                "enabled": True,
                "muted": False,
                "private_settings": {},
            },
        ],
        "groups": [],
        "modules": {},
        "resolution": {"x": 1920, "y": 1080},
        "version": 2,
    }

    with open(scene_json_path, "w", encoding="utf-8") as f:
        json.dump(scene_collection, f, indent=2)

    return {
        "profile_dir": profiles_dir,
        "profile_ini": profile_ini_path,
        "scene_json": scene_json_path,
    }


def verify_production_isolation(obs_dir: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Verify that live production scene Diag.json and user.ini remain completely intact,
    and that no test artifacts leaked into the production directory."""
    base = obs_dir or get_production_obs_config_dir()
    issues: List[str] = []

    diag_path = os.path.join(base, "basic", "scenes", "Diag.json")
    if os.path.exists(diag_path):
        with open(diag_path, "r", encoding="utf-8") as f:
            try:
                diag_data = json.load(f)
                if diag_data.get("name") != "Diag":
                    issues.append("Production Diag.json name corrupted")
            except Exception as e:
                issues.append(f"Production Diag.json read error: {e}")

    user_ini_path = os.path.join(base, "user.ini")
    if os.path.exists(user_ini_path):
        with open(user_ini_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "SceneCollection=StageDirector_Test" in content:
                issues.append("user.ini was inadvertently pointed to test collection")

    # Verify no test artifacts leaked into production directories
    test_scene = os.path.join(base, "basic", "scenes", f"{DISPOSABLE_SCENE_COLLECTION_NAME}.json")
    if os.path.exists(test_scene):
        issues.append(f"Production directory contains test collection file: {test_scene}")

    test_profile = os.path.join(base, "basic", "profiles", DISPOSABLE_PROFILE_NAME)
    if os.path.exists(test_profile):
        issues.append(f"Production directory contains test profile directory: {test_profile}")

    return len(issues) == 0, issues


if __name__ == "__main__":
    paths = setup_disposable_obs_environment()
    print("Disposable OBS test environment configured:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
    ok, errs = verify_production_isolation()
    print(f"Production isolation check: {'PASSED' if ok else 'FAILED: ' + str(errs)}")
