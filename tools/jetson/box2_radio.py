#!/usr/bin/env python3
"""BOX 2 Broadcast Radio & Ad-Swap Engine (Suno Discover + YurrMom.Com Spotify + House Ads).

Routes isolated PipeWire browser profiles (`box2-suno` and `box2-spotify`) into the virtual
`box2_dj_bus` null-sink, monitors live track/artist metadata over Linux DBus (MPRIS2),
rotates blocks between Suno Discover and YurrMom.Com on Spotify Free, and automatically
swaps out Spotify ad breaks or unowned third-party artist mix-ins on the Twitch feed with
custom promos from `/mnt/ssd/media/box2-ads/` — without pausing or blocking Spotify's player.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

SPOTIFY_ARTIST_ID = "6C2jJcvEiE7iXnVY8H11LX"
SPOTIFY_ARTIST_URI = f"spotify:artist:{SPOTIFY_ARTIST_ID}"
SPOTIFY_ARTIST_URL = f"https://open.spotify.com/artist/{SPOTIFY_ARTIST_ID}"
SUNO_DISCOVER_URL = "https://suno.com/discover"
DJ_BUS_SINK = "box2_dj_bus"
DJ_BUS_MONITOR = f"{DJ_BUS_SINK}.monitor"
GO_LIBRESPOT_API = "http://127.0.0.1:3678"

DEFAULT_ALLOWED_SPOTIFY_ARTISTS = (
    "yurrmom.com",
    "yurrmom",
    "yurr mom",
)

AD_TITLE_KEYWORDS = (
    "advertisement",
    "spotify",
    "sponsored",
    "commercial",
    "audio ad",
    "upgrade to premium",
    "spotify free",
)


@dataclass
class PlayerSnapshot:
    bus_name: str
    role: str  # "spotify", "suno", or "browser"
    playback_status: str  # "Playing", "Paused", "Stopped"
    title: str = ""
    artist: str = ""
    url: str = ""
    pid: int = 0


@dataclass
class TrackDecision:
    action: str  # "air_bus", "ad_break_swap", "dmca_shield_swap", "idle"
    reason: str
    source_role: str = ""
    title: str = ""
    artist: str = ""
    ticker_banner: str = ""


def classify_mpris_track(
    source_role: str,
    playback_status: str,
    title: str,
    artist: str,
    url: str = "",
    allowed_spotify_artists=DEFAULT_ALLOWED_SPOTIFY_ARTISTS,
    sponsor_banner="SPONSOR BREAK: YURRMOM.COM — BOOK STAGE TIME AT HTTPS://BOX2.YURRMOM.COM",
) -> TrackDecision:
    """Classify live MPRIS player metadata for broadcast routing and Ad/DMCA shielding."""
    status_norm = str(playback_status or "").strip().lower()
    if status_norm != "playing":
        return TrackDecision(action="idle", reason="not_playing", source_role=source_role)

    raw_title = str(title or "").strip()
    raw_artist = str(artist or "").strip()
    title_l = raw_title.lower()
    artist_l = raw_artist.lower()
    url_l = str(url or "").strip().lower()
    role = str(source_role or "browser").strip().lower()

    # 1. Explicit ad markers (Spotify Free web player sets title="Advertisement" or url="spotify:ad:...")
    if (
        url_l.startswith("spotify:ad:")
        or "/ad/" in url_l
        or title_l in AD_TITLE_KEYWORDS
        or any(title_l.startswith(k + " ") for k in ("advertisement", "sponsored"))
        or (role == "spotify" and artist_l == "spotify")
        or (role == "spotify" and not raw_title and not raw_artist)
    ):
        return TrackDecision(
            action="ad_break_swap",
            reason="spotify_advertisement",
            source_role=role,
            title=raw_title,
            artist=raw_artist,
            ticker_banner=sponsor_banner,
        )

    # 2. Whitelist-first DMCA & ad shield on Spotify profile:
    # Only air tracks whose artist matches YurrMom.Com (unless "*" wildcard explicitly configured).
    if role == "spotify":
        allowed_norm = tuple(str(a).strip().lower() for a in (allowed_spotify_artists or ()))
        if "*" not in allowed_norm:
            artist_ok = bool(raw_artist) and any(a and (a in artist_l) for a in allowed_norm)
            # Also allow if browser window title formatted "Song - YurrMom.Com" into title while artist blank
            title_has_artist = (not raw_artist) and any(a and (a in title_l) for a in allowed_norm)
            if not (artist_ok or title_has_artist):
                # Empty artist during active playback on Spotify Web is typically an ad bumper;
                # non-matching artist is a Spotify Free recommended-artist mix-in.
                act = "ad_break_swap" if (not raw_artist or "spotify" in title_l) else "dmca_shield_swap"
                rsn = "spotify_unlabeled_ad" if act == "ad_break_swap" else f"non_owned_artist:{raw_artist}"
                return TrackDecision(
                    action=act,
                    reason=rsn,
                    source_role=role,
                    title=raw_title,
                    artist=raw_artist,
                    ticker_banner=sponsor_banner,
                )

        clean_title = raw_title
        for suffix in (" - Spotify", " | Spotify", " • Spotify"):
            if clean_title.endswith(suffix):
                clean_title = clean_title[:-len(suffix)].strip()
        disp_artist = raw_artist or "YurrMom.Com"
        banner = f"NOW PLAYING ON SPOTIFY: {disp_artist} - {clean_title}" if clean_title else f"NOW PLAYING ON SPOTIFY: {disp_artist}"
        return TrackDecision(
            action="air_bus",
            reason="yurrmom_verified",
            source_role="spotify",
            title=clean_title,
            artist=disp_artist,
            ticker_banner=banner,
        )

    # 3. Suno Discover / generic browser audio
    clean_title = raw_title
    for suffix in (" | Suno", " - Suno", " — Mozilla Firefox", " - Mozilla Firefox"):
        if clean_title.endswith(suffix):
            clean_title = clean_title[:-len(suffix)].strip()
    if role == "suno":
        if clean_title.lower() in ("suno", "discover", "explore", ""):
            banner = "SUNO DISCOVER RADIO: AI Music Showcase"
        elif raw_artist and raw_artist.lower() not in ("suno", "mozilla firefox"):
            banner = f"SUNO DISCOVER RADIO: {clean_title} ({raw_artist})"
        else:
            banner = f"SUNO DISCOVER RADIO: {clean_title}"
        return TrackDecision(
            action="air_bus",
            reason="suno_discover",
            source_role="suno",
            title=clean_title,
            artist=raw_artist,
            ticker_banner=banner,
        )

    banner = f"NOW PLAYING: {clean_title}" if clean_title else ""
    return TrackDecision(
        action="air_bus",
        reason="browser_audio",
        source_role=role,
        title=clean_title,
        artist=raw_artist,
        ticker_banner=banner,
    )


class RadioRotationScheduler:
    """Alternates playback blocks between Suno Discover and YurrMom.Com on Spotify Free."""

    def __init__(self, suno_tracks_per_block=3, spotify_tracks_per_block=3, max_block_seconds=720.0):
        self.suno_tracks_per_block = max(1, int(suno_tracks_per_block))
        self.spotify_tracks_per_block = max(1, int(spotify_tracks_per_block))
        self.max_block_seconds = float(max_block_seconds)

        self.active_target = "suno"  # "suno" or "spotify"
        self.block_started_mono = 0.0
        self.tracks_in_block = 0
        self._last_track_key = None

    def configure(self, suno_tracks=None, spotify_tracks=None):
        if suno_tracks is not None:
            self.suno_tracks_per_block = max(1, int(suno_tracks))
        if spotify_tracks is not None:
            self.spotify_tracks_per_block = max(1, int(spotify_tracks))

    def step(self, mode: str, players: dict, decisions: dict, now_mono: float):
        """Return (desired_role, commands_list) where commands_list is [(role, 'Play'|'Pause')]."""
        mode = str(mode or "rotate").lower()
        if mode in ("house", "beds"):
            cmds = []
            for r, snap in players.items():
                if snap.playback_status.lower() == "playing":
                    cmds.append((r, "Pause"))
            return mode, cmds

        has_suno = "suno" in players
        has_spotify = "spotify" in players

        if mode == "suno":
            target = "suno" if has_suno else ("spotify" if has_spotify else "house")
        elif mode == "spotify":
            target = "spotify" if has_spotify else ("suno" if has_suno else "house")
        else:
            # "rotate" mode
            if has_suno and has_spotify:
                target = self.active_target if self.active_target in ("suno", "spotify") else "suno"
            elif has_suno:
                target = "suno"
            elif has_spotify:
                target = "spotify"
            else:
                return "house", []

        if target != self.active_target or self.block_started_mono <= 0.0:
            self.active_target = target
            self.block_started_mono = float(now_mono)
            self.tracks_in_block = 0
            self._last_track_key = None

        cur_dec = decisions.get(target)
        cur_snap = players.get(target)

        # Count real track completions in "rotate" mode when both players exist
        if mode == "rotate" and has_suno and has_spotify and cur_snap is not None and cur_dec is not None:
            is_ad = cur_dec.action in ("ad_break_swap", "dmca_shield_swap")
            if cur_dec.action == "air_bus" and cur_dec.title:
                tkey = (target, cur_dec.title.lower(), cur_dec.artist.lower())
                if self._last_track_key is None:
                    self._last_track_key = tkey
                elif tkey != self._last_track_key:
                    self._last_track_key = tkey
                    self.tracks_in_block += 1

            quota = self.suno_tracks_per_block if target == "suno" else self.spotify_tracks_per_block
            elapsed = float(now_mono) - self.block_started_mono
            # Never interrupt Spotify mid-ad so Spotify Free finishes its ad cleanly
            if not is_ad and (self.tracks_in_block >= quota or elapsed >= self.max_block_seconds):
                target = "spotify" if target == "suno" else "suno"
                self.active_target = target
                self.block_started_mono = float(now_mono)
                self.tracks_in_block = 0
                self._last_track_key = None

        cmds = []
        other = "spotify" if target == "suno" else "suno"
        if other in players and players[other].playback_status.lower() == "playing":
            cmds.append((other, "Pause"))
        if target in players and players[target].playback_status.lower() != "playing":
            cmds.append((target, "Play"))
        return target, cmds


def discover_desktop_env(uid=None):
    """Discover DISPLAY, XAUTHORITY, DBUS_SESSION_BUS_ADDRESS, and XDG_RUNTIME_DIR from live GNOME session."""
    if uid is None:
        uid = os.getuid()
    runtime_dir = f"/run/user/{uid}"
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir}/bus")
    env.setdefault("PULSE_SERVER", f"unix:{runtime_dir}/pulse/native")

    try:
        pids = subprocess.check_output(["pgrep", "-u", str(uid), "-x", "gnome-shell"], text=True).splitlines()
        if pids:
            raw = Path(f"/proc/{pids[0].strip()}/environ").read_bytes().split(b"\x00")
            for item in raw:
                kv = item.decode("utf-8", errors="ignore")
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"):
                        env[k] = v
    except Exception:
        env.setdefault("DISPLAY", ":1")
        if os.path.exists(f"{runtime_dir}/gdm/Xauthority"):
            env.setdefault("XAUTHORITY", f"{runtime_dir}/gdm/Xauthority")
    return env


def ensure_pipewire_dj_bus():
    """Ensure the persistent virtual PipeWire sink `box2_dj_bus` is loaded and active."""
    env = discover_desktop_env()
    try:
        out = subprocess.run(["/usr/bin/wpctl", "status"], env=env, capture_output=True, text=True, timeout=4).stdout
        if "BOX 2 Broadcast DJ Bus" in out:
            return True
        subprocess.run(
            [
                "/usr/bin/pw-cli", "create-node", "adapter",
                '{ factory.name=support.null-audio-sink node.name=box2_dj_bus '
                'node.description="BOX 2 Broadcast DJ Bus" media.class=Audio/Sink '
                'object.linger=true monitor.channel-volumes=true monitor.passthrough=true '
                'node.pause-on-idle=false audio.position=[FL FR] }',
            ],
            env=env, capture_output=True, timeout=5,
        )
        return True
    except Exception:
        return False


def _role_from_pid_and_meta(pid: int, url: str, title: str, artist: str, bus_name: str = "") -> str:
    b = (bus_name or "").lower()
    if "librespot" in b or "spotifyd" in b or "spotify" in b:
        return "spotify"
    if pid > 0:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore").lower()
            if any(k in cmdline for k in ("box2-spotify", "open.spotify.com", "librespot", "spotifyd")):
                return "spotify"
            if "box2-suno" in cmdline or "suno.com" in cmdline:
                return "suno"
        except OSError:
            pass
    u = (url or "").lower()
    t = (title or "").lower()
    a = (artist or "").lower()
    if "spotify" in u or "spotify" in t or "yurrmom" in a or "advertisement" == t:
        return "spotify"
    if "suno" in u or "suno" in t or "suno" in a:
        return "suno"
    return "browser"


def poll_librespot_status(api_url: str = GO_LIBRESPOT_API, timeout_s: float = 0.6):
    """Query local go-librespot Spotify Connect daemon (`BOX 2 Stream` speaker).

    Returns (daemon_reachable: bool, snapshot_or_none: Optional[PlayerSnapshot]).
    """
    try:
        req = urllib.request.Request(f"{api_url.rstrip('/')}/status", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            code = resp.getcode()
            raw = resp.read().decode("utf-8", errors="ignore").strip()
            if code == 204 or not raw:
                return True, None
            data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return True, None
        return True, None
    except Exception:
        return False, None

    if not isinstance(data, dict):
        return True, None
    stopped = bool(data.get("stopped", False))
    paused = bool(data.get("paused", False))
    status = "Stopped" if stopped else ("Paused" if paused else "Playing")
    tr = data.get("track") if isinstance(data.get("track"), dict) else {}
    title = str(tr.get("name", "") or "")
    artists = tr.get("artist_names") or []
    if isinstance(artists, (list, tuple)):
        artist = ", ".join(str(x) for x in artists if x)
    else:
        artist = str(artists or "")
    uri = str(tr.get("uri", "") or "")
    if status == "Stopped" and not title and not uri:
        return True, None
    return True, PlayerSnapshot(
        bus_name=api_url.rstrip("/"),
        role="spotify",
        playback_status=status,
        title=title,
        artist=artist,
        url=uri,
        pid=0,
    )


def send_librespot_command(api_url: str, method: str, fallback_uri: str = SPOTIFY_ARTIST_URI, timeout_s: float = 1.2) -> bool:
    """Send Play/Pause/Next/Queue commands to local go-librespot REST API (also powers future Chat DJ)."""
    base = api_url.rstrip("/")
    route_map = {
        "Play": ("/player/resume", b"{}"),
        "Pause": ("/player/pause", b"{}"),
        "PlayPause": ("/player/playpause", b"{}"),
        "Next": ("/player/next", b"{}"),
        "Stop": ("/player/pause", b"{}"),
    }
    if method not in route_map:
        return False
    path, payload = route_map[method]
    try:
        req = urllib.request.Request(
            f"{base}{path}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s):
            return True
    except urllib.error.HTTPError as exc:
        if method == "Play" and fallback_uri and exc.code in (400, 404, 409, 500):
            try:
                body = json.dumps({"uri": fallback_uri}).encode("utf-8")
                req2 = urllib.request.Request(
                    f"{base}/player/play",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req2, timeout=timeout_s):
                    return True
            except Exception:
                return False
        return False
    except Exception:
        return False


def queue_librespot_uri(spotify_uri: str, api_url: str = GO_LIBRESPOT_API, timeout_s: float = 1.2) -> bool:
    """Queue a track URI (`spotify:track:...`) on BOX 2 Stream — ready hook for Twitch Chat DJ."""
    uri = str(spotify_uri or "").strip()
    if not uri.startswith("spotify:track:"):
        return False
    try:
        body = json.dumps({"uri": uri}).encode("utf-8")
        req = urllib.request.Request(
            f"{api_url.rstrip('/')}/player/add_to_queue",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s):
            return True
    except Exception:
        return False


class MprisRadioController:
    """Queries and controls Suno & Spotify Firefox instances over DBus MPRIS2 using Gio."""

    def __init__(self, allowed_spotify_artists=DEFAULT_ALLOWED_SPOTIFY_ARTISTS):
        self.allowed_spotify_artists = tuple(allowed_spotify_artists)
        self.scheduler = RadioRotationScheduler()
        self._bus = None
        self._gio = None
        self._glib = None
        self._last_cmd_mono = {}
        self._init_dbus()

    def _init_dbus(self):
        try:
            env = discover_desktop_env()
            os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", env["DBUS_SESSION_BUS_ADDRESS"])
            os.environ.setdefault("XDG_RUNTIME_DIR", env["XDG_RUNTIME_DIR"])
            from gi.repository import Gio, GLib
            self._gio = Gio
            self._glib = GLib
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            self._bus = None

    def list_players(self):
        if self._bus is None:
            self._init_dbus()

        players = {}
        names = []
        if self._bus is not None:
            try:
                res = self._bus.call_sync(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "ListNames",
                    None,
                    self._glib.VariantType("(as)"),
                    self._gio.DBusCallFlags.NONE,
                    1500,
                    None,
                )
                names = [n for n in res.unpack()[0] if n.startswith("org.mpris.MediaPlayer2.")]
            except Exception:
                names = []

        for name in names:
            try:
                pid_res = self._bus.call_sync(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "GetConnectionUnixProcessID",
                    self._glib.Variant("(s)", (name,)),
                    self._glib.VariantType("(u)"),
                    self._gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
                pid = int(pid_res.unpack()[0])
            except Exception:
                pid = 0

            try:
                prop_res = self._bus.call_sync(
                    name,
                    "/org/mpris/MediaPlayer2",
                    "org.freedesktop.DBus.Properties",
                    "GetAll",
                    self._glib.Variant("(s)", ("org.mpris.MediaPlayer2.Player",)),
                    self._glib.VariantType("(a{sv})"),
                    self._gio.DBusCallFlags.NONE,
                    1200,
                    None,
                )
                props = prop_res.unpack()[0]
            except Exception:
                continue

            status = str(props.get("PlaybackStatus", "Stopped"))
            meta = props.get("Metadata", {}) if isinstance(props.get("Metadata"), dict) else {}
            title = str(meta.get("xesam:title", "") or "")
            raw_artists = meta.get("xesam:artist", [])
            if isinstance(raw_artists, (list, tuple)):
                artist = ", ".join(str(x) for x in raw_artists if x)
            else:
                artist = str(raw_artists or "")
            url = str(meta.get("xesam:url", "") or "")

            role = _role_from_pid_and_meta(pid, url, title, artist, bus_name=name)
            snap = PlayerSnapshot(
                bus_name=name,
                role=role,
                playback_status=status,
                title=title,
                artist=artist,
                url=url,
                pid=pid,
            )
            # Prefer a 'Playing' instance if multiple tabs exist under the same role
            if role not in players or (snap.playback_status == "Playing" and players[role].playback_status != "Playing"):
                players[role] = snap

        # Merge headless go-librespot Spotify Connect speaker (`BOX 2 Stream`) if active
        _, ls_snap = poll_librespot_status()
        if ls_snap is not None:
            if "spotify" not in players or (ls_snap.playback_status == "Playing" and players["spotify"].playback_status != "Playing"):
                players["spotify"] = ls_snap
        return players

    def send_command(self, bus_name: str, method: str, min_interval_s=2.5):
        if method not in ("Play", "Pause", "PlayPause", "Next", "Stop"):
            return False
        now_m = time.monotonic()
        key = (bus_name, method)
        if now_m - self._last_cmd_mono.get(key, 0.0) < min_interval_s:
            return False
        self._last_cmd_mono[key] = now_m
        if str(bus_name).startswith("http://") or str(bus_name).startswith("https://"):
            return send_librespot_command(bus_name, method)
        if self._bus is None:
            return False
        try:
            self._bus.call_sync(
                bus_name,
                "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player",
                method,
                None,
                None,
                self._gio.DBusCallFlags.NONE,
                1200,
                None,
            )
            return True
        except Exception:
            return False

    def poll_and_step(self, music_desired_now: bool, dj_mode="rotate", suno_tracks=3, spotify_tracks=3):
        """Poll MPRIS players, run rotation & Ad/DMCA shield classification, and return status + TrackDecision."""
        self.scheduler.configure(suno_tracks=suno_tracks, spotify_tracks=spotify_tracks)
        players = self.list_players()
        decisions = {
            role: classify_mpris_track(
                source_role=role,
                playback_status=snap.playback_status,
                title=snap.title,
                artist=snap.artist,
                url=snap.url,
                allowed_spotify_artists=self.allowed_spotify_artists,
            )
            for role, snap in players.items()
        }

        now_m = time.monotonic()
        if not music_desired_now:
            # Pause browser streams while stage music is disabled (e.g. daytime standby or rehearsal)
            for role, snap in players.items():
                if snap.playback_status.lower() == "playing":
                    self.send_command(snap.bus_name, "Pause", min_interval_s=3.0)
            return TrackDecision(action="idle", reason="music_disabled"), players

        target_role, cmds = self.scheduler.step(dj_mode, players, decisions, now_m)
        for role, method in cmds:
            if role in players:
                self.send_command(players[role].bus_name, method, min_interval_s=3.0)

        if target_role in decisions and players[target_role].playback_status.lower() == "playing":
            return decisions[target_role], players

        # Check if any other browser instance is actively playing
        for role, dec in decisions.items():
            if dec.action != "idle":
                return dec, players

        return TrackDecision(action="idle", reason="no_active_browser_stream"), players


def launch_dj_browsers(target="both"):
    """Launch isolated Suno Discover & YurrMom.Com Spotify Firefox windows routed exclusively to box2_dj_bus."""
    ensure_pipewire_dj_bus()
    env = discover_desktop_env()
    env["PULSE_SINK"] = DJ_BUS_SINK
    env["MOZ_ENABLE_WAYLAND"] = "0"

    ff_base = Path.home() / "snap" / "firefox" / "common" / ".mozilla" / "firefox"
    launched = []

    specs = []
    if target in ("both", "suno"):
        specs.append(("box2-suno", SUNO_DISCOVER_URL))
    if target in ("both", "spotify"):
        specs.append(("box2-spotify", SPOTIFY_ARTIST_URL))

    for prof_name, url in specs:
        prof_dir = ff_base / prof_name
        prof_dir.mkdir(parents=True, exist_ok=True)
        # Skip launching if this profile already has a running Firefox process
        already = subprocess.run(["pgrep", "-f", f"firefox.*{prof_name}"], capture_output=True, text=True).stdout.strip()
        if already:
            launched.append({"profile": prof_name, "status": "already_running", "pids": already.splitlines(), "url": url})
            continue
        proc = subprocess.Popen(
            ["/usr/bin/firefox", "--no-remote", "--new-instance", "--profile", str(prof_dir), url],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        launched.append({"profile": prof_name, "status": "launched", "pid": proc.pid, "url": url})
    return launched
