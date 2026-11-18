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

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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


class TickerOverlay:
    """Renders broadcast header banner with live moving timestamp and scrolling ticker tape."""

    def __init__(self, config_path="/home/joseph1/box2-stream/ticker.json", top_h=110):
        self.config_path = config_path
        self.top_h = top_h
        self.last_load = 0.0
        self.data = {
            "title": "BOX 2  |  CANTON REFINERY",
            "messages": [
                "NOW ON STAGE: Open Mic Comedy Session",
                "BOOK STAGE TIME: https://box2.yurrmom.com",
                "SPONSOR: YURRMOM.COM",
                "UP NEXT: Comedians In The Box",
            ],
            "scroll_speed": 4,
        }
        self.scroll_x = 0
        self.full_ticker_str = ""
        self._update_full_str()

    def _update_full_str(self):
        msgs = self.data.get("messages", [])
        if not msgs:
            msgs = ["BOX 2 LIVE"]
        self.full_ticker_str = "      *      ".join(msgs) + "      *      "

    def reload_if_needed(self):
        now = time.monotonic()
        if now - self.last_load > 2.0:
            self.last_load = now
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path) as f:
                        loaded = json.load(f)
                    if loaded != self.data:
                        self.data = loaded
                        self._update_full_str()
                except Exception:
                    pass

    def draw(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        self.reload_if_needed()

        # 1. Solid matte banner background (y=0 to top_h)
        frame_bgr[:self.top_h, :] = (15, 15, 18)
        # Separator accent line
        cv2.line(frame_bgr, (0, self.top_h - 1), (w, self.top_h - 1), (70, 70, 80), 2)

        # 2. [● LIVE] badge
        cv2.rectangle(frame_bgr, (20, 12), (120, 42), (30, 30, 190), -1)
        cv2.circle(frame_bgr, (38, 27), 4, (255, 255, 255), -1)
        cv2.putText(frame_bgr, "LIVE", (52, 33), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)

        # 3. Stage title
        title = self.data.get("title", "BOX 2  |  CANTON REFINERY")
        cv2.putText(frame_bgr, title, (140, 33), cv2.FONT_HERSHEY_DUPLEX, 0.6, (220, 220, 220), 1)

        # 4. Live moving timestamp (updates each second)
        now_str = datetime.now().strftime("%m/%d/%Y  %I:%M:%S %p")
        cv2.putText(frame_bgr, now_str, (w - 380, 33), cv2.FONT_HERSHEY_DUPLEX, 0.58, (220, 220, 220), 1)

        # 5. Ticker tape box (y=50 to 96)
        box_x1, box_y1, box_x2, box_y2 = 20, 50, w - 20, 96
        cv2.rectangle(frame_bgr, (box_x1, box_y1), (box_x2, box_y2), (28, 28, 34), -1)
        cv2.rectangle(frame_bgr, (box_x1, box_y1), (box_x2, box_y2), (60, 60, 70), 1)

        # 6. Smooth scrolling text clipped inside ROI
        ticker_roi = frame_bgr[box_y1+1:box_y2-1, box_x1+2:box_x2-2]
        roi_h, roi_w = ticker_roi.shape[:2]

        font = cv2.FONT_HERSHEY_DUPLEX
        font_scale = 0.58
        font_thick = 1
        (tw, th), _ = cv2.getTextSize(self.full_ticker_str, font, font_scale, font_thick)

        speed = self.data.get("scroll_speed", 4)
        self.scroll_x = (self.scroll_x + speed) % max(1, tw)

        start_x = -self.scroll_x
        cv2.putText(ticker_roi, self.full_ticker_str, (start_x, 30), font, font_scale, (0, 230, 255), font_thick)
        if start_x + tw < roi_w:
            cv2.putText(ticker_roi, self.full_ticker_str, (start_x + tw, 30), font, font_scale, (0, 230, 255), font_thick)


class WallOverlay:
    """Subtle painted wall branding displayed on the dark stage wall when stage is empty.
    Fades smoothly away to 0 opacity when a performer is detected/framed.
    Hot-reloads from ticker.json without restarting the stream.
    """
    def __init__(self, config_path="/home/joseph1/box2-stream/ticker.json", base_w=1280, base_h=720):
        self.config_path = config_path
        self.w = base_w
        self.h = base_h
        self.last_mtime = 0
        self.last_check = 0
        self.enabled = True
        self.lines = ["PARKING LOT", "CENTER"]
        self.x = 210
        self.y = 170
        self.font_size = 32
        self.letter_spacing = 6
        self.max_opacity = 0.55
        self.fade_speed = 0.04
        self.color = (220, 222, 225)
        self.style = "stacked"  # "stacked", "stencil_lines", "single_line"
        
        self.current_opacity = 0.55
        self.roi_x1 = 0
        self.roi_y1 = 0
        self.roi_x2 = 0
        self.roi_y2 = 0
        self.alpha_mask_roi = None
        self.color_bgr = None
        self._load_config(force=True)

    def reload_if_needed(self, force=False):
        now = time.monotonic()
        if not force and (now - self.last_check < 2.0):
            return
        self.last_check = now
        if not os.path.exists(self.config_path):
            return
        try:
            mtime = os.path.getmtime(self.config_path)
            if force or mtime > self.last_mtime:
                self.last_mtime = mtime
                self._load_config(force=force)
        except OSError:
            pass

    def _load_config(self, force=False):
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
            wall_cfg = data.get("wall_overlay", {})
            self.enabled = wall_cfg.get("enabled", True)
            self.lines = wall_cfg.get("lines", ["PARKING LOT", "CENTER"])
            self.x = wall_cfg.get("x", 210)
            self.y = wall_cfg.get("y", 170)
            self.font_size = wall_cfg.get("font_size", 32)
            self.letter_spacing = wall_cfg.get("letter_spacing", 6)
            self.max_opacity = float(wall_cfg.get("max_opacity", 0.55))
            self.fade_speed = float(wall_cfg.get("fade_speed", 0.04))
            self.style = wall_cfg.get("style", "stacked")
            raw_color = wall_cfg.get("color", [220, 222, 225])
            self.color = tuple(raw_color)
            self._precompute_overlay()
        except Exception:
            pass

    def _precompute_overlay(self):
        if not HAS_PIL:
            return
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf",
        ]
        font = None
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, self.font_size)
                    break
                except Exception:
                    pass
        if font is None:
            font = ImageFont.load_default()

        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        lines_to_render = self.lines
        if self.style == "single_line":
            lines_to_render = [" ".join(self.lines)]

        curr_y = self.y
        total_w = 0
        line_bboxes = []
        for line in lines_to_render:
            chars = list(line)
            line_w = 0
            char_widths = []
            for ch in chars:
                bbox = font.getbbox(ch)
                cw = bbox[2] - bbox[0] + self.letter_spacing
                char_widths.append(cw)
                line_w += cw
            line_w -= self.letter_spacing
            line_bboxes.append((line, line_w, char_widths))
            total_w = max(total_w, line_w)
            
        for line, line_w, char_widths in line_bboxes:
            curr_x = self.x + (total_w - line_w) // 2
            for ch, cw in zip(list(line), char_widths):
                draw.text((curr_x, curr_y), ch, font=font, fill=(self.color[0], self.color[1], self.color[2], 255))
                curr_x += cw
            curr_y += self.font_size + 14

        if self.style == "stencil_lines":
            draw.line([(self.x - 15, self.y - 12), (self.x + total_w + 15, self.y - 12)], fill=(self.color[0], self.color[1], self.color[2], 200), width=2)
            draw.line([(self.x - 15, curr_y - 2), (self.x + total_w + 15, curr_y - 2)], fill=(self.color[0], self.color[1], self.color[2], 200), width=2)

        overlay_np = np.array(overlay)
        alpha_raw = overlay_np[:, :, 3].astype(float) / 255.0
        alpha_blur = cv2.GaussianBlur(alpha_raw, (3, 3), 0.6)
        
        y_indices, x_indices = np.where(alpha_blur > 0.005)
        if len(y_indices) > 0:
            self.roi_y1, self.roi_y2 = max(0, int(y_indices.min()) - 2), min(self.h, int(y_indices.max()) + 3)
            self.roi_x1, self.roi_x2 = max(0, int(x_indices.min()) - 2), min(self.w, int(x_indices.max()) + 3)
            self.alpha_mask_roi = alpha_blur[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2, np.newaxis]
            self.color_bgr = np.array([self.color[2], self.color[1], self.color[0]], dtype=float)
        else:
            self.alpha_mask_roi = None

    def draw(self, frame_bgr, is_performer_framed=False):
        if not self.enabled or self.alpha_mask_roi is None:
            return

        self.reload_if_needed()

        target_opacity = 0.0 if is_performer_framed else self.max_opacity
        if self.current_opacity < target_opacity:
            self.current_opacity = min(target_opacity, self.current_opacity + self.fade_speed)
        elif self.current_opacity > target_opacity:
            self.current_opacity = max(target_opacity, self.current_opacity - self.fade_speed)

        if self.current_opacity > 0.005:
            eff_alpha = self.alpha_mask_roi * self.current_opacity
            roi = frame_bgr[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2]
            frame_bgr[self.roi_y1:self.roi_y2, self.roi_x1:self.roi_x2] = (
                (1.0 - eff_alpha) * roi + eff_alpha * self.color_bgr
            ).astype(np.uint8)


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
        self.ticker = TickerOverlay(config_path="/home/joseph1/box2-stream/ticker.json", top_h=self.top_matte_h)
        self.wall_overlay = WallOverlay(config_path="/home/joseph1/box2-stream/ticker.json", base_w=self.out_w, base_h=self.out_h)

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
            (int(5 * scale_x), int(20 * scale_y)),
            (int((640 - 5) * scale_x), int(20 * scale_y)),
            (int((640 - 5) * scale_x), floor_cutoff_y),
            (int(5 * scale_x), floor_cutoff_y),
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

                # Subtle painted wall overlay (fades to 0 when performer is on stage)
                is_performer_framed = (proposal.tracking_state == "tracking") or (onstage_count > 0)
                self.wall_overlay.draw(rendered, is_performer_framed=is_performer_framed)

                # Draw top broadcast banner with live moving timestamp & scrolling ticker tape
                if self.top_matte_h > 0:
                    self.ticker.draw(rendered)

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
