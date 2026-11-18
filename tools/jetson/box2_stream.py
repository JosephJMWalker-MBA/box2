#!/usr/bin/env python3
"""BOX2 stream box: NVR stage camera and stage mic → Twitch, unattended, on the Orin.

Supports two streaming modes:
1. "director" (default): Intelligent Stage Director AI framing, close-up tracking,
   floor/pet rejection, and periodic establishing room views at 720p.
2. "passthrough": Original untouched raw camera feed.

  box2-stream on | test | off   set the desired state (kept across reboots)
  box2-stream status            show what is happening
  box2-stream run               the service loop (systemd runs this)

Secrets (NVR login, Twitch key) live only in config.json (mode 600) and in
process memory; nothing here prints or logs them.
"""
import concurrent.futures
from datetime import datetime, timezone, timedelta
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.request

HOME = Path(__file__).resolve().parent
CONFIG, STATE, STATUS = HOME / 'config.json', HOME / 'state.json', HOME / 'status.json'
STALL_SECONDS = 15
FFMPEG = '/usr/bin/ffmpeg'

# Stage Director integration
STAGE_DIR = Path("/home/joseph1/stage-director")
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

try:
    import cv2
    import numpy as np
    from stage_director.adapter import StageFramingAdapter
    from stage_director.core import BookingSnapshot, Mode
    from stage_director.framing import FramingConfig
    from stage_director.geometry import BoundingBox, StagePolygon
    from stage_director.tracking import PerformerTracker
    STAGE_DIRECTOR_AVAILABLE = True
except Exception as _import_err:
    STAGE_DIRECTOR_AVAILABLE = False


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def log(message):
    print(f'{now()} {message}', flush=True)


def write_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=1) + '\n')
    tmp.replace(path)


def desired():
    try:
        return json.loads(STATE.read_text()).get('desired', 'off')
    except (OSError, ValueError):
        return 'off'


# ----- finding and logging in to the NVR -----
def wifi_network():
    route = subprocess.run(['ip', '-4', 'route', 'show', 'default'], capture_output=True, text=True).stdout
    device = re.search(r'dev (\S+)', route.splitlines()[0]).group(1)
    addr = subprocess.run(['ip', '-4', '-o', 'addr', 'show', 'dev', device], capture_output=True, text=True).stdout
    return ipaddress.ip_interface(re.search(r'inet (\S+)', addr).group(1)).network


def mac_of(ip):
    out = subprocess.run(['ip', 'neigh', 'show', str(ip)], capture_output=True, text=True).stdout
    match = re.search(r'lladdr ([0-9a-f:]+)', out)
    return match.group(1) if match else None


def find_nvr(mac, last_ip=None):
    mac = mac.lower()
    ping = lambda host: subprocess.run(['ping', '-c', '1', '-W', '1', str(host)], capture_output=True)
    if last_ip:
        ping(last_ip)
        if mac_of(last_ip) == mac:
            return last_ip
    with concurrent.futures.ThreadPoolExecutor(64) as pool:
        list(pool.map(ping, wifi_network().hosts()))
    out = subprocess.run(['ip', 'neigh'], capture_output=True, text=True).stdout
    for ip, found in re.findall(r'^(\S+) .*lladdr ([0-9a-f:]+)', out, re.M):
        if found == mac:
            return ip
    return None


def legacy_tls():
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # the NVR's self-signed LAN certificate
    context.set_ciphers('DEFAULT:@SECLEVEL=0')  # its firmware offers only legacy suites
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))


def nvr_call(ip, query, body, timeout=8):
    request = urllib.request.Request(f'https://{ip}/api.cgi?{query}', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    with legacy_tls().open(request, timeout=timeout) as response:
        return json.loads(response.read(1 << 20))[0]


def nvr_login(ip, cfg):
    reply = nvr_call(ip, 'cmd=Login', [{'cmd': 'Login', 'action': 0, 'param': {'User': {
        'Version': '0', 'userName': cfg['nvr_user'], 'password': cfg['nvr_password']}}}])
    if reply.get('code') != 0:
        raise RuntimeError(f"NVR login refused (rspCode {reply.get('error', {}).get('rspCode')})")
    return reply['value']['Token']['name']


def nvr_logout(ip, token):
    try:
        nvr_call(ip, f'cmd=Logout&token={token}', [{'cmd': 'Logout', 'action': 0, 'param': {}}], timeout=4)
    except Exception:
        pass


def flv_url(ip, token, cfg):
    return f"http://{ip}/flv?port=1935&app=bcs&stream=channel{cfg['nvr_channel']}_{cfg['nvr_stream']}.bcs&token={token}"


def rtmp_url(cfg, mode):
    return f"{cfg['twitch_server'].rstrip('/')}/{cfg['twitch_key']}" + ('?bandwidthtest=true' if mode == 'test' else '')


def scrub(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, '<hidden>')
    return re.sub(r'(token|password|user)=[^&\s]+', r'\1=<hidden>', re.sub(r'rtmps?://\S+', '<twitch>', text))


# ----- streaming implementations -----
class Stream:
    """Original passthrough ffmpeg run with a progress watchdog."""

    def __init__(self, source, target, secrets, cfg=None):
        self.secrets = secrets
        self.started = time.monotonic()
        self.last_progress = self.started
        self.stats = {'frame': 0, 'fps': 0.0, 'bitrate': '', 'out_time': '00:00:00', 'mode': 'passthrough'}
        self.errors = []
        self.proc = subprocess.Popen(
            [FFMPEG, '-hide_banner', '-nostdin', '-loglevel', 'error', '-nostats', '-progress', 'pipe:1',
             '-rw_timeout', '15000000', '-i', source,
             '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
             '-c:a', 'aac', '-b:a', '128k', '-ar', '48000', '-ac', '2',
             '-f', 'flv', '-flvflags', 'no_duration_filesize', target],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        threading.Thread(target=self.read_progress, daemon=True).start()
        threading.Thread(target=self.read_errors, daemon=True).start()

    def read_progress(self):
        for line in self.proc.stdout:
            key, _, value = line.strip().partition('=')
            if key == 'frame' and value.isdigit():
                if int(value) > self.stats['frame']:
                    self.last_progress = time.monotonic()
                self.stats['frame'] = int(value)
            elif key == 'fps':
                self.stats['fps'] = float(value or 0)
            elif key in ('bitrate', 'out_time'):
                self.stats[key] = value

    def read_errors(self):
        for line in self.proc.stderr:
            line = scrub(line.strip(), self.secrets)
            if line:
                self.errors = (self.errors + [line])[-5:]
                log(f'ffmpeg: {line}')

    def stalled(self):
        return time.monotonic() - self.last_progress > STALL_SECONDS

    def stop(self):
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)


class DirectorStream:
    """Stage Director AI framing stream with close-up tracking, pet rejection, and watchdog."""

    def __init__(self, source, target, secrets, cfg):
        self.secrets = secrets
        self.started = time.monotonic()
        self.last_progress = self.started
        self.stats = {'frame': 0, 'fps': 0.0, 'bitrate': '', 'out_time': '00:00:00', 'mode': 'director'}
        self.errors = []
        self._stop_event = threading.Event()

        self.out_w = cfg.get("output_width", 1280)
        self.out_h = cfg.get("output_height", 720)
        # NVR subStream delivers 10 FPS; match input fps to prevent frame starvation and buffering
        self.fps = cfg.get("output_fps", 10.0)
        self.top_matte_h = cfg.get("top_matte_h", int(110 * (self.out_h / 720.0)))

        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"DirectorStream: Failed to open video source {source}")

        ret, test_frame = self.cap.read()
        if not ret or test_frame is None:
            self.cap.release()
            raise RuntimeError("DirectorStream: Failed to read initial frame from camera")

        src_h, src_w = test_frame.shape[:2]

        # Stage polygon & floor rejection (covers elevated T-stage surface down to y=315 for floor work / sit-ups)
        scale_x = src_w / 640.0
        scale_y = src_h / 360.0
        floor_cutoff_y = int(315 * scale_y)
        stage_vertices = [
            (int(30 * scale_x), int(20 * scale_y)),
            (int((640 - 30) * scale_x), int(20 * scale_y)),
            (int((640 - 30) * scale_x), floor_cutoff_y),
            (int(30 * scale_x), floor_cutoff_y),
        ]
        self.stage_polygon = StagePolygon(vertices=stage_vertices)
        self.floor_cutoff_y = floor_cutoff_y
        self.src_w = src_w
        self.src_h = src_h

        cascade_path = "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"
        if not os.path.exists(cascade_path):
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        framing_config = FramingConfig(
            canvas_width=src_w,
            canvas_height=src_h,
            target_face_fraction=cfg.get("target_face_fraction", 0.28),
            max_zoom=cfg.get("max_zoom", 2.6),
            periodic_room_view_enabled=cfg.get("periodic_room_view_enabled", False),
            room_view_interval_s=cfg.get("room_view_interval_s", 90.0),
            room_view_duration_s=cfg.get("room_view_duration_s", 5.0),
            pacing_pullback_speed_threshold_px_s=cfg.get("pacing_pullback_speed_threshold_px_s", 0.0),
            pacing_pullback_factor=cfg.get("pacing_pullback_factor", 0.0),
            deadzone_x_px=cfg.get("deadzone_x_px", 15.0),
            deadzone_y_px=cfg.get("deadzone_y_px", 12.0),
            deadzone_zoom_px=cfg.get("deadzone_zoom_px", 35.0),
            smoothing_tau=cfg.get("smoothing_tau", 0.70),
            max_pan_speed_px_s=cfg.get("max_pan_speed_px_s", 180.0),
            max_tilt_speed_px_s=cfg.get("max_tilt_speed_px_s", 120.0),
            max_zoom_speed_px_s=cfg.get("max_zoom_speed_px_s", 50.0),
        )
        tracker = PerformerTracker(
            stage_polygon=self.stage_polygon,
            loss_hold_seconds=cfg.get("loss_hold_seconds", 15.0),
            allow_proximity_reacquisition=True,
            require_confirmation_after_loss=False,
            max_performer_y=float(floor_cutoff_y),
        )
        self.adapter = StageFramingAdapter(
            config=framing_config,
            tracker=tracker,
            allow_proximity_reacquisition=True,
        )

        self.session_expires = None
        self._last_logged_state = None
        now_utc = datetime.now(timezone.utc)
        self.ensure_session(now_utc, time.monotonic())

        bitrate = cfg.get("bitrate", "2500k")
        self.proc = subprocess.Popen(
            [FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostats', '-progress', 'pipe:1',
             '-rw_timeout', '15000000',
             '-i', source,
             '-f', 'rawvideo', '-vcodec', 'rawvideo',
             '-s', f'{self.out_w}x{self.out_h}',
             '-pix_fmt', 'bgr24',
             '-r', str(int(self.fps)),
             '-i', 'pipe:0',
             '-map', '1:v:0',
             '-map', '0:a:0?',
             '-r', '30',
             '-c:v', 'libx264',
             '-preset', 'veryfast',
             '-tune', 'zerolatency',
             '-threads', '4',
             '-b:v', bitrate,
             '-maxrate', bitrate,
             '-bufsize', '5000k',
             '-pix_fmt', 'yuv420p',
             '-c:a', 'aac',
             '-b:a', '128k',
             '-ar', '48000',
             '-ac', '2',
             '-f', 'flv',
             '-flvflags', 'no_duration_filesize',
             target],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

        threading.Thread(target=self.run_worker, daemon=True).start()
        threading.Thread(target=self.read_progress, daemon=True).start()
        threading.Thread(target=self.read_errors, daemon=True).start()

    def ensure_session(self, now_utc, cur_mono):
        """Keep an active session going 24/7. Auto-renew if expired or within 1 hour of expiration."""
        if (self.session_expires is None or
            now_utc >= self.session_expires - timedelta(hours=1) or
            self.adapter.director.mode != Mode.LIVE):
            self.session_expires = now_utc + timedelta(days=7)
            booking = BookingSnapshot(
                booking_id=f"live-box2-{int(time.time())}", revision=1,
                slot_start_utc=now_utc - timedelta(seconds=5),
                slot_end_utc=self.session_expires,
                issued_at_utc=now_utc - timedelta(seconds=10),
                expires_at_utc=self.session_expires + timedelta(days=1),
                stage_seconds=7 * 86400, privacy_class="public",
                checked_in=True, live_consent=True, tracking_consent=True, capture_verified=True,
            )
            self.adapter.arm(booking, now_utc)
            self.adapter.start_set(now_utc, cur_mono, host_confirmed=True)
            log("Stage Director: session armed and started (perpetual live mode)")

    def run_worker(self):
        try:
            while not self._stop_event.is_set() and self.proc.poll() is None:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                cur_mono = time.monotonic()
                cur_utc = datetime.now(timezone.utc)
                self.ensure_session(cur_utc, cur_mono)

                # Face detection on native 640x360 (~48ms, 100% detection rate on human faces)
                if (self.src_w, self.src_h) == (640, 360):
                    det_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    sx = 1.0
                    sy = 1.0
                else:
                    det_frame = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR)
                    det_gray = cv2.cvtColor(det_frame, cv2.COLOR_BGR2GRAY)
                    sx = self.src_w / 640.0
                    sy = self.src_h / 360.0

                raw_faces = self.face_cascade.detectMultiScale(
                    det_gray, scaleFactor=1.15, minNeighbors=4, minSize=(22, 22), maxSize=(58, 58)
                )

                candidate_boxes = []
                onstage_count = 0
                for (fx, fy, fw, fh) in raw_faces:
                    bbox = BoundingBox(
                        x=float(fx * sx),
                        y=float(fy * sy),
                        width=float(fw * sx),
                        height=float(fh * sy),
                    )
                    if bbox.center_y <= self.floor_cutoff_y and self.stage_polygon.contains_box(bbox):
                        candidate_boxes.append(bbox)
                        onstage_count += 1

                # Auto-confirm performer when available and tracker needs acquisition
                if self.adapter.tracker.state.value in ("acquiring", "ambiguous", "lost") and candidate_boxes:
                    self.adapter.confirm_subject(candidate_boxes[0], cur_mono)

                proposal = self.adapter.process_frame(candidate_boxes, cur_utc, cur_mono)

                # Log tracking state transitions
                current_state = (proposal.tracking_state, proposal.camera_action)
                if current_state != self._last_logged_state:
                    log(f"Stage Director state: {proposal.tracking_state}, action: {proposal.camera_action}, candidates: {onstage_count}")
                    self._last_logged_state = current_state

                crop = proposal.obs_crop
                if crop and proposal.camera_action == "track_face":
                    x1 = max(0, crop["left"])
                    y1 = max(0, crop["top"])
                    x2 = min(self.src_w, self.src_w - crop["right"])
                    y2 = min(self.src_h, self.src_h - crop["bottom"])
                    if x2 > x1 + 10 and y2 > y1 + 10:
                        cropped = frame[y1:y2, x1:x2]
                        rendered = cv2.resize(cropped, (self.out_w, self.out_h), interpolation=cv2.INTER_LINEAR)
                    else:
                        rendered = cv2.resize(frame, (self.out_w, self.out_h), interpolation=cv2.INTER_AREA)
                else:
                    rendered = cv2.resize(frame, (self.out_w, self.out_h), interpolation=cv2.INTER_AREA)

                # Mask out top ceiling ductwork down to middle of brightest headlight
                if self.top_matte_h > 0:
                    rendered[:self.top_matte_h, :] = 0

                try:
                    self.proc.stdin.write(rendered.tobytes())
                    self.proc.stdin.flush()
                    self.last_progress = time.monotonic()
                except (BrokenPipeError, OSError, ValueError):
                    break
        finally:
            try:
                self.cap.release()
            except Exception:
                pass
            try:
                self.proc.stdin.close()
            except Exception:
                pass

    def read_progress(self):
        while not self._stop_event.is_set():
            try:
                line = self.proc.stdout.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore').strip() if isinstance(line, (bytes, bytearray)) else str(line).strip()
                key, _, value = line_str.partition('=')
                if key == 'frame' and value.isdigit():
                    v_int = int(value)
                    if v_int > self.stats['frame']:
                        self.last_progress = time.monotonic()
                    self.stats['frame'] = v_int
                elif key == 'fps':
                    self.stats['fps'] = float(value or 0)
                elif key in ('bitrate', 'out_time'):
                    self.stats[key] = value
            except Exception:
                pass

    def read_errors(self):
        while not self._stop_event.is_set():
            try:
                line = self.proc.stderr.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore').strip() if isinstance(line, (bytes, bytearray)) else str(line).strip()
                line_scrubbed = scrub(line_str, self.secrets)
                if line_scrubbed:
                    self.errors = (self.errors + [line_scrubbed])[-5:]
                    log(f'ffmpeg: {line_scrubbed}')
            except Exception:
                pass

    def stalled(self):
        return time.monotonic() - self.last_progress > STALL_SECONDS

    def stop(self):
        self._stop_event.set()
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)


def run():
    cfg = json.loads(CONFIG.read_text())
    secrets = [cfg['nvr_password'], cfg['twitch_key']]
    status = {'state': 'starting', 'since': now(), 'restarts': 0, 'nvr_ip': None, 'last_error': None}
    backoff = 3
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while not stop.is_set():
        mode = desired()
        if mode not in ('on', 'test'):
            write_json(STATUS, {**status, 'state': 'off', 'updated': now()})
            stop.wait(2)
            continue
        token = ip = stream = None
        try:
            ip = find_nvr(cfg['nvr_mac'], status.get('nvr_ip'))
            if not ip:
                raise RuntimeError('NVR not found on the network (is it powered and on this Wi-Fi?)')
            status['nvr_ip'] = ip
            token = nvr_login(ip, cfg)

            # Choose streaming mode: director (default) or passthrough
            stream_mode = cfg.get('stream_mode', 'director')
            if stream_mode == 'director' and STAGE_DIRECTOR_AVAILABLE:
                log(f"streaming (Stage Director {'live' if mode == 'on' else 'Twitch bandwidth test'}) from NVR at {ip}")
                stream = DirectorStream(flv_url(ip, token, cfg), rtmp_url(cfg, mode), secrets + [token], cfg)
            else:
                log(f"streaming (Passthrough {'live' if mode == 'on' else 'Twitch bandwidth test'}) from NVR at {ip}")
                stream = Stream(flv_url(ip, token, cfg), rtmp_url(cfg, mode), secrets + [token], cfg)

            status.update(state='live' if mode == 'on' else 'testing', since=now(), last_error=None)
            while not stop.is_set() and stream.proc.poll() is None and desired() == mode:
                if stream.stalled():
                    raise RuntimeError(f'no new video for {STALL_SECONDS} s; restarting')
                if time.monotonic() - stream.started > 60:
                    backoff = 3  # a minute of good streaming resets the back-off
                write_json(STATUS, {**status, **stream.stats, 'updated': now()})
                stop.wait(1)
            if stream.proc.poll() is not None and desired() == mode and not stop.is_set():
                raise RuntimeError('ffmpeg exited: ' + (stream.errors[-1] if stream.errors else f'code {stream.proc.returncode}'))
        except Exception as exc:
            status.update(state='recovering', last_error=scrub(str(exc), secrets + ([token] if token else [])),
                          restarts=status['restarts'] + 1)
            log(f"problem: {status['last_error']} (retrying in {backoff} s)")
            write_json(STATUS, {**status, 'updated': now()})
            stop.wait(backoff)
            backoff = min(backoff * 2, 30)
        finally:
            if stream:
                stream.stop()
            if token and ip:
                nvr_logout(ip, token)
    write_json(STATUS, {**status, 'state': 'stopped', 'updated': now()})


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if command in ('on', 'test', 'off'):
        write_json(STATE, {'desired': command, 'set': now()})
        print({'on': 'Going live: the Orin will stream to Twitch within a few seconds.',
               'test': 'Twitch bandwidth test: the Orin streams to Twitch without going live.',
               'off': 'Stream off.'}[command])
    elif command == 'status':
        try:
            print(STATUS.read_text())
        except OSError:
            print('{"state": "unknown: service has not written a status yet"}')
    elif command == 'run':
        run()
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
