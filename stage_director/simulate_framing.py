"""Run a synthetic performance simulation with virtual camera framing proposals.

Demonstrates:
  - Consented booking arming and host-confirmed start.
  - Performer walking and pacing across the stage (smooth 16:9 medium shot tracking).
  - Offstage audience/bystander ignored by stage polygon.
  - Brief head turns / mic occlusion held without camera jitter.
  - Fast stage sprint rate-limited by maximum pan speed.
  - Prolonged subject absence holding for 2s then smoothly transitioning to safe-wide.
  - Seamless subject reacquisition upon return.
  - Countdown time cues (warn_60, warn_15, time_up).
  - Immediate fail-closed shutoff.

Run: python3 -m stage_director.simulate_framing
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from .adapter import StageFramingAdapter
from .core import BookingSnapshot
from .geometry import BoundingBox, StagePolygon


def run_simulation() -> None:
    start_time = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)
    base_monotonic = 1000.0

    booking = BookingSnapshot(
        booking_id="synthetic-comedian-jane-doe",
        revision=1,
        slot_start_utc=start_time,
        slot_end_utc=start_time + timedelta(minutes=10),
        issued_at_utc=start_time - timedelta(seconds=30),
        expires_at_utc=start_time + timedelta(minutes=11),
        stage_seconds=600,
        privacy_class="public",
        checked_in=True,
        live_consent=True,
        tracking_consent=True,
        capture_verified=True,
    )

    adapter = StageFramingAdapter()

    # Scripted timeline of synthetic performance events
    # Each item: (elapsed_seconds, description, detections)
    scripted_steps: List[tuple[float, str, List[BoundingBox]]] = [
        # 1. Arming before set starts
        (-5.0, "stage_armed_awaiting_host", []),
        # 2. Host confirms start at t=0
        (0.0, "host_start_comedian_onstage_center", [
            BoundingBox(x=1860.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 3. Comedian warming up, slight movement
        (5.0, "comedian_pacing_slight_left", [
            BoundingBox(x=1750.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 4. Offstage bystander walks through audience wing (x=100)
        (10.0, "offstage_bystander_ignored", [
            BoundingBox(x=1700.0, y=700.0, width=120.0, height=150.0),
            BoundingBox(x=100.0, y=1000.0, width=120.0, height=150.0)  # Offstage
        ]),
        # 5. Comedian head turn / mic blocks face for 1.0s (held without snapping wide)
        (11.0, "face_occluded_holding_framing", []),
        # 6. Face returns at 11.8s (within 2s hold limit)
        (11.8, "face_returned_smooth_reacquisition", [
            BoundingBox(x=1680.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 7. Fast walk across stage to right side (x=2400)
        (25.0, "comedian_walks_stage_right", [
            BoundingBox(x=2400.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 8. Comedian working the room mid-set
        (300.0, "mid_set_comfortable_framing", [
            BoundingBox(x=2100.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 9. T-60s warning cue
        (541.0, "warn_60_cue_fired", [
            BoundingBox(x=1920.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 10. Comedian steps off stage: brief hold (1s) then subject loss (>2s)
        (550.0, "comedian_steps_offstage_last_seen", [
            BoundingBox(x=1920.0, y=700.0, width=120.0, height=150.0)
        ]),
        (551.0, "comedian_away_holding_framing", []),
        (553.5, "subject_lost_smooth_fallback_to_safe_wide", []),
        # 11. Comedian returns to stage: prolonged absence (>2s) enters AMBIGUOUS
        (560.0, "comedian_returns_ambiguous_safety_check", [
            BoundingBox(x=1880.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 12. Host explicitly confirms comedian: tracking resumes smoothly
        (565.0, "host_confirms_comedian_tracking_resumed", [
            BoundingBox(x=1880.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 13. T-15s warning cue
        (586.0, "warn_15_cue_fired", [
            BoundingBox(x=1880.0, y=700.0, width=120.0, height=150.0)
        ]),
        # 14. Set finishes at 600s
        (600.0, "time_up_cue_switches_to_stage_wide", [
            BoundingBox(x=1880.0, y=700.0, width=120.0, height=150.0)
        ]),
    ]

    print("=== BOX2 STAGE DIRECTOR: SYNTHETIC FRAMING SIMULATION ===")
    print("Mode: Offline prototype (no live camera or OBS connection)")
    print()

    # Arm
    arm_proposal = adapter.arm(booking, start_time - timedelta(seconds=5))
    print(f"[{arm_proposal.timestamp_utc}] STEP: arm")
    print(f"  Proposal: {arm_proposal.to_json()}")
    print()

    # Host Start
    start_proposal = adapter.start_set(start_time, base_monotonic, host_confirmed=True)
    print(f"[{start_proposal.timestamp_utc}] STEP: host_start")
    print(f"  Proposal: {start_proposal.to_json()}")
    print()

    # Process scripted steps
    for elapsed, label, detections in scripted_steps:
        if elapsed < 0:
            continue
        current_time = start_time + timedelta(seconds=elapsed)
        current_mono = base_monotonic + elapsed

        if label == "host_confirms_comedian_tracking_resumed" and detections:
            adapter.confirm_subject(detections[0], current_mono)
            print(f"[{current_time.strftime('%Y-%m-%dT%H:%M:%SZ')}] HOST ACTION: operator confirmed comedian on stage")

        proposal = adapter.process_frame(detections, current_time, current_mono)
        print(f"[{proposal.timestamp_utc}] STEP: {label} (elapsed: {elapsed}s)")
        print(f"  Mode: {proposal.mode} | Camera: {proposal.camera_action} | Tracking: {proposal.tracking_state}")
        if proposal.cue:
            print(f"  >>> CUE EMITTED: {proposal.cue} (Remaining: {proposal.remaining_seconds}s)")
        if proposal.events:
            print(f"  Events: {proposal.events}")
        if proposal.obs_crop:
            print(f"  OBS Crop: {proposal.obs_crop}")
        if proposal.framing:
            print(f"  Framing: center=({proposal.framing['center_x']}, {proposal.framing['center_y']}), zoom={proposal.framing['zoom_factor']}x")
        print()

    print("=== SIMULATION COMPLETE ===")


if __name__ == "__main__":
    run_simulation()
