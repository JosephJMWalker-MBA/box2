#!/usr/bin/env python3
"""Tests for obs_probe.py against an in-process mock obs-websocket 5.x server.

Run:  python3 -I tools/jetson/test_obs_probe.py
Standard library only; no OBS, network or camera access needed.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import obs_probe  # noqa: E402

PASSWORD = "test-pw"
SECRET_URL = "rtsp://admin:hunter2@192.0.2.10:554/h264Preview_01_main"
STREAM_KEY = "live_000000000_FAKEKEYFAKEKEY"


def _recv_exact(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError("client went away")
        data += chunk
    return data


def _server_frame(opcode, payload, fin=True):
    head = bytes([(0x80 if fin else 0) | opcode])
    n = len(payload)
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack("!H", n)
    else:
        head += bytes([127]) + struct.pack("!Q", n)
    return head + payload


class MockObs:
    """Speaks just enough obs-websocket 5.x to exercise the probe."""

    def __init__(self, password=PASSWORD, http_only=False, fragment_input_list=False):
        self.password = password
        self.http_only = http_only
        self.fragment_input_list = fragment_input_list
        self.requests = []
        self.identifies = []
        self.unmasked_client_frames = 0
        self.program_scene = "Reolink Stage"
        self.events_after_identify = []
        self.close_after_events = False
        self.connections = 0
        self.lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stopped = False
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self):
        self.stopped = True
        self.sock.close()

    def _accept_loop(self):
        while not self.stopped:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    # -- framing -------------------------------------------------------
    def _read_client_message(self, conn):
        b0, b1 = _recv_exact(conn, 2)
        opcode, masked, n = b0 & 0x0F, bool(b1 & 0x80), b1 & 0x7F
        if not masked:
            self.unmasked_client_frames += 1
        if n == 126:
            n = struct.unpack("!H", _recv_exact(conn, 2))[0]
        elif n == 127:
            n = struct.unpack("!Q", _recv_exact(conn, 8))[0]
        mask = _recv_exact(conn, 4) if masked else b"\0\0\0\0"
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(_recv_exact(conn, n)))
        return opcode, payload

    def _send(self, conn, obj, fragment=False):
        data = json.dumps(obj).encode()
        if not fragment:
            conn.sendall(_server_frame(0x1, data))
            return
        third = len(data) // 3
        conn.sendall(_server_frame(0x1, data[:third], fin=False))
        conn.sendall(_server_frame(0x9, b"keepalive"))  # control frame mid-message
        conn.sendall(_server_frame(0x0, data[third : 2 * third], fin=False))
        conn.sendall(_server_frame(0x0, data[2 * third :], fin=True))

    # -- protocol ------------------------------------------------------
    def _handle(self, conn):
        with self.lock:
            self.connections += 1
        try:
            req = b""
            while b"\r\n\r\n" not in req:
                req += conn.recv(4096)
            if self.http_only:
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
                return
            key = [l.split(":", 1)[1].strip() for l in req.decode().split("\r\n")
                   if l.lower().startswith("sec-websocket-key:")][0]
            accept = base64.b64encode(hashlib.sha1((key + obs_probe._WS_GUID).encode()).digest()).decode()
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Accept: %s\r\nSec-WebSocket-Protocol: obswebsocket.json\r\n\r\n"
                          % accept).encode())
            salt, challenge = "c2FsdHNhbHQ=", "Y2hhbGxlbmdl"
            self._send(conn, {"op": 0, "d": {"obsWebSocketVersion": "5.6.3", "rpcVersion": 1,
                                             "authentication": {"salt": salt, "challenge": challenge}}})
            _, payload = self._read_client_message(conn)
            identify = json.loads(payload)
            self.identifies.append(identify)
            secret = base64.b64encode(hashlib.sha256((self.password + salt).encode()).digest())
            expected = base64.b64encode(hashlib.sha256(secret + challenge.encode()).digest()).decode()
            if identify["d"].get("authentication") != expected:
                conn.sendall(_server_frame(0x8, struct.pack("!H", 4009) + b"Authentication failed."))
                return
            self._send(conn, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
            answered = 0
            while True:
                if answered == 3:
                    # The watch probe makes three state requests after connecting;
                    # push events (and optionally hang up) once those are answered.
                    for event in self.events_after_identify:
                        self._send(conn, {"op": 5, "d": event})
                    if self.close_after_events:
                        time.sleep(0.2)
                        conn.sendall(_server_frame(0x8, struct.pack("!H", 1001)))
                        return
                opcode, payload = self._read_client_message(conn)
                if opcode == 0x8:
                    return
                if opcode == 0xA:
                    continue
                msg = json.loads(payload)
                d = msg["d"]
                self.requests.append(d["requestType"])
                ok, data = self._respond(d["requestType"], d.get("requestData") or {})
                reply = {"op": 7, "d": {"requestType": d["requestType"], "requestId": d["requestId"],
                                        "requestStatus": {"result": ok, "code": 100 if ok else 600}}}
                if ok:
                    reply["d"]["responseData"] = data
                fragment = self.fragment_input_list and d["requestType"] == "GetInputList"
                self._send(conn, reply, fragment=fragment)
                answered += 1
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            conn.close()

    INPUTS = [
        {"inputName": "Reolink Cam", "unversionedInputKind": "ffmpeg_source"},
        {"inputName": "macOS Audio Capture", "unversionedInputKind": "sck_audio_capture"},
        {"inputName": "Mic/Aux", "unversionedInputKind": "coreaudio_input_capture"},
        {"inputName": "Desktop Audio", "unversionedInputKind": "coreaudio_output_capture"},
        {"inputName": "House Ad Loop", "unversionedInputKind": "ffmpeg_source"},
        {"inputName": "Lower Third", "unversionedInputKind": "browser_source"},
    ]
    MUTES = {"Reolink Cam": True, "macOS Audio Capture": False, "Mic/Aux": False,
             "Desktop Audio": True, "House Ad Loop": False}
    SCENES = {
        "Reolink Stage": [
            {"sourceName": "Reolink Cam", "sceneItemEnabled": True, "sourceType": "OBS_SOURCE_TYPE_INPUT",
             "inputKind": "ffmpeg_source", "isGroup": False},
            {"sourceName": "macOS Audio Capture", "sceneItemEnabled": False,
             "sourceType": "OBS_SOURCE_TYPE_INPUT", "inputKind": "sck_audio_capture", "isGroup": False},
            {"sourceName": "Graphics", "sceneItemEnabled": True, "sourceType": "OBS_SOURCE_TYPE_SCENE",
             "inputKind": None, "isGroup": True},
            {"sourceName": "Branding", "sceneItemEnabled": True, "sourceType": "OBS_SOURCE_TYPE_SCENE",
             "inputKind": None, "isGroup": False},
        ],
        "Branding": [
            {"sourceName": "House Ad Loop", "sceneItemEnabled": True, "sourceType": "OBS_SOURCE_TYPE_INPUT",
             "inputKind": "ffmpeg_source", "isGroup": False},
        ],
        "Parking Lot Center": [],
    }
    GROUPS = {
        "Graphics": [
            {"sourceName": "Lower Third", "sceneItemEnabled": True, "sourceType": "OBS_SOURCE_TYPE_INPUT",
             "inputKind": "browser_source", "isGroup": False},
        ],
    }

    def _respond(self, request_type, data):
        if request_type == "GetVersion":
            return True, {"obsVersion": "32.2.2", "obsWebSocketVersion": "5.6.3", "rpcVersion": 1,
                          "platform": "macos", "platformDescription": "macOS 15.1",
                          "availableRequests": sorted(obs_probe.READ_ONLY_REQUESTS | {
                              "SetCurrentProgramScene", "GetInputSettings", "GetStreamServiceSettings"}),
                          "supportedImageFormats": ["png"]}
        if request_type == "GetSceneList":
            return True, {"currentProgramSceneName": self.program_scene, "currentPreviewSceneName": None,
                          "scenes": [{"sceneName": n, "sceneIndex": i} for i, n in enumerate(self.SCENES)]}
        if request_type == "GetCurrentProgramScene":
            return True, {"sceneName": self.program_scene, "currentProgramSceneName": self.program_scene}
        if request_type == "GetStudioModeEnabled":
            return True, {"studioModeEnabled": False}
        if request_type == "GetSceneItemList":
            if data.get("sceneName") not in self.SCENES:
                return False, {}
            return True, {"sceneItems": self.SCENES[data["sceneName"]]}
        if request_type == "GetGroupSceneItemList":
            if data.get("sceneName") not in self.GROUPS:
                return False, {}
            return True, {"sceneItems": self.GROUPS[data["sceneName"]]}
        if request_type == "GetInputList":
            padding = [{"inputName": "Spare %05d" % i, "unversionedInputKind": "color_source"}
                       for i in range(1500)] if self.fragment_input_list else []
            return True, {"inputs": self.INPUTS + padding}
        if request_type == "GetSpecialInputs":
            return True, {"desktop1": "Desktop Audio", "desktop2": None, "mic1": "Mic/Aux",
                          "mic2": None, "mic3": None, "mic4": None}
        if request_type == "GetInputMute":
            name = data.get("inputName")
            if name not in self.MUTES:
                return False, {}
            return True, {"inputMuted": self.MUTES[name]}
        if request_type == "GetStreamStatus":
            return True, {"outputActive": True, "outputReconnecting": False, "outputTimecode": "01:02:03.000",
                          "outputCongestion": 0, "outputSkippedFrames": 0, "outputTotalFrames": 1000,
                          "outputBytes": 1}
        if request_type == "GetRecordStatus":
            return True, {"outputActive": False, "outputPaused": False, "outputTimecode": "00:00:00.000"}
        if request_type == "GetVirtualCamStatus":
            return True, {"outputActive": False}
        if request_type == "GetReplayBufferStatus":
            return False, {}
        if request_type == "GetStats":
            return True, {"activeFps": 30, "cpuUsage": 4.2, "memoryUsage": 512}
        if request_type in ("GetInputSettings", "GetStreamServiceSettings"):
            return True, {"inputSettings": {"input": SECRET_URL},
                          "streamServiceSettings": {"key": STREAM_KEY}}
        return False, {}


def run_main(args, env=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}, clear=False), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = obs_probe.main(args)
    return code, out.getvalue(), err.getvalue()


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.stop()

    def server(self, **kw):
        s = MockObs(**kw)
        self.servers.append(s)
        return s

    def test_auth_known_answer(self):
        # Same formula as the obs-websocket protocol doc and obsws-python.
        self.assertEqual(
            obs_probe.auth_response("supersecretpassword", "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=",
                                    "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY="),
            "1Ct943GAT+6YQUUX47Ia/ncufilbe6+oD6lY+5kaCu4=")

    def test_allowlist_is_get_only_and_excludes_secret_bearing_requests(self):
        for name in obs_probe.READ_ONLY_REQUESTS:
            self.assertTrue(name.startswith("Get"), name)
        for forbidden in ("GetInputSettings", "GetStreamServiceSettings", "GetProfileParameter",
                          "GetPersistentData", "GetSourceScreenshot", "SetCurrentProgramScene",
                          "StartStream", "StopStream", "ToggleStream", "StartRecord"):
            self.assertNotIn(forbidden, obs_probe.READ_ONLY_REQUESTS)

    def test_snapshot_json(self):
        s = self.server()
        code, out, err = run_main(["--host", "127.0.0.1", "--port", str(s.port), "--json"],
                                  {"OBS_WS_PASSWORD": PASSWORD})
        self.assertEqual(code, 0, err)
        snap = json.loads(out)
        self.assertEqual(snap["program_scene"], "Reolink Stage")
        self.assertEqual(snap["platform"], "macos")
        self.assertTrue(snap["auth_required"])
        self.assertEqual(snap["stream"]["outputActive"], True)
        self.assertIsNone(snap["replay_buffer_active"])
        visible = {r["path"] for r in snap["program_visible_sources"]}
        self.assertEqual(visible, {"Reolink Stage > Reolink Cam", "Reolink Stage > Graphics > Lower Third",
                                   "Reolink Stage > Branding > House Ad Loop"})
        hidden = snap["program_hidden_items"]
        self.assertEqual([h["source"] for h in hidden], ["macOS Audio Capture"])
        self.assertIs(hidden[0]["audio_muted"], False)
        mic = [g for g in snap["global_audio"] if g["slot"] == "Mic/Aux"][0]
        self.assertIs(mic["muted"], False)
        # Read-only: only allowlisted requests reached the server, and no secrets left it.
        self.assertTrue(s.requests)
        self.assertTrue(set(s.requests) <= obs_probe.READ_ONLY_REQUESTS, s.requests)
        self.assertNotIn(PASSWORD, out)
        self.assertEqual(s.identifies[0]["d"]["eventSubscriptions"], 0)
        self.assertEqual(s.unmasked_client_frames, 0)

    def test_snapshot_text(self):
        s = self.server()
        code, out, err = run_main(["--port", str(s.port)], {"OBS_WS_PASSWORD": PASSWORD})
        self.assertEqual(code, 0, err)
        self.assertIn("Program scene: Reolink Stage", out)
        self.assertIn("platform: macos", out)
        self.assertIn("Stream: LIVE", out)
        self.assertIn("macOS Audio Capture  [sck_audio_capture]  audio input UNMUTED", out)
        self.assertIn("Mic/Aux: Mic/Aux  UNMUTED", out)
        self.assertIn("Replay buffer: not configured", out)

    def test_large_fragmented_response_with_interleaved_ping(self):
        s = self.server(fragment_input_list=True)
        code, out, err = run_main(["--port", str(s.port), "--json"], {"OBS_WS_PASSWORD": PASSWORD})
        self.assertEqual(code, 0, err)
        self.assertEqual(len(json.loads(out)["inputs"]), len(MockObs.INPUTS) + 1500)

    def test_wrong_password_exit_3(self):
        s = self.server()
        code, out, err = run_main(["--port", str(s.port)], {"OBS_WS_PASSWORD": "nope"})
        self.assertEqual(code, 3)
        self.assertIn("rejected", err)
        self.assertNotIn("nope", err + out)

    def test_missing_password_noninteractive_exit_3(self):
        s = self.server()
        env = dict(os.environ)
        env.pop("OBS_WS_PASSWORD", None)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys.stdin, "isatty", lambda: False):
            code, out, err = run_main(["--port", str(s.port)])
        self.assertEqual(code, 3)
        self.assertIn("OBS_WS_PASSWORD", err)

    def test_nothing_listening_exit_2(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        code, _, err = run_main(["--port", str(port), "--timeout", "1"], {"OBS_WS_PASSWORD": PASSWORD})
        self.assertEqual(code, 2, err)

    def test_not_a_websocket_exit_2(self):
        s = self.server(http_only=True)
        code, _, err = run_main(["--port", str(s.port)], {"OBS_WS_PASSWORD": PASSWORD})
        self.assertEqual(code, 2)
        self.assertIn("OBS WebSocket port", err)

    def test_guard_refuses_write_requests_before_sending(self):
        s = self.server()
        client = obs_probe._connect("127.0.0.1", s.port, 5, lambda: PASSWORD, 0)
        try:
            with self.assertRaises(obs_probe.ReadOnlyViolation):
                client.request("SetCurrentProgramScene", {"sceneName": "Parking Lot Center"})
            with self.assertRaises(obs_probe.ReadOnlyViolation):
                client.request("GetStreamServiceSettings")
            ok, data, _ = client.request("GetCurrentProgramScene")
            self.assertTrue(ok)
        finally:
            client.ws.close()
        self.assertEqual(s.requests, ["GetCurrentProgramScene"])

    def test_watch_filters_events_reconnects_and_reconciles(self):
        s = self.server()
        s.events_after_identify = [
            {"eventType": "InputSettingsChanged", "eventIntent": 8,
             "eventData": {"inputName": "Reolink Cam", "inputSettings": {"input": SECRET_URL}}},
            {"eventType": "CurrentProgramSceneChanged", "eventIntent": 4,
             "eventData": {"sceneName": "Parking Lot Center", "sceneUuid": "u1"}},
            {"eventType": "StreamStateChanged", "eventIntent": 64,
             "eventData": {"outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_STARTED"}},
            {"eventType": "InputVolumeChanged", "eventIntent": 8,
             "eventData": {"inputName": "Mic/Aux", "inputVolumeMul": 0.5}},
        ]
        s.close_after_events = True
        env = dict(os.environ, OBS_WS_PASSWORD=PASSWORD)
        proc = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "obs_probe.py"), "--watch",
                                 "--port", str(s.port), "--heartbeat", "0.5"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
        records = []
        try:
            deadline = time.time() + 20
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                records.append(json.loads(line))
                types = [r["event_type"] for r in records]
                if types.count("probe_connected") == 1 and "probe_disconnected" in types:
                    # Second connection: stay up, then change scene without an event.
                    s.close_after_events = False
                    s.events_after_identify = []
                if types.count("probe_connected") >= 2 and s.program_scene != "Reolink Stage 2":
                    s.program_scene = "Reolink Stage 2"
                if "probe_state_reconciled" in types:
                    break
        finally:
            proc.terminate()
            proc.wait(5)
            proc.stdout.close()
            proc.stderr.close()
        types = [r["event_type"] for r in records]
        blob = json.dumps(records)
        self.assertNotIn("hunter2", blob)
        self.assertNotIn("InputSettingsChanged", types)
        self.assertNotIn("InputVolumeChanged", types)
        self.assertEqual(types[:4], ["probe_connected", "CurrentProgramSceneChanged",
                                     "StreamStateChanged", "probe_disconnected"])
        self.assertEqual(records[1]["data"], {"sceneName": "Parking Lot Center"})
        self.assertIn("probe_state_reconciled", types)
        rec = [r for r in records if r["event_type"] == "probe_state_reconciled"][-1]
        self.assertEqual(rec["data"]["sceneName"], "Reolink Stage 2")
        for r in records:
            self.assertRegex(r["observed_at_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertTrue(set(s.requests) <= obs_probe.READ_ONLY_REQUESTS)
        self.assertEqual(s.identifies[0]["d"]["eventSubscriptions"], obs_probe.WATCH_SUBSCRIPTIONS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
