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

## Milestone 3: Subject Safety and Read-Only Hardware Discovery (PR #9 Second Review)

Addressed tracking safety edge cases with failing regression tests first, followed by a non-invasive, read-only audit of the local production environment:

### 1. Subject Safety Hardening (`tracking.py`, `adapter.py`)
- **Near-Position Reacquisition Safety**: Proximity alone does not prove identity after an extended loss (>2.0s). If the performer steps offstage and another person appears near or in the performer's last recorded position, the tracker rejects automatic reacquisition and transitions to `TrackingState.AMBIGUOUS` with a `performer_confirmation_required` event, keeping the camera smoothly framed safe-wide until host confirmation.
- **Ambiguous Initial Acquisition**: If two or more faces appear onstage at set start, the tracker refuses to auto-select the largest face. It enters `TrackingState.AMBIGUOUS` requiring operator confirmation or subject selection.
- **Adapter Authorization Gating**: `StageFramingAdapter.confirm_subject()` and `switch_subject()` fail closed (`return False`) unless the director is in authorized `Mode.LIVE`.
- **Preserved Test Coverage**: 63 unit tests pass in 0.013s (`stage_director/tests/test_hardening.py`, `test_adapter.py`, `test_tracking.py`).

### 2. Sanitized Read-Only Hardware & OBS Environment Audit
*All credentials, internal IPs, and private data are redacted.*

- **Host & Architecture**:
  - Model: Apple Mac (Apple Silicon M4, 10 cores, 16 GB unified RAM).
  - OS: macOS 26.6.2 (Darwin Kernel 25.6.0).
  - Process Placement: Local Mac runs OBS Studio and a background watchdog script (`obs_sck_watchdog.py`) ensuring host microphone muting on startup. Edge vision detection / Jetson Orin operates on LAN; no vision inferencing processes run on Mac host.
- **OBS Studio Setup**:
  - Application: OBS Studio 32.2.2 (64-bit mac).
  - Canvas & Profiles: Profile `basic.ini` sets Base Canvas at 1920x1080 (16:9) and Output at 1920x1080 @ 30 FPS.
  - Audio Topology: Audio monitoring device configured to `BlackHole 16ch` (`BlackHole16ch_UID`) at 48 kHz stereo.
- **OBS WebSocket Server**:
  - Version: 5.7.4 (RPC Version 1 protocol).
  - Bind: Port 4455.
  - Security: Authentication enabled (`auth_required: True`), password configured.
- **Scene Inventory & Transform Configuration (`Diag.json` active profile)**:
  - Active Scene: `Reolink Direct RTSP`.
  - Video Source: `Stage Camera (Direct RTSP)` (`ffmpeg_source`, ID 1):
    - Configured properties: `bounds_type: 2` (`OBS_BOUNDS_SCALE_INNER`), `bounds: {x: 1920.0, y: 1080.0}`, alignment: 5 (Top-Left), `pos: {0, 0}`, `scale: {1.0, 1.0}`, `crop: {0, 0, 0, 0}`.
    - Options: `rtsp_transport=tcp allowed_media_types=video fflags=nobuffer flags=low_delay use_wallclock_as_timestamps=1`.
    - Verification: OBS native inner bounds (`OBS_BOUNDS_SCALE_INNER`) automatically scales inner 16:9 crop boxes to fit the 1920x1080 canvas without manual pixel scaling distortion.
  - Audio Source: `Reolink Stage Mic (RTSP)` (`ffmpeg_source`, ID 10) configured with low-delay RTSP transport.
  - Secondary scenes on host: `Scene`, `TWITCH REPLAY`, `Box2 Live`, `Security Cams`, `Video Presentation Loop`, `Chess Arena`.
- **Camera & NVR Topology**:
  - Reolink RLC-823A camera delivers low-delay RTSP directly to OBS over TCP.
  - NVR recording is independently maintained on LAN; live OBS crop proposals do not alter camera PTZ firmware, NVR storage, or recording schedules.

### 3. Readiness for Next Step
- Automated tracking and OBS transform translation logic are hardened, verified by 63 passing unit tests and offline fixtures.
- Ready for: **Isolated Prerecorded-Video Framing Test** (feeding an offline recorded performance video into an isolated test scene to evaluate visual framing, zoom speeds, and transition aesthetics before any live hardware control).

## Milestone 4: Visual Framing Proof & OBS Transform Strategy Validation (PR #9 Third Review)

Status: **Implemented, offline tested, visually verified with synthetic 4K media and disposable OBS profile**.

### 1. Ambiguous Subject Confirmation Hardening (`tracking.py`)
- **Loophole Closed**: In `PerformerTracker.confirm_subject()`, calling with `box=None` while in `AMBIGUOUS` or `LOST` state is strictly rejected (`return False`).
- **Policy Enforced**: Clearing ambiguity requires explicit selection of a specific onstage bounding box (`box is not None and stage_polygon.contains_box(box)`). An operator cannot clear the ambiguity gate without identifying who the performer is.
- **Regression Test**: Added failing test `test_ambiguous_no_box_confirm_rejected_and_does_not_auto_acquire_stranger` verifying that:
  - Performer A is tracked -> lost > 2s -> Stranger B appears in A's prior position -> tracker enters `AMBIGUOUS`.
  - Operator calls `confirm_subject(None)` -> rejected (`False`), state remains `AMBIGUOUS`.
  - Subsequent frames with stranger B do NOT auto-acquire B.
  - Only explicit `confirm_subject(person_b)` acquires and tracks B.

### 2. Synthetic 4K Calibration Test Pattern (`stage_director/test_pattern.py`)
- Generated native 3840×2160 (16:9) reference calibration image at `stage_director/fixtures/synthetic_stage_4k.png`:
  - 100px / 500px coordinate grid with labeled coordinates.
  - Diagonal corner-to-corner fiducials (slope = 9/16 = 0.5625) to expose non-uniform stretching.
  - 16:9 outer boundary frame and corner ticks.
  - Authorized stage polygon boundary outline in cyan.
  - Concentric calibration circles centered at (1920, 1080) that reveal aspect distortion (eccentricity > 1.000).
  - Primary performer face target `(1800, 750, 240, 300)` and torso/microphone guideline at center stage.
  - Offstage audience bystander `(100, 1200, 120, 160)` outside the stage boundary.

### 3. Transform Strategy Evaluation & Libobs Compositor Verification (`stage_director/visual_test_harness.py`)
Tested three OBS transform strategies rendering the 4K source onto a broadcast 1920×1080 canvas:

| Metric | Strategy (a): Bounds Inner, Crop Only | Strategy (b): Explicit Scale, No Bounds | Strategy (c): Combined Scale + Bounds Inner |
| :--- | :--- | :--- | :--- |
| **OBS `boundsType`** | `OBS_BOUNDS_SCALE_INNER` | `OBS_BOUNDS_NONE` | `OBS_BOUNDS_SCALE_INNER` |
| **Request `scaleX, scaleY`** | `(1.0, 1.0)` | `(0.7202, 0.7200)` | `(0.7202, 0.7200)` |
| **Request `boundsWidth, boundsHeight`** | `1920.0, 1080.0` | `0.0, 0.0` | `1920.0, 1080.0` |
| **Libobs effective scale** | `(0.7200, 0.7200)` | `(0.7202, 0.7200)` | `(0.72018, 0.71998)` |
| **Rendered Canvas Size** | `1920 × 1080` | `1920 × 1080` | `1920 × 1080` |
| **Canvas Fill %** | **100.0%** | **100.0%** | **100.0%** |
| **Aspect Ratio Error** | **0.000%** | 0.014% (float rounding) | 0.014% (aspect fighting) |
| **Double-Scaling Risk** | **None** (direct shader scale) | None (direct scale) | **Present** (`mul = 0.99997` rescaled by libobs) |
| **Letterbox / Clipping** | **None** | None | None |

**Determination**:
- **Strategy (a) (`OBS_BOUNDS_SCALE_INNER` with crop only, scale=1.0)** is the mathematically pure, officially intended architecture for OBS bounding box scaling.
- In libobs (`obs-scene.c` lines 446–476), when `bounds_type == OBS_BOUNDS_SCALE_INNER`, OBS calculates `mul = bounds.x / visible_width` and performs the hardware scaling directly to fill the canvas.
- Passing explicit `scale` alongside `bounds_type: 2` (Strategy c) introduces floating-point division roundoff differences between horizontal and vertical scales, causing libobs to recalculate `mul` and double-scale.
- Strategy (a) matches the exact properties already observed in production `Diag.json` (`bounds_type: 2`, `bounds: 1920x1080`, `scale: 1.0`).

### 4. Framing Geometry and Rollback Measurements
- **Canvas Centering**: On the 1920×1080 broadcast canvas, the rendered performer center is at `x = 959.8 px` vs target `960.0 px` (**centering error: -0.24 px**, subpixel accuracy).
- **Headroom Guideline**: Face top rendered at `y = 248.4 px` within comfortable medium shot framing.
- **Rollback Restoration**: Transforming back from active medium shot to initial safe-wide via `restore_transform_request()` was compared against the initial wide frame using bitwise difference (`ImageChops.difference`). **Rollback fidelity is bit-for-bit exact (`diff.getbbox() is None`)**.
- **Rendered Reference Previews**: Generated and saved in `stage_director/fixtures/`:
  - `rendered_stage_wide_1080p.png`
  - `rendered_medium_shot_strategy_a_1080p.png`
  - `rendered_medium_shot_strategy_b_1080p.png`
  - `rendered_medium_shot_strategy_c_1080p.png`
  - `rendered_restored_wide_1080p.png`

### 5. Disposable OBS Profile & Scene Collection (`stage_director/obs_disposable_env.py`)
- Created completely isolated, disposable test configuration:
  - Profile: `StageDirector_Test` (`~/Library/Application Support/obs-studio/basic/profiles/StageDirector_Test/basic.ini`) configured with 1920×1080 @ 30 FPS, no stream keys, no recording destinations, and no audio inputs.
  - Scene Collection: `StageDirector_Test.json` (`~/Library/Application Support/obs-studio/basic/scenes/StageDirector_Test.json`) containing a single scene `"Stage Director Test Scene"` with one `image_source` pointing to `fixtures/synthetic_stage_4k.png`.
- **Production Isolation Verified**:
  - `Diag.json`, `Untitled.json`, and `user.ini` were checked and verified **completely untouched**.
  - Safe launch command for independent manual inspection:
    ```bash
    /Applications/OBS.app/Contents/MacOS/OBS --profile StageDirector_Test --collection StageDirector_Test
    ```

### 6. Verification Commands & Evidence
- Run all 67 tests (including visual framing suite and isolation checks):
  ```bash
  python3 -m unittest discover -s stage_director/tests -v
  ```
  Result: 67 tests passed in 0.272s.
- Run standalone visual comparison harness:
  ```bash
  python3 -m stage_director.visual_test_harness
  ```
- Run disposable OBS environment validator:
  ```bash
  python3 -m stage_director.obs_disposable_env
  ```
- Run OBS request fixture:
  ```bash
  python3 -m stage_director.obs_request_fixture
  ```
- Run synthetic framing simulator:
  ```bash
  python3 -m stage_director.simulate_framing
  ```

## Milestone 5: Jetson Orin Nano 8GB Feasibility Benchmark & Code Hardening

Addressed all Milestone 4 review findings, implemented safety regressions with negative tests, and executed an empirical hardware benchmark on the physical Jetson Orin Nano [Edge Device / Jetson Orin Nano 8GB]:

### 1. Safety Regressions & Negative Tests Completed
- **Strict OBS Isolation & Symlink Protection (`obs_disposable_env.py`)**:
  - The production-root guard resolves paths using `os.path.realpath()` and compares against the production directory tree using `os.path.commonpath()`. Refuses to write into the production root or any of its subdirectories/descendants, including symlink escapes.
  - Removed the `allow_production_root` escape hatch; test paths must be strictly anchored outside the production OBS tree.
  - Added overwrite safeguard: if *either* `profile_ini_path` or `scene_json_path` exists when `overwrite=False`, raises `FileExistsError` before touching any files.
- **OBS Transform Validation (`obs_transform.py`)**:
  - Validates `strategy` against `VALID_STRATEGIES = {"bounds_inner", "explicit_scale", "combined"}`; raises `ValueError` on unknown strategies (no silent fallback).
  - Validates canvas dimensions, source dimensions, and crop values; raises `ValueError` on negative, non-finite (`NaN`/`inf`), or out-of-bounds crops.
  - Maintained `bounds_inner` as the default strategy.
- **Test Suite**: 72 automated unit and regression tests pass in 0.29s (`python3 -m unittest discover -s stage_director/tests -v`).

### 2. Live Baseline Audit: Existing `box2-stream.py` Service
A non-invasive read-only audit of the running service on the Jetson Orin Nano revealed:
- **Architecture**: `box2-stream.py` ingests an HTTP-FLV sub-stream from the NVR and runs FFmpeg with `-c:v copy -c:a aac` to Twitch.
- **Nature**: Pure **passthrough / remux** of the camera's 640×360 sub-stream at 10.01 FPS. It does **not** decode or encode video on the Jetson.
- **Resource Footprint**: Consumes ~1.1% of total system CPU and ~70 MB RSS. Uptime > 40 hours.
- **Safety**: Benchmarking in parallel leaves ~98.9% CPU capacity and ~4.6 GB RAM available, avoiding interference with the running stream.

### 3. Jetson Orin Nano 8GB Empirical Benchmark Results
Full report documented in [`docs/JETSON_BENCHMARK_REPORT.md`](JETSON_BENCHMARK_REPORT.md) and benchmark scripts at `tools/jetson/jetson_pipeline_test.py` and `tools/jetson/benchmark_jetson_encoding.py`:

- **Hardware & Environment**:
  - NVIDIA Jetson Orin Nano Developer Kit Super (8GB) running L4T R39.2.1 (**JetPack 7.2.1**) on Ubuntu 24.04.4 LTS (Linux 6.8.12-1021-tegra, aarch64).
  - 6-core ARM Cortex-A78AE CPU @ up to 1.728 GHz in 25W MAXN power mode.
  - Silicon Capabilities: NVDEC hardware decoder present; **no NVENC in silicon** (software H.264 encode required).
- **Stage Director Real Python Engine Latency**:
  - Executed 1,800 frames of real `StageFramingAdapter` + `PerformerTracker` + `FramingEngine` + `OBSProposal` logic.
  - Latency: **111.6 µs per frame** (throughput: **8,960.3 FPS**).
  - Consumes only **0.33%** of the 33.3 ms frame budget.
- **Edge Face Detection Cost Across Resolutions**:
  - Native 4K (3840×2160): **497.6 ms** (2.0 FPS) — CPU 4K detection is unviable.
  - 1080p (1920×1080): **138.9 ms** (7.2 FPS) — CPU 1080p detection is unviable.
  - Sub-stream (640×360): **25.9 ms** (38.7 FPS) — **Real-time viable**.
  - Architectural rule: Face detection must run on the camera's 640×360 sub-stream or asynchronously via TensorRT/GPU, while Stage Director tracking interpolates at 30 FPS.
- **Continuous Synthetic AV Pipeline Performance**:
  - Complete GStreamer pipeline (Source 4K H.264 -> NVDEC `nvv4l2decoder` -> NVMM `nvvidconv compute-hw=1` dynamic crop/resize -> NVMM-to-CPU transfer -> `x264enc veryfast` @ 4500k -> 48kHz AAC mux -> local sink).
  - Sustained **42.7 FPS (1.42× real-time headroom)** with 0 dropped frames.
  - Thermal rise: **-0.6°C** (peaking at **49.2°C**, 35°C below throttle threshold).
  - Impact on live `box2-stream.py`: **Zero**. Stream continued uninterrupted.
- **Overall Assessment**: **CONDITIONAL PASS** for 1080p30 autonomous broadcast on a single Jetson Orin Nano, subject to live camera RTSP network jitter and booking snapshot synchronization tests.

## Milestone 6: Jetson-Native Autonomous Video Framing Pipeline & Empirical Validation

Executed the first physical, real-time paced autonomous auto-framing pipeline natively on the NVIDIA Jetson Orin Nano 8GB [Edge Device / Jetson Orin Nano 8GB], fulfilling all Milestone 6 review findings:

### 1. `JetsonFramePipeline` Engine (`stage_director/jetson_pipeline.py`)
- Bridges `StageFramingAdapter` decisions directly into continuous video rendering and H.264/AAC pipe encoding.
- Guarantees strictly **1920×1080 @ 30.0 FPS** broadcast canvas output with monotonic PTS.
- Decouples dynamic 16:9 slice calculations from GStreamer pipeline mutations, preventing caps renegotiation errors.
- Immediate fail-closed blackout upon operator emergency stop or missing consent, emitting bit-for-bit black frames ($mean\_lum = 0.00$).

### 2. Physical 75-Second Real-Time Paced Validation Run
- **Test File**: Written to local sandboxed MP4 (15.09 MB; SHA-256: `ed79645bb06bcb946bc90cbd4359fb45132e677623c785ab262e1bf8c173df90`).
- **Timing & Cadence**: **2,250 frames processed in 75.05s** (speed ratio: **1.00× / 30.0 FPS**). Monotonic PTS verified by `ffprobe` across all 2,250 packets (max jitter: **0.067 ms**).
- **Dynamic 8-Phase Scenario Verified**:
  1. *Arm & Host Start*: Safe-wide holds until host confirmation at 1.0s safely transitions to medium shot ($1.6\times$ zoom).
  2. *Smooth Pacing Tracking*: Follows moving performer ($x=1500 \rightarrow 2400$) with rate-limited pan/tilt.
  3. *Offstage Bystander Rejection*: Bystander at $x=150$ outside stage polygon is strictly ignored.
  4. *Secondary Onstage & Operator Switch*: Guest comic ($x=2700$) ignored until explicit operator command `switch_second` at 35.0s cleanly transfers camera lock.
  5. *Subject Loss Hold & Safe-Wide Fallback*: Performer loss triggers 2.0s hold; expiration smoothly returns to safe wide.
  6. *Seamless Reacquisition*: Returning performer reacquired cleanly without sudden snaps.
  7. *Countdown Cues*: Suggested cues `warn_60`, `warn_15`, and `time_up` emitted at their respective countdown thresholds.
  8. *Emergency Blackout*: Operator emergency stop at 70.0s immediately forces solid black canvas.
- **Transition Stills**: 11 PNG stills captured across all transitions in [`tools/jetson/stills/`](../tools/jetson/stills/).

### 3. Decoupled Face Detection Benchmark (Face-Positive Stimuli)
Tested installed OpenCV Haar cascade on a synthetic facial stimulus across resolutions:
- Native 4K: 577.1 ms (1.7 FPS, TP: 1, FP: 0) — unviable inline.
- 1080p: 170.1 ms (5.9 FPS, TP: 1, FP: 0) — unviable inline.
- qHD 540p: 65.9 ms (15.2 FPS, TP: 1, FP: 0) — borderline.
- Sub-stream 360p: 34.9 ms (28.7 FPS, TP: 1, FP: 0) — **Viable for decoupled/async inference**.

### 4. Telemetry & Live Service Baseline Continuity
- **Tegrastats (75 1-second samples)**:
  - Average CPU load: **51.8%** across 6 cores.
  - RAM used: **2,879.5 MB mean** (38.5% utilization, 4.55 GB free).
  - Swap: **1,034 MB static** (zero swap allocation).
  - Thermals: CPU mean **48.0°C** (peak 48.8°C), 36.2°C below 85°C throttle threshold.
  - Power: Mean **6.72 W** (peak 7.41 W) of 25.0 W budget.
- **Live Baseline Service Continuity (`box2_stream.py`)**:
  - Audited before (`19-22:42:46` uptime) and after (`19-22:44:16` uptime).
  - **Zero restarts, zero dropped frames, PID 266619 uninterrupted**.
- **Automated Tests**: All 77 unit and regression tests pass natively on Jetson (`python3 -m unittest discover -s stage_director/tests -v`).

## Integration steps only after read-only audits

1. Verify installed Reolink firmware/control support, whether direct camera vs NVR RTSP is used, and PTZ limits; first test physical PTZ offline.
2. Verify OBS host, scenes, video transforms, installed OBS WebSocket and studio isolation from a separate Twitch viewer.
3. Design a short-lived authenticated, **Jetson-pulled** minimal booking snapshot; do not scrape the public schedule or provide any web-to-OBS control endpoint.
4. Measure clock offsets, stream buffering, stage framing jitter/latency and end-cue channel routing.
5. Host-arm an expressly consenting test set only after privacy and scene-recovery tests succeed.

## Failure policy

Uncertainty means **no room capture, no broadcast identity, no alarm and no physical PTZ movement**. A scheduled slot does not establish who is present; detection does not establish permission. Preserve the existing ability to run house-only media or stop the broadcast when a private session cannot be isolated.
