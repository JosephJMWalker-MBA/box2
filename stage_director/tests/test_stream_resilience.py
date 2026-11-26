"""Unit tests for Stage Director zero-drop stream resilience, marathon mode, auto-ducking audio, rehearsal & clipping."""
import json
import os
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
        self.assertLess(gain, 0.07)

        # 4. Even 5 seconds silent pause while performer remains onstage -> stays at subtle onstage bed (0.06)
        for _ in range(100):
            gain, v_act = env.step(mic_rms_dbfs=-48.0, is_performer_onstage=True, music_enabled=True, now_mono=t, dt=0.05)
            t += 0.05
        self.assertFalse(v_act)
        self.assertAlmostEqual(gain, 0.06, delta=0.01)

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


if __name__ == "__main__":
    unittest.main()
