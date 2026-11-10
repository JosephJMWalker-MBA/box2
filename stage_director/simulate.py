"""Run a fully synthetic set: python -m stage_director.simulate.

Pass --framing to run the full camera framing and OBS crop simulation:
  python3 -m stage_director.simulate --framing
or
  python3 -m stage_director.simulate_framing

No network, camera, booking server, OBS, speaker, or audio dependency.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .core import BookingSnapshot, StageDirector


def main() -> None:
    if "--framing" in sys.argv:
        from .simulate_framing import run_simulation
        run_simulation()
        return

    start = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)
    booking = BookingSnapshot(
        booking_id="synthetic-performer-001",
        revision=1,
        slot_start_utc=start,
        slot_end_utc=start + timedelta(minutes=10),
        issued_at_utc=start - timedelta(seconds=5),
        expires_at_utc=start + timedelta(minutes=11),
        stage_seconds=600,
        privacy_class="public",
        checked_in=True,
        live_consent=True,
        tracking_consent=True,
        capture_verified=True,
    )
    director = StageDirector()
    events = [
        ("arm", director.arm(booking, start)),
        ("host_start", director.start_set(start, 1000, host_confirmed=True)),
    ]
    for elapsed in (100, 539, 541, 584, 586, 600):
        events.append((
            f"elapsed_{elapsed}s",
            director.tick(start + timedelta(seconds=elapsed), 1000 + elapsed),
        ))
    for label, decision in events:
        record = asdict(decision)
        record["step"] = label
        print(json.dumps(record, default=lambda item: item.value))


if __name__ == "__main__":
    main()
