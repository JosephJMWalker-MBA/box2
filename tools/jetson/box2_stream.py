#!/usr/bin/env python3
"""BOX2 stream box: NVR stage camera, stage mic + auto-ducking show mixer → Twitch + SSD clip buffer.

Supports two streaming modes:
1. "director" (default): Intelligent Stage Director AI framing, close-up tracking,
   floor/pet rejection, Box 2 privacy standby, auto-ducking show audio mixer,
   uninterrupted marathon streaming, and instant lossless SSD set clipping at 720p.
2. "passthrough": Original untouched raw camera feed.

Core commands:
  box2-stream on | test | off           set desired stream state (kept across reboots)
  box2-stream status                    show live stream, view, audio mix & clip status
  box2-stream marathon | vod-mode       longest uninterrupted stream vs 3-hour VOD drops
  box2-stream showtime                  9PM show mode: stage active + auto-ducking music
  box2-stream rehearse [minutes]        stage active now for rehearsal (auto-reverts to schedule)
  box2-stream auto | done               resume 9PM-2AM stage / 2AM-9PM privacy schedule
  box2-stream stage | privacy           manual view lock without dropping stream
  box2-stream music [auto|on|off|next|undertone|bed|walkup|vol <0..1>|onstage-vol <0..1>]   live music & mix control
  box2-stream sync-catalog              pull any new YurrMom.Com releases into rotation live
  box2-stream dj [status|spotify|rotate|suno|house|ad-every <m|off>|ad-now|skip-ad|launch]  Spotify Connect + Ad Scheduler
  box2-stream joke [list|add "text"|remove <n>]   manage live rotating stream & ticker jokes
  box2-stream theme [black_friday|thanksgiving|classic]   set broadcast seasonal theme live
  box2-stream mark-set                  mark start of a comedy set right now
  box2-stream clip [dur|--last-set] [label]   save lossless .mp4 clip without dropping stream
  box2-stream clips                     list recent detected sets and saved .mp4 clips
  box2-stream run                       the service loop (systemd runs this)

Secrets (NVR login, Twitch key) live only in config.json (mode 600) and in
process memory; nothing here prints or logs them.
"""
import collections
import concurrent.futures
from datetime import datetime, timezone, timedelta
import ipaddress
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

HOME = Path(__file__).resolve().parent
CONFIG, STATE, STATUS = HOME / 'config.json', HOME / 'state.json', HOME / 'status.json'
JOKES_FILE = HOME / 'jokes.json'
STALL_SECONDS = 20
FFMPEG = '/usr/bin/ffmpeg'
FFPROBE = '/usr/bin/ffprobe'

DEFAULT_SSD_ROOT = Path('/mnt/ssd')
DEFAULT_CLIP_BASE = (DEFAULT_SSD_ROOT / 'box2-clips') if DEFAULT_SSD_ROOT.exists() else (HOME / 'clips')
DEFAULT_MUSIC_DIR = (DEFAULT_SSD_ROOT / 'media' / 'box2-music') if DEFAULT_SSD_ROOT.exists() else (HOME / 'music')
DEFAULT_STAGE_BEDS_DIR = (DEFAULT_SSD_ROOT / 'media' / 'box2-stage-beds') if DEFAULT_SSD_ROOT.exists() else (HOME / 'stage-beds')
DEFAULT_ADS_DIR = (DEFAULT_SSD_ROOT / 'media' / 'box2-ads') if DEFAULT_SSD_ROOT.exists() else (HOME / 'ads')
AUDIO_EXTS = ('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.mp4')

if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))

try:
    import box2_radio
except ImportError:
    from tools.jetson import box2_radio

try:
    import box2_chessheat
except ImportError:
    from tools.jetson import box2_chessheat

try:
    import box2_captions
except ImportError:
    from tools.jetson import box2_captions

# Stage Director integration
STAGE_DIR = Path("/home/joseph1/stage-director")
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage_director.cinematography import (
    OpticalSlewConcealer,
    ShotDirector,
    ShotType,
    ShotVocabularyConfig,
    build_stage_isp_payload,
)
from stage_director.signal_integrity import (
    AudioAuthorityPolicy,
    ProvenanceVerdict,
    SignalIntegrityMonitor,
    discover_authorized_usb_mic,
    measure_visual_quality,
    verify_audio_provenance,
)

try:
    import cv2
    import numpy as np
    from stage_director.adapter import StageFramingAdapter
    from stage_director.core import BookingSnapshot, Mode
    from stage_director.framing import FramingConfig
    from stage_director.geometry import BoundingBox, StagePolygon
    from stage_director.tracking import PerformerTracker
    STAGE_DIRECTOR_AVAILABLE = True
except Exception:
    try:
        import numpy as np  # still enable audio/clip math tests if stage_director path differs
    except Exception:
        np = None
    STAGE_DIRECTOR_AVAILABLE = False


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def log(message):
    print(f'{now()} {message}', flush=True)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=1) + '\n')
    tmp.replace(path)


def read_state():
    try:
        data = json.loads(STATE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def update_state(**updates):
    cur = read_state()
    for k, v in updates.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    cur['set'] = now()
    write_json(STATE, cur)
    return cur


def desired():
    return read_state().get('desired', 'off')


def effective_refresh_hours(cfg=None, state_data=None):
    """Resolve scheduled VOD rollover interval (0 = uninterrupted marathon stream)."""
    st = state_data if state_data is not None else read_state()
    cadence = st.get('cadence')
    if cadence == 'marathon':
        return 0
    if cadence == 'vod':
        vod_h = int((cfg or {}).get('vod_refresh_hours', 3))
        return vod_h if vod_h > 0 else 3
    # Default to 0 (uninterrupted marathon mode) unless explicitly configured > 0
    return int((cfg or {}).get('scheduled_refresh_hours', 0))


def is_within_show_hours(now_dt=None, start_hour=21, end_hour=2):
    """Return True if local time falls inside the active live stage window (default 9:00 PM - 2:00 AM)."""
    if now_dt is None:
        now_dt = datetime.now()
    h = now_dt.hour
    start_hour = int(start_hour) % 24
    end_hour = int(end_hour) % 24
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= h < end_hour
    return h >= start_hour or h < end_hour


def seconds_until_showtime(now_dt=None, start_hour=21, end_hour=2):
    """Return seconds until next `start_hour:00:00` showtime (0.0 if currently within show hours)."""
    if now_dt is None:
        now_dt = datetime.now()
    if is_within_show_hours(now_dt=now_dt, start_hour=start_hour, end_hour=end_hour):
        return 0.0
    target = now_dt.replace(hour=int(start_hour) % 24, minute=0, second=0, microsecond=0)
    if target <= now_dt:
        target += timedelta(days=1)
    return max(0.0, (target - now_dt).total_seconds())


def normalize_seasonal_theme(raw_theme, default="black_friday"):
    t = str(raw_theme or "").strip().lower().replace("-", "_").replace(" ", "_")
    if t in ("black_friday", "blackfriday", "bf"):
        return "black_friday"
    if t in ("thanksgiving", "tg"):
        return "thanksgiving"
    if t in ("classic", "none", "default", "standard"):
        return "classic"
    return t or default


def load_jokes_data(jokes_path=None):
    p = Path(jokes_path) if jokes_path else JOKES_FILE
    if not p.exists():
        return {"seasonal_greeting": "", "jokes": []}
    try:
        data = json.loads(p.read_text())
        if isinstance(data, list):
            return {"seasonal_greeting": "", "jokes": [str(x).strip() for x in data if str(x).strip()]}
        if isinstance(data, dict):
            jokes = [str(x).strip() for x in data.get("jokes", []) if str(x).strip()]
            return {"seasonal_greeting": str(data.get("seasonal_greeting", "")), "jokes": jokes}
    except Exception:
        pass
    return {"seasonal_greeting": "", "jokes": []}


def format_now_playing_label(raw_track, audio_source="house_ssd", ad_shield_active=False):
    """Format clean (badge_tag, display_title) for the attached Now Playing tab beneath the ticker."""
    src = str(audio_source or "").lower()
    t = str(raw_track or "").strip()
    if ad_shield_active or src == "box2_ads_swap" or t.upper().startswith("SPONSOR:"):
        promo_lbl = t.split(":", 1)[1].strip() if ":" in t else "YurrMom.Com"
        return "SPONSOR", (promo_lbl or "YurrMom.Com")
    if not t:
        return "", ""
    # Strip leading numeric track indices like '01_' or '04 - '
    t = re.sub(r'^\d{1,3}[\s_.-]+', '', t).strip()
    if " - " not in t and "_" in t:
        t = t.replace("_", " ").strip()
    if len(t) > 52:
        t = t[:49].rstrip() + "..."

    if src == "dj_spotify":
        return "SPOTIFY", t
    if src == "dj_suno":
        return "SUNO", t
    if src == "stage_bed" or t.lower().startswith("stage groove -"):
        bed_lbl = re.sub(r'^stage groove\s*-\s*', '', t, flags=re.I).strip()
        return "STAGE GROOVE", (bed_lbl or t)
    return "NOW PLAYING", t


def view_policy(now_epoch=None, state_data=None):
    """Return ('privacy' | 'stage' | 'rehearse' | 'auto'). Timed rehearse overrides auto-expire."""
    st = state_data if state_data is not None else read_state()
    v = st.get('view', 'auto')
    until = st.get('view_until')
    if until is not None:
        cur_ts = float(now_epoch if now_epoch is not None else time.time())
        try:
            if cur_ts >= float(until):
                return 'auto'
        except (TypeError, ValueError):
            return 'auto'
    if v in ('privacy', 'standby', 'brb'):
        return 'privacy'
    if v == 'rehearse':
        return 'rehearse'
    if v == 'stage':
        return 'stage'
    return 'auto'


def desired_view(ticker_path="/home/joseph1/box2-stream/ticker.json", now_dt=None, start_hour=21, end_hour=2, now_epoch=None):
    """Resolve active view ('privacy' vs 'stage') from explicit overrides, timed rehearsal, or 9PM-2AM schedule."""
    try:
        if ticker_path and os.path.exists(ticker_path):
            tk = json.loads(Path(ticker_path).read_text())
            if tk.get('privacy_mode') is True or tk.get('privacy_placeholder', {}).get('enabled') is True:
                return 'privacy'
    except (OSError, ValueError):
        pass

    pol = view_policy(now_epoch=now_epoch)
    if pol == 'privacy':
        return 'privacy'
    if pol in ('stage', 'rehearse'):
        return 'stage'
    return 'stage' if is_within_show_hours(now_dt=now_dt, start_hour=start_hour, end_hour=end_hour) else 'privacy'


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


def nvr_goto_preset(ip, token, preset_id, channel=0, speed=32, settle_confirm=False):
    """Recall a saved optical PTZ preset on the Reolink NVR (with optional backlash settle pass)."""
    if not ip or not token or not preset_id:
        return False
    body = [{'cmd': 'PtzCtrl', 'action': 0, 'param': {'channel': int(channel), 'op': 'ToPos', 'id': int(preset_id), 'speed': int(speed)}}]
    try:
        res = nvr_call(ip, f'cmd=PtzCtrl&token={token}', body, timeout=5)
        ok = res.get('code') == 0
        if ok and settle_confirm:
            time.sleep(3.2)
            nvr_call(ip, f'cmd=PtzCtrl&token={token}', body, timeout=5)
        return ok
    except Exception:
        return False


def nvr_set_zoom_pos(ip, token, zoom_pos, channel=0):
    """Command absolute closed-loop optical zoom position (`0..34`) on Reolink RLC-823A."""
    if not ip or not token:
        return False
    pos_clamped = max(0, min(34, int(zoom_pos)))
    body = [{'cmd': 'StartZoomFocus', 'action': 0, 'param': {'ZoomFocus': {'channel': int(channel), 'op': 'ZoomPos', 'pos': pos_clamped}}}]
    try:
        res = nvr_call(ip, f'cmd=StartZoomFocus&token={token}', body, timeout=5)
        return res.get('code') == 0
    except Exception:
        return False


def nvr_get_channel_osd(ip, token, channel=0):
    """Return NVR channel OSD room/camera name for P1/#I provenance verification."""
    if not ip or not token:
        return None
    try:
        res = nvr_call(ip, f'cmd=GetOsd&token={token}', [{'cmd': 'GetOsd', 'action': 0, 'param': {'channel': int(channel)}}], timeout=4)
        if res.get('code') == 0:
            return res.get('value', {}).get('Osd', {}).get('osdChannel', {}).get('name')
    except Exception:
        pass
    return None


def nvr_configure_stage_optics(ip, token, channel=0, face_luma=70.0, jukebox_luma=190.0):
    """Enforce exclusive PTZ ownership (`aiTrack=0`) and face-optimized ISP (`60HZ` + DRC against jukebox glare)."""
    if not ip or not token:
        return False
    ok_any = False
    try:
        # 1. Assert exclusive PTZ control: disable onboard firmware AI auto-tracking if enabled
        ai_res = nvr_call(ip, f'cmd=GetAiCfg&token={token}', [{'cmd': 'GetAiCfg', 'action': 0, 'param': {'channel': int(channel)}}], timeout=4)
        ai_val = ai_res.get('value', {})
        if ai_val.get('aiTrack', 0) != 0:
            ai_off = dict(ai_val)
            ai_off['channel'] = int(channel)
            ai_off['aiTrack'] = 0
            nvr_call(ip, f'cmd=SetAiCfg&token={token}', [{'cmd': 'SetAiCfg', 'action': 0, 'param': ai_off}], timeout=4)
        ok_any = True
    except Exception:
        pass

    try:
        # 2. Optimize ISP exposure for stage skin tones rather than the illuminated jukebox
        isp_res = nvr_call(ip, f'cmd=GetIsp&token={token}', [{'cmd': 'GetIsp', 'action': 0, 'param': {'channel': int(channel)}}], timeout=4)
        cur_isp = isp_res.get('value', {}).get('Isp')
        if isinstance(cur_isp, dict):
            target_isp = dict(cur_isp)
            patch = build_stage_isp_payload(channel=channel, face_luma=face_luma, jukebox_luma=jukebox_luma)['Isp']
            target_isp['antiFlicker'] = patch['antiFlicker']
            target_isp['backLight'] = patch['backLight']
            target_isp['drc'] = patch['drc']
            r = nvr_call(ip, f'cmd=SetIsp&token={token}', [{'cmd': 'SetIsp', 'action': 0, 'param': {'Isp': target_isp}}], timeout=5)
            ok_any = ok_any or (r.get('code') == 0)
    except Exception:
        pass
    return ok_any


def probe_stage_video_source(ip, token, cfg):
    """Auto-detect native 4K RTSP main stream once NVR firmware/password supports it; fallback cleanly to FLV."""
    fallback = flv_url(ip, token, cfg)
    if not ip or not cfg.get('prefer_4k_ingest', True) or not os.path.exists(FFPROBE):
        return fallback, False
    ch = int(cfg.get('nvr_channel', 0)) + 1
    u = urllib.parse.quote(str(cfg.get('nvr_user', '')), safe='')
    p = urllib.parse.quote(str(cfg.get('nvr_password', '')), safe='')
    for suffix in (f'Preview_{ch:02d}_main', f'/h265Preview_{ch:02d}_main', f'h265Preview_{ch:02d}_main'):
        cand = f"rtsp://{u}:{p}@{ip}:554/{suffix.lstrip('/')}" if not suffix.startswith('/') else f"rtsp://{u}:{p}@{ip}:554/{suffix}"
        try:
            pr = subprocess.run(
                [FFPROBE, '-rtsp_transport', 'tcp', '-probesize', '1000000', '-analyzeduration', '1000000',
                 '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'json', cand],
                capture_output=True, text=True, timeout=2.5,
            )
            if pr.returncode == 0 and pr.stdout.strip():
                meta = json.loads(pr.stdout)
                streams = meta.get('streams') or []
                if streams and int(streams[0].get('width', 0)) >= 2560:
                    log(f"Stage Director P3: Unlocked native {streams[0]['width']}x{streams[0]['height']} main stream -> upgrading broadcast to 1080p30 @ 6 Mbps!")
                    return cand, True
        except Exception:
            continue
    return fallback, False


def flv_url(ip, token, cfg):
    return f"http://{ip}/flv?port=1935&app=bcs&stream=channel{cfg['nvr_channel']}_{cfg['nvr_stream']}.bcs&token={token}"


def flv_url_ch(ip, token, channel, stream='sub'):
    return f"http://{ip}/flv?port=1935&app=bcs&stream=channel{channel}_{stream}.bcs&token={token}"


def rtsp_url_ch(ip, cfg, channel=None, stream=None):
    ch = int(cfg.get('nvr_channel', 0) if channel is None else channel) + 1
    st = (cfg.get('nvr_stream', 'sub') if stream is None else stream)
    u = urllib.parse.quote(str(cfg.get('nvr_user', '')), safe='')
    p = urllib.parse.quote(str(cfg.get('nvr_password', '')), safe='')
    return f"rtsp://{u}:{p}@{ip}:554/h264Preview_{ch:02d}_{st}"


def rtmp_url(cfg, mode):
    return f"{cfg['twitch_server'].rstrip('/')}/{cfg['twitch_key']}" + ('?bandwidthtest=true' if mode == 'test' else '')


def scrub(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, '<hidden>')
            text = text.replace(urllib.parse.quote(str(secret), safe=''), '<hidden>')
    text = re.sub(r'rtsp://[^@\s]+@', 'rtsp://<hidden>@', text)
    return re.sub(r'(token|password|user)=[^&\s]+', r'\1=<hidden>', re.sub(r'rtmps?://\S+', '<twitch>', text))


# ----- broadcast audio mixing, auto-ducking & playlist engine -----
class AutoDuckEnvelope:
    """Broadcast voice/stage auto-ducking sidechain + soft limiter.

    - High-passes stage mic (<90 Hz rumble/hum removal) before measuring voice RMS.
    - Fast sidechain attack (~60ms) when speech exceeds `voice_threshold_dbfs` (-35 dBFS).
    - Hold timer (`hold_seconds` = 1.8s) + smooth release (`release_tau` = 1.2s) prevents
      pumping between words or sentences.
    - Stage-presence awareness (`is_performer_onstage`):
      * In `"undertone"` mode (default): keeps the live Spotify / YurrMom.Com songs streaming
        underneath the comedian at an audible undertone (`onstage_volume` = 0.18, tucking to
        `onstage_speech_volume` = 0.11 while speaking) with a real-time Mid-channel vocal-pocket
        carve (~300-3400 Hz) so punchlines cut through crystal-clear over the groove.
      * In `"bed"` mode: crossfades onstage into an instrumental Stage Attention Bed.
      * In `"walkup"` mode: plays walk-up intro for `walkup_seconds` (8.0s) when someone
        steps onto the stage (ducking immediately if they speak), then fades completely to
        0.0 for a clean dry comedy set until they step off stage.
    """

    def __init__(
        self,
        idle_volume=0.34,
        ducked_volume=0.08,
        onstage_volume=0.18,
        onstage_speech_volume=None,
        walkup_volume=0.24,
        walkup_seconds=8.0,
        onstage_mode="undertone",
        mic_gain=1.85,
        voice_threshold_dbfs=-35.0,
        hold_seconds=1.8,
        attack_tau=0.06,
        onstage_fade_tau=0.45,
        release_tau=1.20,
        hp_window=320,
    ):
        self.idle_volume = float(idle_volume)
        self.ducked_volume = float(ducked_volume)
        self.onstage_volume = float(onstage_volume)
        if onstage_speech_volume is None:
            self.onstage_speech_volume = round(float(onstage_volume) * (0.11 / 0.18), 4)
        else:
            self.onstage_speech_volume = float(onstage_speech_volume)
        self.walkup_volume = float(walkup_volume)
        self.walkup_seconds = float(walkup_seconds)
        self.onstage_mode = str(onstage_mode)
        self.mic_gain = float(mic_gain)
        self.voice_threshold_dbfs = float(voice_threshold_dbfs)
        self.hold_seconds = float(hold_seconds)
        self.attack_tau = float(attack_tau)
        self.onstage_fade_tau = float(onstage_fade_tau)
        self.release_tau = float(release_tau)
        self.hp_window = max(8, int(hp_window))

        self.current_gain = 0.0
        self.voice_hold_until = -1e9
        self.onstage_since = None
        self._hp_tail = None
        self._vp_tail_lo = None
        self._vp_tail_hi = None
        self._vp_delay_mid = None
        self._vp_delay_side = None

    def highpass_rumble_cut(self, mono_f32):
        """Fast causal moving-average subtraction cutting <90 Hz rumble & DC offset."""
        if mono_f32.size == 0:
            return mono_f32
        w = self.hp_window
        if self._hp_tail is None or self._hp_tail.size != w - 1:
            self._hp_tail = np.zeros(w - 1, dtype=np.float32)
        padded = np.concatenate([self._hp_tail, mono_f32])
        self._hp_tail = padded[-(w - 1):].copy()
        csum = np.cumsum(np.insert(padded, 0, 0.0, axis=0), dtype=np.float64)
        lowpass = ((csum[w:] - csum[:-w]) / float(w)).astype(np.float32)
        return mono_f32 - lowpass

    @staticmethod
    def compute_rms_dbfs(samples_f32):
        if samples_f32.size == 0:
            return -100.0
        rms = float(np.sqrt(np.mean(np.square(samples_f32, dtype=np.float64))))
        return 20.0 * math.log10(max(rms, 1e-5))

    def step(self, mic_rms_dbfs, is_performer_onstage, music_enabled, now_mono, dt=0.05):
        dt = max(0.001, float(dt))
        if mic_rms_dbfs >= self.voice_threshold_dbfs:
            self.voice_hold_until = float(now_mono) + self.hold_seconds
        voice_active = float(now_mono) < self.voice_hold_until

        if is_performer_onstage:
            if self.onstage_since is None:
                self.onstage_since = float(now_mono)
            onstage_dur = float(now_mono) - self.onstage_since
        else:
            self.onstage_since = None
            onstage_dur = 0.0

        if not music_enabled:
            target = 0.0
        elif voice_active:
            if is_performer_onstage and self.onstage_mode == "walkup" and onstage_dur > self.walkup_seconds:
                target = 0.02
            elif is_performer_onstage and self.onstage_mode in ("undertone", "bed"):
                # Undertone / vocal-carved bed stays warmly audible while never exceeding onstage_volume
                target = min(self.onstage_volume, self.onstage_speech_volume)
            else:
                target = self.ducked_volume
        elif is_performer_onstage:
            if self.onstage_mode == "walkup":
                target = self.walkup_volume if onstage_dur <= self.walkup_seconds else 0.0
            else:
                target = self.onstage_volume
        else:
            target = self.idle_volume

        if target < self.current_gain:
            tau = self.attack_tau if voice_active else self.onstage_fade_tau
        else:
            tau = self.release_tau

        alpha = 1.0 - math.exp(-dt / max(0.005, tau))
        self.current_gain += alpha * (target - self.current_gain)
        if self.current_gain < 0.0005 and target == 0.0:
            self.current_gain = 0.0
        return self.current_gain, voice_active

    def apply_undertone_vocal_pocket(self, stereo_f32, carve_strength=0.60):
        """Linear-phase Mid-channel vocal-pocket carve (~300 Hz - 3.2 kHz) keeping bass, air & stereo Sides lush."""
        if stereo_f32.size == 0:
            return stereo_f32
        mid = 0.5 * (stereo_f32[:, 0] + stereo_f32[:, 1])
        side = 0.5 * (stereo_f32[:, 0] - stereo_f32[:, 1])
        w_hi = 15    # odd length -> exact 7-sample group delay (~3.2 kHz low-pass @ 48 kHz)
        d_hi = (w_hi - 1) // 2
        w_lo = 161   # ~300 Hz low-pass @ 48 kHz
        if self._vp_tail_hi is None or self._vp_tail_hi.size != w_hi - 1:
            self._vp_tail_hi = np.zeros(w_hi - 1, dtype=np.float32)
        if self._vp_tail_lo is None or self._vp_tail_lo.size != w_lo - 1:
            self._vp_tail_lo = np.zeros(w_lo - 1, dtype=np.float32)
        if self._vp_delay_mid is None or self._vp_delay_mid.size != d_hi:
            self._vp_delay_mid = np.zeros(d_hi, dtype=np.float32)
            self._vp_delay_side = np.zeros(d_hi, dtype=np.float32)

        p_hi = np.concatenate([self._vp_tail_hi, mid])
        self._vp_tail_hi = p_hi[-(w_hi - 1):].copy()
        c_hi = np.cumsum(np.insert(p_hi, 0, 0.0, axis=0), dtype=np.float64)
        lp_hi = ((c_hi[w_hi:] - c_hi[:-w_hi]) / float(w_hi)).astype(np.float32)

        p_lo = np.concatenate([self._vp_tail_lo, mid])
        self._vp_tail_lo = p_lo[-(w_lo - 1):].copy()
        c_lo = np.cumsum(np.insert(p_lo, 0, 0.0, axis=0), dtype=np.float64)
        lp_lo = ((c_lo[w_lo:] - c_lo[:-w_lo]) / float(w_lo)).astype(np.float32)

        # Delay dry Mid and Side by exact 7 samples (0.146 ms) so lp_hi subtraction is zero-phase (no comb filter!)
        mid_all = np.concatenate([self._vp_delay_mid, mid])
        side_all = np.concatenate([self._vp_delay_side, side])
        self._vp_delay_mid = mid_all[-d_hi:].copy()
        self._vp_delay_side = side_all[-d_hi:].copy()
        mid_aligned = mid_all[:-d_hi]
        side_aligned = side_all[:-d_hi]

        vocal_band = lp_hi - lp_lo
        carved_mid = mid_aligned - float(carve_strength) * vocal_band
        return np.column_stack([carved_mid + side_aligned, carved_mid - side_aligned]).astype(np.float32)

    def mix_and_limit(self, mic_stereo_f32, music_stereo_f32, music_gain):
        """Combine gained stage mic + ducked stereo music with soft-knee tanh broadcast limiting."""
        mixed = mic_stereo_f32 * self.mic_gain + music_stereo_f32 * float(music_gain)
        # Transparent linear pass below 0.70, smooth soft-knee saturation ceiling at 0.96
        abs_m = np.abs(mixed)
        over = abs_m > 0.70
        if np.any(over):
            sign = np.sign(mixed[over])
            excess = (abs_m[over] - 0.70) / 0.26
            mixed = mixed.copy()
            mixed[over] = sign * (0.70 + 0.26 * np.tanh(excess))
        return np.clip(mixed * 32767.0, -32767.0, 32767.0).astype(np.int16)


def resolve_effective_dj_mode(cur_view: str, dj_mode: str, stage_dj_mode: str = "beds") -> str:
    """Resolve active DJ source by view window.

    - Off-hours (`privacy`, 2 AM - 9 PM): runs `dj_mode` (`spotify` / `rotate` / `house`) so Spotify & YurrMom.Com tracks play.
    - Showtime (`stage`, 9 PM - 2 AM): defaults to `stage_dj_mode` (`beds`), pausing Spotify & vocal songs and airing the vocal-carved Stage Groove bed.
    """
    djm = str(dj_mode or "spotify").lower()
    st_djm = str(stage_dj_mode or "beds").lower()
    if cur_view == "stage":
        return st_djm if st_djm in ("beds", "rotate", "suno", "spotify", "house") else "beds"
    if cur_view == "privacy" and djm == "rotate":
        return "spotify"
    return djm


class BroadcastAudioMixer:
    """Real-time 48kHz stereo PCM broadcast mixer feeding FFmpeg via local OS pipe.

    Decouples FFmpeg completely from NVR network sockets so NVR audio hiccups or
    playlist track transitions never stall or drop the Twitch RTMP stream.
    """

    SAMPLE_RATE = 48000
    CHANNELS = 2
    CHUNK_SEC = 0.05  # 20 chunks/sec = 2400 stereo samples = 9600 bytes per tick
    CHUNK_FRAMES = int(SAMPLE_RATE * CHUNK_SEC)
    CHUNK_BYTES = CHUNK_FRAMES * CHANNELS * 2

    def __init__(
        self,
        cfg,
        ip=None,
        cam0_url_getter=None,
        view_getter=None,
        policy_getter=None,
        onstage_getter=None,
        caption_engine=None,
        secrets=None,
        ticker_path="/home/joseph1/box2-stream/ticker.json",
    ):
        self.cfg = cfg or {}
        self.ip = ip
        self.cam0_url_getter = cam0_url_getter
        self.view_getter = view_getter or (lambda: "stage")
        self.policy_getter = policy_getter or (lambda: "auto")
        self.onstage_getter = onstage_getter or (lambda: False)
        self.caption_engine = caption_engine
        self.secrets = secrets or []
        self.ticker_path = ticker_path

        # P1 Audio Source Authority: pin strictly to Box 2 Stage (auto-prefer USB stage receiver; fail-closed on CH 0)
        self.audio_policy = AudioAuthorityPolicy(
            room_id="box2_stage",
            preferred_usb_alsa_match=self.cfg.get("usb_stage_mic_match", "StageMic"),
            authorized_nvr_mac=str(self.cfg.get("nvr_mac", "ec:71:db:bb:69:56")),
            authorized_nvr_channel=int(self.cfg.get("nvr_channel", 0)),
            expected_osd_name=str(self.cfg.get("expected_stage_osd", "Camera1")),
            mic_stall_timeout_s=float(self.cfg.get("mic_stall_timeout_s", 3.0)),
        )
        self._verified_nvr_mac = mac_of(self.ip) if self.ip else self.audio_policy.authorized_nvr_mac
        self._verified_osd_name = str(self.cfg.get("verified_stage_osd", self.audio_policy.expected_osd_name))
        self._active_mic_kind = "nvr_channel"
        self._active_mic_id = f"nvr://{self.ip or 'local'}/ch{self.audio_policy.authorized_nvr_channel}"
        self._last_mic_chunk_mono = time.monotonic()
        self._raw_pre_mix_dbfs = -90.0
        self.mic_verdict = verify_audio_provenance(
            self.audio_policy,
            source_kind="nvr_channel",
            source_id=self._active_mic_id,
            nvr_mac=self._verified_nvr_mac,
            nvr_channel=self.audio_policy.authorized_nvr_channel,
            osd_name=self._verified_osd_name,
            last_audio_age_s=0.0,
        )

        self.music_dir = Path(self.cfg.get("music_dir", str(DEFAULT_MUSIC_DIR)))
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.stage_beds_dir = Path(self.cfg.get("stage_beds_dir", str(DEFAULT_STAGE_BEDS_DIR)))
        self.stage_beds_dir.mkdir(parents=True, exist_ok=True)
        self.ads_dir = Path(self.cfg.get("ads_dir", str(DEFAULT_ADS_DIR)))
        self.ads_dir.mkdir(parents=True, exist_ok=True)

        self.envelope = AutoDuckEnvelope(
            idle_volume=float(self.cfg.get("music_idle_volume", 0.34)),
            ducked_volume=float(self.cfg.get("music_ducked_volume", 0.08)),
            onstage_volume=float(self.cfg.get("music_onstage_volume", 0.18)),
            onstage_speech_volume=float(self.cfg.get("music_onstage_speech_volume", 0.11)),
            walkup_volume=float(self.cfg.get("music_walkup_volume", 0.24)),
            walkup_seconds=float(self.cfg.get("music_walkup_seconds", 8.0)),
            onstage_mode=str(self.cfg.get("music_onstage_mode", "undertone")),
            mic_gain=float(self.cfg.get("mic_gain", 1.85)),
            voice_threshold_dbfs=float(self.cfg.get("voice_threshold_dbfs", -35.0)),
        )

        self.read_fd, self.write_fd = os.pipe()
        self._stop_event = threading.Event()
        self._mic_queue = collections.deque(maxlen=5)   # max 250ms buffer for tight lip-sync
        self._music_queue = collections.deque(maxlen=16)
        self._stage_bed_queue = collections.deque(maxlen=16)
        self._dj_bus_queue = collections.deque(maxlen=6)
        self._ads_queue = collections.deque(maxlen=16)
        self._mic_lock = threading.Lock()
        self._music_lock = threading.Lock()
        self._stage_bed_lock = threading.Lock()
        self._dj_bus_lock = threading.Lock()
        self._ads_lock = threading.Lock()
        self._mic_proc = None
        self._music_proc = None
        self._stage_bed_proc = None
        self._dj_bus_proc = None
        self._ads_proc = None

        self._music_mode = "auto"  # "auto" (on during standby & showtime), "on", "off"
        self._dj_mode = str(self.cfg.get("dj_mode", "spotify"))  # "spotify", "rotate", "suno", "house", "beds"
        self._stage_dj_mode = str(self.cfg.get("stage_dj_mode", "beds"))  # 9PM-2AM showtime default: pause Spotify & play Stage Groove bed
        self._effective_dj_mode = resolve_effective_dj_mode(self.view_getter(), self._dj_mode, self._stage_dj_mode)
        self._suno_block_tracks = int(self.cfg.get("suno_tracks_per_block", 3))
        self._spotify_block_tracks = int(self.cfg.get("spotify_tracks_per_block", 3))
        self._test_ad_until_epoch = 0.0
        self._ad_interval_minutes = float(self.cfg.get("ad_interval_minutes", 30.0))
        self._next_scheduled_ad_mono = (
            time.monotonic() + self._ad_interval_minutes * 60.0
            if self._ad_interval_minutes > 0.0
            else 0.0
        )
        self._scheduled_ad_active = False
        self._ad_now_seq = 0
        self._mute_mic_in_privacy = bool(self.cfg.get("mute_mic_in_privacy", True))
        self._gate_mic_offstage = bool(self.cfg.get("gate_mic_offstage", True))
        self._offstage_mic_scale = float(self.cfg.get("offstage_mic_scale", 0.0))
        self._mic_stage_gate = 0.0
        self._skip_seq = 0
        self._ad_skip_seq = 0
        self._last_cfg_poll = 0.0
        self._last_mpris_poll = 0.0
        self._current_track = ""
        self._current_stage_bed = ""
        self._current_ad_track = ""
        self._bed_mix_ratio = 0.0  # 0.0 = YurrMom/DJ radio, 1.0 = Vocal-carved Stage Attention Bed
        self._music_desired_now = False
        self._ad_swap_desired_now = False
        self._dj_bus_last_audible_mono = -1e9
        self._radio_decision = box2_radio.TrackDecision(action="idle", reason="init")
        self._radio_ctrl = box2_radio.MprisRadioController(
            allowed_spotify_artists=self.cfg.get("allowed_spotify_artists", box2_radio.DEFAULT_ALLOWED_SPOTIFY_ARTISTS)
        )
        box2_radio.ensure_pipewire_dj_bus()

        self.stats = {
            "audio_mixer": "active",
            "mic_dbfs": -60.0,
            "voice_ducking": False,
            "music_mode": "auto",
            "dj_mode": self._dj_mode,
            "audio_source": "house_ssd",
            "ad_shield_active": False,
            "music_playing": False,
            "music_track": "",
            "now_playing_banner": "",
            "music_gain": 0.0,
            "music_onstage_mode": self.envelope.onstage_mode,
        }

        self._poll_live_controls(force=True)
        self._mic_thread = threading.Thread(target=self._mic_reader_worker, daemon=True)
        self._dj_bus_thread = threading.Thread(target=self._dj_bus_reader_worker, daemon=True)
        self._ads_thread = threading.Thread(target=self._ads_reader_worker, daemon=True)
        self._stage_bed_thread = threading.Thread(target=self._stage_bed_reader_worker, daemon=True)
        self._music_thread = threading.Thread(target=self._music_reader_worker, daemon=True)
        self._mix_thread = threading.Thread(target=self._mixer_loop, daemon=True)
        self._mic_thread.start()
        self._dj_bus_thread.start()
        self._ads_thread.start()
        self._stage_bed_thread.start()
        self._music_thread.start()
        self._mix_thread.start()

    def _poll_live_controls(self, force=False):
        now_mono = time.monotonic()
        if not force and (now_mono - self._last_cfg_poll < 1.0):
            return
        self._last_cfg_poll = now_mono

        # 1. Optional ticker.json audio_mixer overrides
        if self.ticker_path and os.path.exists(self.ticker_path):
            try:
                tk = json.loads(Path(self.ticker_path).read_text())
                am = tk.get("audio_mixer", {})
                if isinstance(am, dict) and am:
                    if "idle_volume" in am:
                        self.envelope.idle_volume = float(am["idle_volume"])
                    if "ducked_volume" in am:
                        self.envelope.ducked_volume = float(am["ducked_volume"])
                    if "onstage_volume" in am:
                        self.envelope.onstage_volume = float(am["onstage_volume"])
                    if "onstage_speech_volume" in am:
                        self.envelope.onstage_speech_volume = float(am["onstage_speech_volume"])
                    if "onstage_mode" in am and am["onstage_mode"] in ("undertone", "bed", "walkup"):
                        self.envelope.onstage_mode = str(am["onstage_mode"])
                    if "mic_gain" in am:
                        self.envelope.mic_gain = float(am["mic_gain"])
                    if "voice_threshold_dbfs" in am:
                        self.envelope.voice_threshold_dbfs = float(am["voice_threshold_dbfs"])
                    if "mute_mic_in_privacy" in am:
                        self._mute_mic_in_privacy = bool(am["mute_mic_in_privacy"])
                    if "gate_mic_offstage" in am:
                        self._gate_mic_offstage = bool(am["gate_mic_offstage"])
                    if "offstage_mic_scale" in am:
                        self._offstage_mic_scale = max(0.0, min(1.0, float(am["offstage_mic_scale"])))
                    if "stage_dj_mode" in am and str(am["stage_dj_mode"]).lower() in ("beds", "rotate", "suno", "spotify", "house"):
                        self._stage_dj_mode = str(am["stage_dj_mode"]).lower()
            except Exception:
                pass

        # 2. Live CLI state.json music controls
        st = read_state()
        m_cfg = st.get("music", {})
        if isinstance(m_cfg, dict):
            mode = m_cfg.get("mode", "auto")
            if mode in ("auto", "on", "off"):
                self._music_mode = mode
            if "idle_volume" in m_cfg:
                self.envelope.idle_volume = max(0.0, min(1.0, float(m_cfg["idle_volume"])))
            if "onstage_volume" in m_cfg:
                self.envelope.onstage_volume = max(0.0, min(1.0, float(m_cfg["onstage_volume"])))
            if "onstage_speech_volume" in m_cfg:
                self.envelope.onstage_speech_volume = max(0.0, min(1.0, float(m_cfg["onstage_speech_volume"])))
            if "onstage_mode" in m_cfg and m_cfg["onstage_mode"] in ("undertone", "bed", "walkup"):
                self.envelope.onstage_mode = m_cfg["onstage_mode"]
            new_skip = int(m_cfg.get("skip_seq", 0))
            if new_skip != self._skip_seq:
                self._skip_seq = new_skip
                self._terminate_proc(self._music_proc)

        dj_cfg = st.get("dj", {})
        if isinstance(dj_cfg, dict):
            djm = str(dj_cfg.get("mode", self._dj_mode)).lower()
            if djm in ("rotate", "suno", "spotify", "house", "beds"):
                self._dj_mode = djm
            if "stage_mode" in dj_cfg and str(dj_cfg["stage_mode"]).lower() in ("beds", "rotate", "suno", "spotify", "house"):
                self._stage_dj_mode = str(dj_cfg["stage_mode"]).lower()
            if "suno_tracks" in dj_cfg:
                self._suno_block_tracks = max(1, int(dj_cfg["suno_tracks"]))
            if "spotify_tracks" in dj_cfg:
                self._spotify_block_tracks = max(1, int(dj_cfg["spotify_tracks"]))
            self._test_ad_until_epoch = float(dj_cfg.get("test_ad_until_epoch", 0.0) or 0.0)
            if "ad_interval_minutes" in dj_cfg:
                new_iv = max(0.0, float(dj_cfg.get("ad_interval_minutes", 0.0) or 0.0))
                if abs(new_iv - self._ad_interval_minutes) > 1e-3:
                    self._ad_interval_minutes = new_iv
                    self._next_scheduled_ad_mono = (now_mono + new_iv * 60.0) if new_iv > 0.0 else 0.0
            new_ad_now = int(dj_cfg.get("ad_now_seq", 0))
            if new_ad_now != self._ad_now_seq:
                if self._ad_now_seq != 0 or new_ad_now > 0:
                    # Only trigger immediately when ad_now_seq advances after startup, or if explicitly requested now
                    if self._last_mpris_poll > 0.0:
                        self._scheduled_ad_active = True
                self._ad_now_seq = new_ad_now
            new_ad_skip = int(dj_cfg.get("ad_skip_seq", 0))
            if new_ad_skip != self._ad_skip_seq:
                self._ad_skip_seq = new_ad_skip
                self._terminate_proc(self._ads_proc)

        cur_view = self.view_getter()
        cur_pol = self.policy_getter()
        self._effective_dj_mode = resolve_effective_dj_mode(cur_view, self._dj_mode, self._stage_dj_mode)
        if self._music_mode == "on":
            self._music_desired_now = True
        elif self._music_mode == "off":
            self._music_desired_now = False
        else:
            # "auto": play Spotify/YurrMom.Com in privacy standby (2 AM - 9 PM) and Stage Groove bed during 9 PM - 2 AM showtime.
            self._music_desired_now = (cur_pol != "rehearse")

        if force or (now_mono - self._last_mpris_poll >= 1.0):
            self._last_mpris_poll = now_mono
            try:
                dec, _ = self._radio_ctrl.poll_and_step(
                    music_desired_now=self._music_desired_now,
                    dj_mode=self._effective_dj_mode,
                    suno_tracks=self._suno_block_tracks,
                    spotify_tracks=self._spotify_block_tracks,
                )
                self._radio_decision = dec
            except Exception:
                self._radio_decision = box2_radio.TrackDecision(action="idle", reason="mpris_err")

        cur_view = self.view_getter()
        is_onstage_now = bool(self.onstage_getter()) if cur_view == "stage" else False
        if (
            cur_view == "privacy"
            and self._ad_interval_minutes > 0.0
            and self._music_desired_now
            and not self._scheduled_ad_active
            and self._next_scheduled_ad_mono > 0.0
            and now_mono >= self._next_scheduled_ad_mono
        ):
            # Comedian-first guard: never interrupt a live performer on stage; wait until between sets / standby
            if not is_onstage_now:
                if self._list_tracks(self.ads_dir):
                    self._scheduled_ad_active = True
                else:
                    self._next_scheduled_ad_mono = now_mono + self._ad_interval_minutes * 60.0

        test_ad_now = time.time() < self._test_ad_until_epoch
        self._ad_swap_desired_now = bool(
            self._music_desired_now
            and (
                test_ad_now
                or self._scheduled_ad_active
                or self._radio_decision.action in ("ad_break_swap", "dmca_shield_swap")
            )
        )

    @staticmethod
    def _terminate_proc(proc):
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _mic_reader_worker(self):
        """P1 Authoritative Stage Microphone Reader.

        1. Auto-prefers a dedicated USB/XLR wireless stage receiver plugged into the Jetson (`usb_stage_mic`).
        2. Otherwise binds strictly to verified NVR `CH 0` (`Box 2 Stage`, never `CH 1-7` other rooms).
        3. Fails closed if provenance fails or audio disconnects (`STAGE_MIC_INTERRUPTED`).
        """
        use_rtsp = bool(self.ip and self.cfg.get("nvr_user") and self.cfg.get("nvr_password"))
        auth_ch = int(self.audio_policy.authorized_nvr_channel)
        fail_streak = 0
        while not self._stop_event.is_set():
            src = None
            input_args = []

            # 1. Check for dedicated USB stage microphone receiver on Jetson ALSA bus
            alsa_cards = ""
            if os.path.exists("/proc/asound/cards"):
                try:
                    alsa_cards = Path("/proc/asound/cards").read_text()
                except OSError:
                    alsa_cards = ""
            usb_match = discover_authorized_usb_mic(alsa_cards, self.audio_policy.preferred_usb_alsa_match)
            if usb_match is not None:
                card_idx, card_desc = usb_match
                self._active_mic_kind = "usb_stage_mic"
                self._active_mic_id = f"alsa:hw:{card_idx},0 ({card_desc})"
                src = f"hw:{card_idx},0"
                input_args = ["-f", "alsa", "-i", src]
            else:
                # 2. Strict NVR CH 0 stage provenance check (never substitute CH 1-7)
                self._active_mic_kind = "nvr_channel"
                self._active_mic_id = f"nvr://{self.ip or 'local'}/ch{auth_ch}"
                if self.ip:
                    live_mac = mac_of(self.ip)
                    if live_mac:
                        self._verified_nvr_mac = live_mac
                pre_check = verify_audio_provenance(
                    self.audio_policy,
                    source_kind="nvr_channel",
                    source_id=self._active_mic_id,
                    nvr_mac=self._verified_nvr_mac,
                    nvr_channel=auth_ch,
                    osd_name=self._verified_osd_name,
                    last_audio_age_s=0.0,
                )
                if not pre_check.authorized:
                    self.mic_verdict = pre_check
                    log(f"Stage Director P1 FAIL-CLOSED: rejected audio source ({pre_check.reason})")
                    time.sleep(2.0)
                    continue
                if use_rtsp and fail_streak < 3:
                    src = rtsp_url_ch(self.ip, self.cfg, channel=auth_ch, stream="sub")
                    input_args = ["-rtsp_transport", "tcp", "-timeout", "8000000", "-i", src]
                elif self.cam0_url_getter and auth_ch == 0:
                    src = self.cam0_url_getter()
                    if src:
                        input_args = ["-rw_timeout", "10000000", "-i", src]

            if not src or not input_args:
                time.sleep(1.5)
                continue

            cmd = [
                FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error",
                *input_args,
                "-vn", "-ac", "2", "-ar", str(self.SAMPLE_RATE), "-f", "s16le", "pipe:1",
            ]
            proc = None
            got_audio = False
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                self._mic_proc = proc
                while not self._stop_event.is_set():
                    buf = proc.stdout.read(self.CHUNK_BYTES)
                    if not buf or len(buf) < self.CHUNK_BYTES:
                        break
                    got_audio = True
                    fail_streak = 0
                    self._last_mic_chunk_mono = time.monotonic()
                    with self._mic_lock:
                        self._mic_queue.append(buf)
            except Exception as exc:
                log(f"Audio mixer mic reader warning: {scrub(str(exc), self.secrets)}")
            finally:
                self._terminate_proc(proc)
                self._mic_proc = None

            if not got_audio:
                fail_streak += 1
            if not self._stop_event.is_set():
                time.sleep(1.0)

    def _list_tracks(self, folder=None):
        target_dir = Path(folder) if folder is not None else self.music_dir
        if not target_dir.exists():
            return []
        tracks = [
            p for p in sorted(target_dir.iterdir())
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not p.name.startswith(".")
        ]
        return tracks

    def _dj_bus_reader_worker(self):
        """Capture stereo 48kHz PCM from PipeWire virtual sink `box2_dj_bus.monitor`."""
        while not self._stop_event.is_set():
            if not self._music_desired_now or self._effective_dj_mode in ("house", "beds"):
                with self._dj_bus_lock:
                    self._dj_bus_queue.clear()
                time.sleep(0.4)
                continue

            box2_radio.ensure_pipewire_dj_bus()
            env = box2_radio.discover_desktop_env()
            cmd = [
                FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "pulse", "-i", box2_radio.DJ_BUS_MONITOR,
                "-ac", "2", "-ar", str(self.SAMPLE_RATE), "-f", "s16le", "pipe:1",
            ]
            proc = None
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
                self._dj_bus_proc = proc
                while not self._stop_event.is_set() and self._music_desired_now and self._effective_dj_mode not in ("house", "beds"):
                    buf = proc.stdout.read(self.CHUNK_BYTES)
                    if not buf or len(buf) < self.CHUNK_BYTES:
                        break
                    if np is not None:
                        s_f32 = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
                        if self.envelope.compute_rms_dbfs(s_f32) > -62.0:
                            self._dj_bus_last_audible_mono = time.monotonic()
                    with self._dj_bus_lock:
                        self._dj_bus_queue.append(buf)
            except Exception:
                pass
            finally:
                self._terminate_proc(proc)
                self._dj_bus_proc = None
            if not self._stop_event.is_set():
                time.sleep(1.5)

    def _ads_reader_worker(self):
        """On-demand decoder for custom sponsor & house promos in `/mnt/ssd/media/box2-ads/`."""
        ad_idx = 0
        while not self._stop_event.is_set():
            if not self._ad_swap_desired_now:
                self._current_ad_track = ""
                with self._ads_lock:
                    self._ads_queue.clear()
                time.sleep(0.15)
                continue

            ads = self._list_tracks(self.ads_dir)
            if not ads:
                self._current_ad_track = ""
                time.sleep(0.5)
                continue

            ad_path = ads[ad_idx % len(ads)]
            ad_idx = (ad_idx + 1) % max(1, len(ads))
            self._current_ad_track = ad_path.stem
            local_skip = self._ad_skip_seq
            was_scheduled_spot = bool(self._scheduled_ad_active)
            finished_cleanly = False

            cmd = [
                FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(ad_path),
                "-vn",
                "-af", "dynaudnorm=f=200:g=11:p=0.88",
                "-ac", "2", "-ar", str(self.SAMPLE_RATE), "-f", "s16le", "pipe:1",
            ]
            proc = None
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                self._ads_proc = proc
                while not self._stop_event.is_set() and self._ad_swap_desired_now and local_skip == self._ad_skip_seq:
                    with self._ads_lock:
                        q_len = len(self._ads_queue)
                    if q_len >= 12:
                        time.sleep(0.03)
                        continue
                    buf = proc.stdout.read(self.CHUNK_BYTES)
                    if not buf:
                        finished_cleanly = True
                        break
                    if len(buf) < self.CHUNK_BYTES:
                        buf = buf + b"\x00" * (self.CHUNK_BYTES - len(buf))
                    with self._ads_lock:
                        self._ads_queue.append(buf)
                if was_scheduled_spot and (finished_cleanly or local_skip != self._ad_skip_seq):
                    # Wait for buffered chunks of this single scheduled spot to finish playing out before returning to music
                    while not self._stop_event.is_set() and local_skip == self._ad_skip_seq:
                        with self._ads_lock:
                            if not self._ads_queue:
                                break
                        time.sleep(0.04)
                    self._scheduled_ad_active = False
                    if self._ad_interval_minutes > 0.0:
                        self._next_scheduled_ad_mono = time.monotonic() + self._ad_interval_minutes * 60.0
            except Exception as exc:
                log(f"Audio mixer ads reader warning: {exc}")
            finally:
                self._terminate_proc(proc)
                self._ads_proc = None

    def _stage_bed_reader_worker(self):
        """Ready-buffered decoder for psychoacoustic vocal-carved Stage Attention Beds (`/mnt/ssd/media/box2-stage-beds/`).

        Stays idle (0% CPU) during daytime privacy standby unless `dj_mode == 'beds'`;
        pre-buffers 600ms whenever `view == 'stage'` so crossfade on performer arrival is instantaneous.
        """
        bed_deck = []
        rng = random.Random()
        last_bed = None
        while not self._stop_event.is_set():
            want_bed_ready = self._music_desired_now and (self.view_getter() == "stage" or self._dj_mode == "beds" or self._bed_mix_ratio > 0.01)
            if not want_bed_ready:
                self._current_stage_bed = ""
                with self._stage_bed_lock:
                    self._stage_bed_queue.clear()
                time.sleep(0.3)
                continue

            beds = self._list_tracks(self.stage_beds_dir)
            if not beds:
                self._current_stage_bed = ""
                time.sleep(2.0)
                continue

            valid_set = set(beds)
            bed_deck = [p for p in bed_deck if p in valid_set]
            if not bed_deck:
                bed_deck = list(beds)
                rng.shuffle(bed_deck)
                if len(bed_deck) > 1 and bed_deck[0] == last_bed:
                    bed_deck.append(bed_deck.pop(0))
            bed_path = bed_deck.pop(0)
            last_bed = bed_path
            self._current_stage_bed = bed_path.stem
            local_skip = self._skip_seq

            cmd = [
                FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(bed_path),
                "-vn",
                "-ac", "2", "-ar", str(self.SAMPLE_RATE), "-f", "s16le", "pipe:1",
            ]
            proc = None
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                self._stage_bed_proc = proc
                while not self._stop_event.is_set() and local_skip == self._skip_seq:
                    if not (self._music_desired_now and (self.view_getter() == "stage" or self._dj_mode == "beds" or self._bed_mix_ratio > 0.01)):
                        break
                    with self._stage_bed_lock:
                        q_len = len(self._stage_bed_queue)
                    if q_len >= 12:
                        time.sleep(0.03)
                        continue
                    buf = proc.stdout.read(self.CHUNK_BYTES)
                    if not buf:
                        break
                    if len(buf) < self.CHUNK_BYTES:
                        buf = buf + b"\x00" * (self.CHUNK_BYTES - len(buf))
                    with self._stage_bed_lock:
                        self._stage_bed_queue.append(buf)
            except Exception as exc:
                log(f"Audio mixer stage bed reader warning: {exc}")
            finally:
                self._terminate_proc(proc)
                self._stage_bed_proc = None

    def _music_reader_worker(self):
        deck = []
        played_since_promo = 0
        promo_every_n = int(self.cfg.get("house_promo_every_tracks", 12))
        rng = random.Random()
        last_path = None

        while not self._stop_event.is_set():
            bed_only_idle = (self._effective_dj_mode == "beds" and self._bed_mix_ratio >= 0.99 and not self._ad_swap_desired_now)
            if (not self._music_desired_now and self.envelope.current_gain <= 0.001) or bed_only_idle:
                self._current_track = ""
                with self._music_lock:
                    self._music_queue.clear()
                time.sleep(0.25)
                continue

            tracks = self._list_tracks()
            if not tracks:
                self._current_track = ""
                time.sleep(2.0)
                continue

            # Periodically weave in a sponsor/house promo from /mnt/ssd/media/box2-ads/ every N previews
            ads = self._list_tracks(self.ads_dir) if promo_every_n > 0 else []
            if ads and played_since_promo >= promo_every_n:
                played_since_promo = 0
                track_path = rng.choice(ads)
                is_promo_spot = True
            else:
                # Shuffled non-repeating deck across the entire YurrMom.Com preview catalog
                valid_set = set(tracks)
                deck = [p for p in deck if p in valid_set]
                if not deck:
                    deck = list(tracks)
                    rng.shuffle(deck)
                    if len(deck) > 1 and deck[0] == last_path:
                        deck.append(deck.pop(0))
                track_path = deck.pop(0)
                last_path = track_path
                played_since_promo += 1
                is_promo_spot = False

            self._current_track = "SPONSOR: YurrMom.Com" if is_promo_spot else track_path.stem
            local_skip = self._skip_seq

            cmd = [
                FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(track_path),
                "-vn",
                "-af", "dynaudnorm=f=250:g=15:p=0.85",
                "-ac", "2", "-ar", str(self.SAMPLE_RATE), "-f", "s16le", "pipe:1",
            ]
            proc = None
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                self._music_proc = proc
                while not self._stop_event.is_set() and local_skip == self._skip_seq:
                    if (not self._music_desired_now and self.envelope.current_gain <= 0.001) or (
                        self._effective_dj_mode == "beds" and self._bed_mix_ratio >= 0.99 and not self._ad_swap_desired_now
                    ):
                        break
                    with self._music_lock:
                        q_len = len(self._music_queue)
                    if q_len >= 12:
                        time.sleep(0.03)
                        continue
                    buf = proc.stdout.read(self.CHUNK_BYTES)
                    if not buf:
                        break
                    if len(buf) < self.CHUNK_BYTES:
                        buf = buf + b"\x00" * (self.CHUNK_BYTES - len(buf))
                    with self._music_lock:
                        self._music_queue.append(buf)
            except Exception as exc:
                log(f"Audio mixer track reader warning: {exc}")
            finally:
                self._terminate_proc(proc)
                self._music_proc = None

    def _mixer_loop(self):
        zero_stereo = np.zeros((self.CHUNK_FRAMES, 2), dtype=np.float32)
        zero_bytes = b"\x00" * self.CHUNK_BYTES
        next_tick = time.monotonic()

        try:
            while not self._stop_event.is_set():
                now_mono = time.monotonic()
                if now_mono < next_tick:
                    time.sleep(min(0.02, next_tick - now_mono))
                    continue
                next_tick += self.CHUNK_SEC
                if now_mono - next_tick > 0.25:
                    next_tick = now_mono + self.CHUNK_SEC

                self._poll_live_controls()

                with self._mic_lock:
                    mic_raw = self._mic_queue.popleft() if self._mic_queue else None

                # P1 Fail-Closed Audio Provenance Check on every mixer tick
                mic_age_s = max(0.0, now_mono - self._last_mic_chunk_mono)
                self.mic_verdict = verify_audio_provenance(
                    self.audio_policy,
                    source_kind=self._active_mic_kind,
                    source_id=self._active_mic_id,
                    nvr_mac=self._verified_nvr_mac,
                    nvr_channel=self.audio_policy.authorized_nvr_channel,
                    osd_name=self._verified_osd_name,
                    last_audio_age_s=mic_age_s,
                )
                if not self.mic_verdict.authorized:
                    # Fail-closed: never feed unverified or stalled audio to broadcast or ASR!
                    mic_raw = None

                cur_view = self.view_getter()
                is_onstage = bool(self.onstage_getter()) if cur_view == "stage" else False

                # Smooth camera-mic stage gate:
                # - 2 AM - 9 PM (`privacy`): 100% muted when `mute_mic_in_privacy` is True (0.12x otherwise).
                # - 9 PM - 2 AM (`stage`): gated down to `offstage_mic_scale` (default 0.0) whenever nobody is on stage
                #   so ambient desk typing, speakers, or across-the-room voices never bleed onto Twitch; ramps smoothly
                #   in 80 ms to 1.0 the instant a performer steps onto the stage.
                if not self.mic_verdict.authorized:
                    target_mic_gate = 0.0
                elif cur_view == "privacy":
                    target_mic_gate = 0.0 if self._mute_mic_in_privacy else 0.12
                elif is_onstage or not self._gate_mic_offstage:
                    target_mic_gate = 1.0
                else:
                    target_mic_gate = self._offstage_mic_scale

                if target_mic_gate > self._mic_stage_gate:
                    gate_alpha = 1.0 - math.exp(-self.CHUNK_SEC / 0.08)
                else:
                    gate_alpha = 1.0 - math.exp(-self.CHUNK_SEC / 0.65)
                self._mic_stage_gate += gate_alpha * (target_mic_gate - self._mic_stage_gate)
                if self._mic_stage_gate < 0.0005 and target_mic_gate == 0.0:
                    self._mic_stage_gate = 0.0

                if mic_raw is not None and np is not None:
                    mic_i16 = np.frombuffer(mic_raw, dtype=np.int16).reshape(-1, 2)
                    mic_f32 = mic_i16.astype(np.float32) / 32768.0
                    mono = 0.5 * (mic_f32[:, 0] + mic_f32[:, 1])
                    mono_hp = self.envelope.highpass_rumble_cut(mono)
                    self._raw_pre_mix_dbfs = self.envelope.compute_rms_dbfs(mono_hp)
                    if self._mic_stage_gate > 0.0005:
                        # Broadcast stereo vocal cleanup: apply rumble cut to both channels
                        rumble = (mono - mono_hp)[:, None]
                        mic_clean = (mic_f32 - rumble) * self._mic_stage_gate
                        mic_dbfs = self.envelope.compute_rms_dbfs(mono_hp * self._mic_stage_gate)
                        # Strictly pre-mix, provenance-verified speech routed to ASR before any music track!
                        if self.caption_engine is not None and is_onstage and self.mic_verdict.authorized:
                            self.caption_engine.push_mic_pcm48_mono(mono_hp * self.envelope.mic_gain, is_onstage=True)
                    else:
                        mic_clean = zero_stereo
                        mic_dbfs = -90.0
                else:
                    self._raw_pre_mix_dbfs = -90.0
                    mic_clean = zero_stereo
                    mic_dbfs = -90.0

                duck_mic_dbfs = mic_dbfs if is_onstage else -90.0
                dj_bus_hot = (now_mono - self._dj_bus_last_audible_mono) < 3.0
                dec = self._radio_decision
                ad_swap_active = self._ad_swap_desired_now
                dj_air_active = (
                    not ad_swap_active
                    and self._effective_dj_mode not in ("house", "beds")
                    and dec.action == "air_bus"
                    and dj_bus_hot
                )

                # Smoothly crossfade (~0.9s) into the vocal-carved Stage Attention Bed throughout
                # 9 PM - 2 AM showtime (`effective_dj_mode == 'beds'`) or when pinned on stage
                want_stage_bed = bool(
                    self._current_stage_bed
                    and not ad_swap_active
                    and (self._effective_dj_mode == "beds" or (is_onstage and self.envelope.onstage_mode == "bed"))
                )
                target_bed_ratio = 1.0 if want_stage_bed else 0.0
                bed_step = self.CHUNK_SEC / 0.90
                if self._bed_mix_ratio < target_bed_ratio:
                    self._bed_mix_ratio = min(1.0, self._bed_mix_ratio + bed_step)
                elif self._bed_mix_ratio > target_bed_ratio:
                    self._bed_mix_ratio = max(0.0, self._bed_mix_ratio - bed_step)

                has_program_audio = bool(ad_swap_active or dj_air_active or self._current_track or self._current_stage_bed)
                music_gain, voice_active = self.envelope.step(
                    mic_rms_dbfs=duck_mic_dbfs,
                    is_performer_onstage=is_onstage,
                    music_enabled=(self._music_desired_now and has_program_audio),
                    now_mono=now_mono,
                    dt=self.CHUNK_SEC,
                )

                music_raw = None
                bed_raw = None
                active_source = "off"
                active_track_label = ""
                banner_str = ""

                # Always drain _dj_bus_queue during ad swaps so Spotify/browser plays silently without stale lag
                if ad_swap_active:
                    with self._dj_bus_lock:
                        if self._dj_bus_queue:
                            self._dj_bus_queue.popleft()
                    if music_gain > 0.0005:
                        with self._ads_lock:
                            music_raw = self._ads_queue.popleft() if self._ads_queue else None
                        if music_raw is None:
                            with self._music_lock:
                                music_raw = self._music_queue.popleft() if self._music_queue else None
                    active_source = "box2_ads_swap"
                    active_track_label = self._current_ad_track or self._current_track
                    banner_str = dec.ticker_banner or "SPONSOR BREAK: YURRMOM.COM -- BOOK STAGE TIME AT HTTPS://BOX2.YURRMOM.COM"
                else:
                    if music_gain > 0.0005 and self._bed_mix_ratio > 0.001:
                        with self._stage_bed_lock:
                            bed_raw = self._stage_bed_queue.popleft() if self._stage_bed_queue else None

                    if self._bed_mix_ratio < 0.999:
                        if dj_air_active:
                            if music_gain > 0.0005:
                                with self._dj_bus_lock:
                                    music_raw = self._dj_bus_queue.popleft() if self._dj_bus_queue else None
                            active_source = f"dj_{dec.source_role or 'bus'}"
                            active_track_label = f"{dec.artist} - {dec.title}".strip(" -") if (dec.artist or dec.title) else dec.source_role
                            banner_str = dec.ticker_banner
                        elif self._music_desired_now:
                            if music_gain > 0.0005:
                                with self._music_lock:
                                    music_raw = self._music_queue.popleft() if self._music_queue else None
                            active_source = "house_ssd"
                            active_track_label = self._current_track

                    if self._bed_mix_ratio >= 0.5 and bed_raw is not None:
                        active_source = "stage_bed"
                        active_track_label = self._current_stage_bed

                if np is not None:
                    m_f32 = (np.frombuffer(music_raw, dtype=np.int16).reshape(-1, 2).astype(np.float32) / 32768.0) if music_raw is not None else zero_stereo
                    if is_onstage and self.envelope.onstage_mode == "undertone" and not ad_swap_active and music_raw is not None:
                        # Carve center vocal frequency pocket (~300-3400 Hz) so comedian's mic cuts cleanly over Spotify song
                        m_f32 = self.envelope.apply_undertone_vocal_pocket(m_f32)
                    b_f32 = (np.frombuffer(bed_raw, dtype=np.int16).reshape(-1, 2).astype(np.float32) / 32768.0) if bed_raw is not None else zero_stereo
                    if bed_raw is not None and music_raw is not None and 0.001 < self._bed_mix_ratio < 0.999:
                        # Equal-power crossfade between vocal YurrMom radio and vocal-carved Stage Attention Bed
                        w_bed = math.sin(0.5 * math.pi * self._bed_mix_ratio)
                        w_mus = math.cos(0.5 * math.pi * self._bed_mix_ratio)
                        music_f32 = m_f32 * w_mus + b_f32 * w_bed
                    elif self._bed_mix_ratio >= 0.5 and bed_raw is not None:
                        music_f32 = b_f32
                    else:
                        music_f32 = m_f32
                else:
                    music_f32 = zero_stereo

                any_prog_chunk = (music_raw is not None) or (bed_raw is not None)

                if np is not None:
                    out_i16 = self.envelope.mix_and_limit(mic_clean, music_f32, music_gain)
                    out_bytes = out_i16.tobytes()
                else:
                    out_bytes = mic_raw if (mic_raw and not mute_mic) else zero_bytes

                next_ad_s = (
                    max(0, int(round(self._next_scheduled_ad_mono - now_mono)))
                    if (self._ad_interval_minutes > 0.0 and self._next_scheduled_ad_mono > 0.0)
                    else None
                )
                self.stats.update(
                    mic_dbfs=round(mic_dbfs, 1),
                    mic_gated=bool(self._mic_stage_gate < 0.05),
                    mic_authority=self.mic_verdict.status_code,
                    mic_source_id=self.mic_verdict.source_id,
                    voice_ducking=bool(voice_active),
                    music_mode=self._music_mode,
                    dj_mode=self._dj_mode,
                    effective_dj_mode=self._effective_dj_mode,
                    audio_source=active_source if self._music_desired_now else "off",
                    ad_shield_active=bool(ad_swap_active),
                    ad_interval_minutes=self._ad_interval_minutes,
                    next_scheduled_ad_in_s=next_ad_s,
                    music_playing=bool(music_gain > 0.005 and any_prog_chunk),
                    music_track=active_track_label if self._music_desired_now else "",
                    now_playing_banner=banner_str if self._music_desired_now else "",
                    music_gain=round(music_gain, 3),
                    music_onstage_mode=self.envelope.onstage_mode,
                )

                try:
                    os.write(self.write_fd, out_bytes)
                except OSError:
                    break
        finally:
            try:
                os.close(self.write_fd)
            except OSError:
                pass

    def stop(self):
        self._stop_event.set()
        self._terminate_proc(self._mic_proc)
        self._terminate_proc(self._dj_bus_proc)
        self._terminate_proc(self._ads_proc)
        self._terminate_proc(self._stage_bed_proc)
        self._terminate_proc(self._music_proc)
        try:
            os.close(self.write_fd)
        except OSError:
            pass
        try:
            os.close(self.read_fd)
        except OSError:
            pass


# ----- non-blocking primary camera capture -----
class PrimaryCameraReader:
    """Dedicated background reader for NVR Channel 0 so DirectorStream never blocks on TCP stalls."""

    def __init__(self, initial_url, url_getter=None, on_reconnect=None):
        self.url_getter = url_getter or (lambda: initial_url)
        self.on_reconnect = on_reconnect
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self.latest_frame = None
        self.last_frame_mono = 0.0
        self.frame_seq = 0

        cap = self._open_capture(initial_url)
        if not cap.isOpened():
            raise RuntimeError("PrimaryCameraReader: Failed to open initial video source")
        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            raise RuntimeError("PrimaryCameraReader: Failed to read initial frame from camera")

        self._cap = cap
        self.latest_frame = frame.copy()
        self.last_frame_mono = time.monotonic()
        self.frame_seq = 1
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @staticmethod
    def _open_capture(url):
        cap = cv2.VideoCapture()
        for prop_name, val in (("CAP_PROP_OPEN_TIMEOUT_MSEC", 5000), ("CAP_PROP_READ_TIMEOUT_MSEC", 5000)):
            prop = getattr(cv2, prop_name, None)
            if prop is not None:
                try:
                    cap.set(prop, val)
                except Exception:
                    pass
        cap.open(url)
        return cap

    def _worker(self):
        fail_count = 0
        while not self._stop_event.is_set():
            cap = self._cap
            if cap is None or not cap.isOpened():
                fail_count = 99
            else:
                try:
                    ret, frame = cap.read()
                except Exception:
                    ret, frame = False, None

                if ret and frame is not None:
                    fail_count = 0
                    with self._lock:
                        self.latest_frame = frame
                        self.last_frame_mono = time.monotonic()
                        self.frame_seq += 1
                    continue
                fail_count += 1

            if fail_count >= 12 or (time.monotonic() - self.last_frame_mono > 4.0):
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
                self._cap = None
                if self.on_reconnect:
                    try:
                        self.on_reconnect()
                    except Exception:
                        pass
                url = self.url_getter()
                if url and not self._stop_event.is_set():
                    new_cap = self._open_capture(url)
                    if new_cap.isOpened():
                        ret, frame = new_cap.read()
                        if ret and frame is not None:
                            self._cap = new_cap
                            fail_count = 0
                            with self._lock:
                                self.latest_frame = frame
                                self.last_frame_mono = time.monotonic()
                                self.frame_seq += 1
                            log("Stage Director: Camera connection recovered seamlessly (zero Twitch dropped frames)")
                            continue
                        new_cap.release()
                time.sleep(1.0)
            else:
                time.sleep(0.05)

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass

    def get_frame(self):
        """Non-blocking (<0.01ms) access to latest camera frame and freshness flag."""
        with self._lock:
            age = time.monotonic() - self.last_frame_mono
            frame = self.latest_frame.copy() if self.latest_frame is not None else None
        return frame, (age < 1.5)

    def stop(self):
        self._stop_event.set()


# ----- rolling SSD clip ring buffer & set logger -----
def parse_duration_seconds(spec, default_seconds=600.0):
    """Parse flexible clip duration strings ('10m', '90s', '1h15m', '12') into seconds."""
    if spec is None or str(spec).strip() == "":
        return float(default_seconds)
    s = str(spec).strip().lower()
    if re.fullmatch(r'\d+(\.\d+)?', s):
        return max(5.0, float(s) * 60.0)  # bare number defaults to minutes (e.g. `clip 10` = 10 minutes)
    total = 0.0
    matched = False
    for val, unit in re.findall(r'(\d+(?:\.\d+)?)\s*([hms])', s):
        matched = True
        v = float(val)
        if unit == 'h':
            total += v * 3600.0
        elif unit == 'm':
            total += v * 60.0
        elif unit == 's':
            total += v
    if not matched:
        raise ValueError(f"Unrecognized duration '{spec}' (examples: 10m, 90s, 15, --last-set)")
    return max(5.0, total)


def record_set_event(sets_file, start_epoch, end_epoch, event_type="auto_set", label=""):
    dur = max(0.0, float(end_epoch) - float(start_epoch))
    entry = {
        "type": event_type,
        "label": label,
        "start_epoch": round(float(start_epoch), 2),
        "end_epoch": round(float(end_epoch), 2),
        "duration_s": round(dur, 1),
        "start_local": datetime.fromtimestamp(start_epoch).strftime('%Y-%m-%d %I:%M:%S %p'),
        "end_local": datetime.fromtimestamp(end_epoch).strftime('%Y-%m-%d %I:%M:%S %p'),
    }
    p = Path(sets_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_recent_sets(sets_file, limit=15):
    p = Path(sets_file)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    except Exception:
        pass
    return out[-limit:]


def select_ring_segments(ring_dir, start_epoch, end_epoch, seg_seconds=15.0):
    """Select contiguous .ts ring segments covering [start_epoch, end_epoch], handling wrap-around via mtime."""
    ring_path = Path(ring_dir)
    if not ring_path.exists():
        return [], 0.0

    items = []
    for p in ring_path.glob("seg_*.ts"):
        try:
            st = p.stat()
            if st.st_size > 1024:
                items.append((st.st_mtime, p))
        except OSError:
            continue

    if not items:
        return [], 0.0

    # Sort chronologically by mtime (handles segment_wrap seg_2879 -> seg_0000 seamlessly)
    items.sort(key=lambda t: t[0])

    # Keep only the latest contiguous stream run if there is a multi-minute gap from an old boot
    contiguous = [items[-1]]
    max_gap = max(45.0, seg_seconds * 3.5)
    for idx in range(len(items) - 2, -1, -1):
        newer_mtime = contiguous[-1][0]
        cur_mtime = items[idx][0]
        if newer_mtime - cur_mtime > max_gap:
            break
        contiguous.append(items[idx])
    contiguous.reverse()

    # Each segment file's mtime is when that segment finished writing (~seg_end); seg_start ~= mtime - seg_seconds
    selected = []
    for mtime, p in contiguous:
        seg_start = mtime - seg_seconds
        seg_end = mtime
        if seg_end >= (start_epoch - 2.0) and seg_start <= (end_epoch + seg_seconds):
            selected.append((mtime, p))

    if not selected:
        return [], 0.0

    first_seg_start = selected[0][0] - seg_seconds
    trim_offset = max(0.0, float(start_epoch) - first_seg_start)
    return [p for _, p in selected], trim_offset


def resolve_last_set_window(sets_file, status_file=STATUS, state_data=None, now_epoch=None, pre_roll=10.0, post_roll=6.0):
    """Determine [start_epoch, end_epoch, source_desc] for `box2-stream clip --last-set`."""
    now_ts = float(now_epoch if now_epoch is not None else time.time())
    st = state_data if state_data is not None else read_state()

    # 1. Explicit manual `mark-set` marker if within last 2 hours
    mark_ts = st.get("manual_set_start_epoch")
    if mark_ts is not None and 5.0 <= (now_ts - float(mark_ts)) <= 7200.0:
        return float(mark_ts) - pre_roll, now_ts, "manual set marker"

    # 2. Currently active onstage set in status.json (e.g. comic just stepped off <25s ago)
    try:
        if status_file and Path(status_file).exists():
            live_st = json.loads(Path(status_file).read_text())
            act_start = live_st.get("active_set_start_epoch")
            if act_start is not None and 8.0 <= (now_ts - float(act_start)) <= 7200.0:
                return float(act_start) - pre_roll, now_ts, "active onstage set"
    except Exception:
        pass

    # 3. Most recent completed onstage set in sets.jsonl within last 90 minutes
    recent = load_recent_sets(sets_file, limit=10)
    if recent:
        last = recent[-1]
        end_ts = float(last["end_epoch"])
        start_ts = float(last["start_epoch"])
        if (now_ts - end_ts) <= 5400.0:
            return start_ts - pre_roll, min(now_ts, end_ts + post_roll), f"detected set ({int(last.get('duration_s', 0))}s)"

    # 4. Fallback: last 10 minutes
    return now_ts - 600.0, now_ts, "last 10m fallback (no recent set marker)"


def extract_clip(
    duration_or_mode=None,
    label=None,
    clip_base=DEFAULT_CLIP_BASE,
    status_file=STATUS,
    seg_seconds=15.0,
):
    """Losslessly extract an .mp4 clip from the rolling .ts ring buffer without interrupting Twitch."""
    clip_base = Path(clip_base)
    ring_dir = clip_base / "ring"
    saved_dir = clip_base / "saved"
    sets_file = clip_base / "sets.jsonl"
    saved_dir.mkdir(parents=True, exist_ok=True)

    now_ts = time.time()
    mode_str = str(duration_or_mode or "").strip().lower()
    if mode_str in ("", "--last-set", "last-set", "set"):
        start_epoch, end_epoch, source_desc = resolve_last_set_window(
            sets_file=sets_file, status_file=status_file, now_epoch=now_ts
        )
        # Clear one-shot manual set marker once clipped
        if source_desc == "manual set marker":
            update_state(manual_set_start_epoch=None)
    else:
        dur_s = parse_duration_seconds(duration_or_mode, default_seconds=600.0)
        start_epoch = now_ts - dur_s
        end_epoch = now_ts
        source_desc = f"last {int(round(dur_s))}s"

    segs, trim_offset = select_ring_segments(ring_dir, start_epoch, end_epoch, seg_seconds=seg_seconds)
    if not segs:
        raise RuntimeError(f"No rolling clip segments found in {ring_dir} yet (give stream ~15-30s after start).")

    target_dur = max(5.0, end_epoch - start_epoch)
    safe_label = re.sub(r'[^a-zA-Z0-9_-]+', '_', str(label or 'set')).strip('_') or 'set'
    ts_str = datetime.fromtimestamp(now_ts).strftime('%Y%m%d_%H%M%S')
    out_mp4 = saved_dir / f"clip_{ts_str}_{safe_label}.mp4"

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        concat_path = tf.name
        for seg in segs:
            escaped = str(seg).replace("'", "'\\''")
            tf.write(f"file '{escaped}'\n")

    try:
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_path,
        ]
        if trim_offset >= 2.0:
            cmd.extend(["-ss", f"{trim_offset:.2f}"])
        cmd.extend([
            "-t", f"{target_dur + 4.0:.2f}",
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            str(out_mp4),
        ])
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg clip remux failed: {res.stderr.strip()}")
    finally:
        try:
            os.unlink(concat_path)
        except OSError:
            pass

    size_mb = out_mp4.stat().st_size / (1024.0 * 1024.0)
    actual_dur = target_dur
    if os.path.exists(FFPROBE):
        try:
            pr = subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(out_mp4)],
                capture_output=True, text=True, timeout=5,
            )
            if pr.returncode == 0 and pr.stdout.strip():
                actual_dur = float(pr.stdout.strip())
        except Exception:
            pass

    first_seg_start = segs[0].stat().st_mtime - seg_seconds
    clip_actual_start = first_seg_start + (trim_offset if trim_offset >= 2.0 else 0.0)
    srt_out = box2_captions.export_srt_for_clip(
        mp4_path=out_mp4,
        clip_start_epoch=clip_actual_start,
        clip_end_epoch=clip_actual_start + actual_dur,
        captions_log=clip_base / "captions.jsonl",
    )

    return {
        "path": str(out_mp4),
        "srt_path": str(srt_out) if srt_out else None,
        "duration_s": round(actual_dur, 1),
        "size_mb": round(size_mb, 2),
        "segments_used": len(segs),
        "source": source_desc,
    }


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


def next_scheduled_refresh_time(interval_hours=0):
    """Calculates the next top-of-the-hour timestamp divisible by interval_hours (None in marathon mode)."""
    if not interval_hours or interval_hours <= 0:
        return None
    now_dt = datetime.now()
    cand = now_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while cand.hour % interval_hours != 0 or cand <= now_dt:
        cand += timedelta(hours=1)
    return cand


class TickerOverlay:
    """Renders broadcast header banner with live moving timestamp, scrolling ticker tape,
    centered STAGE STANDBY badge, and optional warnings when 3-hour VOD mode is active.
    """

    def __init__(self, config_path="/home/joseph1/box2-stream/ticker.json", top_h=110, refresh_hours=0, jokes_path=None):
        self.config_path = config_path
        self.jokes_path = str(jokes_path or JOKES_FILE)
        self.top_h = top_h
        self.refresh_hours = int(refresh_hours)
        self.last_load = 0.0
        self.last_countdown_update = 0.0
        self.current_rem_sec = None
        self.next_time_str = ""
        self.jokes_data = load_jokes_data(self.jokes_path)
        self.data = {
            "title": "BOX 2  |  CANTON REFINERY",
            "seasonal_theme": "black_friday",
            "messages": [
                "NOW ON STAGE: Open Mic Comedy Session",
                "BOOK STAGE TIME: https://box2.yurrmom.com",
                "SPONSOR: YURRMOM.COM",
                "UP NEXT: Comedians In The Box",
            ],
            "scroll_speed": 4,
        }
        self.scroll_x = 0
        self.live_banner = ""
        self.full_ticker_str = ""
        self._np_cache_key = None
        self._np_bgr = None
        self._np_alpha = None
        self._np_font_tag = None
        self._np_font_song = None
        self._update_full_str()

    def set_live_banner(self, banner_text):
        b = str(banner_text or "").strip()
        if b != self.live_banner:
            self.live_banner = b
            self._update_full_str()

    def set_refresh_hours(self, refresh_hours):
        rh = int(refresh_hours)
        if rh != self.refresh_hours:
            self.refresh_hours = rh
            self._update_full_str()

    def _update_full_str(self, test_rem_sec=None):
        base_msgs = list(self.data.get("messages", []))
        if self.refresh_hours <= 0 and test_rem_sec is None:
            # Strip static 3-hour VOD drop notices automatically when running in uninterrupted marathon mode
            base_msgs = [m for m in base_msgs if "3-hour vod" not in m.lower()]

        # Interleave seasonal greeting & jokes cleanly into ticker rotation
        jokes = list(self.jokes_data.get("jokes", []))
        greeting = self.jokes_data.get("seasonal_greeting", "").strip()
        theme = normalize_seasonal_theme(self.data.get("seasonal_theme", "black_friday"))
        raw_msgs = []
        if greeting and theme != "classic":
            raw_msgs.append(greeting)
        if jokes:
            # Weave core venue messages with seasonal & Yurrmom.com jokes in the scrolling ticker
            max_len = max(len(base_msgs), len(jokes))
            for i in range(max_len):
                if i < len(base_msgs):
                    raw_msgs.append(base_msgs[i])
                if i < len(jokes):
                    raw_msgs.append(jokes[i])
        else:
            raw_msgs.extend(base_msgs)

        if self.live_banner:
            raw_msgs = [self.live_banner] + raw_msgs
        if not raw_msgs:
            raw_msgs = ["BOX 2 LIVE"]

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

    @staticmethod
    def _draw_autumn_leaf_cv2(img, cx, cy, scale=1.0, color_bgr=(35, 130, 240)):
        """Draw an unmistakable 3-lobe autumn maple leaf with a bottom stem."""
        blade = np.array([
            [cx, int(cy - 10 * scale)],                    # top center point
            [int(cx + 3 * scale), int(cy - 4 * scale)],
            [int(cx + 10 * scale), int(cy - 6 * scale)],   # upper-right lobe tip
            [int(cx + 7 * scale), int(cy + 0 * scale)],
            [int(cx + 9 * scale), int(cy + 3 * scale)],    # lower-right lobe tip
            [int(cx + 2 * scale), int(cy + 5 * scale)],    # leaf base right
            [int(cx - 2 * scale), int(cy + 5 * scale)],    # leaf base left
            [int(cx - 9 * scale), int(cy + 3 * scale)],    # lower-left lobe tip
            [int(cx - 7 * scale), int(cy + 0 * scale)],
            [int(cx - 10 * scale), int(cy - 6 * scale)],   # upper-left lobe tip
            [int(cx - 3 * scale), int(cy - 4 * scale)],
        ], dtype=np.int32)
        cv2.fillPoly(img, [blade], color_bgr, lineType=cv2.LINE_AA)
        # Stem + central midrib vein
        stem_bgr = tuple(max(0, int(c * 0.65)) for c in color_bgr)
        cv2.line(img, (cx, int(cy - 5 * scale)), (cx, int(cy + 10 * scale)), stem_bgr, max(1, int(round(1.6 * scale))), cv2.LINE_AA)
        cv2.line(img, (cx, int(cy + 10 * scale)), (int(cx + 2 * scale), int(cy + 11 * scale)), color_bgr, max(1, int(round(1.5 * scale))), cv2.LINE_AA)

    @staticmethod
    def _draw_price_tag_cv2(img, cx, cy, scale=1.0):
        """Draw a crisp angled Black Friday deal tag (crimson body, gold border & punch hole)."""
        pts = np.array([
            [int(cx - 9 * scale), int(cy - 2 * scale)],
            [int(cx - 2 * scale), int(cy - 9 * scale)],
            [int(cx + 8 * scale), int(cy + 1 * scale)],
            [int(cx + 1 * scale), int(cy + 8 * scale)],
        ], dtype=np.int32)
        cv2.fillPoly(img, [pts], (45, 32, 218), lineType=cv2.LINE_AA)
        cv2.polylines(img, [pts], True, (55, 200, 255), max(1, int(round(1.3 * scale))), cv2.LINE_AA)
        cv2.circle(img, (int(cx - 4 * scale), int(cy - 4 * scale)), max(1, int(round(1.8 * scale))), (12, 12, 16), -1, cv2.LINE_AA)

    def reload_if_needed(self):
        now_mono = time.monotonic()
        if now_mono - self.last_load > 2.0:
            self.last_load = now_mono
            changed = False
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path) as f:
                        loaded = json.load(f)
                    if loaded != self.data:
                        self.data = loaded
                        changed = True
                except Exception:
                    pass
            new_jokes = load_jokes_data(self.jokes_path)
            if new_jokes != self.jokes_data:
                self.jokes_data = new_jokes
                changed = True
            if changed:
                self._update_full_str()

        if now_mono - self.last_countdown_update >= 1.0:
            self.last_countdown_update = now_mono
            self._update_full_str()

    def draw(self, frame_bgr, standby_mode=False):
        h, w = frame_bgr.shape[:2]
        self.reload_if_needed()
        theme = normalize_seasonal_theme(self.data.get("seasonal_theme", "black_friday"))
        is_tg = (theme == "thanksgiving")
        is_bf = (theme == "black_friday")

        # 1. Solid matte banner background (y=0 to top_h)
        frame_bgr[:self.top_h, :] = (10, 10, 14) if is_bf else ((12, 14, 20) if is_tg else (15, 15, 18))
        sep_color = (48, 188, 250) if is_bf else ((40, 115, 205) if is_tg else (70, 70, 80))
        cv2.line(frame_bgr, (0, self.top_h - 1), (w, self.top_h - 1), sep_color, 2)

        # 2. [● LIVE] badge
        cv2.rectangle(frame_bgr, (20, 12), (120, 42), (30, 30, 190), -1)
        cv2.circle(frame_bgr, (38, 27), 4, (255, 255, 255), -1)
        cv2.putText(frame_bgr, "LIVE", (52, 33), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

        # 3. Stage title (+ seasonal accent icon)
        title = self.data.get("title", "BOX 2  |  CANTON REFINERY")
        title_x = 140
        if is_bf:
            self._draw_price_tag_cv2(frame_bgr, 143, 27, scale=1.0)
            title_x = 160
        elif is_tg:
            self._draw_autumn_leaf_cv2(frame_bgr, 142, 27, scale=0.95, color_bgr=(30, 135, 245))
            title_x = 160
        cv2.putText(frame_bgr, title, (title_x, 33), cv2.FONT_HERSHEY_DUPLEX, 0.6, (225, 232, 242), 1, cv2.LINE_AA)

        # 4. Imminent reset warning badge (<= 180s) OR centered STAGE STANDBY badge
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

            (tw, th), _ = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
            bx1, by1 = 500, 12
            bx2, by2 = max(730, bx1 + tw + 32), 42
            tx = bx1 + ((bx2 - bx1) - tw) // 2
            ty = by1 + ((by2 - by1) + th) // 2
            cv2.rectangle(frame_bgr, (bx1, by1), (bx2, by2), badge_bg, -1)
            cv2.rectangle(frame_bgr, (bx1, by1), (bx2, by2), badge_border, 1)
            cv2.putText(frame_bgr, badge_text, (tx, ty), cv2.FONT_HERSHEY_DUPLEX, 0.55, text_color, 1, cv2.LINE_AA)
        elif standby_mode and self.data.get("privacy_placeholder", {}).get("show_standby_badge", True):
            default_standby = (
                "BLACK FRIDAY | STANDBY"
                if is_bf
                else ("HAPPY THANKSGIVING | STANDBY" if is_tg else "STAGE STANDBY")
            )
            standby_label = self.data.get("privacy_placeholder", {}).get("badge_label", default_standby)
            (tw, th), _ = cv2.getTextSize(standby_label, cv2.FONT_HERSHEY_DUPLEX, 0.50, 1)
            bx1, by1 = (490 if is_bf else (478 if is_tg else 500)), 12
            bx2, by2 = max(710, bx1 + tw + 30), 42
            tx = bx1 + ((bx2 - bx1) - tw) // 2
            ty = by1 + ((by2 - by1) + th) // 2
            bg_c = (18, 16, 36) if is_bf else ((18, 28, 48) if is_tg else (32, 34, 42))
            bd_c = (55, 195, 255) if is_bf else ((45, 145, 235) if is_tg else (110, 115, 130))
            tx_c = (105, 222, 255) if is_bf else ((120, 205, 255) if is_tg else (205, 210, 220))
            cv2.rectangle(frame_bgr, (bx1, by1), (bx2, by2), bg_c, -1)
            cv2.rectangle(frame_bgr, (bx1, by1), (bx2, by2), bd_c, 1)
            cv2.putText(frame_bgr, standby_label, (tx, ty), cv2.FONT_HERSHEY_DUPLEX, 0.50, tx_c, 1, cv2.LINE_AA)

        # 5. Live moving timestamp (updates each second)
        now_str = datetime.now().strftime("%m/%d/%Y  %I:%M:%S %p")
        cv2.putText(frame_bgr, now_str, (w - 380, 33), cv2.FONT_HERSHEY_DUPLEX, 0.58, (220, 225, 230), 1, cv2.LINE_AA)

        # 6. Ticker tape box (y=50 to 96)
        is_imminent = rem_sec is not None and rem_sec <= 300
        if is_imminent:
            box_border_color = (0, 180, 255)
            ticker_text_color = (0, 220, 255)
            box_bg_color = (28, 28, 34)
        elif is_bf:
            box_border_color = (48, 185, 248)   # crisp Black Friday deal gold in BGR
            ticker_text_color = (75, 218, 255)  # high-contrast Black Friday gold (#FFDA4B) in BGR
            box_bg_color = (12, 13, 18)         # deep matte obsidian
        elif is_tg:
            box_border_color = (42, 125, 218)   # warm harvest copper-gold in BGR
            ticker_text_color = (75, 198, 255)  # rich warm Thanksgiving gold (#FFC64B) in BGR
            box_bg_color = (18, 22, 32)
        else:
            box_border_color = (60, 60, 70)
            ticker_text_color = (0, 230, 255)
            box_bg_color = (28, 28, 34)

        box_x1, box_y1, box_x2, box_y2 = 20, 50, w - 20, 96
        cv2.rectangle(frame_bgr, (box_x1, box_y1), (box_x2, box_y2), box_bg_color, -1)
        cv2.rectangle(frame_bgr, (box_x1, box_y1), (box_x2, box_y2), box_border_color, 1)

        # 7. Smooth scrolling text clipped inside ROI
        ticker_roi = frame_bgr[box_y1 + 1:box_y2 - 1, box_x1 + 2:box_x2 - 2]
        roi_h, roi_w = ticker_roi.shape[:2]

        font = cv2.FONT_HERSHEY_DUPLEX
        font_scale = 0.58
        font_thick = 1
        (tw, _), _ = cv2.getTextSize(self.full_ticker_str, font, font_scale, font_thick)

        speed = self.data.get("scroll_speed", 4)
        self.scroll_x = (self.scroll_x + speed) % max(1, tw)

        start_x = -self.scroll_x
        cv2.putText(ticker_roi, self.full_ticker_str, (start_x, 30), font, font_scale, ticker_text_color, font_thick, cv2.LINE_AA)
        if start_x + tw < roi_w:
            cv2.putText(ticker_roi, self.full_ticker_str, (start_x + tw, 30), font, font_scale, ticker_text_color, font_thick, cv2.LINE_AA)

    def _get_np_fonts(self):
        if self._np_font_tag is not None or not HAS_PIL:
            return self._np_font_tag, self._np_font_song
        for fp in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf",
        ):
            if os.path.exists(fp):
                try:
                    self._np_font_tag = ImageFont.truetype(fp, 11)
                    self._np_font_song = ImageFont.truetype(fp, 13)
                    return self._np_font_tag, self._np_font_song
                except Exception:
                    pass
        self._np_font_tag = ImageFont.load_default()
        self._np_font_song = ImageFont.load_default()
        return self._np_font_tag, self._np_font_song

    def _build_now_playing_tab(self, tag_str, song_str, theme):
        is_tg = (theme == "thanksgiving")
        is_bf = (theme == "black_friday")
        tab_h = 30
        if not HAS_PIL:
            full_s = f"{tag_str}: {song_str}"
            (tw, _), _ = cv2.getTextSize(full_s, cv2.FONT_HERSHEY_DUPLEX, 0.45, 1)
            tab_w = min(560, max(220, tw + 46))
            bgr = np.full((tab_h, tab_w, 3), (12, 12, 16) if is_bf else (16, 20, 30), dtype=np.uint8)
            alpha = np.full((tab_h, tab_w, 1), 0.90, dtype=np.float32)
            bd = (50, 190, 245) if is_bf else ((42, 130, 225) if is_tg else (90, 110, 140))
            cv2.line(bgr, (0, 0), (0, tab_h - 1), bd, 1)
            cv2.line(bgr, (tab_w - 1, 0), (tab_w - 1, tab_h - 1), bd, 1)
            cv2.line(bgr, (0, tab_h - 1), (tab_w - 1, tab_h - 1), bd, 1)
            cv2.putText(bgr, full_s, (34, 20), cv2.FONT_HERSHEY_DUPLEX, 0.44, (230, 240, 250), 1, cv2.LINE_AA)
            return bgr, alpha

        f_tag, f_song = self._get_np_fonts()
        dummy = Image.new("RGBA", (10, 10))
        d0 = ImageDraw.Draw(dummy)
        tb = d0.textbbox((0, 0), tag_str, font=f_tag)
        sb = d0.textbbox((0, 0), song_str, font=f_song)
        tag_w = tb[2] - tb[0]
        song_w = sb[2] - sb[0]
        # Layout: [12px pad] [18px eq bars] [8px gap] [tag pill] [10px gap] [song title] [14px pad]
        tab_w = min(620, max(230, 12 + 18 + 8 + (tag_w + 14) + 10 + song_w + 16))

        img = Image.new("RGBA", (tab_w, tab_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        bg_rgba = (12, 12, 16, 238) if is_bf else ((24, 15, 10, 232) if is_tg else (18, 20, 28, 230))
        border_rgba = (245, 190, 50, 240) if is_bf else ((225, 128, 42, 235) if is_tg else (90, 130, 175, 220))
        # Docked tab shape: square top corners flush against y=top_h-1, rounded bottom corners
        draw.rounded_rectangle([(0, -8), (tab_w - 1, tab_h - 1)], radius=9, fill=bg_rgba, outline=border_rgba, width=1)

        pill_x1 = 38
        pill_x2 = pill_x1 + tag_w + 14
        if tag_str == "SPOTIFY":
            pill_fill = (24, 135, 68, 235)
            pill_txt = (240, 255, 245, 255)
        elif is_bf:
            pill_fill = (175, 28, 42, 245)
            pill_txt = (255, 232, 135, 255)
        elif is_tg:
            pill_fill = (78, 36, 14, 245)
            pill_txt = (255, 210, 108, 255)
        else:
            pill_fill = (32, 46, 68, 240)
            pill_txt = (120, 225, 255, 255)

        draw.rounded_rectangle([(pill_x1, 6), (pill_x2, tab_h - 6)], radius=5, fill=pill_fill)
        draw.text((pill_x1 + 7, 8), tag_str, font=f_tag, fill=pill_txt)

        song_x = pill_x2 + 10
        draw.text((song_x + 1, 8), song_str, font=f_song, fill=(0, 0, 0, 180))
        draw.text((song_x, 7), song_str, font=f_song, fill=(255, 246, 230, 255))

        arr = np.array(img)
        bgr = arr[:, :, [2, 1, 0]].copy()
        alpha = (arr[:, :, 3:4].astype(np.float32)) / 255.0
        return bgr, alpha

    def draw_now_playing_tab(self, frame_bgr, music_stats):
        """Draw compact docked 'Now Playing' tab right beneath the ticker bar when music is playing."""
        if not music_stats or not music_stats.get("music_playing"):
            return
        np_cfg = self.data.get("now_playing_tab", {})
        if isinstance(np_cfg, dict) and not np_cfg.get("enabled", True):
            return

        tag_str, song_str = format_now_playing_label(
            raw_track=music_stats.get("music_track", ""),
            audio_source=music_stats.get("audio_source", "house_ssd"),
            ad_shield_active=bool(music_stats.get("ad_shield_active", False)),
        )
        if not song_str:
            return

        theme = normalize_seasonal_theme(self.data.get("seasonal_theme", "black_friday"))
        is_tg = (theme == "thanksgiving")
        is_bf = (theme == "black_friday")
        ckey = (tag_str, song_str, theme)
        if ckey != self._np_cache_key or self._np_bgr is None:
            self._np_bgr, self._np_alpha = self._build_now_playing_tab(tag_str, song_str, theme)
            self._np_cache_key = ckey

        fh, fw = frame_bgr.shape[:2]
        tab_h, tab_w = self._np_bgr.shape[:2]
        align = str((np_cfg or {}).get("align", "right")).lower()
        x1 = 20 if align == "left" else max(20, (fw - 20) - tab_w)
        y1 = self.top_h - 1
        x2, y2 = min(fw, x1 + tab_w), min(fh, y1 + tab_h)
        if y2 - y1 != tab_h or x2 - x1 != tab_w:
            return

        roi = frame_bgr[y1:y2, x1:x2].astype(np.float32)
        frame_bgr[y1:y2, x1:x2] = (
            roi * (1.0 - self._np_alpha) + self._np_bgr.astype(np.float32) * self._np_alpha
        ).astype(np.uint8)

        # Animated 4-bar mini audio equalizer on left side of tab
        t = time.monotonic()
        bar_color = (
            (95, 215, 50)
            if tag_str == "SPOTIFY"
            else ((55, 205, 255) if is_bf else ((65, 195, 255) if is_tg else (0, 225, 255)))
        )
        for bi, freq in enumerate((5.2, 7.1, 4.3, 6.4)):
            bh = int(4 + 11 * (0.5 + 0.5 * math.sin(t * freq + bi * 1.3)))
            bx = x1 + 13 + bi * 5
            by2 = y1 + tab_h - 7
            by1 = by2 - bh
            cv2.rectangle(frame_bgr, (bx, by1), (bx + 2, by2), bar_color, -1)


class ShowtimeCountdownOverlay:
    """Large bottom-right Showtime Countdown + Seasonal Cheer + Rotating Joke Spotlight card.

    - Displays a big, high-contrast PIL-rendered countdown (`HH : MM : SS`) to 9:00 PM EST
      in the bottom-right corner alongside a rotating comedy/YurrMom.com joke spotlight.
    - Re-renders the card image only once per second (cached RGBA array), keeping per-frame
      blending under 0.3ms on Jetson Orin Nano.
    - Adds subtle drifting autumn harvest leaves in the dark standby side margins when
      `seasonal_theme == "thanksgiving"`.
    """

    def __init__(
        self,
        config_path="/home/joseph1/box2-stream/ticker.json",
        jokes_path=None,
        base_w=1280,
        base_h=720,
        start_hour=21,
        end_hour=2,
    ):
        self.config_path = config_path
        self.jokes_path = str(jokes_path or JOKES_FILE)
        self.base_w = base_w
        self.base_h = base_h
        self.start_hour = int(start_hour)
        self.end_hour = int(end_hour)

        self.enabled = True
        self.theme = "black_friday"
        # 15% more compact (382x142 vs 450x166), vertically center-aligned with Parking Lot PIP (y=495..686 -> mid_y=590.5)
        self.card_w = 382
        self.card_h = 142
        self.timer_font_size = 52
        self.x = base_w - self.card_w - 26  # x = 872 on 1280x720 (matches 26px left margin of Parking Lot PIP)
        self.y = int(round((495 + 191 / 2.0) - self.card_h / 2.0))  # y = 520 -> mid_y = 591.0 (matches PIP mid_y = 590.5)
        self.show_falling_leaves = False

        self.last_check = 0.0
        self._fonts = {}
        self._cached_key = None
        self._cached_bgr = None
        self._cached_alpha = None
        self._leaf_particles = [
            {"x": 42.0, "y": 140.0, "vy": 1.6, "phase": 0.0, "color": (30, 125, 240), "scale": 1.0},
            {"x": 355.0, "y": 290.0, "vy": 1.3, "phase": 1.8, "color": (35, 70, 210), "scale": 0.85},
            {"x": 850.0, "y": 180.0, "vy": 1.5, "phase": 3.1, "color": (55, 185, 250), "scale": 0.95},
            {"x": 1225.0, "y": 260.0, "vy": 1.8, "phase": 4.5, "color": (28, 110, 235), "scale": 1.05},
            {"x": 1060.0, "y": 130.0, "vy": 1.4, "phase": 2.2, "color": (45, 160, 245), "scale": 0.80},
        ]
        self._reload(force=True)

    def _get_font(self, size):
        if size in self._fonts:
            return self._fonts[size]
        if not HAS_PIL:
            return None
        for fp in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf",
        ):
            if os.path.exists(fp):
                try:
                    f = ImageFont.truetype(fp, size)
                    self._fonts[size] = f
                    return f
                except Exception:
                    pass
        f = ImageFont.load_default()
        self._fonts[size] = f
        return f

    def _reload(self, force=False):
        now_m = time.monotonic()
        if not force and (now_m - self.last_check < 2.0):
            return
        self.last_check = now_m
        if os.path.exists(self.config_path):
            try:
                tk = json.loads(Path(self.config_path).read_text())
                self.theme = normalize_seasonal_theme(tk.get("seasonal_theme", "black_friday"))
                p_cfg = tk.get("privacy_placeholder", {})
                cam_cfg = tk.get("parking_lot_camera", {})
                pip_x = int(p_cfg.get("cam2_x", 26))
                pip_y = int(p_cfg.get("cam2_y", 495))
                pip_h = int(cam_cfg.get("height", 191))
                pip_mid_y = pip_y + pip_h / 2.0

                c_cfg = tk.get("showtime_countdown", {})
                if isinstance(c_cfg, dict):
                    self.enabled = bool(c_cfg.get("enabled", True))
                    new_w = int(c_cfg.get("width", 382))
                    new_h = int(c_cfg.get("height", 142))
                    new_fs = int(c_cfg.get("timer_font_size", 52))
                    if (new_w, new_h, new_fs) != (self.card_w, self.card_h, self.timer_font_size):
                        self.card_w, self.card_h, self.timer_font_size = new_w, new_h, new_fs
                        self._cached_key = None
                    default_x = self.base_w - self.card_w - pip_x
                    default_y = int(round(pip_mid_y - self.card_h / 2.0))
                    self.x = int(c_cfg.get("x", default_x))
                    self.y = int(c_cfg.get("y", default_y))
                    self.show_falling_leaves = bool(c_cfg.get("falling_leaves", self.theme == "thanksgiving"))
                else:
                    self.x = self.base_w - self.card_w - pip_x
                    self.y = int(round(pip_mid_y - self.card_h / 2.0))
            except Exception:
                pass

    @staticmethod
    def _wrap_text(draw, text, font, max_w, max_lines=3):
        words = str(text or "").split()
        if not words:
            return []
        lines = []
        cur = words[0]
        for w in words[1:]:
            test = f"{cur} {w}"
            bbox = draw.textbbox((0, 0), test, font=font)
            if (bbox[2] - bbox[0]) <= max_w:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            if len(lines[-1]) > 3:
                lines[-1] = lines[-1].rstrip(" .,") + "..."
        return lines

    @staticmethod
    def _draw_pil_maple_leaf(draw, cx, cy, r, fill_rgba):
        """Draw a crisp 3-lobed autumn maple leaf with visible petiole stem & veins."""
        pts = [
            (cx, cy - r * 1.05),                 # crown tip
            (cx + r * 0.22, cy - r * 0.45),
            (cx + r * 0.52, cy - r * 0.72),
            (cx + r * 0.48, cy - r * 0.30),
            (cx + r * 1.02, cy - r * 0.42),      # right main lobe
            (cx + r * 0.68, cy + r * 0.05),
            (cx + r * 0.85, cy + r * 0.28),      # right lower flare
            (cx + r * 0.16, cy + r * 0.42),      # base right
            (cx - r * 0.16, cy + r * 0.42),      # base left
            (cx - r * 0.85, cy + r * 0.28),      # left lower flare
            (cx - r * 0.68, cy + r * 0.05),
            (cx - r * 1.02, cy - r * 0.42),      # left main lobe
            (cx - r * 0.48, cy - r * 0.30),
            (cx - r * 0.52, cy - r * 0.72),
            (cx - r * 0.22, cy - r * 0.45),
        ]
        draw.polygon(pts, fill=fill_rgba)
        # Stem extending below leaf base + darker midrib vein
        vein_rgba = (max(0, fill_rgba[0] - 75), max(0, fill_rgba[1] - 55), max(0, fill_rgba[2] - 25), fill_rgba[3])
        draw.line([(cx, cy + r * 0.40), (cx + r * 0.18, cy + r * 1.05)], fill=fill_rgba, width=2)
        draw.line([(cx, cy - r * 0.55), (cx, cy + r * 0.42)], fill=vein_rgba, width=1)
        draw.line([(cx, cy + r * 0.10), (cx + r * 0.55, cy - r * 0.20)], fill=vein_rgba, width=1)
        draw.line([(cx, cy + r * 0.10), (cx - r * 0.55, cy - r * 0.20)], fill=vein_rgba, width=1)

    @staticmethod
    def _draw_pil_price_tag(draw, cx, cy, r):
        """Draw a crisp angled Black Friday deal tag icon with gold outline and punch hole."""
        pts = [
            (cx - r * 0.90, cy - r * 0.20),
            (cx - r * 0.20, cy - r * 0.90),
            (cx + r * 0.85, cy + r * 0.15),
            (cx + r * 0.15, cy + r * 0.85),
        ]
        draw.polygon(pts, fill=(220, 34, 48, 255), outline=(255, 208, 72, 255))
        hr = max(1.4, r * 0.18)
        hx, hy = cx - r * 0.40, cy - r * 0.40
        draw.ellipse([(hx - hr, hy - hr), (hx + hr, hy + hr)], fill=(20, 14, 18, 255))

    def _build_card(self, rem_sec_int, theme):
        is_tg = (theme == "thanksgiving")
        is_bf = (theme == "black_friday")
        w, h = self.card_w, self.card_h
        if not HAS_PIL:
            bgr = np.full((h, w, 3), (12, 12, 16) if is_bf else (18, 22, 32), dtype=np.uint8)
            alpha = np.full((h, w, 1), 0.88, dtype=np.float32)
            hrs = rem_sec_int // 3600
            mins = (rem_sec_int % 3600) // 60
            secs = rem_sec_int % 60
            txt = f"{hrs:02d}:{mins:02d}:{secs:02d}" if rem_sec_int > 0 else "SHOW LIVE!"
            cv2.rectangle(bgr, (0, 0), (w - 1, h - 1), (48, 190, 245) if is_bf else (45, 145, 240), 2)
            cv2.putText(bgr, "BLACK FRIDAY SHOWTIME" if is_bf else "SHOWTIME COUNTDOWN", (22, 34), cv2.FONT_HERSHEY_DUPLEX, 0.65, (80, 215, 255), 1, cv2.LINE_AA)
            cv2.putText(bgr, txt, (32, 114), cv2.FONT_HERSHEY_DUPLEX, 2.0, (255, 255, 255), 3, cv2.LINE_AA)
            return bgr, alpha

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        bg_rgba = (12, 12, 16, 238) if is_bf else ((26, 15, 10, 232) if is_tg else (18, 20, 28, 228))
        outer_border = (245, 190, 48, 248) if is_bf else ((238, 134, 42, 248) if is_tg else (0, 195, 255, 225))
        inner_border = (230, 48, 62, 150) if is_bf else ((255, 204, 96, 130) if is_tg else (90, 140, 190, 100))
        header_fill = (24, 16, 20, 250) if is_bf else ((62, 29, 13, 248) if is_tg else (28, 34, 48, 245))

        draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=12, fill=bg_rgba, outline=outer_border, width=2)
        draw.rounded_rectangle([(4, 4), (w - 5, h - 5)], radius=9, outline=inner_border, width=1)
        hdr_h = 35
        draw.rounded_rectangle([(2, 2), (w - 3, hdr_h)], radius=10, fill=header_fill)
        draw.line([(6, hdr_h), (w - 7, hdr_h)], fill=outer_border, width=1)

        f_hdr = self._get_font(12)
        f_timer = self._get_font(self.timer_font_size)
        f_unit = self._get_font(10)
        f_sub = self._get_font(11)

        if is_bf:
            self._draw_pil_price_tag(draw, 22, 18, 8)
            self._draw_pil_price_tag(draw, w - 22, 18, 8)
            hdr_text = "BLACK FRIDAY  •  SHOWTIME @ 9PM"
            hdr_color = (255, 218, 92, 255)
        elif is_tg:
            self._draw_pil_maple_leaf(draw, 20, 18, 8, (248, 145, 40, 255))
            self._draw_pil_maple_leaf(draw, w - 20, 18, 8, (224, 78, 45, 255))
            hdr_text = "HAPPY THANKSGIVING  •  SHOWTIME @ 9PM"
            hdr_color = (255, 212, 110, 255)
        else:
            hdr_text = "LIVE STAGE SHOWTIME @ 9:00 PM EST"
            hdr_color = (120, 225, 255, 255)

        hb = draw.textbbox((0, 0), hdr_text, font=f_hdr)
        draw.text(((w - (hb[2] - hb[0])) // 2, 11), hdr_text, font=f_hdr, fill=hdr_color)

        unit_fill = (235, 198, 115, 240) if is_bf else ((235, 185, 122, 240) if is_tg else (175, 195, 215, 230))
        if rem_sec_int > 0:
            hrs = rem_sec_int // 3600
            mins = (rem_sec_int % 3600) // 60
            secs = rem_sec_int % 60
            digit_fill = (255, 248, 232, 255) if rem_sec_int > 60 else (255, 198, 72, 255)

            # Render HH, MM, SS in proportional columns with HOURS / MINUTES / SECONDS centered below each pair
            col_step = int(round(w * 0.27))
            col_centers = (w // 2 - col_step, w // 2, w // 2 + col_step)
            parts = ((f"{hrs:02d}", "HOURS"), (f"{mins:02d}", "MINUTES"), (f"{secs:02d}", "SECONDS"))
            ty = 41
            unit_y = h - 24
            for cx, (val_s, lbl_s) in zip(col_centers, parts):
                vb = draw.textbbox((0, 0), val_s, font=f_timer)
                vx = cx - (vb[2] - vb[0]) // 2
                draw.text((vx + 2, ty + 2), val_s, font=f_timer, fill=(0, 0, 0, 200))
                draw.text((vx, ty), val_s, font=f_timer, fill=digit_fill)

                lb = draw.textbbox((0, 0), lbl_s, font=f_unit)
                lx = cx - (lb[2] - lb[0]) // 2
                draw.text((lx, unit_y), lbl_s, font=f_unit, fill=unit_fill)

            colon_fill = (245, 190, 55, 245) if is_bf else ((245, 175, 75, 245) if is_tg else digit_fill)
            for sep_x in (w // 2 - col_step // 2, w // 2 + col_step // 2):
                cb = draw.textbbox((0, 0), ":", font=f_timer)
                cx_s = sep_x - (cb[2] - cb[0]) // 2
                draw.text((cx_s + 2, ty + 2), ":", font=f_timer, fill=(0, 0, 0, 180))
                draw.text((cx_s, ty - 2), ":", font=f_timer, fill=colon_fill)
        else:
            t_str = "SHOWTIME!"
            tb = draw.textbbox((0, 0), t_str, font=f_timer)
            tx = (w - (tb[2] - tb[0])) // 2
            draw.text((tx + 2, 46), t_str, font=f_timer, fill=(0, 0, 0, 200))
            draw.text((tx, 44), t_str, font=f_timer, fill=(255, 205, 85, 255))
            sub_str = "STAGE RETURNING SHORTLY  •  CANTON REFINERY"
            sb = draw.textbbox((0, 0), sub_str, font=f_sub)
            draw.text(((w - (sb[2] - sb[0])) // 2, h - 25), sub_str, font=f_sub, fill=unit_fill)

        arr = np.array(img)
        bgr = arr[:, :, [2, 1, 0]].copy()
        alpha = (arr[:, :, 3:4].astype(np.float32)) / 255.0
        return bgr, alpha

    def _draw_falling_leaves(self, frame_bgr, top_matte_h=110):
        t = time.monotonic()
        fh, fw = frame_bgr.shape[:2]
        for p in self._leaf_particles:
            p["y"] += p["vy"]
            if p["y"] > fh - 235:
                p["y"] = float(top_matte_h + 14)
            sway_x = int(p["x"] + 14.0 * math.sin(t * 1.4 + p["phase"]))
            ly = int(p["y"])
            if top_matte_h + 8 < ly < fh - 230 and 12 < sway_x < fw - 12:
                roi = frame_bgr[ly - 12:ly + 12, sway_x - 12:sway_x + 12]
                if roi.shape[:2] == (24, 24):
                    overlay = roi.copy()
                    TickerOverlay._draw_autumn_leaf_cv2(overlay, 12, 12, scale=p["scale"], color_bgr=p["color"])
                    cv2.addWeighted(overlay, 0.52, roi, 0.48, 0, roi)

    def draw(self, frame_bgr, standby_mode=True, top_matte_h=110, now_dt=None):
        self._reload()
        if not self.enabled or not standby_mode:
            return

        theme = normalize_seasonal_theme(self.theme)
        if theme == "thanksgiving" and self.show_falling_leaves:
            self._draw_falling_leaves(frame_bgr, top_matte_h=top_matte_h)

        rem_sec = int(round(seconds_until_showtime(now_dt=now_dt, start_hour=self.start_hour, end_hour=self.end_hour)))
        cache_key = (rem_sec, theme)
        if cache_key != self._cached_key or self._cached_bgr is None:
            self._cached_bgr, self._cached_alpha = self._build_card(rem_sec, theme)
            self._cached_key = cache_key

        fh, fw = frame_bgr.shape[:2]
        x1 = max(0, min(fw - self.card_w, self.x))
        y1 = max(top_matte_h + 4, min(fh - self.card_h, self.y))
        x2, y2 = x1 + self.card_w, y1 + self.card_h
        roi = frame_bgr[y1:y2, x1:x2].astype(np.float32)
        frame_bgr[y1:y2, x1:x2] = (
            roi * (1.0 - self._cached_alpha) + self._cached_bgr.astype(np.float32) * self._cached_alpha
        ).astype(np.uint8)


class WallOverlay:
    """Subtle painted wall branding displayed on the dark stage wall when stage is empty."""

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
        self.style = "stacked"

        self.current_opacity = 0.55
        self.roi_x1 = 0
        self.roi_y1 = 0
        self.roi_x2 = 0
        self.roi_y2 = 0
        self.alpha_mask_roi = None
        self.color_bgr = None
        self._load_config(force=True)

    def reload_if_needed(self, force=False):
        now_m = time.monotonic()
        if not force and (now_m - self.last_check < 2.0):
            return
        self.last_check = now_m
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

        lines_to_render = [" ".join(self.lines)] if self.style == "single_line" else self.lines

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
    """Live secondary camera feed (Parking Lot Center) projected onto dark stage wall or privacy PIP."""

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
        self.style = "feathered"
        self.show_label = True
        self.label = "PARKING LOT CENTER"
        self.crop_osd = True
        self.src_crop_norm = (0.105, 0.144, 0.894, 0.933)
        self.temporal_smooth = True

        self.current_opacity = 0.65
        self.latest_frame = None
        self._ema_frame = None
        self._lock = threading.Lock()
        self._running = True
        self.last_check = 0
        self.last_mtime = 0

        self._feather_mask = None
        self._build_feather_mask()
        self._reload_config(force=True)

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
                cap = PrimaryCameraReader._open_capture(url)
                if not cap.isOpened():
                    time.sleep(2.0)
                    continue
                while self._running:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        fail_count += 1
                        if fail_count > 20:
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
        now_m = time.monotonic()
        if not force and (now_m - self.last_check < 2.0):
            return
        self.last_check = now_m
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
    """Stage Director AI framing stream with marathon resilience, auto-ducking show mixer & SSD clipper."""

    SET_GRACE_SECONDS = 25.0
    MIN_SET_SECONDS = 15.0

    def __init__(self, source, target, secrets, cfg, cam2_url=None, ip=None, token=None):
        self.ip = ip
        self.cfg = cfg
        self.secrets = secrets
        self.target = target
        self.started = time.monotonic()
        self.last_progress = self.started
        self.stage_preset_id = int(cfg.get("stage_resting_preset_id", 16))
        self.privacy_preset_id = int(cfg.get("privacy_preset_id", 17))
        self.show_start_hour = int(cfg.get("show_start_hour", 21))
        self.show_end_hour = int(cfg.get("show_end_hour", 2))
        self.current_view_mode = desired_view(start_hour=self.show_start_hour, end_hour=self.show_end_hour)
        self._current_policy = view_policy()
        self._is_performer_framed = False
        self._last_view_check = 0.0
        self._ptz_slew_until = 0.0
        self._held_canvas = None

        # Onstage set tracking for instant post-set clipping
        self.clip_base = Path(cfg.get("clip_dir", str(DEFAULT_CLIP_BASE)))
        self.ring_dir = self.clip_base / "ring"
        self.sets_file = self.clip_base / "sets.jsonl"
        self.enable_clip_buffer = bool(cfg.get("enable_clip_buffer", True))
        self.clip_seg_seconds = int(cfg.get("clip_segment_seconds", 15))
        self.clip_seg_wrap = int(cfg.get("clip_segment_wrap", 2880))  # 2880 * 15s = 12 hours rolling SSD history
        if self.enable_clip_buffer:
            try:
                self.ring_dir.mkdir(parents=True, exist_ok=True)
                (self.clip_base / "saved").mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                log(f"Clip ring buffer disabled (storage path error): {exc}")
                self.enable_clip_buffer = False

        self._active_set_start_epoch = None
        self._active_set_last_seen_epoch = None

        self.stats = {
            'frame': 0,
            'fps': 0.0,
            'bitrate': '',
            'out_time': '00:00:00',
            'mode': 'director',
            'view': self.current_view_mode,
            'view_policy': f"{self._current_policy} ({self.show_start_hour:02d}:00-{self.show_end_hour:02d}:00 stage)",
            'clip_buffer': str(self.ring_dir) if self.enable_clip_buffer else 'disabled',
            'active_set_start_epoch': None,
        }
        self.errors = []
        self._stop_event = threading.Event()

        self.token = token
        self.token_lock = threading.Lock()
        self.last_token_renew = time.monotonic()

        # P1/P3: Verify stage channel OSD provenance & auto-probe native 4K RTSP stream if unlocked on NVR
        self._high_res_rtsp_url = None
        self._high_res_ingest = False
        if self.ip and self.token:
            osd_live = nvr_get_channel_osd(self.ip, self.token, channel=int(cfg.get("nvr_channel", 0)))
            if osd_live:
                cfg = dict(cfg)
                cfg["verified_stage_osd"] = osd_live
            probed_url, is_hi = probe_stage_video_source(self.ip, self.token, cfg)
            if is_hi:
                self._high_res_rtsp_url = probed_url
                self._high_res_ingest = True

        default_out_w = 1920 if self._high_res_ingest else 1280
        default_out_h = 1080 if self._high_res_ingest else 720
        self.out_w = int(cfg.get("output_width", default_out_w))
        self.out_h = int(cfg.get("output_height", default_out_h))
        self.fps = cfg.get("output_fps", 15.0 if self._high_res_ingest else 10.0)
        out_scale = self.out_h / 720.0
        self.top_matte_h = cfg.get("top_matte_h", int(round(110 * out_scale)))
        refresh_hours = effective_refresh_hours(cfg)
        self.ticker = TickerOverlay(config_path="/home/joseph1/box2-stream/ticker.json", top_h=self.top_matte_h, refresh_hours=refresh_hours)
        self.countdown_overlay = ShowtimeCountdownOverlay(
            config_path="/home/joseph1/box2-stream/ticker.json",
            base_w=self.out_w,
            base_h=self.out_h,
            start_hour=self.show_start_hour,
            end_hour=self.show_end_hour,
        )
        self.chessheat_overlay = box2_chessheat.ChessHeatLiveOverlay(
            config_path="/home/joseph1/box2-stream/ticker.json",
            card_w=self.countdown_overlay.card_w,
            card_h=int(round(362 * out_scale)),
            x=self.countdown_overlay.x,
            y=int(round(148 * out_scale)),
        )
        self.wall_overlay = WallOverlay(config_path="/home/joseph1/box2-stream/ticker.json", base_w=self.out_w, base_h=self.out_h)
        self.caption_engine = box2_captions.LiveCaptionEngine(
            enabled=bool(cfg.get("live_captions_enabled", True)),
            model_name=str(cfg.get("asr_model", "base.en")),
            captions_log=self.clip_base / "captions.jsonl",
        )
        self.caption_overlay = box2_captions.LiveCaptionOverlay(
            engine=self.caption_engine,
            config_path="/home/joseph1/box2-stream/ticker.json",
            state_path=str(STATE),
            base_w=self.out_w,
            base_h=self.out_h,
        )

        cam2_getter = self.get_cam2_url if (self.ip and self.token) else cam2_url
        self.cam2_overlay = CameraFeedWallOverlay(cam2_getter, config_path="/home/joseph1/box2-stream/ticker.json", base_w=self.out_w, base_h=self.out_h) if (cam2_url or self.ip) else None

        initial_url = self.get_cam0_url() if (self.ip and self.token) else source
        self.cam_reader = PrimaryCameraReader(
            initial_url=initial_url,
            url_getter=(self.get_cam0_url if self.ip else (lambda: source)),
            on_reconnect=(self._renew_nvr_token if self.ip else None),
        )
        test_frame, _ = self.cam_reader.get_frame()
        src_h, src_w = test_frame.shape[:2]

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

        prof_path = "/usr/share/opencv4/haarcascades/haarcascade_profileface.xml"
        if not os.path.exists(prof_path):
            prof_path = cv2.data.haarcascades + "haarcascade_profileface.xml"
        self.profile_cascade = cv2.CascadeClassifier(prof_path) if os.path.exists(prof_path) else None

        self._empty_stage_gray = None
        self._torso_hold_started_mono = None
        self.max_torso_hold_seconds = float(cfg.get("max_torso_hold_seconds", 90.0))
        self.torso_diff_threshold = float(cfg.get("torso_diff_threshold", 18.0))

        framing_config = FramingConfig(
            canvas_width=src_w,
            canvas_height=src_h,
            target_face_fraction=cfg.get("target_face_fraction", 0.25),
            headroom_fraction=cfg.get("headroom_fraction", 0.55),
            max_zoom=cfg.get("max_zoom", 2.25),
            periodic_room_view_enabled=cfg.get("periodic_room_view_enabled", False),
            room_view_interval_s=cfg.get("room_view_interval_s", 90.0),
            room_view_duration_s=cfg.get("room_view_duration_s", 5.0),
            pacing_pullback_speed_threshold_px_s=cfg.get("pacing_pullback_speed_threshold_px_s", 0.0),
            pacing_pullback_factor=cfg.get("pacing_pullback_factor", 0.0),
            face_size_smoothing_tau=float(cfg.get("face_size_smoothing_tau", 5.0)),
            deadzone_x_px=cfg.get("deadzone_x_px", 18.0),
            deadzone_y_px=cfg.get("deadzone_y_px", 15.0),
            deadzone_zoom_px=cfg.get("deadzone_zoom_px", 58.0),
            smoothing_tau=cfg.get("smoothing_tau", 0.85),
            max_pan_speed_px_s=cfg.get("max_pan_speed_px_s", 140.0 * scale_x),
            max_tilt_speed_px_s=cfg.get("max_tilt_speed_px_s", 95.0 * scale_y),
            max_zoom_speed_px_s=cfg.get("max_zoom_speed_px_s", 55.0 * scale_x),
        )
        tracker = PerformerTracker(
            stage_polygon=self.stage_polygon,
            loss_hold_seconds=cfg.get("loss_hold_seconds", 14.0),
            base_match_radius_px=cfg.get("base_match_radius_px", 95.0 * scale_x),
            max_performer_speed_px_s=cfg.get("max_performer_speed_px_s", 260.0 * scale_x),
            allow_proximity_reacquisition=True,
            require_confirmation_after_loss=False,
            max_performer_y=float(floor_cutoff_y),
            exclusion_boxes=self.exclusion_boxes,
            acquisition_confirm_frames=int(cfg.get("acquisition_confirm_frames", 4)),
            acquisition_window_seconds=float(cfg.get("acquisition_window_seconds", 1.2)),
            reacquire_confirm_frames=int(cfg.get("reacquire_confirm_frames", 1)),
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

        # Start real-time local audio mixer (stage mic + auto-ducked show music -> local OS pipe)
        self.audio_mixer = BroadcastAudioMixer(
            cfg=cfg,
            ip=self.ip,
            cam0_url_getter=(self.get_cam0_flv_url if self.ip else (lambda: source)),
            view_getter=(lambda: self.current_view_mode),
            policy_getter=(lambda: self._current_policy),
            onstage_getter=(lambda: self._is_performer_framed),
            caption_engine=self.caption_engine,
            secrets=secrets,
        )

        # P2/#C/#I: Autonomous Shot Director, Optical Slew Concealer & Signal Integrity Monitor
        shot_cfg = ShotVocabularyConfig(
            enable_live_optical_shot_moves=bool(cfg.get("enable_live_optical_shot_moves", True)),
            optical_zoom_wide_pos=int(cfg.get("optical_zoom_wide_pos", 5)),
            optical_zoom_medium_pos=int(cfg.get("optical_zoom_medium_pos", 10)),
            optical_zoom_closeup_pos=int(cfg.get("optical_zoom_closeup_pos", 14)),
        )
        self.shot_director = ShotDirector(config=shot_cfg, canvas_width=src_w)
        self.slew_concealer = OpticalSlewConcealer()
        self.integrity_monitor = SignalIntegrityMonitor(
            policy=self.audio_mixer.audio_policy,
            integrity_log_path=self.clip_base / "integrity.jsonl",
        )
        self._active_optical_zoom_pos = shot_cfg.optical_zoom_wide_pos
        self._last_utterance_seen = 0
        self._last_visual_report = None
        self._last_visual_eval_mono = 0.0
        self._last_integrity_eval_mono = 0.0
        self._last_rendered_stage_frame = None

        default_br = "6000k" if self.out_w >= 1920 else "2500k"
        bitrate = cfg.get("bitrate_1080p", default_br) if self.out_w >= 1920 else cfg.get("bitrate", default_br)
        bufsize = "12000k" if self.out_w >= 1920 else "5000k"
        if self.enable_clip_buffer:
            tee_spec = (
                f"[f=flv:flvflags=no_duration_filesize]{target}|"
                f"[f=segment:onfail=ignore:segment_time={self.clip_seg_seconds}:"
                f"segment_wrap={self.clip_seg_wrap}:reset_timestamps=1:bsfs/v=dump_extra]"
                f"{self.ring_dir}/seg_%04d.ts"
            )
            output_args = ["-flags", "+global_header", "-f", "tee", tee_spec]
        else:
            output_args = ["-f", "flv", "-flvflags", "no_duration_filesize", target]

        self.proc = subprocess.Popen(
            [FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostats', '-progress', 'pipe:1',
             '-thread_queue_size', '256', '-probesize', '32768', '-analyzeduration', '0',
             '-f', 'rawvideo', '-vcodec', 'rawvideo',
             '-s', f'{self.out_w}x{self.out_h}',
             '-pix_fmt', 'bgr24',
             '-r', str(int(self.fps)),
             '-i', 'pipe:0',
             '-thread_queue_size', '512', '-probesize', '32768', '-analyzeduration', '0',
             '-f', 's16le', '-ar', '48000', '-ac', '2',
             '-i', f'pipe:{self.audio_mixer.read_fd}',
             '-map', '0:v:0',
             '-map', '1:a:0',
             '-r', '30',
             '-c:v', 'libx264',
             '-preset', 'veryfast',
             '-tune', 'zerolatency',
             '-threads', '4',
             '-g', '60', '-keyint_min', '60', '-sc_threshold', '0',
             '-b:v', bitrate,
             '-maxrate', bitrate,
             '-bufsize', bufsize,
             '-pix_fmt', 'yuv420p',
             '-c:a', 'aac',
             '-b:a', '128k',
             '-ar', '48000',
             '-ac', '2',
             *output_args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            pass_fds=(self.audio_mixer.read_fd,), start_new_session=True)

        # Parent closes its duplicate of read_fd now that FFmpeg child owns it
        try:
            os.close(self.audio_mixer.read_fd)
        except OSError:
            pass

        self.last_progress = time.monotonic()
        if self.ip and self.token:
            init_preset = self.privacy_preset_id if self.current_view_mode == 'privacy' else self.stage_preset_id
            def _init_cam_hw():
                nvr_goto_preset(self.ip, self.get_token(), init_preset)
                if self.current_view_mode == 'stage':
                    nvr_configure_stage_optics(self.ip, self.get_token(), channel=int(self.cfg.get('nvr_channel', 0)))
            threading.Thread(target=_init_cam_hw, daemon=True).start()
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
            cx1 = int(p_cfg.get("crop_x1", 0))
            cy1 = int(p_cfg.get("crop_y1", 54))
            cx2 = int(p_cfg.get("crop_x2", 356))
            cy2 = int(p_cfg.get("crop_y2", 224))
            x1, y1, x2, y2 = int(cx1 * sx), int(cy1 * sy), int(cx2 * sx), int(cy2 * sy)
            sub = src_frame[max(0, y1):min(self.src_h, y2), max(0, x1):min(self.src_w, x2)].copy()
            sw = sub.shape[1]
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

    def get_cam0_flv_url(self):
        token = self.get_token()
        if self.ip and token:
            return flv_url(self.ip, token, self.cfg)
        return None

    def get_cam0_url(self):
        if self._high_res_rtsp_url:
            return self._high_res_rtsp_url
        return self.get_cam0_flv_url()

    def get_cam2_url(self):
        token = self.get_token()
        if self.ip and token:
            return flv_url_ch(self.ip, token, 1, 'sub')
        return None

    def _renew_nvr_token(self):
        if not self.ip:
            return
        try:
            new_token = nvr_login(self.ip, self.cfg)
            with self.token_lock:
                self.token = new_token
                self.last_token_renew = time.monotonic()
            log("Stage Director: renewed NVR session token for camera recovery")
        except Exception as exc:
            log(f"Stage Director token renewal warning: {scrub(str(exc), self.secrets)}")

    def _keepalive_worker(self):
        """Active NVR session heartbeat and proactive token renewal every 30m."""
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
                self._renew_nvr_token()

    def _update_set_tracker(self, is_onstage, force_close=False):
        now_ts = time.time()
        if is_onstage and not force_close:
            if self._active_set_start_epoch is None:
                self._active_set_start_epoch = now_ts
                log("Stage Director: performer onstage session started (auto-clip tracking active)")
            self._active_set_last_seen_epoch = now_ts
            self.stats["active_set_start_epoch"] = round(self._active_set_start_epoch, 2)
        elif self._active_set_start_epoch is not None:
            last_seen = self._active_set_last_seen_epoch or now_ts
            if force_close or (now_ts - last_seen >= self.SET_GRACE_SECONDS):
                dur = last_seen - self._active_set_start_epoch
                if dur >= self.MIN_SET_SECONDS and self.enable_clip_buffer:
                    entry = record_set_event(self.sets_file, self._active_set_start_epoch, last_seen, event_type="auto_set")
                    log(f"Stage Director: logged {entry['duration_s']}s onstage set ({entry['start_local']} - {entry['end_local']})")
                self._active_set_start_epoch = None
                self._active_set_last_seen_epoch = None
                self.stats["active_set_start_epoch"] = None

    def ensure_session(self, now_utc, cur_mono):
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
        proposal = None

        try:
            while not self._stop_event.is_set() and self.proc.poll() is None:
                loop_start = time.monotonic()
                frame, is_fresh = self.cam_reader.get_frame()
                if frame is None:
                    frame = np.zeros((self.src_h, self.src_w, 3), dtype=np.uint8)

                cur_mono = time.monotonic()
                cur_utc = datetime.now(timezone.utc)
                self.ensure_session(cur_utc, cur_mono)

                # Poll desired view mode & marathon/VOD cadence every 0.5s with zero stream drops
                if cur_mono - self._last_view_check >= 0.5:
                    self._last_view_check = cur_mono
                    self.ticker.set_refresh_hours(effective_refresh_hours(self.cfg))
                    pol = view_policy()
                    self._current_policy = pol
                    target_view = desired_view(start_hour=self.show_start_hour, end_hour=self.show_end_hour)
                    self.stats['view_policy'] = f"{pol} ({self.show_start_hour:02d}:00-{self.show_end_hour:02d}:00 stage)"
                    if target_view != self.current_view_mode:
                        log(f"Stage Director view transition: {self.current_view_mode} -> {target_view}")
                        if target_view == "privacy":
                            self._is_performer_framed = False
                            self._update_set_tracker(False, force_close=True)
                            self._held_canvas = self._render_stage_box2_fallback(frame)
                            self._ptz_slew_until = cur_mono + 2.8
                            if self.ip:
                                threading.Thread(
                                    target=nvr_goto_preset,
                                    args=(self.ip, self.get_token(), self.privacy_preset_id),
                                    kwargs={"settle_confirm": True},
                                    daemon=True,
                                ).start()
                        else:
                            self._held_canvas = self._render_privacy_canvas(frame)
                            self._ptz_slew_until = cur_mono + 2.8
                            self._empty_stage_gray = None
                            self._torso_hold_started_mono = None
                            self._active_optical_zoom_pos = self.shot_director.config.optical_zoom_wide_pos
                            self.shot_director.reset(monotonic_seconds=cur_mono)
                            self.adapter.framing.reset(monotonic_seconds=cur_mono)
                            self.adapter.tracker.enable()
                            if self.ip:
                                def _enter_stage_hw():
                                    nvr_goto_preset(self.ip, self.get_token(), self.stage_preset_id)
                                    nvr_configure_stage_optics(self.ip, self.get_token(), channel=int(self.cfg.get('nvr_channel', 0)))
                                threading.Thread(target=_enter_stage_hw, daemon=True).start()
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
                    self._is_performer_framed = False
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
                    if is_fresh:
                        if (self.src_w, self.src_h) == (640, 360):
                            det_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                            sx = 1.0
                            sy = 1.0
                        else:
                            det_frame = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR)
                            det_gray = cv2.cvtColor(det_frame, cv2.COLOR_BGR2GRAY)
                            sx = self.src_w / 640.0
                            sy = self.src_h / 360.0

                        # Scale Haar maxSize dynamically with optical zoom so close-up faces (up to 150px) stay locked
                        if self._active_optical_zoom_pos <= 6:
                            max_face_640 = 62
                        elif self._active_optical_zoom_pos <= 12:
                            max_face_640 = 110
                        else:
                            max_face_640 = 158
                        check_right_wall_exclusion = (self._active_optical_zoom_pos <= 8)

                        raw_faces = self.face_cascade.detectMultiScale(
                            det_gray, scaleFactor=1.15, minNeighbors=4, minSize=(22, 22), maxSize=(max_face_640, max_face_640)
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
                                and (not check_right_wall_exclusion or not self.adapter.tracker._is_excluded(bbox))
                                and self.stage_polygon.contains_box(bbox)
                            ):
                                candidate_boxes.append(bbox)
                                onstage_count += 1

                        # Active Performer Continuity Fallbacks (solves zoom-out drops when looking down at notes,
                        # holding mic over mouth/beard, or turning head in profile):
                        anchor = self.adapter.tracker._held_subject or self.adapter.tracker.active_subject
                        is_locked_state = self.adapter.tracker.state.value in ("tracking", "holding")

                        # 1) Local ROI profile-face check (~3ms) when frontal cascade misses an active performer
                        if not candidate_boxes and is_locked_state and anchor is not None and self.profile_cascade is not None:
                            ax, ay = int(anchor.center_x / sx), int(anchor.center_y / sy)
                            rx1, ry1 = max(0, ax - 95), max(0, ay - 85)
                            rx2, ry2 = min(640, ax + 95), min(360, ay + 85)
                            roi_g = det_gray[ry1:ry2, rx1:rx2]
                            if roi_g.shape[0] >= 36 and roi_g.shape[1] >= 36:
                                p_faces = self.profile_cascade.detectMultiScale(
                                    roi_g, scaleFactor=1.15, minNeighbors=4, minSize=(22, 22), maxSize=(max_face_640, max_face_640)
                                )
                                if len(p_faces) == 0:
                                    roi_flip = cv2.flip(roi_g, 1)
                                    p_flip = self.profile_cascade.detectMultiScale(
                                        roi_flip, scaleFactor=1.15, minNeighbors=4, minSize=(22, 22), maxSize=(max_face_640, max_face_640)
                                    )
                                    if len(p_flip) > 0:
                                        fx_f, fy_f, fw_f, fh_f = p_flip[0]
                                        p_faces = [(roi_g.shape[1] - fx_f - fw_f, fy_f, fw_f, fh_f)]
                                for (pfx, pfy, pfw, pfh) in p_faces[:1]:
                                    pbbox = BoundingBox(
                                        x=float((rx1 + pfx) * sx),
                                        y=float((ry1 + pfy) * sy),
                                        width=float(pfw * sx),
                                        height=float(pfh * sy),
                                    )
                                    if (
                                        pbbox.center_y <= self.floor_cutoff_y
                                        and (not check_right_wall_exclusion or not self.adapter.tracker._is_excluded(pbbox))
                                        and self.stage_polygon.contains_box(pbbox)
                                    ):
                                        candidate_boxes.append(pbbox)
                                        onstage_count += 1

                        # 2) Empty-stage reference update & Torso Presence Anchor Hold:
                        # Never zoom out to wide room shot while performer's body is still occupying the stage spot!
                        if not is_locked_state and not candidate_boxes and cur_mono > self._ptz_slew_until + 2.0:
                            if self._empty_stage_gray is None or self._empty_stage_gray.shape != det_gray.shape:
                                self._empty_stage_gray = det_gray.astype(np.float32)
                            else:
                                # Slowly adapt empty-stage background to gradual room lighting changes
                                self._empty_stage_gray = 0.98 * self._empty_stage_gray + 0.02 * det_gray.astype(np.float32)
                            self._torso_hold_started_mono = None
                        elif candidate_boxes:
                            self._torso_hold_started_mono = None
                        elif is_locked_state and anchor is not None and self._empty_stage_gray is not None:
                            tx1 = max(12, int((anchor.center_x / sx) - 44))
                            tx2 = min(512, int((anchor.center_x / sx) + 44))
                            ty1 = max(24, int((anchor.bottom / sy)))
                            ty2 = min(int(self.floor_cutoff_y / sy), ty1 + 92)
                            if tx2 > tx1 + 16 and ty2 > ty1 + 16:
                                torso_diff = float(np.mean(np.abs(
                                    det_gray[ty1:ty2, tx1:tx2].astype(np.float32) - self._empty_stage_gray[ty1:ty2, tx1:tx2]
                                )))
                                if torso_diff >= self.torso_diff_threshold:
                                    if self._torso_hold_started_mono is None:
                                        self._torso_hold_started_mono = cur_mono
                                    if (cur_mono - self._torso_hold_started_mono) <= self.max_torso_hold_seconds:
                                        # Performer torso is still right there (e.g. reading phone notes / mic occlusion): hold lock!
                                        candidate_boxes.append(anchor)
                                        onstage_count = 1
                                else:
                                    self._torso_hold_started_mono = None

                        if self.adapter.tracker.state.value == "ambiguous" and candidate_boxes:
                            primary = max(candidate_boxes, key=lambda b: b.area)
                            if self.adapter.tracker._check_acquisition_persistence(primary, cur_mono):
                                self.adapter.confirm_subject(primary, cur_mono)

                        proposal = self.adapter.process_frame(candidate_boxes, cur_utc, cur_mono)

                        # #I Visual Quality + P2 Autonomous Shot Direction
                        active_face = self.adapter.tracker.active_subject or self.adapter.tracker._held_subject
                        if self.slew_concealer.is_active or (cur_mono - self._last_visual_eval_mono >= 0.5):
                            self._last_visual_eval_mono = cur_mono
                            face_640 = (
                                BoundingBox(active_face.x / sx, active_face.y / sy, active_face.width / sx, active_face.height / sy)
                                if active_face is not None
                                else None
                            )
                            self._last_visual_report = measure_visual_quality(det_gray, face_box=face_640)

                        cap_snap = self.caption_engine.get_snapshot()
                        utt_committed = bool(cap_snap.is_final and cap_snap.utterance_id > 0 and cap_snap.utterance_id != self._last_utterance_seen)
                        if utt_committed:
                            self._last_utterance_seen = cap_snap.utterance_id
                        speech_age = (cur_mono - cap_snap.last_speech_mono) if cap_snap.last_speech_mono > 0.0 else 99.0

                        directive = self.shot_director.step(
                            monotonic_seconds=cur_mono,
                            tracking_state=proposal.tracking_state,
                            face_box=active_face,
                            is_speaking=bool(self.audio_mixer.stats.get("voice_ducking", False)),
                            recent_speech_age_s=speech_age,
                            utterance_just_committed=utt_committed,
                        )
                        self.adapter.framing.set_shot_framing(
                            target_face_fraction=directive.target_face_fraction,
                            headroom_fraction=directive.target_headroom_fraction,
                        )
                        if directive.request_optical_move and self.ip:
                            self._active_optical_zoom_pos = directive.desired_optical_zoom_pos
                            # Reset empty-stage background when optical zoom changes field of view
                            self._empty_stage_gray = None
                            self.slew_concealer.notify_optical_move_started(self._last_rendered_stage_frame, cur_mono)
                            log(
                                f"Stage Director P2 shot: {directive.shot.value} ({directive.reason}) "
                                f"-> optical zoom.pos={directive.desired_optical_zoom_pos} (#C conceal active)"
                            )
                            threading.Thread(
                                target=nvr_set_zoom_pos,
                                args=(self.ip, self.get_token(), directive.desired_optical_zoom_pos, int(self.cfg.get('nvr_channel', 0))),
                                daemon=True,
                            ).start()
                        self.stats['shot'] = directive.shot.value
                        self.stats['shot_reason'] = directive.reason
                        self.stats['optical_zoom_pos'] = self._active_optical_zoom_pos

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

                    # #C Conceal optical zoom & autofocus hunting until Laplacian sharpness settles
                    cur_sharp = self._last_visual_report.focus_sharpness if self._last_visual_report else 40.0
                    if self.slew_concealer.is_active:
                        rendered = self.slew_concealer.blend_if_concealing(rendered, cur_sharp, cur_mono)
                    else:
                        self._last_rendered_stage_frame = rendered.copy()
                    self.stats['slew_concealing'] = self.slew_concealer.is_active

                    zoom_factor = (proposal.framing or {}).get("zoom_factor", 1.0)
                    is_performer_framed = (
                        proposal.tracking_state in ("tracking", "holding")
                        or zoom_factor > 1.15
                        or self._active_optical_zoom_pos > self.shot_director.config.optical_zoom_wide_pos
                    )
                    self._is_performer_framed = is_performer_framed
                    self._update_set_tracker(is_performer_framed)

                    if self.cam2_overlay is not None and self.cam2_overlay.enabled:
                        self.cam2_overlay.draw(rendered, is_performer_framed=is_performer_framed)
                    else:
                        self.wall_overlay.draw(rendered, is_performer_framed=is_performer_framed)

                    # Big punchy live stand-up captions at bottom-center (only when performer is onstage)
                    self.caption_overlay.draw(rendered, is_performer_framed=is_performer_framed, now_mono=cur_mono)

                if self.current_view_mode == "privacy":
                    self.countdown_overlay.draw(rendered, standby_mode=True, top_matte_h=self.top_matte_h)
                    self.chessheat_overlay.x = self.countdown_overlay.x
                    self.chessheat_overlay.draw(rendered, standby_mode=True, top_matte_h=self.top_matte_h)

                if self.top_matte_h > 0:
                    # Only push sponsor break alerts into scrolling ticker text; song titles display in the dedicated tab below!
                    banner_override = self.audio_mixer.stats.get("now_playing_banner", "") if self.audio_mixer.stats.get("ad_shield_active") else ""
                    self.ticker.set_live_banner(banner_override)
                    self.ticker.draw(rendered, standby_mode=(self.current_view_mode == "privacy"))
                    self.ticker.draw_now_playing_tab(rendered, self.audio_mixer.stats)

                self.stats.update(self.audio_mixer.stats)
                self.stats.update(self.caption_engine.stats)

                # #I Continuous Signal Integrity evaluation (1 Hz)
                if cur_mono - self._last_integrity_eval_mono >= 1.0:
                    self._last_integrity_eval_mono = cur_mono
                    self.integrity_monitor.update_speech_rms(
                        self.audio_mixer._raw_pre_mix_dbfs,
                        is_onstage=self._is_performer_framed,
                    )
                    with self.audio_mixer._mic_lock:
                        mic_q_ms = max(0.0, (len(self.audio_mixer._mic_queue) - 2) * 50.0)
                    cap_snap_i = self.caption_engine.get_snapshot()
                    asr_lag = max(0.0, (cur_mono - cap_snap_i.updated_mono) * 1000.0) if (self._is_performer_framed and cap_snap_i.updated_mono > 0) else 0.0
                    sig_snap = self.integrity_monitor.evaluate(
                        now_epoch=time.time(),
                        now_mono=cur_mono,
                        camera_verified=bool(is_fresh),
                        camera_source_id=f"nvr://{self.ip or 'local'}/ch{int(self.cfg.get('nvr_channel', 0))} ({self.src_w}x{self.src_h})",
                        video_fresh=bool(is_fresh),
                        audio_verdict=self.audio_mixer.mic_verdict,
                        visual_report=self._last_visual_report,
                        av_drift_ms=mic_q_ms,
                        asr_lag_ms=min(2500.0, asr_lag),
                        pre_mix_speech_isolated=True,
                    )
                    self.stats['signal_integrity'] = {
                        'status': sig_snap.status_code,
                        'camera_source': sig_snap.camera_source_id,
                        'mic_source': sig_snap.mic_source_id,
                        'mic_verified': sig_snap.mic_verified,
                        'pre_mix_isolated': sig_snap.pre_mix_speech_isolated,
                        'focus_sharpness': sig_snap.focus_sharpness,
                        'face_luma': sig_snap.face_luma,
                        'jukebox_luma': sig_snap.jukebox_luma,
                        'speech_snr_db': sig_snap.speech_snr_db,
                        'av_drift_ms': sig_snap.av_drift_ms,
                        'mic_interruptions': sig_snap.mic_interruption_count,
                    }

                try:
                    self.proc.stdin.write(rendered.tobytes())
                    self.proc.stdin.flush()
                    self.last_progress = time.monotonic()
                except (BrokenPipeError, OSError, ValueError):
                    break

                elapsed = time.monotonic() - loop_start
                sleep_needed = frame_interval - elapsed
                if sleep_needed > 0.002:
                    time.sleep(sleep_needed)
        finally:
            self._update_set_tracker(False, force_close=True)
            self.cam_reader.stop()
            self.audio_mixer.stop()
            self.caption_engine.stop()
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
        self.cam_reader.stop()
        self.audio_mixer.stop()
        self.caption_engine.stop()
        self.chessheat_overlay.stop()
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
                    backoff = 3

                refresh_hours = effective_refresh_hours(cfg)
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
                next_ref_str = next_ref.strftime('%Y-%m-%d %I:%M:%S %p') if next_ref else 'marathon (uninterrupted)'
                write_json(STATUS, {
                    **status,
                    **stream.stats,
                    'stream_cadence': 'marathon' if refresh_hours <= 0 else f'vod-{refresh_hours}h',
                    'next_scheduled_refresh': next_ref_str,
                    'updated': now(),
                })
                stop.wait(1)

            if scheduled_rollover:
                stream.stop()
                status.update(last_error=None)
                stop.wait(7)
                continue

            if stream.proc.poll() is not None and desired() == mode and not stop.is_set():
                raise RuntimeError('ffmpeg exited: ' + (stream.errors[-1] if stream.errors else f'code {stream.proc.returncode}'))
        except Exception as exc:
            status.update(state='recovering', last_error=scrub(str(exc), secrets + ([token] if token else [])),
                          restarts=status['restarts'] + 1)
            wait_s = max(backoff, 6)
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


def _handle_music_cli(args):
    st = read_state()
    m_cfg = dict(st.get('music', {})) if isinstance(st.get('music'), dict) else {}
    sub = args[0].lower() if args else 'status'

    if sub in ('on', 'play', 'start'):
        m_cfg['mode'] = 'on'
        update_state(music=m_cfg)
        print(f"Music ON (playing from {DEFAULT_MUSIC_DIR} with automatic voice & stage ducking).")
    elif sub in ('off', 'stop', 'mute'):
        m_cfg['mode'] = 'off'
        update_state(music=m_cfg)
        print("Music OFF (smooth fade out; stage mic stays live).")
    elif sub == 'auto':
        m_cfg['mode'] = 'auto'
        update_state(music=m_cfg)
        print("Music AUTO (plays 24/7 in standby — prioritizing YurrMom.Com Spotify to cover room dead air — and auto-ducks during 9PM-2AM stage sets; quiet only during rehearsal).")
    elif sub in ('next', 'skip'):
        m_cfg['skip_seq'] = int(m_cfg.get('skip_seq', 0)) + 1
        update_state(music=m_cfg)
        print("Skipping to next track in playlist.")
    elif sub in ('undertone', 'bed', 'walkup'):
        m_cfg['onstage_mode'] = sub
        update_state(music=m_cfg)
        desc = {
            'undertone': "live Spotify / YurrMom.Com songs stay audible underneath comedian (0.18 gain, 0.11 + vocal-pocket EQ when speaking)",
            'bed': "crossfades into instrumental Stage Groove bed during onstage sets",
            'walkup': "8-second walk-up intro when taking stage, then fades to 0.0 for dry set",
        }[sub]
        print(f"Onstage music mix mode set to '{sub}': {desc}.")
    elif sub in ('onstage-vol', 'undertone-vol') and len(args) >= 2:
        vol = max(0.0, min(1.0, float(args[1])))
        m_cfg['onstage_volume'] = vol
        m_cfg['onstage_speech_volume'] = round(vol * 0.62, 3)
        update_state(music=m_cfg)
        print(f"Onstage undertone volume set to {vol:.2f} (tucks to {m_cfg['onstage_speech_volume']:.2f} during speech).")
    elif sub in ('vol', 'volume') and len(args) >= 2:
        vol = max(0.0, min(1.0, float(args[1])))
        m_cfg['idle_volume'] = vol
        update_state(music=m_cfg)
        print(f"Idle music volume set to {vol:.2f} (auto-ducks when speaking/onstage).")
    else:
        tracks = sorted([p.name for p in DEFAULT_MUSIC_DIR.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]) if DEFAULT_MUSIC_DIR.exists() else []
        ads = sorted([p.name for p in DEFAULT_ADS_DIR.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]) if DEFAULT_ADS_DIR.exists() else []
        print(json.dumps({
            "music_state": m_cfg,
            "dj_state": st.get("dj", {}),
            "music_dir": str(DEFAULT_MUSIC_DIR),
            "tracks_available": tracks,
            "ads_dir": str(DEFAULT_ADS_DIR),
            "ads_available": ads,
        }, indent=2))


def _handle_dj_cli(args):
    st = read_state()
    dj_cfg = dict(st.get('dj', {})) if isinstance(st.get('dj'), dict) else {}
    sub = args[0].lower() if args else 'status'

    if sub in ('launch', 'open', 'browsers'):
        target = args[1].lower() if len(args) >= 2 else 'both'
        launched = box2_radio.launch_dj_browsers(target=target)
        print(json.dumps({
            "pipewire_sink": box2_radio.DJ_BUS_SINK,
            "browsers": launched,
            "note": "Sign into Suno & Spotify Free once on the Jetson desktop and hit Play; BOX 2 auto-rotates & swaps ads with /mnt/ssd/media/box2-ads/.",
        }, indent=2))
    elif sub == 'rotate':
        if len(args) >= 2:
            dj_cfg['suno_tracks'] = max(1, int(args[1]))
        if len(args) >= 3:
            dj_cfg['spotify_tracks'] = max(1, int(args[2]))
        dj_cfg['mode'] = 'rotate'
        update_state(dj=dj_cfg)
        sn = dj_cfg.get('suno_tracks', 3)
        sp = dj_cfg.get('spotify_tracks', 3)
        print(f"DJ Rotation ON: Alternating {sn} Suno Discover songs -> {sp} YurrMom.Com Spotify songs (Spotify ads auto-swapped with {DEFAULT_ADS_DIR}).")
    elif sub in ('suno', 'spotify', 'house', 'beds'):
        dj_cfg['mode'] = sub
        update_state(dj=dj_cfg)
        print(f"DJ source pinned to '{sub}'.")
    elif sub in ('ad-every', 'ads-every', 'ad-schedule') and len(args) >= 2:
        raw_v = str(args[1]).strip().lower()
        mins = 0.0 if raw_v in ('0', 'off', 'none', 'disable', 'disabled') else max(1.0, float(raw_v))
        dj_cfg['ad_interval_minutes'] = mins
        update_state(dj=dj_cfg)
        if mins <= 0.0:
            print("Scheduled house ads OFF (only manual `dj ad-now` or ad-shield swaps will play).")
        else:
            print(f"Scheduled house ads ON: 1 promo from {DEFAULT_ADS_DIR} every {mins:g} min (auto-deferred if a comedian is on stage).")
    elif sub in ('ad-now', 'run-ad', 'play-ad'):
        dj_cfg['ad_now_seq'] = int(dj_cfg.get('ad_now_seq', 0)) + 1
        update_state(dj=dj_cfg)
        print(f"Queued immediate house promo spot from {DEFAULT_ADS_DIR}!")
    elif sub in ('test-ad', 'ad-test'):
        secs = float(args[1]) if len(args) >= 2 else 15.0
        dj_cfg['test_ad_until_epoch'] = round(time.time() + max(3.0, secs), 2)
        update_state(dj=dj_cfg)
        print(f"Simulating {int(secs)}s ad-break takeover: playing {DEFAULT_ADS_DIR} over Twitch stream while muting DJ bus!")
    elif sub == 'skip-ad':
        dj_cfg['ad_skip_seq'] = int(dj_cfg.get('ad_skip_seq', 0)) + 1
        update_state(dj=dj_cfg)
        print("Skipped current promo spot in box2-ads.")
    else:
        ctrl = box2_radio.MprisRadioController()
        players = ctrl.list_players()
        ls_ready, _ = box2_radio.poll_librespot_status()
        ads = sorted([p.name for p in DEFAULT_ADS_DIR.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]) if DEFAULT_ADS_DIR.exists() else []
        print(json.dumps({
            "dj_config": dj_cfg,
            "pipewire_bus_ready": box2_radio.ensure_pipewire_dj_bus(),
            "spotify_connect_speaker": {
                "device_name": "BOX 2 Stream",
                "daemon_listening": ls_ready,
                "how_to_connect": "Open Spotify on your phone or Mac -> Devices icon -> select 'BOX 2 Stream'",
            },
            "spotify_artist_url": box2_radio.SPOTIFY_ARTIST_URL,
            "suno_discover_url": box2_radio.SUNO_DISCOVER_URL,
            "detected_mpris_players": {
                role: {
                    "bus_name": p.bus_name,
                    "status": p.playback_status,
                    "title": p.title,
                    "artist": p.artist,
                    "pid": p.pid,
                }
                for role, p in players.items()
            },
            "ads_dir": str(DEFAULT_ADS_DIR),
            "ads_available": ads,
        }, indent=2))


def _handle_joke_cli(args):
    sub = args[0].lower() if args else 'list'
    cur = load_jokes_data(JOKES_FILE)
    jokes = list(cur.get('jokes', []))

    if sub == 'add' and len(args) >= 2:
        new_joke = " ".join(args[1:]).strip()
        if new_joke:
            jokes.insert(0, new_joke)
            cur['jokes'] = jokes
            write_json(JOKES_FILE, cur)
            print(f"Added joke #1 (now live on stream & ticker within 2s): {new_joke}")
    elif sub in ('remove', 'rm', 'del') and len(args) >= 2:
        idx = int(args[1]) - 1
        if 0 <= idx < len(jokes):
            removed = jokes.pop(idx)
            cur['jokes'] = jokes
            write_json(JOKES_FILE, cur)
            print(f"Removed joke #{idx + 1}: {removed}")
        else:
            print(f"Invalid joke index {idx + 1} (1..{len(jokes)}).")
    else:
        print(json.dumps({
            "jokes_file": str(JOKES_FILE),
            "seasonal_greeting": cur.get("seasonal_greeting", ""),
            "count": len(jokes),
            "jokes": [f"{i + 1}. {j}" for i, j in enumerate(jokes)],
        }, indent=2))


def _handle_captions_cli(args):
    st = read_state()
    cc = dict(st.get('captions', {})) if isinstance(st.get('captions'), dict) else {}
    sub = args[0].lower() if args else 'status'
    if sub in ('on', 'enable', 'start'):
        cc['enabled'] = True
        update_state(captions=cc)
        print("Live onstage stand-up captions ON (bottom-center punchy overlay + automatic .srt export on clips).")
    elif sub in ('off', 'disable', 'stop'):
        cc['enabled'] = False
        update_state(captions=cc)
        print("Live onstage stand-up captions OFF (hot-reloaded with zero stream drop).")
    elif sub == 'transcribe' and len(args) >= 2:
        src_mp4 = Path(args[1]).expanduser()
        srt_p = box2_captions.transcribe_media_to_srt(src_mp4, ffmpeg_bin=FFMPEG)
        if srt_p is None:
            raise SystemExit(f"Could not transcribe {src_mp4} (check file path and faster-whisper installation).")
        print(json.dumps({"mp4": str(src_mp4), "srt": str(srt_p), "bytes": srt_p.stat().st_size}, indent=2))
    else:
        live_st = {}
        if STATUS.exists():
            try:
                live_st = json.loads(STATUS.read_text())
            except Exception:
                pass
        print(json.dumps({
            "captions_enabled": cc.get("enabled", True),
            "captions_engine": live_st.get("captions_engine", "ready"),
            "last_caption": live_st.get("last_caption", ""),
            "captions_log": str(DEFAULT_CLIP_BASE / "captions.jsonl"),
        }, indent=2))


def _handle_theme_cli(args):
    theme = normalize_seasonal_theme(args[0] if args else 'black_friday')
    tk_path = HOME / 'ticker.json'
    tk = {}
    if tk_path.exists():
        try:
            tk = json.loads(tk_path.read_text())
        except Exception:
            tk = {}
    tk['seasonal_theme'] = theme
    write_json(tk_path, tk)
    print(f"Broadcast seasonal theme set to '{theme}' (live hot-reload in <=2s, zero stream drop).")


def _handle_clips_list():
    sets_file = DEFAULT_CLIP_BASE / "sets.jsonl"
    saved_dir = DEFAULT_CLIP_BASE / "saved"
    ring_dir = DEFAULT_CLIP_BASE / "ring"
    recent_sets = load_recent_sets(sets_file, limit=10)
    saved = []
    if saved_dir.exists():
        for p in sorted(saved_dir.glob("*.mp4"))[-15:]:
            st = p.stat()
            saved.append({
                "file": str(p),
                "size_mb": round(st.st_size / (1024 * 1024), 2),
                "created": datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %I:%M:%S %p'),
            })
    ring_count = len(list(ring_dir.glob("seg_*.ts"))) if ring_dir.exists() else 0
    print(json.dumps({
        "ring_buffer_segments": ring_count,
        "approx_ring_history_minutes": round(ring_count * 15.0 / 60.0, 1),
        "recent_onstage_sets": recent_sets,
        "saved_clips": saved,
    }, indent=2))


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'status'
    cur_desired = desired()
    live_desired = cur_desired if cur_desired in ('on', 'test') else 'on'

    if command in ('on', 'test', 'off'):
        update_state(desired=command, view='auto', view_until=None)
        print({'on': 'Going live (uninterrupted marathon + 9PM-2AM stage schedule): streaming to Twitch.',
               'test': 'Twitch bandwidth test: the Orin streams to Twitch without going live.',
               'off': 'Stream off.'}[command])
    elif command in ('auto', 'done'):
        update_state(desired=live_desired, view='auto', view_until=None)
        cur_v = desired_view()
        print(f'Auto schedule ON (Stage Director 9:00 PM - 2:00 AM EST, Privacy Standby 2:00 AM - 9:00 PM EST). Current active view: {cur_v}.')
    elif command in ('privacy', 'standby', 'brb'):
        update_state(desired=live_desired, view='privacy', view_until=None)
        print('Manual override: Privacy placeholder ON (Box 2 wall sign + bottom-left parking lot). Run "box2-stream auto" to resume 9PM-2AM schedule.')
    elif command == 'stage':
        update_state(desired=live_desired, view='stage', view_until=None)
        print('Manual override: Stage view ON (Preset 16 + Stage Director). Run "box2-stream auto" to resume 9PM-2AM schedule.')
    elif command == 'rehearse':
        mins = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
        until_ts = time.time() + max(5.0, mins * 60.0)
        until_str = datetime.fromtimestamp(until_ts).strftime('%I:%M %p').lstrip('0')
        update_state(desired=live_desired, view='rehearse', view_until=until_ts, manual_set_start_epoch=time.time())
        print(f'Rehearsal mode ON: Camera switched to Stage Active (Preset 16 + Stage Director, background music quiet) until {until_str} — zero stream drop! Run "box2-stream clip" after a run-through or "box2-stream done" when finished.')
    elif command == 'showtime':
        st = read_state()
        m_cfg = dict(st.get('music', {})) if isinstance(st.get('music'), dict) else {}
        if m_cfg.get('mode') == 'off':
            m_cfg['mode'] = 'auto'
        update_state(desired=live_desired, view='stage', view_until=None, music=m_cfg)
        print('SHOWTIME ON: Stage camera active + warm-up music playing with smart auto-ducking whenever you take the stage or speak into the mic!')
    elif command == 'marathon':
        update_state(cadence='marathon')
        print('Marathon mode ON: Uninterrupted continuous stream (3-hour VOD drops disabled; 12-hour SSD rolling clip buffer active).')
    elif command in ('vod', 'vod-mode'):
        update_state(cadence='vod')
        print('VOD mode ON: Stream will briefly refresh every 3 hours at the top of the hour for Twitch VOD archiving.')
    elif command == 'music':
        _handle_music_cli(sys.argv[2:])
    elif command in ('sync-catalog', 'sync-music'):
        import sync_yurrmom_previews
        print(json.dumps(sync_yurrmom_previews.sync_catalog(DEFAULT_MUSIC_DIR), indent=2))
    elif command == 'dj':
        _handle_dj_cli(sys.argv[2:])
    elif command in ('joke', 'jokes'):
        _handle_joke_cli(sys.argv[2:])
    elif command == 'theme':
        _handle_theme_cli(sys.argv[2:])
    elif command in ('captions', 'caption', 'subtitles'):
        _handle_captions_cli(sys.argv[2:])
    elif command in ('integrity', 'signal', 'cinematography'):
        live_st = json.loads(STATUS.read_text()) if STATUS.exists() else {}
        print(json.dumps({
            "state": live_st.get("state"),
            "view": live_st.get("view"),
            "shot": live_st.get("shot", "wide"),
            "shot_reason": live_st.get("shot_reason", ""),
            "optical_zoom_pos": live_st.get("optical_zoom_pos", 5),
            "slew_concealing": live_st.get("slew_concealing", False),
            "signal_integrity": live_st.get("signal_integrity", {}),
        }, indent=2))
    elif command == 'mark-set':
        update_state(manual_set_start_epoch=time.time())
        print(f'Set start marker recorded at {now()}. Run "box2-stream clip [label]" right after your set!')
    elif command == 'clip':
        arg1 = sys.argv[2] if len(sys.argv) > 2 else None
        arg2 = sys.argv[3] if len(sys.argv) > 3 else None
        # Allow `box2-stream clip my_set_name` (single non-duration label) -> clips --last-set with label!
        if arg1 and arg2 is None and arg1 not in ('--last-set', 'last-set', 'set'):
            try:
                parse_duration_seconds(arg1)
                dur_arg, lbl_arg = arg1, None
            except ValueError:
                dur_arg, lbl_arg = '--last-set', arg1
        else:
            dur_arg, lbl_arg = arg1, arg2
        info = extract_clip(duration_or_mode=dur_arg, label=lbl_arg)
        print(json.dumps(info, indent=2))
    elif command == 'clips':
        _handle_clips_list()
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
