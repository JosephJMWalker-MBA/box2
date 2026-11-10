"""Synthetic 4K calibration test pattern generator for Stage Director.

Generates a native 3840x2160 (16:9) reference test image with:
- Calibrated coordinate grid (100px increments)
- 16:9 edge border and corner fiducials
- Stage boundary polygon guides
- Concentric calibration circles for aspect ratio preservation verification
- Primary performer target face/torso at stage center with 33% headroom mark
- Offstage bystander marker for spatial filtering verification
"""
from __future__ import annotations

import math
import os
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont


def generate_synthetic_stage_test_pattern(
    width: int = 3840,
    height: int = 2160,
    output_path: str = "stage_director/fixtures/synthetic_stage_4k.png",
) -> str:
    """Generate and save a deterministic synthetic 4K stage calibration pattern."""
    img = Image.new("RGB", (width, height), color=(18, 20, 26))
    draw = ImageDraw.Draw(img)

    # 1. Coordinate Grid (100px minor, 500px major)
    for x in range(0, width, 100):
        color = (40, 45, 58) if (x % 500 != 0) else (65, 75, 95)
        width_px = 1 if (x % 500 != 0) else 2
        draw.line([(x, 0), (x, height)], fill=color, width=width_px)
        if x % 500 == 0 and x > 0:
            draw.text((x + 4, 10), f"X={x}", fill=(140, 150, 175))

    for y in range(0, height, 100):
        color = (40, 45, 58) if (y % 500 != 0) else (65, 75, 95)
        width_px = 1 if (y % 500 != 0) else 2
        draw.line([(0, y), (width, y)], fill=color, width=width_px)
        if y % 500 == 0 and y > 0:
            draw.text((10, y + 4), f"Y={y}", fill=(140, 150, 175))

    # 2. Diagonal fiducials (corner to corner to verify slope = 9/16 = 0.5625)
    draw.line([(0, 0), (width, height)], fill=(45, 50, 65), width=2)
    draw.line([(0, height), (width, 0)], fill=(45, 50, 65), width=2)

    # 3. Outer 16:9 boundary line & corner ticks
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(255, 255, 255), width=4)
    tick_len = 80
    # Top-Left, Top-Right, Bottom-Left, Bottom-Right corner ticks
    draw.line([(tick_len, 40), (40, 40), (40, tick_len)], fill=(255, 200, 0), width=4)
    draw.line([(width - tick_len, 40), (width - 40, 40), (width - 40, tick_len)], fill=(255, 200, 0), width=4)
    draw.line([(tick_len, height - 40), (40, height - 40), (40, height - tick_len)], fill=(255, 200, 0), width=4)
    draw.line([(width - tick_len, height - 40), (width - 40, height - 40), (width - 40, height - tick_len)], fill=(255, 200, 0), width=4)

    # 4. Stage Boundary Polygon
    # [(400.0, 300.0), (3440.0, 300.0), (3600.0, 2100.0), (240.0, 2100.0)]
    stage_poly = [(400, 300), (3440, 300), (3600, 2100), (240, 2100)]
    draw.polygon(stage_poly, outline=(0, 220, 255), width=4)
    draw.text((420, 320), "BOX2 AUTHORIZED STAGE BOUNDARY (IN-POLYGON)", fill=(0, 220, 255))

    # 5. Concentric Calibration Circles at Stage Center (1920, 1080)
    # True circles reveal any non-uniform scaling or aspect ratio stretch
    cx, cy = width // 2, height // 2
    for r in [200, 400, 600, 800]:
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=(80, 100, 130), width=2)

    # Center crosshair
    draw.line([(cx - 100, cy), (cx + 100, cy)], fill=(255, 255, 255), width=3)
    draw.line([(cx, cy - 100), (cx, cy + 100)], fill=(255, 255, 255), width=3)
    draw.text((cx + 15, cy + 15), f"CENTER ({cx}, {cy})", fill=(255, 255, 255))

    # 6. Primary Performer Target (Center Stage)
    # Face bounding box: x=1800, y=750, w=240, h=300 -> Center=(1920, 900)
    face_box = (1800, 750, 1800 + 240, 750 + 300)
    draw.rectangle(face_box, outline=(0, 255, 120), width=4)
    draw.text((1810, 760), "PERFORMER FACE TARGET", fill=(0, 255, 120))
    draw.text((1810, 785), "3840x2160 Native 16:9", fill=(0, 255, 120))
    draw.text((1810, 810), f"Box: {face_box}", fill=(0, 255, 120))

    # Face center
    face_cx, face_cy = 1920, 900
    draw.ellipse([(face_cx - 20, face_cy - 20), (face_cx + 20, face_cy + 20)], fill=(0, 255, 120))

    # Torso and Mic Representation
    torso_box = (1760, 1050, 1760 + 320, 1050 + 600)
    draw.rectangle(torso_box, outline=(0, 180, 90), width=3)
    draw.text((1780, 1070), "TORSO & STAGE MIC GUIDELINE", fill=(0, 180, 90))

    # 7. Offstage Bystander / Audience (outside stage polygon)
    # x=100, y=1200, w=120, h=160
    bystander_box = (100, 1200, 100 + 120, 1200 + 160)
    draw.rectangle(bystander_box, outline=(255, 70, 70), width=3)
    draw.text((30, 1170), "OFFSTAGE AUDIENCE (DISCARDED)", fill=(255, 70, 70))

    # 8. Calibration Legend
    legend_y = height - 120
    draw.text((100, legend_y), "STAGE DIRECTOR 4K REFERENCE CALIBRATION PATTERN", fill=(255, 255, 255))
    draw.text((100, legend_y + 30), "Source: 3840x2160 (16:9) | Target OBS Canvas: 1920x1080 (16:9)", fill=(200, 210, 225))
    draw.text((100, legend_y + 60), "Verification: Aspect Preservation (1.000) | No Double-Scaling | Zero Audio/PTZ Control", fill=(200, 210, 225))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


if __name__ == "__main__":
    out = generate_synthetic_stage_test_pattern()
    print(f"Generated synthetic test pattern at: {out}")
