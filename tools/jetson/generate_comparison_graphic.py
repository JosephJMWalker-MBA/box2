"""Create a 3-panel comparison graphic illustrating:
1. Original Unattended Wide Stage
2. Stage Director Head-and-Shoulders Close-Up
3. "Breathing Wide" Establishing Room Shot Cadence
"""
import os
from PIL import Image, ImageDraw, ImageFont

DIR = "/Users/josephjmwalker-mba/.gemini/antigravity/scratch/box2/tools/jetson"
p1_path = os.path.join(DIR, "still_01_original_wide_reference.jpg")
p2_path = os.path.join(DIR, "still_01_closeup_head_and_shoulders.jpg")
p3_path = os.path.join(DIR, "still_02_periodic_room_view_establishing.jpg")

im1 = Image.open(p1_path)
im2 = Image.open(p2_path)
im3 = Image.open(p3_path)

panel_w, panel_h = 640, 360
im1_resized = im1.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
im2_resized = im2.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
im3_resized = im3.resize((panel_w, panel_h), Image.Resampling.LANCZOS)

# Create a horizontal strip: 3 panels wide (1920x360 + header)
header_h = 60
footer_h = 40
canvas_w = panel_w * 3
canvas_h = panel_h + header_h + footer_h

canvas = Image.new("RGB", (canvas_w, canvas_h), (20, 24, 33))
draw = ImageDraw.Draw(canvas)

# Paste panels
canvas.paste(im1_resized, (0, header_h))
canvas.paste(im2_resized, (panel_w, header_h))
canvas.paste(im3_resized, (panel_w * 2, header_h))

# Draw header
draw.text((20, 15), "BOX2 STAGE DIRECTOR - REAL-TIME LIVE REHEARSAL VERIFICATION", fill=(255, 255, 255))
draw.text((20, 35), "Automated Cinematography: Head-and-Shoulders Close-Up & Breathing Wide Cadence", fill=(140, 160, 190))

# Panel banners
# Panel 1
draw.rectangle([(0, header_h), (panel_w, header_h + 30)], fill=(0, 0, 0, 180))
draw.text((15, header_h + 8), "1. RAW WIDE (Prior System / Unattended)", fill=(240, 180, 50))

# Panel 2
draw.rectangle([(panel_w, header_h), (panel_w * 2, header_h + 30)], fill=(0, 0, 0, 180))
draw.text((panel_w + 15, header_h + 8), "2. HEAD-AND-SHOULDERS CLOSE-UP (Target Fraction 0.33, Zoom 3.6x)", fill=(50, 220, 120))

# Panel 3
draw.rectangle([(panel_w * 2, header_h), (canvas_w, header_h + 30)], fill=(0, 0, 0, 180))
draw.text((panel_w * 2 + 15, header_h + 8), "3. BREATHING WIDE ROOM VIEW (Every 45-50s for ~5s)", fill=(80, 180, 255))

# Footer
draw.text((20, canvas_h - 28), "Verified on physical Jetson Orin Nano with live rehearsal recording (11m 19s). Proximity auto-reacquisition active.", fill=(160, 175, 195))

out_path = os.path.join(DIR, "stage_director_three_panel_comparison.jpg")
canvas.save(out_path, quality=95)
print(f"Saved comparison to: {out_path}")
