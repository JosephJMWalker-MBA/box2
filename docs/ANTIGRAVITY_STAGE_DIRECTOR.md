# BOX2 Stage Director — Antigravity kickoff

Status: **development-only, offline prototype**. This branch is not merged or deployed. No hardware, live OBS scene, microphone, alarm, booking database or website is connected.

## Read first

- Root `AGENTS.md`, `README.md` and `docs/PRIVATE_REHEARSAL_BROADCAST_CONTINUITY.md`.
- `docs/IMPLEMENTATION.md` and `docs/LIVE_STUDIO_AND_GALAXY_SET.md`.
- Pending booking PR #1, private capture PR #5, Jetson/OBS design PR #7, and issue #8. They are NOT merged; don't silently adopt their code or claim existing booking integration.
- Antigravity auto-discovers root `AGENTS.md` as a repository rule. Keep the worktree isolated and review terminal/network permissions before authorizing an agent.

## Architecture now

`stage_director/core.py` is pure Python standard-library decision logic; it does not import OpenCV, Reolink, OBS, audio interfaces, network clients, PHP, or SQLite. A versioned, opaque booking snapshot must carry independent check-in, live consent, tracking consent, and verified capture state. It NEVER carries stage name, legal name, phone, email, address, script, private lineup, credentials, or graphic rights.

- `OFF` must return `capture_off`, never a wide camera shot.
- `ARMED` merely proposes an authorized stage-wide shot and waits for human start.
- `LIVE` merely proposes `track_face` plus single 60-second, 15-second and end cue events.
- Each slot has its immutable UTC deadline even if the host starts the set late.
- `private`, unknown consent, stale snapshot, revoke, monotonic regression or identity change stop outputs. Any future adapter must independently prove all NVR/SD/cloud/OBS/microphone capture is off for private rehearsals; a software decision cannot prove this.
- Face *detection* is planned, not biometric face *recognition*. Never enroll faces, create embeddings, or cross-session identity profiles.
- Cues are structured data only. No automatic siren. Future local room audio requires manual arm and a tested independent audio path.

## Run initial proof

From repository root with Python 3.10+:

```bash
python3 -m unittest discover -s stage_director/tests -v
python3 -m stage_director.simulate
```

The simulator prints proposed decisions for a **synthetic 10-minute set**. The seconds and UTC dates are test inputs, not actual bookings or camera measurements.

## Antigravity next assignment (paste into the agent)

> In `JosephJMWalker-MBA/box2`, use the `feature/stage-director-antigravity-kickoff` branch and read `AGENTS.md`, `docs/ANTIGRAVITY_STAGE_DIRECTOR.md`, and issue #8. Run the existing unit suite and simulator first. Keep all real endpoints unconfigured. Build a **local, consented-video-only face bounding-box simulator** behind an isolated adapter: camera feed input is an explicitly provided local sample/video, not a discovered RTSP address or live camera. Use stage polygon, one manually selected/confirmed performer, subject-loss timeout, dead-zone and smoothing to generate **OBS crop/transform proposals as JSON only**. Include deterministic unit tests using synthetic bounding-box sequences (no real face images required) covering fast movement, offstage bystanders, missing face, subject switch, sudden zoom, privacy revoke and process restart. No face recognition or storage. Do not install heavyweight dependencies or touch camera/PTZ, OBS WebSocket, Twitch, NVR, hosting, booking DB, or speaker without a separate explicit integration approval. Document the exact test commands and evidence. Make a reviewable incremental commit/PR rather than changing production.

## Completed milestone: Offline face bounding-box tracking and OBS crop prototype

Status: **Implemented, offline tested, zero live hardware or network connection**.

### Implemented modules (Pure Python standard library)

1. `stage_director/geometry.py`:
   - `BoundingBox`: Bounding box properties, center, area, IoU, and Euclidean distance.
   - `StagePolygon`: 2D stage polygon boundary with ray-casting point/box containment. Detections outside the stage polygon are treated as offstage bystanders and discarded.
2. `stage_director/framing.py`:
   - `FramingEngine` & `FramingWindow`: 16:9 medium-shot target crop calculation (face at ~33% headroom, torso/mic visible in lower 67%).
   - `deadzone_x_px`, `deadzone_y_px`, `deadzone_zoom_px`: Suppresses micro-twitches and camera jitter.
   - Velocity capping (`max_pan_speed_px_s`, `max_tilt_speed_px_s`, `max_zoom_speed_px_s`) and exponential smoothing (`smoothing_tau = 0.25s`).
   - Zoom boundaries strictly clamped between 1.0x (full frame) and 2.4x.
3. `stage_director/tracking.py`:
   - `PerformerTracker`: Single primary stage performer tracking via spatial continuity (NO biometric identity recognition, embeddings, or enrollment).
   - Stage polygon filtering: Offstage audience/bystanders are ignored.
   - Hold timeout (`loss_hold_seconds = 2.0s`): Brief head turns or mic occlusions hold framing steady. Prolonged absence transitions to `lost` and falls back to safe wide with `camera_subject_lost`.
   - Reacquisition: Returning performer is seamlessly re-locked.
   - Manual confirmation and subject switching support.
4. `stage_director/obs_transform.py`:
   - `OBSProposal`: Structured JSON schema for OBS crop proposals (`crop_left`, `crop_top`, `crop_right`, `crop_bottom`), framing metadata, tracking state, cues, and events.
5. `stage_director/adapter.py`:
   - `StageFramingAdapter`: Integrates `StageDirector` privacy and clock authorization with performer tracking and framing.
   - Fail-closed: `capture_off` when unconsented, stopped, or private; full frame when armed/finished; active medium shot crop only when live and tracked.
6. `stage_director/simulate_framing.py`:
   - End-to-end synthetic performance simulator walking through arrival, tracking, pacing, bystander filtering, brief occlusion hold, fast sprint speed capping, prop fetch safe-wide fallback, reacquisition, and time cues.

### Verification evidence

Run all 60 tests (including hardening and translator regression suites):
```bash
python3 -m unittest discover -s stage_director/tests -v
```
Result: 60 tests passed in 0.011s.

Run OBS WebSocket v5 request fixture validator:
```bash
python3 -m stage_director.obs_request_fixture
```

Run synthetic framing simulator:
```bash
python3 -m stage_director.simulate --framing
# or
python3 -m stage_director.simulate_framing
```

## Hardened Tracking & OBS Transform Milestone (PR #9 Review Findings)

Addressed all three P1 review findings using failing regression tests first:

1. **P1 — Gated Spatial Matching & Subject Stealing Prevention (`tracking.py`)**:
   - Replaced unconstrained Euclidean distance matching with gated spatial continuity (`_is_plausible_match`): maximum distance scaled by elapsed time (`base_match_radius_px + max_performer_speed_px_s * dt`) and area ratio bounds (`max_area_ratio = 3.0`).
   - If Performer A vanishes while Person B is on stage, B is rejected as an implausible match; the tracker holds for A without switching targets.
   - Added `TrackingState.AMBIGUOUS` and `require_confirmation_after_loss` policy: prolonged loss (>2s) transitions to ambiguous/lost, requiring host confirmation rather than silently adopting a stranger.
2. **P1 — First Frame Speed Limits & Smoothing from Safe-Wide (`framing.py`)**:
   - Time anchor is properly initialized upon arming and host start; FramingEngine starts strictly from safe-wide (`zoom = 1.0x`) and applies velocity capping (`max_zoom_speed_px_s`, `max_pan_speed_px_s`) and exponential smoothing from the very first frame.
   - Guarded against long stalls or paused frames via `max_step_dt = 0.50s`.
   - Verified zoom hysteresis against small face size noise within deadzone.
3. **P1 — OBS WebSocket v5 SetSceneItemTransform Translator (`obs_transform.py`, `obs_request_fixture.py`)**:
   - Implemented `translate_to_obs_request()` converting internal proposals to official OBS WebSocket v5 `SetSceneItemTransform` requests.
   - Generates exact `cropLeft`, `cropTop`, `cropRight`, `cropBottom` integer coordinates, calculates scale factors (`scaleX = canvas_width / visible_width`, `scaleY = canvas_height / visible_height`), sets `boundsType = "OBS_BOUNDS_SCALE_INNER"`, and uses top-left alignment `5`.
   - Implemented `create_transform_backup()` and `restore_transform_request()` for clean operator rollback.
   - Standalone `obs_request_fixture.py` validates outgoing request shape, integer crop constraints, and 16:9 aspect ratio at wide, medium, and boundary positions with zero network dependencies.

## Integration steps only after read-only audits

1. Verify installed Reolink firmware/control support, whether direct camera vs NVR RTSP is used, and PTZ limits; first test physical PTZ offline.
2. Verify OBS host, scenes, video transforms, installed OBS WebSocket and studio isolation from a separate Twitch viewer.
3. Design a short-lived authenticated, **Jetson-pulled** minimal booking snapshot; do not scrape the public schedule or provide any web-to-OBS control endpoint.
4. Measure clock offsets, stream buffering, stage framing jitter/latency and end-cue channel routing.
5. Host-arm an expressly consenting test set only after privacy and scene-recovery tests succeed.

## Failure policy

Uncertainty means **no room capture, no broadcast identity, no alarm and no physical PTZ movement**. A scheduled slot does not establish who is present; detection does not establish permission. Preserve the existing ability to run house-only media or stop the broadcast when a private session cannot be isolated.
