"""Unit tests for Stage Director zero-drop stream resilience, marathon mode, auto-ducking audio, rehearsal & clipping."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from datetime import datetime, timedelta

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def _load_b2s():
    try:
        import tools.jetson.box2_stream as b2s
        return b2s
    except ImportError:
        import sys
        sys.path.insert(0, "/home/joseph1/box2-stream")
        import box2_stream as b2s
        return b2s


class StreamResilienceTests(unittest.TestCase):
    def test_frame_starvation_holding_buffer(self):
        """Simulates camera disconnect where read() fails repeatedly.
        Verifies that last_valid_frame cache provides uninterrupted frame flow.
        """
        if not HAS_NUMPY:
            initial_frame = {"type": "frame", "timestamp": 12345}
        else:
            initial_frame = np.zeros((360, 640, 3), dtype=np.uint8)
            initial_frame[10:50, 10:50] = (255, 200, 100)

        last_valid_frame = initial_frame.copy() if hasattr(initial_frame, "copy") else dict(initial_frame)
        consecutive_read_fails = 0
        reconnect_triggered = False

        pumped_frames = []
        for _ in range(20):
            ret, read_frame = False, None
            if ret and read_frame is not None:
                consecutive_read_fails = 0
                last_valid_frame = read_frame.copy() if hasattr(read_frame, "copy") else dict(read_frame)
            else:
                consecutive_read_fails += 1
                frame = (last_valid_frame.copy() if hasattr(last_valid_frame, "copy") else dict(last_valid_frame)) if last_valid_frame is not None else None
                if consecutive_read_fails >= 10:
                    reconnect_triggered = True
            pumped_frames.append(frame)

        self.assertEqual(len(pumped_frames), 20)
        self.assertTrue(reconnect_triggered)
        if HAS_NUMPY:
            np.testing.assert_array_equal(pumped_frames[0], initial_frame)
            np.testing.assert_array_equal(pumped_frames[19], initial_frame)
        else:
            self.assertEqual(pumped_frames[0], initial_frame)
            self.assertEqual(pumped_frames[19], initial_frame)

    def test_dynamic_token_url_generation(self):
        """Verifies that dynamic token renewal seamlessly updates camera URLs."""
        current_token = "token_initial_123"
        ip = "10.0.0.6"
        cfg = {"nvr_channel": 0, "nvr_stream": "sub"}

        def get_token():
            return current_token

        def get_cam0_url():
            return f"http://{ip}/flv?port=1935&app=bcs&stream=channel{cfg['nvr_channel']}_{cfg['nvr_stream']}.bcs&token={get_token()}"

        def get_cam2_url():
            return f"http://{ip}/flv?port=1935&app=bcs&stream=channel1_sub.bcs&token={get_token()}"

        self.assertIn("token_initial_123", get_cam0_url())
        self.assertIn("token_initial_123", get_cam2_url())
        current_token = "token_renewed_456"
        self.assertIn("token_renewed_456", get_cam0_url())
        self.assertIn("token_renewed_456", get_cam2_url())

    def test_next_scheduled_refresh_time_calculation(self):
        """Verifies calculation of next top of hour divisible by 3 hours."""
        def get_next(dt, interval=3):
            cand = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            while cand.hour % interval != 0 or cand <= dt:
                cand += timedelta(hours=1)
            return cand

        self.assertEqual(get_next(datetime(2026, 11, 18, 0, 45, 0)), datetime(2026, 11, 18, 3, 0, 0))
        self.assertEqual(get_next(datetime(2026, 11, 18, 3, 0, 5)), datetime(2026, 11, 18, 6, 0, 0))
        self.assertEqual(get_next(datetime(2026, 11, 18, 22, 15, 0)), datetime(2026, 11, 19, 0, 0, 0))
        self.assertEqual(get_next(datetime(2026, 11, 18, 21, 0, 0)), datetime(2026, 11, 19, 0, 0, 0))

    def test_scheduled_rollover_slot_tracking(self):
        """Verifies rollover only fires once per scheduled slot and respects min runtime."""
        refresh_hours = 3
        last_refreshed_slot = None
        triggered = []

        def check_trigger(now_dt, stream_uptime_s):
            nonlocal last_refreshed_slot
            if (
                refresh_hours > 0
                and now_dt.hour % refresh_hours == 0
                and now_dt.minute == 0
                and (now_dt.year, now_dt.month, now_dt.day, now_dt.hour) != last_refreshed_slot
                and stream_uptime_s > 300
            ):
                last_refreshed_slot = (now_dt.year, now_dt.month, now_dt.day, now_dt.hour)
                triggered.append(now_dt)
                return True
            return False

        self.assertFalse(check_trigger(datetime(2026, 11, 18, 2, 59, 59), 3600))
        self.assertTrue(check_trigger(datetime(2026, 11, 18, 3, 0, 0), 3601))
        self.assertFalse(check_trigger(datetime(2026, 11, 18, 3, 0, 30), 10))
        self.assertFalse(check_trigger(datetime(2026, 11, 18, 4, 0, 0), 3600))
        self.assertTrue(check_trigger(datetime(2026, 11, 18, 6, 0, 0), 7200))
        self.assertEqual(len(triggered), 2)

    def test_ticker_scroll_warning_messages(self):
        """Verifies warning string formatting at different time thresholds before reset."""
        def format_ticker_messages(rem_sec, next_time_str="3:00 AM", raw_msgs=None):
            if raw_msgs is None:
                raw_msgs = ["COMEDY NIGHT"]
            if rem_sec <= 60:
                s = max(1, int(rem_sec))
                alert = f"*** SCHEDULED RESET IN {s}s -- REFRESHING IN 7s FOR VOD CLIPPING ARCHIVE ***"
                return [alert, alert]
            elif rem_sec <= 300:
                m = int(rem_sec // 60)
                s = int(rem_sec % 60)
                alert = f"WARNING: SCHEDULED 3-HOUR RESET IN {m}m {s:02d}s (AT {next_time_str}) FOR VOD CLIPPING ARCHIVE -- BACK IN 7s"
                return [alert] + raw_msgs
            elif rem_sec <= 600:
                m = int(rem_sec // 60)
                notice = f"NOTICE: 3-Hour VOD reset in {m} min (at {next_time_str}) for clipping archive"
                return [notice] + raw_msgs
            else:
                schedule_msg = f"RESET SCHEDULE: Next 3-hour clipping VOD rollover at {next_time_str} (brief 7s pause)"
                return raw_msgs + [schedule_msg]

        self.assertIn("RESET SCHEDULE: Next 3-hour clipping VOD rollover at 3:00 AM", format_ticker_messages(1800)[-1])
        self.assertTrue(format_ticker_messages(480)[0].startswith("NOTICE: 3-Hour VOD reset in 8 min"))
        self.assertTrue(format_ticker_messages(225)[0].startswith("WARNING: SCHEDULED 3-HOUR RESET IN 3m 45s"))
        urgent = format_ticker_messages(25)
        self.assertEqual(len(urgent), 2)
        self.assertIn("SCHEDULED RESET IN 25s", urgent[0])

    def test_privacy_view_mode_resolution(self):
        """Verifies zero-drop privacy/stage view mode resolution from state.json and ticker.json."""
        b2s = _load_b2s()
        with tempfile.TemporaryDirectory() as tmp:
            old_state = b2s.STATE
            try:
                b2s.STATE = b2s.Path(os.path.join(tmp, "state.json"))
                tk_path = os.path.join(tmp, "ticker.json")

                b2s.STATE.write_text(json.dumps({"desired": "on", "view": "stage"}))
                with open(tk_path, "w") as f:
                    json.dump({"privacy_placeholder": {"enabled": False}}, f)
                self.assertEqual(b2s.desired_view(tk_path), "stage")

                b2s.STATE.write_text(json.dumps({"desired": "on", "view": "auto"}))
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 7, 36, 0)), "privacy")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 20, 59, 59)), "privacy")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 21, 0, 0)), "stage")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 26, 0, 30, 0)), "stage")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 26, 1, 59, 59)), "stage")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 26, 2, 0, 0)), "privacy")

                b2s.STATE.write_text(json.dumps({"desired": "on", "view": "privacy"}))
                self.assertEqual(b2s.desired(), "on")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 22, 0, 0)), "privacy")

                b2s.STATE.write_text(json.dumps({"desired": "on", "view": "stage"}))
                with open(tk_path, "w") as f:
                    json.dump({"privacy_placeholder": {"enabled": True}}, f)
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 22, 0, 0)), "privacy")
            finally:
                b2s.STATE = old_state

    def test_rehearse_timed_override_and_auto_expiry(self):
        """Verifies `rehearse` activates stage immediately and expires back to auto schedule."""
        b2s = _load_b2s()
        with tempfile.TemporaryDirectory() as tmp:
            old_state = b2s.STATE
            try:
                b2s.STATE = b2s.Path(os.path.join(tmp, "state.json"))
                tk_path = os.path.join(tmp, "ticker.json")
                with open(tk_path, "w") as f:
                    json.dump({"privacy_placeholder": {"enabled": False}}, f)

                # Daytime 4:00 PM with rehearse active until t=2000
                b2s.update_state(desired="on", view="rehearse", view_until=2000.0)
                daytime = datetime(2026, 11, 26, 16, 0, 0)
                self.assertEqual(b2s.view_policy(now_epoch=1500.0), "rehearse")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=daytime, now_epoch=1500.0), "stage")

                # Once rehearsal timer expires at t=2001 -> automatically reverts to daytime privacy
                self.assertEqual(b2s.view_policy(now_epoch=2001.0), "auto")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=daytime, now_epoch=2001.0), "privacy")
            finally:
                b2s.STATE = old_state

    def test_marathon_vs_vod_cadence_and_ticker_filtering(self):
        """Verifies marathon mode defaults to uninterrupted (0h) and filters stale 3-hour VOD ticker lines."""
        b2s = _load_b2s()
        with tempfile.TemporaryDirectory() as tmp:
            old_state = b2s.STATE
            try:
                b2s.STATE = b2s.Path(os.path.join(tmp, "state.json"))
                tk_path = os.path.join(tmp, "ticker.json")
                with open(tk_path, "w") as f:
                    json.dump({
                        "title": "BOX 2",
                        "messages": [
                            "SPONSOR: YURRMOM.COM",
                            "CLIPS: New 3-Hour VODs drop every 3 hours for clipping!",
                        ],
                    }, f)

                # Default is marathon (0 hours)
                b2s.update_state(desired="on")
                self.assertEqual(b2s.effective_refresh_hours({}), 0)
                self.assertIsNone(b2s.next_scheduled_refresh_time(0))

                ticker = b2s.TickerOverlay(config_path=tk_path, refresh_hours=0)
                ticker.reload_if_needed()
                ticker._update_full_str()
                self.assertNotIn("3-Hour VOD", ticker.full_ticker_str)
                self.assertNotIn("RESET SCHEDULE", ticker.full_ticker_str)

                # Switching to vod-mode enables 3-hour rollover and countdown text
                b2s.update_state(cadence="vod")
                self.assertEqual(b2s.effective_refresh_hours({}), 3)
                ticker.set_refresh_hours(3)
                self.assertIn("RESET SCHEDULE", ticker.full_ticker_str)
            finally:
                b2s.STATE = old_state

    @unittest.skipUnless(HAS_NUMPY, "numpy required for audio DSP test")
    def test_auto_duck_envelope_voice_and_onstage(self):
        """Verifies fast speech ducking, anti-pumping hold, onstage bed, and soft broadcast limiter."""
        b2s = _load_b2s()
        env = b2s.AutoDuckEnvelope(
            idle_volume=0.35,
            ducked_volume=0.05,
            onstage_volume=0.06,
            mic_gain=1.85,
            voice_threshold_dbfs=-35.0,
            hold_seconds=1.8,
        )

        # 1. Empty stage, ambient room noise (-48 dBFS) -> swells up toward 0.35
        t = 0.0
        for _ in range(80):  # 4.0s
            gain, v_act = env.step(mic_rms_dbfs=-48.0, is_performer_onstage=False, music_enabled=True, now_mono=t, dt=0.05)
            t += 0.05
        self.assertFalse(v_act)
        self.assertGreater(gain, 0.32)

        # 2. MC speaks into mic (-22 dBFS) -> ducks rapidly within 200ms (4 ticks)
        for _ in range(4):
            gain, v_act = env.step(mic_rms_dbfs=-22.0, is_performer_onstage=True, music_enabled=True, now_mono=t, dt=0.05)
            t += 0.05
        self.assertTrue(v_act)
        self.assertLess(gain, 0.09)

        # 3. 1-second pause between sentences (-48 dBFS) -> hold keeps music ducked (no pumping!)
        for _ in range(20):  # 1.0s < 1.8s hold
            gain, v_act = env.step(mic_rms_dbfs=-48.0, is_performer_onstage=True, music_enabled=True, now_mono=t, dt=0.05)
            t += 0.05
        self.assertTrue(v_act)
        self.assertLess(gain, 0.10)

        # 4. Even 5 seconds silent pause while performer remains onstage -> stays at subtle onstage bed (0.06)
        for _ in range(100):
            gain, v_act = env.step(mic_rms_dbfs=-48.0, is_performer_onstage=True, music_enabled=True, now_mono=t, dt=0.05)
            t += 0.05
        self.assertFalse(v_act)
        self.assertAlmostEqual(gain, 0.06, delta=0.015)

        # 5. Soft limiter prevents int16 clipping even on loud shout/laugh
        loud_mic = np.full((2400, 2), 0.90, dtype=np.float32)
        music = np.full((2400, 2), 0.50, dtype=np.float32)
        pcm = env.mix_and_limit(loud_mic, music, music_gain=0.35)
        self.assertEqual(pcm.dtype, np.int16)
        self.assertLessEqual(int(np.max(np.abs(pcm))), 32000)

    def test_clip_ring_segment_selection_and_wraparound(self):
        """Verifies mtime-ordered ring segment selection handles wrap-around and ignores stale runs."""
        b2s = _load_b2s()
        with tempfile.TemporaryDirectory() as tmp:
            ring = os.path.join(tmp, "ring")
            os.makedirs(ring, exist_ok=True)
            base_t = time.time() - 120.0

            # Stale segment from yesterday (must be excluded)
            stale = os.path.join(ring, "seg_0100.ts")
            with open(stale, "wb") as f:
                f.write(b"x" * 4096)
            os.utime(stale, (base_t - 86400, base_t - 86400))

            # Simulated wrap-around: seg_2878, seg_2879, seg_0000, seg_0001, seg_0002 (15s apart)
            names = ["seg_2878.ts", "seg_2879.ts", "seg_0000.ts", "seg_0001.ts", "seg_0002.ts"]
            for i, name in enumerate(names):
                p = os.path.join(ring, name)
                with open(p, "wb") as f:
                    f.write(b"x" * 4096)
                mt = base_t + i * 15.0
                os.utime(p, (mt, mt))

            # Request window covering seg_2879 through seg_0002
            segs, trim = b2s.select_ring_segments(ring, start_epoch=base_t + 5.0, end_epoch=base_t + 58.0, seg_seconds=15.0)
            picked = [p.name for p in segs]
            self.assertNotIn("seg_0100.ts", picked)
            self.assertEqual(picked, ["seg_2879.ts", "seg_0000.ts", "seg_0001.ts", "seg_0002.ts"])
            self.assertAlmostEqual(trim, 5.0, delta=0.5)
            self.assertEqual(b2s.parse_duration_seconds("10m"), 600.0)
            self.assertEqual(b2s.parse_duration_seconds("90s"), 90.0)
            self.assertEqual(b2s.parse_duration_seconds("15"), 900.0)

    def test_spotify_ad_interception_and_dmca_artist_shield(self):
        """Verifies Spotify Free ads & non-YurrMom artists trigger box2-ads swap while YurrMom & Suno air cleanly."""
        b2s = _load_b2s()
        radio = b2s.box2_radio

        # 1. Verified YurrMom.Com song on Spotify -> airs live + populates Spotify banner
        d_ok = radio.classify_mpris_track("spotify", "Playing", "Canton Nights", "YurrMom.Com")
        self.assertEqual(d_ok.action, "air_bus")
        self.assertIn("NOW PLAYING ON SPOTIFY: YurrMom.Com - Canton Nights", d_ok.ticker_banner)

        # 2. Explicit Spotify Free ad ("Advertisement" or spotify:ad: URI) -> swaps to box2-ads!
        d_ad1 = radio.classify_mpris_track("spotify", "Playing", "Advertisement", "")
        self.assertEqual(d_ad1.action, "ad_break_swap")
        self.assertIn("SPONSOR BREAK", d_ad1.ticker_banner)

        d_ad2 = radio.classify_mpris_track("spotify", "Playing", "Upgrade to Premium", "Spotify", url="spotify:ad:12345")
        self.assertEqual(d_ad2.action, "ad_break_swap")

        # 3. Random third-party recommended artist mixed in by Spotify Free -> DMCA shield swaps to box2-ads!
        d_dmca = radio.classify_mpris_track("spotify", "Playing", "Major Label Hit", "Random Major Artist")
        self.assertEqual(d_dmca.action, "dmca_shield_swap")
        self.assertIn("SPONSOR BREAK", d_dmca.ticker_banner)

        # 4. Suno Discover track -> airs live + populates Suno Discover banner
        d_suno = radio.classify_mpris_track("suno", "Playing", "Neon Jukebox", "@groovebot")
        self.assertEqual(d_suno.action, "air_bus")
        self.assertIn("SUNO DISCOVER RADIO: Neon Jukebox", d_suno.ticker_banner)

    def test_radio_block_rotation_suno_to_spotify_and_never_interrupts_ad(self):
        """Verifies RadioRotationScheduler alternates Suno <-> YurrMom Spotify blocks without pausing Spotify mid-ad."""
        b2s = _load_b2s()
        radio = b2s.box2_radio
        sched = radio.RadioRotationScheduler(suno_tracks_per_block=2, spotify_tracks_per_block=2)

        def make_state(suno_status, suno_title, spot_status, spot_title, spot_artist):
            players = {
                "suno": radio.PlayerSnapshot("bus.suno", "suno", suno_status, title=suno_title, artist="@ai"),
                "spotify": radio.PlayerSnapshot("bus.spot", "spotify", spot_status, title=spot_title, artist=spot_artist),
            }
            decs = {
                r: radio.classify_mpris_track(r, p.playback_status, p.title, p.artist)
                for r, p in players.items()
            }
            return players, decs

        # Start on Suno song 1 -> pauses Spotify if playing, plays Suno
        p, d = make_state("Playing", "Suno Song 1", "Playing", "Track A", "YurrMom.Com")
        target, cmds = sched.step("rotate", p, d, now_mono=10.0)
        self.assertEqual(target, "suno")
        self.assertIn(("spotify", "Pause"), cmds)

        # Suno transitions to Song 2 -> Song 3 (2 transitions completed == quota 2) -> switches to Spotify!
        p, d = make_state("Playing", "Suno Song 2", "Paused", "Track A", "YurrMom.Com")
        sched.step("rotate", p, d, now_mono=120.0)
        p, d = make_state("Playing", "Suno Song 3", "Paused", "Track A", "YurrMom.Com")
        target, cmds = sched.step("rotate", p, d, now_mono=240.0)
        self.assertEqual(target, "spotify")
        self.assertIn(("suno", "Pause"), cmds)
        self.assertIn(("spotify", "Play"), cmds)

        # Spotify plays 2 YurrMom songs, then enters an Advertisement right at block boundary:
        # Scheduler MUST NOT pause Spotify mid-ad; waits until ad finishes!
        p, d = make_state("Paused", "Suno Song 3", "Playing", "YM Song 1", "YurrMom.Com")
        sched.step("rotate", p, d, now_mono=250.0)
        p, d = make_state("Paused", "Suno Song 3", "Playing", "YM Song 2", "YurrMom.Com")
        sched.step("rotate", p, d, now_mono=380.0)
        p, d = make_state("Paused", "Suno Song 3", "Playing", "Advertisement", "")
        target_during_ad, cmds_ad = sched.step("rotate", p, d, now_mono=1200.0)
        self.assertEqual(target_during_ad, "spotify")
        self.assertNotIn(("spotify", "Pause"), cmds_ad)

        # Once Spotify ad ends and next song starts -> cleanly rotates back to Suno!
        p, d = make_state("Paused", "Suno Song 3", "Playing", "YM Song 3", "YurrMom.Com")
        target_after_ad, cmds_after = sched.step("rotate", p, d, now_mono=1230.0)
        self.assertEqual(target_after_ad, "suno")
        self.assertIn(("spotify", "Pause"), cmds_after)
        self.assertIn(("suno", "Play"), cmds_after)

    def test_showtime_countdown_and_seasonal_jokes_weaving(self):
        """Verifies seconds_until_showtime math, Black Friday default theme, and hot-loaded YurrMom jokes in ticker."""
        b2s = _load_b2s()
        self.assertEqual(b2s.normalize_seasonal_theme("black-friday"), "black_friday")
        self.assertEqual(b2s.normalize_seasonal_theme("bf"), "black_friday")
        self.assertEqual(b2s.normalize_seasonal_theme(""), "black_friday")
        self.assertEqual(b2s.normalize_seasonal_theme("thanksgiving"), "thanksgiving")
        self.assertEqual(b2s.normalize_seasonal_theme("classic"), "classic")

        # Verify repo jokes.json is updated to Black Friday + Yurrmom.com
        repo_jokes = b2s.load_jokes_data()
        self.assertIn("BLACK FRIDAY", repo_jokes["seasonal_greeting"].upper())
        self.assertTrue(any("yurrmom.com" in j.lower() for j in repo_jokes["jokes"]))
        self.assertGreaterEqual(len(repo_jokes["jokes"]), 8)

        # 5:55 PM -> 3 hours 5 minutes (11100s) until 9:00 PM showtime
        self.assertEqual(b2s.seconds_until_showtime(datetime(2026, 11, 27, 17, 55, 0), 21, 2), 11100.0)
        # 9:30 PM -> 0.0s (showtime currently live!)
        self.assertEqual(b2s.seconds_until_showtime(datetime(2026, 11, 27, 21, 30, 0), 21, 2), 0.0)
        # 2:10 AM -> 18 hours 50 minutes (67800s) until next 9:00 PM showtime
        self.assertEqual(b2s.seconds_until_showtime(datetime(2026, 11, 27, 2, 10, 0), 21, 2), 67800.0)

        with tempfile.TemporaryDirectory() as tmp:
            tk_p = os.path.join(tmp, "ticker.json")
            jk_p = os.path.join(tmp, "jokes.json")
            with open(tk_p, "w") as f:
                json.dump({"title": "BOX 2", "seasonal_theme": "black_friday", "messages": ["SPONSOR: YURRMOM.COM"]}, f)
            with open(jk_p, "w") as f:
                json.dump({
                    "seasonal_greeting": "BLACK FRIDAY LIVE FROM BOX 2 & YURRMOM.COM",
                    "jokes": [
                        "Get your nuts from Yurrmom.com -- the only Black Friday doorbuster worth lining up for.",
                        "Happy Black Friday from Yurrmom.com -- 100% off bad vibes, zero trampling required.",
                    ],
                }, f)

            ticker = b2s.TickerOverlay(config_path=tk_p, refresh_hours=0, jokes_path=jk_p)
            ticker.reload_if_needed()
            ticker._update_full_str()
            self.assertIn("BLACK FRIDAY LIVE FROM BOX 2 & YURRMOM.COM", ticker.full_ticker_str)
            self.assertIn("Get your nuts from Yurrmom.com", ticker.full_ticker_str)
            self.assertIn("Black Friday doorbuster", ticker.full_ticker_str)

            # Verify countdown box is 15% smaller (382x142) and vertically center-aligned with Parking Lot PIP (y=495, h=191)
            cd = b2s.ShowtimeCountdownOverlay(config_path=tk_p, jokes_path=jk_p, base_w=1280, base_h=720)
            self.assertEqual(cd.theme, "black_friday")
            self.assertFalse(cd.show_falling_leaves)
            self.assertEqual((cd.card_w, cd.card_h), (382, 142))
            pip_mid_y = 495 + 191 / 2.0
            cd_mid_y = cd.y + cd.card_h / 2.0
            self.assertLessEqual(abs(cd_mid_y - pip_mid_y), 1.0)
            self.assertEqual(cd.x, 1280 - 382 - 26)

            if HAS_NUMPY:
                try:
                    import cv2  # noqa: F401
                    has_cv2 = True
                except ImportError:
                    has_cv2 = False
                if has_cv2:
                    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                    ticker.draw(frame, standby_mode=True)
                    ticker.draw_now_playing_tab(frame, {
                        "music_playing": True,
                        "music_track": "01_YurrMom.Com - I LIKE ROCKS",
                        "audio_source": "house_ssd",
                        "ad_shield_active": False,
                    })
                    cd.draw(frame, standby_mode=True, top_matte_h=110, now_dt=datetime(2026, 11, 27, 16, 30, 0))
                    self.assertEqual(cd._cached_bgr.shape, (142, 382, 3))

            # Verify Now Playing tab label cleanup for YurrMom.Com SSD & Spotify tracks
            self.assertEqual(
                b2s.format_now_playing_label("01_YurrMom.Com - I LIKE ROCKS", "house_ssd", False),
                ("NOW PLAYING", "YurrMom.Com - I LIKE ROCKS"),
            )
            self.assertEqual(
                b2s.format_now_playing_label("YurrMom.Com - Dish Duty Shuffle", "dj_spotify", False),
                ("SPOTIFY", "YurrMom.Com - Dish Duty Shuffle"),
            )
            self.assertEqual(
                b2s.format_now_playing_label("01_yurrmom_sponsor_bumper_20s", "box2_ads_swap", True),
                ("SPONSOR", "YurrMom.Com"),
            )
            self.assertEqual(
                b2s.format_now_playing_label("Stage Groove - Late Night Host Pocket", "stage_bed", False),
                ("STAGE GROOVE", "Late Night Host Pocket"),
            )

    def test_spotify_undertone_onstage_mix_and_vocal_pocket(self):
        """Verifies default 'undertone' onstage mode keeps audible song undertone and carves vocal pocket."""
        b2s = _load_b2s()
        env = b2s.AutoDuckEnvelope()
        self.assertEqual(env.onstage_mode, "undertone")
        self.assertAlmostEqual(env.onstage_volume, 0.18, places=2)
        self.assertAlmostEqual(env.onstage_speech_volume, 0.11, places=2)

        # Idle empty stage -> ramps toward 0.34
        for i in range(40):
            g, v = env.step(mic_rms_dbfs=-60.0, is_performer_onstage=False, music_enabled=True, now_mono=i * 0.1, dt=0.1)
        self.assertFalse(v)
        self.assertGreater(g, 0.30)

        # Performer steps on stage (quiet between lines) -> smooth audible undertone (~0.18, NOT muted 0.06!)
        for i in range(40):
            g_on, v_on = env.step(mic_rms_dbfs=-55.0, is_performer_onstage=True, music_enabled=True, now_mono=10.0 + i * 0.1, dt=0.1)
        self.assertFalse(v_on)
        self.assertAlmostEqual(g_on, 0.18, delta=0.015)

        # Performer speaks into mic (-22 dBFS) -> tucks smoothly to ~0.11 while staying warmly audible
        for i in range(25):
            g_sp, v_sp = env.step(mic_rms_dbfs=-22.0, is_performer_onstage=True, music_enabled=True, now_mono=20.0 + i * 0.05, dt=0.05)
        self.assertTrue(v_sp)
        self.assertAlmostEqual(g_sp, 0.11, delta=0.015)

        if HAS_NUMPY:
            t = np.arange(4800, dtype=np.float32) / 48000.0
            # 1 kHz center vocal tone (Mid) + 1.2 kHz out-of-phase stereo pad (Side)
            mid_1k = 0.5 * np.sin(2.0 * np.pi * 1000.0 * t)
            side_pad = 0.4 * np.sin(2.0 * np.pi * 1200.0 * t)
            stereo_in = np.column_stack([mid_1k + side_pad, mid_1k - side_pad]).astype(np.float32)
            carved = env.apply_undertone_vocal_pocket(stereo_in, carve_strength=0.55)
            in_mid_rms = float(np.sqrt(np.mean((0.5 * (stereo_in[500:, 0] + stereo_in[500:, 1])) ** 2)))
            out_mid_rms = float(np.sqrt(np.mean((0.5 * (carved[500:, 0] + carved[500:, 1])) ** 2)))
            in_side_rms = float(np.sqrt(np.mean((0.5 * (stereo_in[500:, 0] - stereo_in[500:, 1])) ** 2)))
            out_side_rms = float(np.sqrt(np.mean((0.5 * (carved[500:, 0] - carved[500:, 1])) ** 2)))
            # Center 1 kHz vocal pocket is attenuated ~50% while stereo Side pad is untouched!
            self.assertLess(out_mid_rms, in_mid_rms * 0.60)
            self.assertAlmostEqual(out_side_rms, in_side_rms, delta=1e-4)

    def test_chessheat_geometry_and_typed_layer_labels(self):
        """Verifies ChessHeat exact geometry delta, legal destination counts, and typed layer headers."""
        b2s = _load_b2s()
        ch = b2s.box2_chessheat
        self.assertIn("STRUCTURAL GEOMETRY DELTA", ch.LAYER_TITLES["geometry_delta"])
        self.assertIn("DEST MEAN CP REGRET", ch.LAYER_TITLES["dest_cp_regret"])
        self.assertIn("LEGAL DEST MOVE COUNT", ch.LAYER_TITLES["dest_move_count"])
        self.assertIn("PV LINE RECURRENCE", ch.LAYER_TITLES["pv_recurrence"])
        self.assertGreaterEqual(len(ch.HISTORICAL_GAMES), 5)

        if ch.HAS_CHESS:
            board = ch.chess.Board()
            g0 = ch.extract_board_geometry(board)
            board.push_san("e4")
            g1 = ch.extract_board_geometry(board)
            sq_rgba, rays, stats = ch.compute_geometry_delta_layer(g0, g1)
            # Pushing 1. e4 opens Bf1 and Qd1 diagonal rays and modifies attacks!
            self.assertGreater(len(sq_rgba), 0)
            self.assertGreater(len(rays), 0)
            self.assertTrue(stats["row3"][1].startswith("+"))

            dest_rgba, _, dest_stats = ch.compute_dest_move_count_layer(board)
            self.assertEqual(dest_stats["row1"][1], "20")
            self.assertGreater(len(dest_rgba), 10)

    def test_face_size_smoothing_eliminates_haar_box_zoom_breathing(self):
        """Verifies `face_size_smoothing_tau` prevents detector box-size jitter from pumping camera zoom."""
        from stage_director.framing import FramingConfig, FramingEngine
        from stage_director.geometry import BoundingBox

        def run_sim(tau_sz: float):
            cfg = FramingConfig(
                canvas_width=640,
                canvas_height=360,
                target_face_fraction=0.25,
                headroom_fraction=0.55,
                max_zoom=2.25,
                face_size_smoothing_tau=tau_sz,
                deadzone_zoom_px=58.0,
                smoothing_tau=0.85,
                max_zoom_speed_px_s=55.0,
            )
            eng = FramingEngine(cfg)
            t = 0.0
            eng.reset(monotonic_seconds=t)
            # Settle onto performer standing at (300, 140) with nominal 42px face
            for _ in range(120):
                t += 0.1
                win = eng.update(BoundingBox(x=279, y=119, width=42, height=42), t)
            settled_w = win.width
            # Inject noisy Haar face sizes oscillating wildly 28px <-> 56px for 4 seconds at same spot
            widths = []
            for i in range(40):
                t += 0.1
                noisy_h = 28.0 if (i % 2 == 0) else 56.0
                w_now = eng.update(
                    BoundingBox(x=300 - noisy_h / 2, y=140 - noisy_h / 2, width=noisy_h, height=noisy_h), t
                ).width
                widths.append(w_now)
            return settled_w, widths

        _, raw_widths = run_sim(0.0)
        settled_w, smooth_widths = run_sim(5.0)
        # Raw unsmoothed face size causes noticeable zoom drift/breathing, while smoothed stays locked!
        self.assertGreater(max(raw_widths) - min(raw_widths), 5.0)
        self.assertLessEqual(max(smooth_widths) - min(smooth_widths), 1.0)
        self.assertAlmostEqual(smooth_widths[-1], settled_w, delta=1.0)

    def test_showtime_pauses_spotify_and_plays_stage_beds_and_gates_offstage_mic(self):
        """Verifies 9PM stage mode pauses Spotify/vocal shuffle for Stage Groove beds and gates off-stage room mic."""
        b2s = _load_b2s()
        radio = b2s.box2_radio

        # 1. Off-hours (`privacy`) keeps Spotify active; 9PM showtime (`stage`) switches to `beds`
        self.assertEqual(b2s.resolve_effective_dj_mode("privacy", "spotify", "beds"), "spotify")
        self.assertEqual(b2s.resolve_effective_dj_mode("privacy", "rotate", "beds"), "spotify")
        self.assertEqual(b2s.resolve_effective_dj_mode("stage", "spotify", "beds"), "beds")

        # 2. `RadioRotationScheduler` in `beds` mode sends `Pause` to active Spotify Connect / browser players
        sched = radio.RadioRotationScheduler()
        players = {
            "spotify": radio.PlayerSnapshot("http://127.0.0.1:3678", "spotify", "Playing", title="Track 1", artist="YurrMom.Com"),
        }
        decs = {"spotify": radio.classify_mpris_track("spotify", "Playing", "Track 1", "YurrMom.Com")}
        target, cmds = sched.step("beds", players, decs, now_mono=100.0)
        self.assertEqual(target, "beds")
        self.assertIn(("spotify", "Pause"), cmds)

        # And at 2:00 AM when returning to `spotify` mode while Spotify is Paused, it sends `Play`!
        players_paused = {
            "spotify": radio.PlayerSnapshot("http://127.0.0.1:3678", "spotify", "Paused", title="Track 1", artist="YurrMom.Com"),
        }
        decs_paused = {"spotify": radio.classify_mpris_track("spotify", "Paused", "Track 1", "YurrMom.Com")}
        target_2am, cmds_2am = sched.step("spotify", players_paused, decs_paused, now_mono=200.0)
        self.assertEqual(target_2am, "spotify")
        self.assertIn(("spotify", "Play"), cmds_2am)

    def test_live_standup_captions_layout_fade_hallucinations_and_srt_export(self):
        """Verifies stand-up 2-line layout + active highlight, hallucination guard, 2.5s fade, and .srt clip export."""
        b2s = _load_b2s()
        cap = b2s.box2_captions

        # 1. Anti-hallucination filter blocks Whisper silence artifacts while allowing real punchlines
        self.assertTrue(cap.is_whisper_hallucination("Thank you for watching!"))
        self.assertTrue(cap.is_whisper_hallucination("Yeah. Yeah. Yeah. Yeah. Yeah."))
        self.assertFalse(cap.is_whisper_hallucination("My family asked what I'm bringing to Thanksgiving dinner."))

        # 2. Rolling 2-line punchy layout caps visible words and highlights the newest 3 words in Stage Gold
        lines, visible = cap.layout_standup_lines(
            "My family asked what I'm bringing to Thanksgiving dinner and apparently unresolved tension wasn't on the list",
            max_words_visible=12,
            max_chars_per_line=34,
            active_tail_words=3,
        )
        self.assertEqual(len(lines), 2)
        flat = [item for ln in lines for item in ln]
        self.assertEqual(len(flat), 12)
        self.assertEqual([w for w, hi in flat if hi], ["on", "the", "list"])
        self.assertIn("unresolved tension", visible)

        # 3. 2.5s silence hold + 0.40s smooth fade-out + actual canvas sprite rendering
        eng = cap.LiveCaptionEngine(enabled=False)
        try:
            ov = cap.LiveCaptionOverlay(eng, config_path="", state_path="", base_w=1280, base_h=720)
            snap = cap.CaptionSnapshot(
                text="Hey thanks for coming out tonight guys!",
                updated_mono=10.2,
                last_speech_mono=10.0,
                is_final=False,
                utterance_id=1,
            )
            self.assertEqual(ov.compute_opacity(snap, 12.0), 1.0)     # within 2.5s hold -> 100% opaque
            self.assertGreater(ov.compute_opacity(snap, 12.7), 0.1)   # mid-fade
            self.assertEqual(ov.compute_opacity(snap, 13.1), 0.0)     # after 2.5 + 0.4s -> completely gone!

            if HAS_NUMPY:
                eng._snapshot = snap
                ov.enabled = True
                canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
                # Off-stage (`is_performer_framed=False`) -> never draws!
                self.assertFalse(ov.draw(canvas, is_performer_framed=False, now_mono=11.0))
                self.assertEqual(int(np.sum(canvas)), 0)
                # On-stage (`is_performer_framed=True`) -> renders crisp bottom-center stand-up caption!
                self.assertTrue(ov.draw(canvas, is_performer_framed=True, now_mono=11.0))
                self.assertGreater(int(np.sum(canvas[520:710, 200:1080])), 50000)
        finally:
            eng.stop()

        # 4. Timestamped `captions.jsonl` -> `.srt` clip export
        with tempfile.TemporaryDirectory() as tmp:
            log_p = Path(tmp) / "captions.jsonl"
            mp4_p = Path(tmp) / "clip_20261127_test.mp4"
            mp4_p.write_bytes(b"fake")
            cap.append_caption_log(log_p, 1002.4, 1005.9, "I'm going to talk to other animals.")
            cap.append_caption_log(log_p, 1006.3, 1008.8, "Hey, thanks for coming up guys.")
            srt_p = cap.export_srt_for_clip(mp4_p, clip_start_epoch=1000.0, clip_end_epoch=1015.0, captions_log=log_p)
            self.assertIsNotNone(srt_p)
            srt_txt = srt_p.read_text(encoding="utf-8")
            self.assertIn("00:00:02,400 --> 00:00:05,900", srt_txt)
            self.assertIn("I'm going to talk to other animals.", srt_txt)
            self.assertIn("00:00:06,300 --> 00:00:08,800", srt_txt)

    def test_p1_signal_integrity_and_fail_closed_audio_authority(self):
        """Verifies P1 room-bound audio provenance (rejecting wrong rooms/stalls) and #I visual quality checks."""
        from stage_director.signal_integrity import (
            AudioAuthorityPolicy,
            SignalIntegrityMonitor,
            discover_authorized_usb_mic,
            measure_visual_quality,
            verify_audio_provenance,
        )

        pol = AudioAuthorityPolicy(
            room_id="box2_stage",
            preferred_usb_alsa_match="StageMic",
            authorized_nvr_mac="ec:71:db:bb:69:56",
            authorized_nvr_channel=0,
            expected_osd_name="Camera1",
            mic_stall_timeout_s=2.5,
        )

        # 1. Verified CH 0 stage mic -> AUTHORIZED
        v_ok = verify_audio_provenance(
            pol, source_kind="nvr_channel", source_id="nvr://10.0.0.6/ch0",
            nvr_mac="ec:71:db:bb:69:56", nvr_channel=0, osd_name="Camera1", last_audio_age_s=0.1,
        )
        self.assertTrue(v_ok.authorized)
        self.assertFalse(v_ok.fail_closed)

        # 2. Reception desk (CH 5) or Parking Lot (CH 1) -> strictly REJECTED (fail-closed!)
        for wrong_ch, wrong_osd in ((5, "reception 1"), (1, "parking lot center"), (4, "recording booth 1")):
            v_bad = verify_audio_provenance(
                pol, source_kind="nvr_channel", source_id=f"nvr://10.0.0.6/ch{wrong_ch}",
                nvr_mac="ec:71:db:bb:69:56", nvr_channel=wrong_ch, osd_name=wrong_osd, last_audio_age_s=0.1,
            )
            self.assertFalse(v_bad.authorized)
            self.assertTrue(v_bad.fail_closed)
            self.assertEqual(v_bad.status_code, "WRONG_ROOM_REJECTED")

        # 3. Disconnected / stalled stage mic (>2.5s) -> fails closed as STAGE_MIC_INTERRUPTED
        v_stall = verify_audio_provenance(
            pol, source_kind="nvr_channel", source_id="nvr://10.0.0.6/ch0",
            nvr_mac="ec:71:db:bb:69:56", nvr_channel=0, osd_name="Camera1", last_audio_age_s=3.4,
        )
        self.assertFalse(v_stall.authorized)
        self.assertTrue(v_stall.fail_closed)
        self.assertEqual(v_stall.status_code, "STAGE_MIC_INTERRUPTED")

        # 4. Dedicated USB wireless stage receiver auto-discovered while ignoring Jetson Tegra APE
        alsa_txt = (
            " 0 [HDA            ]: tegra-hda - NVIDIA Jetson Orin Nano HDA\n"
            " 1 [APE            ]: tegra-ape - NVIDIA Jetson Orin Nano APE\n"
            " 2 [StageMic       ]: USB-Audio - Wireless StageMic Receiver\n"
        )
        usb_found = discover_authorized_usb_mic(alsa_txt, "StageMic")
        self.assertEqual(usb_found[0], 2)

        # 5. #I Monitor + Laplacian sharpness & face-vs-jukebox exposure report
        mon = SignalIntegrityMonitor(policy=pol)
        snap_err = mon.evaluate(
            now_epoch=1000.0, now_mono=10.0, camera_verified=True, camera_source_id="ch0",
            video_fresh=True, audio_verdict=v_stall,
        )
        self.assertEqual(snap_err.status_code, "STAGE_MIC_INTERRUPTED")
        self.assertEqual(snap_err.mic_interruption_count, 1)

        if HAS_NUMPY:
            # Dark stage face (luma=25) + bright neon jukebox on right (luma=230) -> flags underexposed_face!
            img = np.full((360, 640), 25, dtype=np.uint8)
            img[170:320, 470:560] = 230
            vq = measure_visual_quality(img)
            self.assertTrue(vq.underexposed_face)
            self.assertFalse(vq.exposure_balanced)

    def test_p2_autonomous_shot_director_and_slew_concealer(self):
        """Verifies non-metronomic 01 Wide -> 02 Medium -> 03 Close-Up -> Pause/Movement -> Medium & #C conceal."""
        from stage_director.cinematography import OpticalSlewConcealer, ShotDirector, ShotType, ShotVocabularyConfig
        from stage_director.geometry import BoundingBox

        cfg = ShotVocabularyConfig(
            entrance_wide_seconds=6.0,
            min_medium_dwell_seconds=16.0,
            target_closeup_pause_exit_seconds=8.0,
            max_closeup_seconds=14.0,
            stationary_confirm_seconds=4.0,
            optical_zoom_wide_pos=5,
            optical_zoom_medium_pos=10,
            optical_zoom_closeup_pos=14,
        )
        sd = ShotDirector(config=cfg, canvas_width=640)
        face = BoundingBox(280, 110, 36, 36)

        # 01 Entrance -> starts in ESTABLISHING_WIDE (optical pos=5)
        d0 = sd.step(monotonic_seconds=1.0, tracking_state="tracking", face_box=face, is_speaking=True)
        self.assertEqual(d0.shot, ShotType.ESTABLISHING_WIDE)
        self.assertEqual(d0.desired_optical_zoom_pos, 5)

        # After 6.5s entrance -> transitions to 02 MEDIUM and requests optical move to pos=10!
        d_med = sd.step(monotonic_seconds=7.6, tracking_state="tracking", face_box=face, is_speaking=True)
        self.assertEqual(d_med.shot, ShotType.MEDIUM)
        self.assertEqual(d_med.desired_optical_zoom_pos, 10)
        self.assertTrue(d_med.request_optical_move)

        # Stationary expressive delivery for 17s in Medium -> transitions to 03 CLOSE_UP (pos=14)!
        t = 8.0
        for _ in range(34):
            t += 0.5
            d_cu = sd.step(monotonic_seconds=t, tracking_state="tracking", face_box=face, is_speaking=True, recent_speech_age_s=0.2)
        self.assertEqual(d_cu.shot, ShotType.CLOSE_UP)
        self.assertEqual(d_cu.desired_optical_zoom_pos, 14)

        # Hold Close-Up while mid-sentence at +6s, then cleanly return to Medium on natural pause at +8.5s!
        d_mid_joke = sd.step(monotonic_seconds=t + 6.0, tracking_state="tracking", face_box=face, is_speaking=True, utterance_just_committed=False)
        self.assertEqual(d_mid_joke.shot, ShotType.CLOSE_UP)
        d_pause = sd.step(monotonic_seconds=t + 8.5, tracking_state="tracking", face_box=face, is_speaking=False, utterance_just_committed=True)
        self.assertEqual(d_pause.shot, ShotType.MEDIUM)
        self.assertEqual(d_pause.desired_optical_zoom_pos, 10)

        # Tracking loss -> immediate recovery to 01 ESTABLISHING_WIDE (pos=5)
        d_lost = sd.step(monotonic_seconds=t + 12.0, tracking_state="lost", face_box=None)
        self.assertEqual(d_lost.shot, ShotType.ESTABLISHING_WIDE)
        self.assertEqual(d_lost.desired_optical_zoom_pos, 5)

        # #C OpticalSlewConcealer holds sharp pre-slew bridge while AF is blurry, then cross-dissolves when sharp
        if HAS_NUMPY:
            conc = OpticalSlewConcealer(min_slew_hold_s=1.0, max_slew_conceal_s=2.5, dissolve_out_s=0.4, sharpness_floor=25.0)
            pre = np.full((60, 80, 3), 40, dtype=np.uint8)
            live = np.full((60, 80, 3), 200, dtype=np.uint8)
            conc.notify_optical_move_started(pre, now_mono=50.0)
            # At +1.2s with blurry AF (sharpness=8.0 < 25.0) -> still conceals with pre-slew bridge (40)!
            out_blur = conc.blend_if_concealing(live, focus_sharpness=8.0, now_mono=51.2)
            self.assertEqual(int(out_blur[0, 0, 0]), 40)
            # At +1.4s once AF settles sharp (sharpness=48.0 >= 25.0) -> enters smooth dissolve -> settles to 200!
            conc.blend_if_concealing(live, focus_sharpness=48.0, now_mono=51.4)
            out_mid = conc.blend_if_concealing(live, focus_sharpness=48.0, now_mono=51.6)
            self.assertTrue(50 < int(out_mid[0, 0, 0]) < 190)
            out_done = conc.blend_if_concealing(live, focus_sharpness=48.0, now_mono=51.9)
            self.assertEqual(int(out_done[0, 0, 0]), 200)
            self.assertFalse(conc.is_active)


if __name__ == "__main__":
    unittest.main()
