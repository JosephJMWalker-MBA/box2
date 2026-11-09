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

## Integration steps only after read-only audits

1. Verify installed Reolink firmware/control support, whether direct camera vs NVR RTSP is used, and PTZ limits; first test physical PTZ offline.
2. Verify OBS host, scenes, video transforms, installed OBS WebSocket and studio isolation from a separate Twitch viewer.
3. Design a short-lived authenticated, **Jetson-pulled** minimal booking snapshot; do not scrape the public schedule or provide any web-to-OBS control endpoint.
4. Measure clock offsets, stream buffering, stage framing jitter/latency and end-cue channel routing.
5. Host-arm an expressly consenting test set only after privacy and scene-recovery tests succeed.

## Failure policy

Uncertainty means **no room capture, no broadcast identity, no alarm and no physical PTZ movement**. A scheduled slot does not establish who is present; detection does not establish permission. Preserve the existing ability to run house-only media or stop the broadcast when a private session cannot be isolated.
