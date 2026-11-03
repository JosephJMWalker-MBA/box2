#!/usr/bin/env python3
"""BOX2 read-only OBS WebSocket probe.

Connects to OBS Studio's built-in WebSocket server (obs-websocket 5.x, OBS 28+)
and reports what OBS says about itself: version and platform, scenes, the
current program scene, which sources are reachable from it, audio mute state,
and stream/record/virtual-camera status. With --watch it stays connected and
prints scene/output/mute changes as timestamped JSON lines.

It is read-only by construction: every request passes through an allowlist of
"Get" request types, so the probe cannot switch scenes, start or stop outputs,
or change settings. It never requests input settings or stream-service
settings, which can hold camera RTSP credentials or the Twitch stream key, and
in --watch mode it prints only allowlisted fields of allowlisted events.

Standard library only (Python 3.8+), so it runs on a stock JetPack image.

Password: set OBS_WS_PASSWORD in the environment, or type it at the prompt.
There is deliberately no --password flag (it would land in shell history and
the process list).

Exit codes: 0 ok, 2 cannot connect, 3 authentication failed/missing,
4 protocol error, 5 read-only guard tripped.
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import getpass
import hashlib
import json
import os
import socket
import struct
import sys
import time
import uuid

RPC_VERSION = 1
DEFAULT_PORT = 4455
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# The only requests this probe may send. All are documented obs-websocket
# 5.x requests that read state. Deliberately absent: GetInputSettings,
# GetStreamServiceSettings, GetProfileParameter, GetPersistentData and
# GetSourceScreenshot (credentials, stream key, private pixels), plus every
# Set*/Start*/Stop*/Toggle*/Trigger*/Create*/Remove* request.
READ_ONLY_REQUESTS = frozenset(
    {
        "GetVersion",
        "GetStats",
        "GetSceneList",
        "GetCurrentProgramScene",
        "GetStudioModeEnabled",
        "GetSceneItemList",
        "GetGroupSceneItemList",
        "GetInputList",
        "GetSpecialInputs",
        "GetInputMute",
        "GetStreamStatus",
        "GetRecordStatus",
        "GetVirtualCamStatus",
        "GetReplayBufferStatus",
    }
)

# Events printed in --watch mode, and the only fields of each that are kept.
# Anything else OBS sends (e.g. InputSettingsChanged, which carries input
# settings that may include camera credentials) is dropped unread.
WATCH_EVENT_FIELDS = {
    "CurrentProgramSceneChanged": ("sceneName",),
    "CurrentPreviewSceneChanged": ("sceneName",),
    "StudioModeStateChanged": ("studioModeEnabled",),
    "StreamStateChanged": ("outputActive", "outputState"),
    "RecordStateChanged": ("outputActive", "outputState"),
    "ReplayBufferStateChanged": ("outputActive", "outputState"),
    "VirtualcamStateChanged": ("outputActive", "outputState"),
    "SceneItemEnableStateChanged": ("sceneName", "sceneItemId", "sceneItemEnabled"),
    "InputMuteStateChanged": ("inputName", "inputMuted"),
    "SceneNameChanged": ("oldSceneName", "sceneName"),
    "SceneCreated": ("sceneName",),
    "SceneRemoved": ("sceneName",),
    "ExitStarted": (),
}

# EventSubscription bits from the obs-websocket 5.x protocol.
_SUB_GENERAL = 1 << 0
_SUB_SCENES = 1 << 2
_SUB_INPUTS = 1 << 3
_SUB_OUTPUTS = 1 << 6
_SUB_SCENE_ITEMS = 1 << 7
_SUB_UI = 1 << 10
WATCH_SUBSCRIPTIONS = (
    _SUB_GENERAL | _SUB_SCENES | _SUB_INPUTS | _SUB_OUTPUTS | _SUB_SCENE_ITEMS | _SUB_UI
)

_CLOSE_AUTH_FAILED = 4009
_CLOSE_UNSUPPORTED_RPC = 4010

_GLOBAL_AUDIO_LABELS = {
    "desktop1": "Desktop Audio",
    "desktop2": "Desktop Audio 2",
    "mic1": "Mic/Aux",
    "mic2": "Mic/Aux 2",
    "mic3": "Mic/Aux 3",
    "mic4": "Mic/Aux 4",
}


class ProbeError(Exception):
    exit_code = 4


class ConnectFailed(ProbeError):
    exit_code = 2


class AuthFailed(ProbeError):
    exit_code = 3


class ReadOnlyViolation(ProbeError):
    exit_code = 5


class ServerClosed(ProbeError):
    def __init__(self, code, reason):
        super().__init__("OBS closed the connection (code %s%s)" % (code, ": " + reason if reason else ""))
        self.code = code
        self.reason = reason


def utc_now() -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def auth_response(password: str, salt: str, challenge: str) -> str:
    """obs-websocket 5.x: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode("utf-8")).digest()).decode("ascii")


class WebSocket:
    """Minimal RFC 6455 client: text frames, fragmentation, ping/pong, close."""

    def __init__(self, host: str, port: int, timeout: float):
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise ConnectFailed("cannot reach %s:%s (%s)" % (host, port, exc)) from exc
        self._buf = b""
        self._frag_opcode = None
        self._frag_parts = []
        self.closed = False
        try:
            self._handshake(host, port)
        except BaseException:
            self.sock.close()
            raise

    def _handshake(self, host: str, port: int) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host_header = "[%s]:%d" % (host, port) if ":" in host else "%s:%d" % (host, port)
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: %s\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: obswebsocket.json\r\n"
            "User-Agent: box2-obs-probe\r\n\r\n" % (host_header, key)
        )
        try:
            self.sock.sendall(request.encode("ascii"))
            while b"\r\n\r\n" not in self._buf:
                if len(self._buf) > 16384:
                    raise ProbeError("oversized HTTP upgrade response")
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectFailed("connection closed during WebSocket handshake")
                self._buf += chunk
        except socket.timeout as exc:
            raise ConnectFailed("timed out during WebSocket handshake") from exc
        except OSError as exc:
            raise ConnectFailed("WebSocket handshake failed (%s)" % exc) from exc
        head, self._buf = self._buf.split(b"\r\n\r\n", 1)
        lines = head.decode("iso-8859-1").split("\r\n")
        status = lines[0].split(" ", 2)
        if len(status) < 2 or status[1] != "101":
            raise ConnectFailed(
                "endpoint answered %r instead of a WebSocket upgrade; is this the OBS WebSocket port?" % lines[0]
            )
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise ProbeError("WebSocket handshake returned a bad Sec-WebSocket-Accept")

    def _fill(self, n: int) -> None:
        # Leaves already-received bytes in the buffer if recv times out, so a
        # timeout between frames never corrupts the stream.
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                self.closed = True
                raise ConnectionError("connection closed by OBS")
            self._buf += chunk

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytes([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header += bytes([0x80 | length])
        elif length < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def _read_frame(self):
        self._fill(2)
        b0, b1 = self._buf[0], self._buf[1]
        fin, opcode = bool(b0 & 0x80), b0 & 0x0F
        masked, length = bool(b1 & 0x80), b1 & 0x7F
        offset = 2
        if length == 126:
            self._fill(4)
            length = struct.unpack("!H", self._buf[2:4])[0]
            offset = 4
        elif length == 127:
            self._fill(10)
            length = struct.unpack("!Q", self._buf[2:10])[0]
            offset = 10
        if length > MAX_MESSAGE_BYTES:
            raise ProbeError("frame of %d bytes exceeds limit" % length)
        mask_len = 4 if masked else 0
        self._fill(offset + mask_len + length)
        mask = self._buf[offset : offset + mask_len]
        payload = self._buf[offset + mask_len : offset + mask_len + length]
        self._buf = self._buf[offset + mask_len + length :]
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def recv_text(self) -> str:
        while True:
            fin, opcode, payload = self._read_frame()
            if opcode == 0x8:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
                reason = payload[2:].decode("utf-8", "replace")
                self.closed = True
                try:
                    self._send_frame(0x8, payload[:2])
                except OSError:
                    pass
                raise ServerClosed(code, reason)
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                if self._frag_opcode is not None:
                    raise ProbeError("new data frame inside a fragmented message")
                if fin:
                    if opcode != 0x1:
                        raise ProbeError("unexpected binary frame (expected obswebsocket.json text)")
                    return payload.decode("utf-8")
                self._frag_opcode, self._frag_parts = opcode, [payload]
                continue
            if opcode == 0x0:
                if self._frag_opcode is None:
                    raise ProbeError("continuation frame without a message")
                self._frag_parts.append(payload)
                if sum(len(p) for p in self._frag_parts) > MAX_MESSAGE_BYTES:
                    raise ProbeError("fragmented message exceeds limit")
                if fin:
                    data, first = b"".join(self._frag_parts), self._frag_opcode
                    self._frag_opcode, self._frag_parts = None, []
                    if first != 0x1:
                        raise ProbeError("unexpected binary message")
                    return data.decode("utf-8")
                continue
            raise ProbeError("unknown WebSocket opcode %d" % opcode)

    def settimeout(self, seconds) -> None:
        self.sock.settimeout(seconds)

    def close(self) -> None:
        if not self.closed:
            try:
                self._send_frame(0x8, struct.pack("!H", 1000))
            except OSError:
                pass
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass


class ObsClient:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.events = []
        self.auth_required = None
        self.sent_requests = []

    def _recv(self) -> dict:
        try:
            raw = self.ws.recv_text()
        except ServerClosed as exc:
            if exc.code == _CLOSE_AUTH_FAILED:
                raise AuthFailed("OBS rejected the WebSocket password") from exc
            if exc.code == _CLOSE_UNSUPPORTED_RPC:
                raise ProbeError("OBS does not support obs-websocket RPC version 1") from exc
            raise
        try:
            msg = json.loads(raw)
        except ValueError as exc:
            raise ProbeError("OBS sent invalid JSON") from exc
        if not isinstance(msg, dict) or not isinstance(msg.get("op"), int) or not isinstance(msg.get("d"), dict):
            raise ProbeError("OBS sent a malformed message")
        return msg

    def identify(self, password_source, event_subscriptions: int) -> dict:
        hello = self._recv()
        if hello["op"] != 0:
            raise ProbeError("expected Hello (op 0), got op %s" % hello["op"])
        d = hello["d"]
        identify = {"rpcVersion": RPC_VERSION, "eventSubscriptions": event_subscriptions}
        challenge = d.get("authentication")
        self.auth_required = bool(challenge)
        if challenge:
            password = password_source()
            if password is None:
                raise AuthFailed("OBS requires a password: set OBS_WS_PASSWORD or run interactively")
            identify["authentication"] = auth_response(password, challenge["salt"], challenge["challenge"])
        self.ws.send_text(json.dumps({"op": 1, "d": identify}))
        identified = self._recv()
        if identified["op"] != 2:
            raise ProbeError("expected Identified (op 2), got op %s" % identified["op"])
        return d

    def request(self, request_type: str, data=None):
        """Returns (ok, responseData, requestStatus). Refuses non-allowlisted requests."""
        if request_type not in READ_ONLY_REQUESTS:
            raise ReadOnlyViolation("refusing to send non-read-only request %r" % request_type)
        request_id = uuid.uuid4().hex
        body = {"requestType": request_type, "requestId": request_id}
        if data:
            body["requestData"] = data
        self.sent_requests.append(request_type)
        self.ws.send_text(json.dumps({"op": 6, "d": body}))
        while True:
            msg = self._recv()
            if msg["op"] == 5:
                self.events.append(msg["d"])
                continue
            if msg["op"] == 7 and msg["d"].get("requestId") == request_id:
                status = msg["d"].get("requestStatus") or {}
                return bool(status.get("result")), msg["d"].get("responseData") or {}, status

    def next_event(self) -> dict:
        if self.events:
            return self.events.pop(0)
        while True:
            msg = self._recv()
            if msg["op"] == 5:
                return msg["d"]


def _connect(host, port, timeout, password_source, subscriptions):
    ws = WebSocket(host, port, timeout)
    client = ObsClient(ws)
    try:
        client.identify(password_source, subscriptions)
    except socket.timeout as exc:
        ws.close()
        raise ConnectFailed("timed out waiting for OBS to identify the session") from exc
    except BaseException:
        ws.close()
        raise
    return client


def _walk_scene(client, scene_name, is_group, path, depth, visited, out_visible, out_hidden):
    if depth > 8 or (scene_name, is_group) in visited:
        return
    visited.add((scene_name, is_group))
    request = "GetGroupSceneItemList" if is_group else "GetSceneItemList"
    ok, data, _ = client.request(request, {"sceneName": scene_name})
    if not ok:
        return
    for item in data.get("sceneItems", []):
        name = item.get("sourceName")
        enabled = bool(item.get("sceneItemEnabled"))
        here = path + [name]
        nested = item.get("isGroup") or item.get("sourceType") == "OBS_SOURCE_TYPE_SCENE"
        if nested:
            if enabled:
                _walk_scene(client, name, bool(item.get("isGroup")), here, depth + 1, visited, out_visible, out_hidden)
            else:
                out_hidden.append({"path": " > ".join(here), "kind": "group" if item.get("isGroup") else "scene"})
            continue
        entry = {"source": name, "path": " > ".join(here), "kind": item.get("inputKind")}
        (out_visible if enabled else out_hidden).append(entry)


def take_snapshot(client: ObsClient, endpoint: str) -> dict:
    ok, version, _ = client.request("GetVersion")
    if not ok:
        raise ProbeError("GetVersion failed")
    available = set(version.get("availableRequests") or [])

    def get(request_type, data=None):
        if request_type not in available:
            return False, {}
        ok, resp, _ = client.request(request_type, data)
        return ok, resp

    snap = {
        "observed_at_utc": utc_now(),
        "probe_host": socket.gethostname(),
        "endpoint": endpoint,
        "auth_required": client.auth_required,
        "obs_version": version.get("obsVersion"),
        "obs_websocket_version": version.get("obsWebSocketVersion"),
        "platform": version.get("platform"),
        "platform_description": version.get("platformDescription"),
    }

    ok, scene_list = get("GetSceneList")
    snap["scenes"] = [s.get("sceneName") for s in scene_list.get("scenes", [])] if ok else None
    ok, program = get("GetCurrentProgramScene")
    snap["program_scene"] = (program.get("sceneName") or program.get("currentProgramSceneName")) if ok else None
    ok, studio = get("GetStudioModeEnabled")
    snap["studio_mode"] = studio.get("studioModeEnabled") if ok else None
    snap["preview_scene"] = scene_list.get("currentPreviewSceneName") if snap["studio_mode"] else None

    ok, stream = get("GetStreamStatus")
    snap["stream"] = (
        {k: stream.get(k) for k in ("outputActive", "outputReconnecting", "outputTimecode",
                                     "outputCongestion", "outputSkippedFrames", "outputTotalFrames")}
        if ok else None
    )
    ok, record = get("GetRecordStatus")
    snap["record"] = {k: record.get(k) for k in ("outputActive", "outputPaused", "outputTimecode")} if ok else None
    ok, vcam = get("GetVirtualCamStatus")
    snap["virtual_camera_active"] = vcam.get("outputActive") if ok else None
    ok, replay = get("GetReplayBufferStatus")
    snap["replay_buffer_active"] = replay.get("outputActive") if ok else None  # None: not configured
    ok, stats = get("GetStats")
    snap["stats"] = (
        {k: stats.get(k) for k in ("activeFps", "cpuUsage", "memoryUsage", "availableDiskSpace",
                                    "renderSkippedFrames", "renderTotalFrames",
                                    "outputSkippedFrames", "outputTotalFrames")}
        if ok else None
    )

    ok, inputs = get("GetInputList")
    input_rows = []
    for inp in inputs.get("inputs", []) if ok else []:
        name = inp.get("inputName")
        m_ok, mute = get("GetInputMute", {"inputName": name})
        input_rows.append({
            "name": name,
            "kind": inp.get("unversionedInputKind") or inp.get("inputKind"),
            "has_audio": m_ok,
            "muted": mute.get("inputMuted") if m_ok else None,
        })
    snap["inputs"] = input_rows
    audio = {row["name"]: row for row in input_rows if row["has_audio"]}

    ok, special = get("GetSpecialInputs")
    snap["global_audio"] = []
    for slot, label in _GLOBAL_AUDIO_LABELS.items():
        name = special.get(slot) if ok else None
        if name:
            row = audio.get(name, {})
            snap["global_audio"].append({"slot": label, "name": name, "muted": row.get("muted")})

    visible, hidden = [], []
    if snap["program_scene"]:
        _walk_scene(client, snap["program_scene"], False, [snap["program_scene"]], 0, set(), visible, hidden)
    for row in visible + hidden:
        if row.get("source") in audio:
            row["audio_muted"] = audio[row["source"]]["muted"]
    snap["program_visible_sources"] = visible
    snap["program_hidden_items"] = hidden

    snap["requests_sent"] = sorted(set(client.sent_requests))
    return snap


def _onoff(value, on="ON", off="off"):
    if value is None:
        return "unknown"
    return on if value else off


def render_text(snap: dict) -> str:
    lines = []
    add = lines.append
    add("BOX2 OBS read-only probe  %s  (probe host: %s)" % (snap["observed_at_utc"], snap["probe_host"]))
    add("Endpoint: %s   WebSocket auth: %s" % (
        snap["endpoint"], "required" if snap["auth_required"] else "DISABLED - enable a password in OBS"))
    add("OBS %s  obs-websocket %s  platform: %s (%s)" % (
        snap["obs_version"], snap["obs_websocket_version"], snap["platform"], snap["platform_description"]))
    add("")
    add("Program scene: %s" % snap["program_scene"])
    if snap["studio_mode"]:
        add("Studio mode: ON  (preview scene: %s)" % snap["preview_scene"])
    else:
        add("Studio mode: %s" % _onoff(snap["studio_mode"]))
    s = snap["stream"]
    if s:
        detail = ""
        if s["outputActive"]:
            detail = "  %s  reconnecting: %s  skipped frames: %s/%s" % (
                s["outputTimecode"], "yes" if s["outputReconnecting"] else "no",
                s["outputSkippedFrames"], s["outputTotalFrames"])
        add("Stream: %s%s" % (_onoff(s["outputActive"], "LIVE"), detail))
    r = snap["record"]
    add("Record: %s   Virtual camera: %s   Replay buffer: %s" % (
        (_onoff(r["outputActive"]) + (" (paused)" if r and r.get("outputPaused") else "")) if r else "unknown",
        _onoff(snap["virtual_camera_active"]),
        "not configured" if snap["replay_buffer_active"] is None else _onoff(snap["replay_buffer_active"])))
    add("")
    scenes = snap["scenes"] or []
    add("Scenes (%d):" % len(scenes))
    for name in scenes:
        add("  %s %s" % ("*" if name == snap["program_scene"] else " ", name))
    add("")
    add("Visible in program scene (as OBS reports it):")
    if not snap["program_visible_sources"]:
        add("  (none)")
    for row in snap["program_visible_sources"]:
        audio = ""
        if "audio_muted" in row:
            audio = "  audio: %s" % ("muted" if row["audio_muted"] else "UNMUTED")
        add("  - %s  [%s]%s" % (row["path"], row["kind"], audio))
    if snap["program_hidden_items"]:
        add("Present in program scene but hidden (check their audio by ear):")
        for row in snap["program_hidden_items"]:
            audio = ""
            if row.get("audio_muted") is False:
                audio = "  audio input UNMUTED"
            add("  - %s  [%s]%s" % (row["path"], row["kind"], audio))
    add("Global audio devices (mixed into every scene unless muted):")
    if not snap["global_audio"]:
        add("  (none configured)")
    for row in snap["global_audio"]:
        add("  - %s: %s  %s" % (row["slot"], row["name"], "muted" if row["muted"] else
                                "UNMUTED" if row["muted"] is False else "unknown"))
    add("")
    add("Not verified by this probe: what Twitch viewers actually receive, stream delay,")
    add("audio monitoring/track routing, and recording by the cameras/NVR themselves.")
    add("Read-only requests sent: %s" % ", ".join(snap["requests_sent"]))
    return "\n".join(lines)


def _emit(record: dict) -> None:
    print(json.dumps(record, sort_keys=True), flush=True)


def watch(host, port, timeout, password_source, heartbeat: float) -> int:
    endpoint = "%s:%d" % (host, port)
    backoff = 2.0
    while True:
        try:
            client = _connect(host, port, timeout, password_source, WATCH_SUBSCRIPTIONS)
        except AuthFailed:
            raise
        except (ProbeError, OSError) as exc:
            _emit({"observed_at_utc": utc_now(), "endpoint": endpoint, "event_type": "probe_connect_failed",
                   "data": {"error": str(exc), "retry_in_s": backoff}})
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue
        backoff = 2.0
        last_scene = None
        try:
            ok, version, _ = client.request("GetVersion")
            ok2, program, _ = client.request("GetCurrentProgramScene")
            last_scene = program.get("sceneName") if ok2 else None
            ok3, stream, _ = client.request("GetStreamStatus")
            _emit({"observed_at_utc": utc_now(), "endpoint": endpoint, "event_type": "probe_connected",
                   "data": {"obsVersion": version.get("obsVersion"), "platform": version.get("platform"),
                            "sceneName": last_scene,
                            "streamActive": stream.get("outputActive") if ok3 else None}})
            client.ws.settimeout(heartbeat)
            while True:
                try:
                    event = client.next_event()
                except socket.timeout:
                    # Quiet period: confirm OBS still answers and our view of the
                    # program scene is not stale.
                    client.ws.settimeout(timeout)
                    ok, program, _ = client.request("GetCurrentProgramScene")
                    client.ws.settimeout(heartbeat)
                    scene = program.get("sceneName") if ok else None
                    if scene != last_scene:
                        _emit({"observed_at_utc": utc_now(), "endpoint": endpoint,
                               "event_type": "probe_state_reconciled",
                               "data": {"previousSceneName": last_scene, "sceneName": scene}})
                        last_scene = scene
                    continue
                event_type = event.get("eventType")
                fields = WATCH_EVENT_FIELDS.get(event_type)
                if fields is None:
                    continue
                data = event.get("eventData") or {}
                kept = {k: data.get(k) for k in fields if k in data}
                if event_type == "CurrentProgramSceneChanged":
                    last_scene = kept.get("sceneName")
                _emit({"observed_at_utc": utc_now(), "endpoint": endpoint,
                       "event_type": event_type, "data": kept})
        except (ProbeError, OSError, ConnectionError) as exc:
            if isinstance(exc, (AuthFailed, ReadOnlyViolation)):
                raise
            _emit({"observed_at_utc": utc_now(), "endpoint": endpoint, "event_type": "probe_disconnected",
                   "data": {"error": str(exc) or exc.__class__.__name__, "lastSceneName": last_scene}})
            client.ws.close()
            time.sleep(backoff)


def _password_source_factory():
    cache = {}

    def source():
        if "pw" in cache:
            return cache["pw"]
        pw = os.environ.get("OBS_WS_PASSWORD")
        if pw is None and sys.stdin.isatty():
            pw = getpass.getpass("OBS WebSocket password: ")
        cache["pw"] = pw
        return pw

    return source


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only OBS WebSocket probe for BOX2. Sends only allowlisted Get* requests.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="OBS computer address (default 127.0.0.1; use the Mac mini's LAN IP if OBS runs there)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="OBS WebSocket port (default 4455)")
    parser.add_argument("--timeout", type=float, default=5.0, help="network timeout in seconds (default 5)")
    parser.add_argument("--json", action="store_true", help="print the snapshot as JSON")
    parser.add_argument("--watch", action="store_true",
                        help="stay connected and print scene/output/mute changes as JSON lines")
    parser.add_argument("--heartbeat", type=float, default=15.0,
                        help="--watch: seconds of quiet before re-checking the program scene (default 15)")
    args = parser.parse_args(argv)

    password_source = _password_source_factory()
    try:
        if args.watch:
            return watch(args.host, args.port, args.timeout, password_source, args.heartbeat)
        client = _connect(args.host, args.port, args.timeout, password_source, 0)
        try:
            snap = take_snapshot(client, "%s:%d" % (args.host, args.port))
        finally:
            client.ws.close()
    except KeyboardInterrupt:
        return 0
    except socket.timeout:
        print("error: timed out waiting for OBS", file=sys.stderr)
        return ConnectFailed.exit_code
    except ProbeError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return exc.exit_code
    except (ConnectionError, OSError) as exc:
        print("error: connection lost (%s)" % exc, file=sys.stderr)
        return ConnectFailed.exit_code

    print(json.dumps(snap, indent=2, sort_keys=True) if args.json else render_text(snap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
