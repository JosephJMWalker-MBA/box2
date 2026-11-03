# Jetson ↔ OBS: read-only tools

Groundwork for the OBS dry run in [`docs/JETSON_OBS_EVENT_AND_HIGHLIGHTS.md`](../../docs/JETSON_OBS_EVENT_AND_HIGHLIGHTS.md) (proposed in PR #7). These tools **observe only**. They cannot switch scenes, start or stop the stream or recording, or change any OBS, camera or NVR setting. Scene control is a later, separately approved step.

Requirements: Python 3.8+ and bash (stock JetPack is fine). No pip installs.

## 1. Inventory the Jetson

```bash
bash tools/jetson/inventory.sh               # this machine only
bash tools/jetson/inventory.sh 192.168.1.20  # also test the OBS computer's port 4455
```

Reports OS/JetPack, clock sync, whether `obs`/`ffmpeg`/GStreamer exist and are running, matching services, containers and cron entries, listening ports, and whether an OBS WebSocket is reachable. Process and cron command lines are redacted, because ffmpeg/GStreamer arguments usually contain `rtsp://user:password@camera` URLs and the Twitch stream key. Redaction is best-effort, so read the output before sharing it.

## 2. Turn on the OBS WebSocket (on the computer running OBS)

OBS 28+ includes it: **Tools → WebSocket Server Settings → Enable WebSocket server**, keep **Enable Authentication** on, port `4455`, and use **Show Connect Info** to copy the password. If OBS is on the Mac mini, macOS may ask whether OBS may accept incoming connections. Allow it on the LAN only. **Never port-forward 4455 or expose it to the Internet or the website.**

## 3. Probe OBS

```bash
python3 tools/jetson/obs_probe.py --host 192.168.1.20          # prompts for the password
python3 tools/jetson/obs_probe.py --host 192.168.1.20 --json   # machine-readable snapshot
python3 tools/jetson/obs_probe.py --host 192.168.1.20 --watch | tee -a obs-events.jsonl
```

The password comes from the prompt or from `OBS_WS_PASSWORD`. There is deliberately no `--password` flag.

**Snapshot** shows the OBS version and **platform** (this answers "is OBS on the Jetson or the Mac?"), WebSocket auth on/off, all scenes, the program scene, which sources are visible in it (following nested scenes and groups), items present but hidden, mute state of each audio input including global Desktop/Mic devices, and stream/record/virtual-camera/replay-buffer status.

**Watch** stays connected and prints one JSON line per change: program/preview scene, stream/record/virtual-camera state, scene-item visibility, mute toggles. Each line is stamped with `observed_at_utc` (the Jetson's receive time, so NTP sync matters). On disconnect it logs `probe_disconnected` and reconnects with backoff. When idle it re-reads the program scene every `--heartbeat` seconds and logs `probe_state_reconciled` if it missed a change. These lines are raw observations, not entries in the proposed event ledger.

### Read-only by construction

- Every request goes through an allowlist of `Get*` request types (`READ_ONLY_REQUESTS`). Anything else raises an error **before** it is sent.
- It never requests `GetInputSettings`, `GetStreamServiceSettings`, `GetProfileParameter`, `GetPersistentData` or `GetSourceScreenshot`, which can return camera credentials, the stream key or room images.
- Watch mode keeps only allowlisted fields of allowlisted events. For example, `InputSettingsChanged` (which carries input settings) is dropped.

### What it does not prove

OBS's report is not proof of what Twitch viewers receive. It does not check stream delay, audio monitoring or track routing, or recording done independently by Reolink cameras, the NVR, an SD card or the cloud. The private-room isolation checks in `docs/PRIVATE_REHEARSAL_BROADCAST_CONTINUITY.md` still need a second receiving device.

Snapshot output includes scene names, source names and the LAN address. Review it before posting it anywhere public.

Exit codes: `0` ok, `2` cannot connect / not an OBS WebSocket, `3` password missing or rejected, `4` protocol error, `5` read-only guard tripped.

## Tests

```bash
python3 -I tools/jetson/test_obs_probe.py
```

The tests run against an in-process mock obs-websocket 5.x server. They cover auth, wrong or missing passwords, the write-request guard, large fragmented messages with interleaved pings, nested scenes and groups, event filtering (a planted camera password must not appear in output), reconnects and heartbeat reconciliation.
