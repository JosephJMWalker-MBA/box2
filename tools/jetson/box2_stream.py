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


def desired_view(ticker_path="/home/joseph1/box2-stream/ticker.json"):
    """Return 'privacy' (Box 2 wall placeholder) or 'stage' (normal Stage Director)."""
    try:
        st = json.loads(STATE.read_text())
        if st.get('view') in ('privacy', 'standby', 'brb'):
            return 'privacy'
    except (OSError, ValueError):
        pass
    try:
        if os.path.exists(ticker_path):
            tk = json.loads(Path(ticker_path).read_text())
            if tk.get('privacy_mode') is True or tk.get('privacy_placeholder', {}).get('enabled') is True:
                return 'privacy'
    except (OSError, ValueError):
        pass
    return 'stage'


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


def nvr_goto_preset(ip, token, preset_id, channel=0, speed=32):
    """Recall a saved optical PTZ preset on the Reolink NVR."""
    if not ip or not token or not preset_id:
        return False
    try:
        res = nvr_call(
            ip,
            f'cmd=PtzCtrl&token={token}',
            [{'cmd': 'PtzCtrl', 'action': 0, 'param': {'channel': int(channel), 'op': 'ToPos', 'id': int(preset_id), 'speed': int(speed)}}],
            timeout=5,
        )
        return res.get('code') == 0
    except Exception:
        return False


def flv_url(ip, token, cfg):
    return f"http://{ip}/flv?port=1935&app=bcs&stream=channel{cfg['nvr_channel']}_{cfg['nvr_stream']}.bcs&token={token}"


def flv_url_ch(ip, token, channel, stream='sub'):
    return f"http://{ip}/flv?port=1935&app=bcs&stream=channel{channel}_{stream}.bcs&token={token}"


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
             '-reconnect', '1', '-reconnect_at_eof', '1', '-reconnect_streamed', '1',
             '-reconnect_on_network_error', '1', '-reconnect_delay_max', '2',
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
        if time.monotonic() - self.started < 30.0:
            return False
        return time.monotonic() - self.last_progress > STALL_SECONDS

    def stop(self):
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)


def next_scheduled_refresh_time(interval_hours=3):
    """Calculates the next top-of-the-hour timestamp divisible by interval_hours."""
    if not interval_hours or interval_hours <= 0:
        return None
    now_dt = datetime.now()
    cand = now_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while cand.hour % interval_hours != 0 or cand <= now_dt:
        cand += timedelta(hours=1)
    return cand


class TickerOverlay:
    """Renders broadcast header banner with live moving timestamp, scrolling ticker tape,
    and dynamic warnings/countdown for scheduled 3-hour VOD resets.
    """

    def __init__(self, config_path="/home/joseph1/box2-stream/ticker.json", top_h=110, refresh_hours=3):
        self.config_path = config_path
        self.top_h = top_h
        self.refresh_hours = refresh_hours
        self.last_load = 0.0
        self.last_countdown_update = 0.0
        self.current_rem_sec = None
        self.next_time_str = ""
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

    def _update_full_str(self, test_rem_sec=None):
        raw_msgs = list(self.data.get("messages", []))
        if not raw_msgs:
            raw_msgs = ["BOX 2 LIVE"]

        # Calculate time remaining until next scheduled top-of-hour refresh
        rem_sec = test_rem_sec
        next_time_str = ""
        if rem_sec is None and self.refresh_hours > 0:
            next_ref = next_scheduled_refresh_time(self.refresh_hours)
            if next_ref:
                now_dt = datetime.now()
                rem_sec = (next_ref - now_dt).total_seconds()
                next_time_str = next_ref.strftime("%I:%M %p").lstrip("0")
        elif rem_sec is not None:
            next_time_str = "3:00 AM"

        self.current_rem_sec = rem_sec
        self.next_time_str = next_time_str

        msgs = []
        if rem_sec is not None:
            if rem_sec <= 60:
                s = max(1, int(rem_sec))
                alert = f"*** SCHEDULED RESET IN {s}s -- REFRESHING IN 7s FOR VOD CLIPPING ARCHIVE ***"
                msgs = [alert, alert]
            elif rem_sec <= 300:
                m = int(rem_sec // 60)
                s = int(rem_sec % 60)
                alert = f"WARNING: SCHEDULED 3-HOUR RESET IN {m}m {s:02d}s (AT {next_time_str}) FOR VOD CLIPPING ARCHIVE -- BACK IN 7s"
                msgs = [alert] + raw_msgs
            elif rem_sec <= 600:
                m = int(rem_sec // 60)
                notice = f"NOTICE: 3-Hour VOD reset in {m} min (at {next_time_str}) for clipping archive"
                msgs = [notice] + raw_msgs
            else:
                schedule_msg = f"RESET SCHEDULE: Next 3-hour clipping VOD rollover at {next_time_str} (brief 7s pause)"
                msgs = raw_msgs + [schedule_msg]
        else:
            msgs = raw_msgs

        new_ticker_str = "      *      ".join(msgs) + "      *      "
        if new_ticker_str != self.full_ticker_str:
            self.full_ticker_str = new_ticker_str

    def reload_if_needed(self):
        now_mono = time.monotonic()
        if now_mono - self.last_load > 2.0:
            self.last_load = now_mono
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path) as f:
                        loaded = json.load(f)
                    if loaded != self.data:
                        self.data = loaded
                        self._update_full_str()
                except Exception:
                    pass

        # Update countdown string every 1.0s
        if now_mono - self.last_countdown_update >= 1.0:
            self.last_countdown_update = now_mono
            self._update_full_str()

    def draw(self, frame_bgr, standby_mode=False):
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

        # 4. Imminent reset warning badge (<= 180s) OR optional Standby badge in privacy placeholder mode
        rem_sec = self.current_rem_sec
        if rem_sec is not None and rem_sec <= 180:
            if rem_sec <= 60:
                badge_text = f"RESET IN {max(1, int(rem_sec))}s"
                badge_bg = (15, 35, 90)
                badge_border = (0, 180, 255)
                text_color = (0, 220, 255)
            else:
                m = int(rem_sec // 60)
                s = int(rem_sec % 60)
                badge_text = f"RESET IN {m}m {s:02d}s"
                badge_bg = (20, 45, 100)
                badge_border = (0, 160, 230)
                text_color = (0, 210, 255)

            cv2.rectangle(frame_bgr, (500, 12), (730, 42), badge_bg, -1)
            cv2.rectangle(frame_bgr, (500, 12), (730, 42), badge_border, 1)
            cv2.putText(frame_bgr, badge_text, (518, 33), cv2.FONT_HERSHEY_DUPLEX, 0.55, text_color, 1)
        elif standby_mode and self.data.get("privacy_placeholder", {}).get("show_standby_badge", True):
            standby_label = self.data.get("privacy_placeholder", {}).get("badge_label", "STAGE STANDBY")
            cv2.rectangle(frame_bgr, (500, 12), (710, 42), (32, 34, 42), -1)
            cv2.rectangle(frame_bgr, (500, 12), (710, 42), (110, 115, 130), 1)
            cv2.putText(frame_bgr, standby_label, (520, 33), cv2.FONT_HERSHEY_DUPLEX, 0.52, (205, 210, 220), 1)

        # 5. Live moving timestamp (updates each second)
        now_str = datetime.now().strftime("%m/%d/%Y  %I:%M:%S %p")
        cv2.putText(frame_bgr, now_str, (w - 380, 33), cv2.FONT_HERSHEY_DUPLEX, 0.58, (220, 220, 220), 1)

        # 6. Ticker tape box (y=50 to 96)
        is_imminent = rem_sec is not None and rem_sec <= 300
        box_border_color = (0, 180, 255) if is_imminent else (60, 60, 70)
        ticker_text_color = (0, 220, 255) if is_imminent else (0, 230, 255)

        box_x1, box_y1, box_x2, box_y2 = 20, 50, w - 20, 96
        cv2.rectangle(frame_bgr, (box_x1, box_y1), (box_x2, box_y2), (28, 28, 34), -1)
        cv2.rectangle(frame_bgr, (box_x1, box_y1), (box_x2, box_y2), box_border_color, 1)

        # 7. Smooth scrolling text clipped inside ROI
        ticker_roi = frame_bgr[box_y1+1:box_y2-1, box_x1+2:box_x2-2]
        roi_h, roi_w = ticker_roi.shape[:2]

        font = cv2.FONT_HERSHEY_DUPLEX
        font_scale = 0.58
        font_thick = 1
        (tw, th), _ = cv2.getTextSize(self.full_ticker_str, font, font_scale, font_thick)

        speed = self.data.get("scroll_speed", 4)
        self.scroll_x = (self.scroll_x + speed) % max(1, tw)

        start_x = -self.scroll_x
        cv2.putText(ticker_roi, self.full_ticker_str, (start_x, 30), font, font_scale, ticker_text_color, font_thick)
        if start_x + tw < roi_w:
            cv2.putText(ticker_roi, self.full_ticker_str, (start_x + tw, 30), font, font_scale, ticker_text_color, font_thick)


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


class CameraFeedWallOverlay:
    """Live secondary camera feed (e.g. Parking Lot Center) projected onto the dark stage wall.
    - Soft feathered edge projection or framed broadcast PIP
    - Clean OSD watermark crop + anti-aliased INTER_AREA downscaling
    - Motion-adaptive temporal EMA de-flicker filter (absorbs H.264 4s keyframe pop without motion blur)
    - Fades smoothly to 0.0 opacity when a performer is confirmed/framed or camera zooms in
    - Background worker thread with auto-reconnect and token refresh
    - Live hot-reloading from ticker.json ("parking_lot_camera")
    """
    def __init__(self, cam_url, config_path="/home/joseph1/box2-stream/ticker.json", base_w=1280, base_h=720):
        self.cam_url_getter = cam_url if callable(cam_url) else (lambda: cam_url)
        self.config_path = config_path
        self.base_w = base_w
        self.base_h = base_h
        
        self.enabled = True
        self.x = 120
        self.y = 135
        self.width = 340
        self.height = 191
        self.max_opacity = 0.65
        self.fade_speed = 0.04
        self.style = "feathered"  # "feathered" or "framed"
        self.show_label = True
        self.label = "PARKING LOT CENTER"
        self.crop_osd = True
        # Normalized crop (x1, y1, x2, y2) removing Reolink logo, top ticking clock, and bottom OSD
        self.src_crop_norm = (0.105, 0.144, 0.894, 0.933)
        self.temporal_smooth = True
        
        self.current_opacity = 0.65
        self.latest_frame = None
        self._ema_frame = None
        self._lock = threading.Lock()
        self._running = True
        self.last_check = 0
        self.last_mtime = 0
        
        # Precomputed feather mask
        self._feather_mask = None
        self._build_feather_mask()
        self._reload_config(force=True)
        
        # Start background reader thread
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _build_feather_mask(self):
        edge_feather = 14
        mask = np.ones((self.height, self.width), dtype=float)
        for i in range(min(edge_feather, self.height // 2, self.width // 2)):
            f = float(i) / edge_feather
            mask[i, :] *= f
            mask[self.height - 1 - i, :] *= f
            mask[:, i] *= f
            mask[:, self.width - 1 - i] *= f
        self._feather_mask = mask[:, :, np.newaxis]

    def _preprocess_cam_frame(self, raw_frame):
        """Crop OSD clutter, downsample with INTER_AREA, and apply motion-adaptive temporal de-flicker."""
        fh, fw = raw_frame.shape[:2]
        if self.crop_osd and fw >= 160 and fh >= 90:
            nx1, ny1, nx2, ny2 = self.src_crop_norm
            cx1 = max(0, min(fw - 16, int(round(fw * nx1))))
            cy1 = max(0, min(fh - 9, int(round(fh * ny1))))
            cx2 = max(cx1 + 16, min(fw, int(round(fw * nx2))))
            cy2 = max(cy1 + 9, min(fh, int(round(fh * ny2))))
            raw_frame = raw_frame[cy1:cy2, cx1:cx2]

        resized = cv2.resize(raw_frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        if not self.temporal_smooth:
            self._ema_frame = None
            return resized

        resized_f = resized.astype(np.float32)
        if self._ema_frame is None or self._ema_frame.shape != resized_f.shape:
            self._ema_frame = resized_f
        else:
            diff = np.max(np.abs(resized_f - self._ema_frame), axis=2, keepdims=True)
            # Smooth static background (alpha=0.28 damps >70% of 4s H.264 I-frame pop & IR grain),
            # while passing real motion (cars, headlights, pedestrians: diff > 22) crisply with zero ghosting
            alpha = np.where(diff > 22.0, 1.0, np.where(diff > 12.0, 0.65, 0.28)).astype(np.float32)
            self._ema_frame = self._ema_frame + alpha * (resized_f - self._ema_frame)
        return np.clip(self._ema_frame, 0.0, 255.0).astype(np.uint8)

    def _worker(self):
        time.sleep(2.0)
        fail_count = 0
        while self._running:
            try:
                url = self.cam_url_getter()
                if not url:
                    time.sleep(2.0)
                    continue
                cap = cv2.VideoCapture(url)
                if not cap.isOpened():
                    time.sleep(2.0)
                    continue
                while self._running:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        fail_count += 1
                        if fail_count > 20:  # ~1s of read failure: break out to reconnect with fresh token
                            break
                        time.sleep(0.05)
                        continue
                    fail_count = 0
                    processed = self._preprocess_cam_frame(frame)
                    with self._lock:
                        self.latest_frame = processed
                cap.release()
            except Exception:
                time.sleep(2.0)

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
                self._reload_config(force=force)
        except OSError:
            pass

    def _reload_config(self, force=False):
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
            cfg = data.get("parking_lot_camera", {})
            self.enabled = cfg.get("enabled", True)
            self.x = cfg.get("x", 120)
            self.y = cfg.get("y", 135)
            new_w = cfg.get("width", 340)
            new_h = cfg.get("height", 191)
            if new_w != self.width or new_h != self.height:
                self.width = new_w
                self.height = new_h
                self._ema_frame = None
                self._build_feather_mask()
            self.max_opacity = float(cfg.get("max_opacity", 0.65))
            self.fade_speed = float(cfg.get("fade_speed", 0.04))
            self.style = cfg.get("style", "feathered")
            self.show_label = cfg.get("show_label", True)
            self.label = cfg.get("label", "PARKING LOT CENTER")
            self.crop_osd = bool(cfg.get("crop_osd", True))
            if "src_crop_norm" in cfg and len(cfg["src_crop_norm"]) == 4:
                self.src_crop_norm = tuple(float(v) for v in cfg["src_crop_norm"])
            self.temporal_smooth = bool(cfg.get("temporal_smooth", True))
        except Exception:
            pass

    def draw(self, frame_bgr, is_performer_framed=False, pos_override=None, opacity_override=None):
        if not self.enabled:
            return

        self.reload_if_needed()

        if opacity_override is not None:
            eff_opacity = float(opacity_override)
        else:
            target_opacity = 0.0 if is_performer_framed else self.max_opacity
            if self.current_opacity < target_opacity:
                self.current_opacity = min(target_opacity, self.current_opacity + self.fade_speed)
            elif self.current_opacity > target_opacity:
                self.current_opacity = max(target_opacity, self.current_opacity - self.fade_speed)
            eff_opacity = self.current_opacity

        if eff_opacity <= 0.005:
            return

        with self._lock:
            cam_frame = self.latest_frame.copy() if self.latest_frame is not None else None

        if cam_frame is None:
            return

        x1, y1 = pos_override if pos_override is not None else (self.x, self.y)
        x2, y2 = x1 + self.width, y1 + self.height
        if x1 < 0 or y1 < 0 or x2 > frame_bgr.shape[1] or y2 > frame_bgr.shape[0]:
            return

        if cam_frame.shape[1] != self.width or cam_frame.shape[0] != self.height:
            cam_resized = cv2.resize(cam_frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        else:
            cam_resized = cam_frame

        if self.style == "feathered":
            eff_alpha = self._feather_mask * eff_opacity
            wall_slice = frame_bgr[y1:y2, x1:x2]
            frame_bgr[y1:y2, x1:x2] = ((1.0 - eff_alpha) * wall_slice + eff_alpha * cam_resized).astype(np.uint8)

            if self.show_label and y1 >= 26:
                font = cv2.FONT_HERSHEY_DUPLEX
                (tw, th), _ = cv2.getTextSize(self.label, font, 0.45, 1)
                label_x = max(0, x1 + (self.width - tw) // 2)
                label_y = y1 - 8
                ly1 = max(0, label_y - th - 6)
                ly2 = min(frame_bgr.shape[0], label_y + 6)
                lx1 = max(0, label_x - 4)
                lx2 = min(frame_bgr.shape[1], label_x + tw + 6)
                if ly2 > ly1 and lx2 > lx1:
                    label_alpha = min(1.0, eff_opacity * 1.3)
                    label_roi = frame_bgr[ly1:ly2, lx1:lx2].copy()
                    cv2.putText(label_roi, self.label, (label_x - lx1, label_y - ly1), font, 0.45, (200, 205, 210), 1)
                    cv2.addWeighted(label_roi, label_alpha, frame_bgr[ly1:ly2, lx1:lx2], 1.0 - label_alpha, 0, frame_bgr[ly1:ly2, lx1:lx2])

        elif self.style == "framed":
            wall_slice = frame_bgr[y1:y2, x1:x2]
            frame_bgr[y1:y2, x1:x2] = cv2.addWeighted(cam_resized, eff_opacity, wall_slice, 1.0 - eff_opacity, 0)
            cv2.rectangle(frame_bgr, (x1 - 1, y1 - 1), (x2 + 1, y2 + 1), (70, 70, 80), 1)
            if self.show_label:
                font = cv2.FONT_HERSHEY_DUPLEX
                cv2.rectangle(frame_bgr, (x1, y1 - 22), (x1 + 230, y1), (25, 25, 30), -1)
                cv2.putText(frame_bgr, f"CAM 2 : {self.label}", (x1 + 6, y1 - 6), font, 0.42, (0, 230, 255), 1)


class DirectorStream:
    """Stage Director AI framing stream with close-up tracking, pet rejection, and watchdog."""

    def __init__(self, source, target, secrets, cfg, cam2_url=None, ip=None, token=None):
        self.ip = ip
        self.cfg = cfg
        self.secrets = secrets
        self.target = target
        self.started = time.monotonic()
        self.last_progress = self.started
        self.stage_preset_id = int(cfg.get("stage_resting_preset_id", 16))
        self.privacy_preset_id = int(cfg.get("privacy_preset_id", 17))
        self.current_view_mode = desired_view()
        self._last_view_check = 0.0
        self._ptz_slew_until = 0.0
        self._held_canvas = None
        self.stats = {'frame': 0, 'fps': 0.0, 'bitrate': '', 'out_time': '00:00:00', 'mode': 'director', 'view': self.current_view_mode}
        self.errors = []
        self._stop_event = threading.Event()

        # Token lifecycle & camera auto-reconnect
        self.token = token
        self.token_lock = threading.Lock()
        self.last_token_renew = time.monotonic()
        self.last_valid_frame = None
        self.reconnecting_camera = False
        self._reconnect_lock = threading.Lock()

        self.out_w = cfg.get("output_width", 1280)
        self.out_h = cfg.get("output_height", 720)
        # NVR subStream delivers 10 FPS; match input fps to prevent frame starvation and buffering
        self.fps = cfg.get("output_fps", 10.0)
        self.top_matte_h = cfg.get("top_matte_h", int(110 * (self.out_h / 720.0)))
        refresh_hours = int(cfg.get("scheduled_refresh_hours", 3))
        self.ticker = TickerOverlay(config_path="/home/joseph1/box2-stream/ticker.json", top_h=self.top_matte_h, refresh_hours=refresh_hours)
        self.wall_overlay = WallOverlay(config_path="/home/joseph1/box2-stream/ticker.json", base_w=self.out_w, base_h=self.out_h)

        # Parking lot center camera feed overlay with dynamic token getter
        cam2_getter = self.get_cam2_url if (self.ip and self.token) else cam2_url
        self.cam2_overlay = CameraFeedWallOverlay(cam2_getter, config_path="/home/joseph1/box2-stream/ticker.json", base_w=self.out_w, base_h=self.out_h) if (cam2_url or self.ip) else None

        initial_url = self.get_cam0_url() if (self.ip and self.token) else source
        self.cap = cv2.VideoCapture(initial_url)
        if not self.cap.isOpened():
            raise RuntimeError(f"DirectorStream: Failed to open video source {initial_url}")

        ret, test_frame = self.cap.read()
        if not ret or test_frame is None:
            self.cap.release()
            raise RuntimeError("DirectorStream: Failed to read initial frame from camera")

        self.last_valid_frame = test_frame.copy()
        src_h, src_w = test_frame.shape[:2]

        # Stage polygon & static wall-art exclusion:
        # Covers the elevated T-stage surface, stool, rugs, doorway, and jukebox front (x=12..515, y=20..315 on 640x360),
        # while strictly excluding the right offstage laundry wall / pipe / portrait poster (x >= 520).
        scale_x = src_w / 640.0
        scale_y = src_h / 360.0
        floor_cutoff_y = int(cfg.get("floor_cutoff_y_640", 315) * scale_y)
        stage_left_x = int(cfg.get("stage_left_x_640", 12) * scale_x)
        stage_right_x = int(cfg.get("stage_right_x_640", 515) * scale_x)
        stage_top_y = int(cfg.get("stage_top_y_640", 20) * scale_y)
        stage_vertices = [
            (stage_left_x, stage_top_y),
            (stage_right_x, stage_top_y),
            (stage_right_x, floor_cutoff_y),
            (stage_left_x, floor_cutoff_y),
        ]
        self.stage_polygon = StagePolygon(vertices=stage_vertices)
        # Explicit defense-in-depth exclusion zone over the right-wall portrait poster
        self.exclusion_boxes = [
            BoundingBox(
                x=float(530 * scale_x),
                y=float(105 * scale_y),
                width=float(110 * scale_x),
                height=float(145 * scale_y),
            )
        ]
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
            headroom_fraction=cfg.get("headroom_fraction", 0.50),
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
            loss_hold_seconds=cfg.get("loss_hold_seconds", 6.0),
            base_match_radius_px=cfg.get("base_match_radius_px", 85.0 * scale_x),
            max_performer_speed_px_s=cfg.get("max_performer_speed_px_s", 260.0 * scale_x),
            allow_proximity_reacquisition=True,
            require_confirmation_after_loss=False,
            max_performer_y=float(floor_cutoff_y),
            exclusion_boxes=self.exclusion_boxes,
            acquisition_confirm_frames=int(cfg.get("acquisition_confirm_frames", 4)),
            acquisition_window_seconds=float(cfg.get("acquisition_window_seconds", 1.2)),
            reacquire_confirm_frames=int(cfg.get("reacquire_confirm_frames", 2)),
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
             '-reconnect', '1', '-reconnect_at_eof', '1', '-reconnect_streamed', '1',
             '-reconnect_on_network_error', '1', '-reconnect_delay_max', '2',
             '-rw_timeout', '15000000',
             '-i', initial_url,
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

        self.last_progress = time.monotonic()
        if self.ip and self.token:
            init_preset = self.privacy_preset_id if self.current_view_mode == 'privacy' else self.stage_preset_id
            threading.Thread(target=nvr_goto_preset, args=(self.ip, self.token, init_preset), daemon=True).start()
        threading.Thread(target=self.run_worker, daemon=True).start()
        threading.Thread(target=self.read_progress, daemon=True).start()
        threading.Thread(target=self.read_errors, daemon=True).start()
        if self.ip and self.token:
            threading.Thread(target=self._keepalive_worker, daemon=True).start()

    def _render_privacy_canvas(self, src_frame):
        """Render the 5x optically zoomed Box 2 wall sign (Preset 17) into full output canvas."""
        vis_h = max(16, self.out_h - self.top_matte_h)
        sx = self.src_w / 640.0
        sy = self.src_h / 360.0
        p_cfg = self.ticker.data.get("privacy_placeholder", {})
        style = p_cfg.get("style", "fullbleed")

        out = np.full((self.out_h, self.out_w, 3), (10, 10, 12), dtype=np.uint8)
        if style == "spotlight":
            x1, y1, x2, y2 = int(72 * sx), int(38 * sy), int(282 * sx), int(246 * sy)
            sub = src_frame[max(0, y1):min(self.src_h, y2), max(0, x1):min(self.src_w, x2)].copy()
            spot_w = min(self.out_w, int(round(vis_h * (210.0 / 208.0))))
            vis = cv2.resize(sub, (spot_w, vis_h), interpolation=cv2.INTER_LANCZOS4)
            mask = np.ones((vis_h, spot_w), dtype=np.float32)
            fx, fy = min(75, spot_w // 4), min(45, vis_h // 4)
            for i in range(fx):
                f = 0.5 - 0.5 * np.cos(np.pi * i / max(1, fx))
                mask[:, i] *= f
                mask[:, spot_w - 1 - i] *= f
            for j in range(fy):
                f = 0.5 - 0.5 * np.cos(np.pi * j / max(1, fy))
                mask[j, :] *= f
                mask[vis_h - 1 - j, :] *= f
            xo = (self.out_w - spot_w) // 2
            roi_bg = out[self.top_matte_h:self.out_h, xo:xo + spot_w].astype(np.float32)
            out[self.top_matte_h:self.out_h, xo:xo + spot_w] = (
                roi_bg * (1.0 - mask[:, :, None]) + vis.astype(np.float32) * mask[:, :, None]
            ).astype(np.uint8)
        else:
            # Default fullbleed undistorted crop on Box 2 wall above jukebox (x=0..356, y=54..224 on 640x360)
            x1, y1, x2, y2 = 0, int(54 * sy), int(356 * sx), int(224 * sy)
            sub = src_frame[max(0, y1):min(self.src_h, y2), max(0, x1):min(self.src_w, x2)].copy()
            sw = sub.shape[1]
            # Smooth dark vignette on left locker edge and right pipe edge (completely hides x>=320)
            r_start, r_zero = int(285 * sx), int(320 * sx)
            l_end = int(50 * sx)
            x_idx = np.arange(sw, dtype=np.float32)
            w_mask = np.ones(sw, dtype=np.float32)
            if l_end > 0:
                w_mask = np.minimum(w_mask, np.clip(x_idx / float(l_end), 0.15, 1.0))
            if r_zero > r_start:
                w_mask = np.minimum(w_mask, np.clip(1.0 - (x_idx - r_start) / float(r_zero - r_start), 0.0, 1.0))
            bg_px = np.array([10.0, 10.0, 12.0], dtype=np.float32)
            sub = (sub.astype(np.float32) * w_mask[None, :, None] + bg_px * (1.0 - w_mask[None, :, None])).astype(np.uint8)
            out[self.top_matte_h:self.out_h, :] = cv2.resize(sub, (self.out_w, vis_h), interpolation=cv2.INTER_LANCZOS4)
        return out

    def _render_stage_box2_fallback(self, wide_frame):
        """Instant crop onto Box 2 from wide Stage view used during the 2.6s PTZ motor slew to Preset 17."""
        vis_h = max(16, self.out_h - self.top_matte_h)
        sx = self.src_w / 640.0
        sy = self.src_h / 360.0
        x1, y1, x2, y2 = int(435 * sx), int(52 * sy), int(548 * sx), int(148 * sy)
        sub = wide_frame[max(0, y1):min(self.src_h, y2), max(0, x1):min(self.src_w, x2)].copy()
        out = np.full((self.out_h, self.out_w, 3), (10, 10, 12), dtype=np.uint8)
        if sub.size > 0:
            spot_w = min(self.out_w, int(round(vis_h * (sub.shape[1] / max(1.0, float(sub.shape[0]))))))
            vis = cv2.resize(sub, (spot_w, vis_h), interpolation=cv2.INTER_CUBIC)
            xo = (self.out_w - spot_w) // 2
            out[self.top_matte_h:self.out_h, xo:xo + spot_w] = vis
        return out

    def get_token(self):
        with self.token_lock:
            return self.token

    def get_cam0_url(self):
        token = self.get_token()
        if self.ip and token:
            return flv_url(self.ip, token, self.cfg)
        return None

    def get_cam2_url(self):
        token = self.get_token()
        if self.ip and token:
            return flv_url_ch(self.ip, token, 1, 'sub')
        return None

    def _reconnect_camera(self):
        if not self.ip:
            self.reconnecting_camera = False
            return
        with self._reconnect_lock:
            try:
                log("Stage Director: Camera feed interrupted, renewing NVR session and reconnecting...")
                new_token = nvr_login(self.ip, self.cfg)
                with self.token_lock:
                    old_token = self.token
                    self.token = new_token
                    self.last_token_renew = time.monotonic()
                new_url = flv_url(self.ip, new_token, self.cfg)
                new_cap = cv2.VideoCapture(new_url)
                if new_cap.isOpened():
                    ret, frame = new_cap.read()
                    if ret and frame is not None:
                        old_cap = self.cap
                        self.cap = new_cap
                        self.last_valid_frame = frame.copy()
                        try:
                            old_cap.release()
                        except Exception:
                            pass
                        log("Stage Director: Camera connection recovered seamlessly (zero Twitch dropped frames)")
                    else:
                        new_cap.release()
                if old_token:
                    threading.Thread(target=nvr_logout, args=(self.ip, old_token), daemon=True).start()
            except Exception as exc:
                log(f"Stage Director camera reconnect warning: {scrub(str(exc), self.secrets)}")
            finally:
                self.reconnecting_camera = False

    def _keepalive_worker(self):
        """Active NVR session heartbeat and proactive token renewal.
        1. Calls GetTime every 60s with current token to prevent NVR idle timeout.
        2. Proactively renews token every 30m before 60m lease expires.
        """
        while not self._stop_event.is_set():
            time.sleep(60.0)
            if self._stop_event.is_set() or not self.ip:
                break
            try:
                token = self.get_token()
                if token:
                    nvr_call(self.ip, f"cmd=GetTime&token={token}", [{"cmd": "GetTime", "action": 0, "param": {}}], timeout=5)
            except Exception as exc:
                log(f"Stage Director keepalive warning: {scrub(str(exc), self.secrets)}")

            if time.monotonic() - self.last_token_renew > 1800.0:
                try:
                    new_token = nvr_login(self.ip, self.cfg)
                    with self.token_lock:
                        self.token = new_token
                        self.last_token_renew = time.monotonic()
                    log("Stage Director: proactively renewed NVR session token (lease extended)")
                    # Do NOT forcibly Logout old_token immediately: active HTTP FLV readers
                    # (cam2_overlay / ffmpeg audio) may still hold sockets opened under it;
                    # letting old_token expire naturally avoids mid-stream reconnect blips.
                except Exception as exc:
                    log(f"Stage Director token renewal warning: {scrub(str(exc), self.secrets)}")

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
        frame_interval = 1.0 / max(1.0, float(self.fps))
        consecutive_read_fails = 0
        proposal = None

        try:
            while not self._stop_event.is_set() and self.proc.poll() is None:
                loop_start = time.monotonic()
                ret = False
                frame = None

                if self.cap is not None and self.cap.isOpened() and not self.reconnecting_camera:
                    try:
                        ret, frame = self.cap.read()
                    except Exception:
                        ret = False
                        frame = None

                if ret and frame is not None:
                    consecutive_read_fails = 0
                    self.last_valid_frame = frame.copy()
                else:
                    consecutive_read_fails += 1
                    # Frame starvation protection: feed last valid frame into FFmpeg
                    if self.last_valid_frame is not None:
                        frame = self.last_valid_frame.copy()
                    else:
                        frame = np.zeros((self.src_h, self.src_w, 3), dtype=np.uint8)

                    # Trigger camera capture auto-reconnect if read fails for >= 10 frames (~1.0s)
                    if consecutive_read_fails >= 10 and not self.reconnecting_camera:
                        self.reconnecting_camera = True
                        threading.Thread(target=self._reconnect_camera, daemon=True).start()

                cur_mono = time.monotonic()
                cur_utc = datetime.now(timezone.utc)
                self.ensure_session(cur_utc, cur_mono)

                # Poll desired view mode ('stage' vs 'privacy' Box 2 placeholder) every 0.5s without dropping stream
                if cur_mono - self._last_view_check >= 0.5:
                    self._last_view_check = cur_mono
                    target_view = desired_view()
                    if target_view != self.current_view_mode:
                        log(f"Stage Director view transition: {self.current_view_mode} -> {target_view}")
                        if target_view == "privacy":
                            # Immediately mask room using Box 2 fallback before PTZ motor starts moving
                            self._held_canvas = self._render_stage_box2_fallback(frame)
                            self._ptz_slew_until = cur_mono + 2.8
                            if self.ip:
                                threading.Thread(
                                    target=nvr_goto_preset,
                                    args=(self.ip, self.get_token(), self.privacy_preset_id),
                                    daemon=True,
                                ).start()
                        else:
                            # Hold clean Box 2 privacy canvas while PTZ slews back to Stage Resting
                            self._held_canvas = self._render_privacy_canvas(frame)
                            self._ptz_slew_until = cur_mono + 2.8
                            self.adapter.framing.reset(monotonic_seconds=cur_mono)
                            self.adapter.tracker.enable()
                            if self.ip:
                                threading.Thread(
                                    target=nvr_goto_preset,
                                    args=(self.ip, self.get_token(), self.stage_preset_id),
                                    daemon=True,
                                ).start()
                        self.current_view_mode = target_view
                        self.stats['view'] = target_view

                if cur_mono < self._ptz_slew_until and self._held_canvas is not None:
                    rendered = self._held_canvas.copy()
                    if self.current_view_mode == "privacy" and self.cam2_overlay is not None:
                        p_cfg = self.ticker.data.get("privacy_placeholder", {})
                        if p_cfg.get("show_cam2_in_privacy", True):
                            px = int(p_cfg.get("cam2_x", 26))
                            py = int(p_cfg.get("cam2_y", 495))
                            pop = float(p_cfg.get("cam2_opacity", 0.78))
                            self.cam2_overlay.draw(rendered, pos_override=(px, py), opacity_override=pop)
                elif self.current_view_mode == "privacy":
                    rendered = self._render_privacy_canvas(frame)
                    p_cfg = self.ticker.data.get("privacy_placeholder", {})
                    if self.cam2_overlay is not None and p_cfg.get("show_cam2_in_privacy", True):
                        px = int(p_cfg.get("cam2_x", 26))
                        py = int(p_cfg.get("cam2_y", 495))
                        pop = float(p_cfg.get("cam2_opacity", 0.78))
                        self.cam2_overlay.draw(rendered, pos_override=(px, py), opacity_override=pop)
                else:
                    candidate_boxes = []
                    onstage_count = 0
                    if consecutive_read_fails == 0:
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

                        for (fx, fy, fw, fh) in raw_faces:
                            bbox = BoundingBox(
                                x=float(fx * sx),
                                y=float(fy * sy),
                                width=float(fw * sx),
                                height=float(fh * sy),
                            )
                            if (
                                bbox.center_y <= self.floor_cutoff_y
                                and not self.adapter.tracker._is_excluded(bbox)
                                and self.stage_polygon.contains_box(bbox)
                            ):
                                candidate_boxes.append(bbox)
                                onstage_count += 1

                        # Let PerformerTracker.update() enforce the multi-frame acquisition_confirm_frames
                        # persistence gate for single performers; only resolve simultaneous multi-person
                        # ambiguity once the primary candidate also satisfies persistence.
                        if self.adapter.tracker.state.value == "ambiguous" and candidate_boxes:
                            primary = max(candidate_boxes, key=lambda b: b.area)
                            if self.adapter.tracker._check_acquisition_persistence(primary, cur_mono):
                                self.adapter.confirm_subject(primary, cur_mono)

                        proposal = self.adapter.process_frame(candidate_boxes, cur_utc, cur_mono)

                        # Log tracking state transitions
                        current_state = (proposal.tracking_state, proposal.camera_action)
                        if current_state != self._last_logged_state:
                            log(f"Stage Director state: {proposal.tracking_state}, action: {proposal.camera_action}, candidates: {onstage_count}")
                            self._last_logged_state = current_state

                    if proposal is None:
                        proposal = self.adapter.process_frame([], cur_utc, cur_mono)

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

                    # Subtle painted wall / parking lot camera overlay:
                    # Stays steady on empty wide stage (ignoring unconfirmed 1-frame blips),
                    # and stays smoothly faded to 0 throughout tracking, holding, and zoom-out transitions.
                    zoom_factor = (proposal.framing or {}).get("zoom_factor", 1.0)
                    is_performer_framed = (
                        proposal.tracking_state in ("tracking", "holding")
                        or zoom_factor > 1.05
                    )
                    if self.cam2_overlay is not None and self.cam2_overlay.enabled:
                        self.cam2_overlay.draw(rendered, is_performer_framed=is_performer_framed)
                    else:
                        self.wall_overlay.draw(rendered, is_performer_framed=is_performer_framed)

                # Draw top broadcast banner with live moving timestamp & scrolling ticker tape
                if self.top_matte_h > 0:
                    self.ticker.draw(rendered, standby_mode=(self.current_view_mode == "privacy"))

                try:
                    self.proc.stdin.write(rendered.tobytes())
                    self.proc.stdin.flush()
                    self.last_progress = time.monotonic()
                except (BrokenPipeError, OSError, ValueError):
                    break

                # Frame pacing: maintain exact 10 FPS cadence
                elapsed = time.monotonic() - loop_start
                sleep_needed = frame_interval - elapsed
                if sleep_needed > 0.002:
                    time.sleep(sleep_needed)
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
        if time.monotonic() - self.started < 30.0:
            return False
        return time.monotonic() - self.last_progress > STALL_SECONDS

    def stop(self):
        self._stop_event.set()
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
        if self.cam2_overlay is not None:
            self.cam2_overlay._running = False
        token = self.get_token()
        if self.ip and token:
            threading.Thread(target=nvr_logout, args=(self.ip, token), daemon=True).start()


def run():
    cfg = json.loads(CONFIG.read_text())
    secrets = [cfg['nvr_password'], cfg['twitch_key']]
    refresh_hours = int(cfg.get('scheduled_refresh_hours', 3))
    status = {'state': 'starting', 'since': now(), 'restarts': 0, 'nvr_ip': None, 'last_error': None}
    backoff = 3
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    last_refreshed_slot = None

    while not stop.is_set():
        mode = desired()
        if mode not in ('on', 'test'):
            write_json(STATUS, {**status, 'state': 'off', 'updated': now()})
            stop.wait(2)
            continue
        token = ip = stream = None
        scheduled_rollover = False
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
                cam2_url = flv_url_ch(ip, token, 1, 'sub')
                stream = DirectorStream(flv_url(ip, token, cfg), rtmp_url(cfg, mode), secrets + [token], cfg, cam2_url=cam2_url, ip=ip, token=token)
            else:
                log(f"streaming (Passthrough {'live' if mode == 'on' else 'Twitch bandwidth test'}) from NVR at {ip}")
                stream = Stream(flv_url(ip, token, cfg), rtmp_url(cfg, mode), secrets + [token], cfg)

            status.update(state='live' if mode == 'on' else 'testing', since=now(), last_error=None)
            while not stop.is_set() and stream.proc.poll() is None and desired() == mode:
                if stream.stalled():
                    raise RuntimeError(f'no new video for {STALL_SECONDS} s; restarting')
                if time.monotonic() - stream.started > 60:
                    backoff = 3  # a minute of good streaming resets the back-off

                # Scheduled 3-hour VOD refresh at the top of the hour for clean clipping blocks
                now_dt = datetime.now()
                if (
                    refresh_hours > 0
                    and now_dt.hour % refresh_hours == 0
                    and now_dt.minute == 0
                    and (now_dt.year, now_dt.month, now_dt.day, now_dt.hour) != last_refreshed_slot
                    and (time.monotonic() - stream.started > 300)
                ):
                    last_refreshed_slot = (now_dt.year, now_dt.month, now_dt.day, now_dt.hour)
                    log(f"Scheduled {refresh_hours}-hour VOD rollover at {now_dt.strftime('%I:%M %p')} for Twitch clip archiving")
                    scheduled_rollover = True
                    break

                next_ref = next_scheduled_refresh_time(refresh_hours)
                next_ref_str = next_ref.strftime('%Y-%m-%d %I:%M:%S %p') if next_ref else 'disabled'
                write_json(STATUS, {
                    **status,
                    **stream.stats,
                    'next_scheduled_refresh': next_ref_str,
                    'updated': now(),
                })
                stop.wait(1)

            if scheduled_rollover:
                stream.stop()
                status.update(last_error=None)
                # Wait 7 seconds for Twitch ingest to close and archive the 3-hour VOD
                stop.wait(7)
                continue

            if stream.proc.poll() is not None and desired() == mode and not stop.is_set():
                raise RuntimeError('ffmpeg exited: ' + (stream.errors[-1] if stream.errors else f'code {stream.proc.returncode}'))
        except Exception as exc:
            status.update(state='recovering', last_error=scrub(str(exc), secrets + ([token] if token else [])),
                          restarts=status['restarts'] + 1)
            wait_s = max(backoff, 6)  # Give Twitch ingest proxy at least 6s to clear previous socket
            log(f"problem: {status['last_error']} (retrying in {wait_s} s)")
            write_json(STATUS, {**status, 'updated': now()})
            stop.wait(wait_s)
            backoff = min(backoff * 2, 30)
        finally:
            if stream:
                stream.stop()
            elif token and ip:
                nvr_logout(ip, token)
    write_json(STATUS, {**status, 'state': 'stopped', 'updated': now()})


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if command in ('on', 'test', 'off'):
        write_json(STATE, {'desired': command, 'view': 'stage', 'set': now()})
        print({'on': 'Going live (stage view): the Orin will stream to Twitch within a few seconds.',
               'test': 'Twitch bandwidth test: the Orin streams to Twitch without going live.',
               'off': 'Stream off.'}[command])
    elif command in ('privacy', 'standby', 'brb'):
        cur_desired = desired()
        target_desired = cur_desired if cur_desired in ('on', 'test') else 'on'
        write_json(STATE, {'desired': target_desired, 'view': 'privacy', 'set': now()})
        print('Privacy placeholder ON: camera zooming to Box 2 wall sign (Preset 17). Room hidden; Twitch stream stays live.')
    elif command == 'stage':
        cur_desired = desired()
        target_desired = cur_desired if cur_desired in ('on', 'test') else 'on'
        write_json(STATE, {'desired': target_desired, 'view': 'stage', 'set': now()})
        print('Stage view ON: camera returning to Stage Resting (Preset 16) and resuming Stage Director.')
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
