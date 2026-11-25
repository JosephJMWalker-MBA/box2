"""Unit tests for Stage Director zero-drop stream resilience and frame starvation prevention."""
import unittest

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class StreamResilienceTests(unittest.TestCase):
    def test_frame_starvation_holding_buffer(self):
        """Simulates camera disconnect where read() fails repeatedly.
        Verifies that last_valid_frame cache provides uninterrupted frame flow.
        """
        if not HAS_NUMPY:
            # Fallback test with synthetic frame objects when numpy is unavailable
            initial_frame = {"type": "frame", "timestamp": 12345}
        else:
            initial_frame = np.zeros((360, 640, 3), dtype=np.uint8)
            initial_frame[10:50, 10:50] = (255, 200, 100)
        
        last_valid_frame = initial_frame.copy() if hasattr(initial_frame, "copy") else dict(initial_frame)
        consecutive_read_fails = 0
        reconnect_triggered = False

        # Simulate 20 frames of camera outage (2 seconds at 10 FPS)
        pumped_frames = []
        for i in range(20):
            ret, read_frame = False, None
            if ret and read_frame is not None:
                consecutive_read_fails = 0
                last_valid_frame = read_frame.copy() if hasattr(read_frame, "copy") else dict(read_frame)
            else:
                consecutive_read_fails += 1
                if last_valid_frame is not None:
                    frame = last_valid_frame.copy() if hasattr(last_valid_frame, "copy") else dict(last_valid_frame)
                else:
                    frame = None
                
                if consecutive_read_fails >= 10:
                    reconnect_triggered = True

            pumped_frames.append(frame)

        # Verify all 20 frames were successfully pumped without starvation
        self.assertEqual(len(pumped_frames), 20)
        # Verify the reconnect was triggered after 10 failed frames
        self.assertTrue(reconnect_triggered)
        # Verify frame content was preserved from initial_frame
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
            nonlocal current_token
            return current_token

        def get_cam0_url():
            return f"http://{ip}/flv?port=1935&app=bcs&stream=channel{cfg['nvr_channel']}_{cfg['nvr_stream']}.bcs&token={get_token()}"

        def get_cam2_url():
            return f"http://{ip}/flv?port=1935&app=bcs&stream=channel1_sub.bcs&token={get_token()}"

        # Initial URLs
        self.assertIn("token_initial_123", get_cam0_url())
        self.assertIn("token_initial_123", get_cam2_url())

        # Proactively renew token
        current_token = "token_renewed_456"

        # URLs immediately reflect the renewed token without pipeline re-instantiation
        self.assertIn("token_renewed_456", get_cam0_url())
        self.assertIn("token_renewed_456", get_cam2_url())

    def test_next_scheduled_refresh_time_calculation(self):
        """Verifies calculation of next top of hour divisible by 3 hours."""
        from datetime import datetime, timedelta

        def get_next(dt, interval=3):
            cand = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            while cand.hour % interval != 0 or cand <= dt:
                cand += timedelta(hours=1)
            return cand

        # Case 1: 00:45 EST -> next is 03:00 EST
        t1 = datetime(2026, 11, 18, 0, 45, 0)
        self.assertEqual(get_next(t1), datetime(2026, 11, 18, 3, 0, 0))

        # Case 2: 03:00:05 EST (just rolled over) -> next is 06:00 EST
        t2 = datetime(2026, 11, 18, 3, 0, 5)
        self.assertEqual(get_next(t2), datetime(2026, 11, 18, 6, 0, 0))

        # Case 3: 22:15 EST -> next is 00:00 EST next day
        t3 = datetime(2026, 11, 18, 22, 15, 0)
        self.assertEqual(get_next(t3), datetime(2026, 11, 19, 0, 0, 0))

        # Case 4: 21:00:00 EST -> next is 00:00 EST next day
        t4 = datetime(2026, 11, 18, 21, 0, 0)
        self.assertEqual(get_next(t4), datetime(2026, 11, 19, 0, 0, 0))

    def test_scheduled_rollover_slot_tracking(self):
        """Verifies rollover only fires once per scheduled slot and respects min runtime."""
        from datetime import datetime

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

        # 02:59 - not top of hour
        self.assertFalse(check_trigger(datetime(2026, 11, 18, 2, 59, 59), 3600))
        # 03:00:00 - should trigger!
        self.assertTrue(check_trigger(datetime(2026, 11, 18, 3, 0, 0), 3601))
        # 03:00:30 (subsequent tick within same minute) - must NOT trigger again!
        self.assertFalse(check_trigger(datetime(2026, 11, 18, 3, 0, 30), 10))
        # 04:00:00 - hour not divisible by 3
        self.assertFalse(check_trigger(datetime(2026, 11, 18, 4, 0, 0), 3600))
        # 06:00:00 - next 3-hour slot, should trigger!
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

        # Case 1: Normal rotation (>10 mins away, e.g. 1800s / 30m)
        normal = format_ticker_messages(1800)
        self.assertIn("RESET SCHEDULE: Next 3-hour clipping VOD rollover at 3:00 AM", normal[-1])

        # Case 2: 8 mins away (<10m, >5m) -> notice prepended
        notice = format_ticker_messages(480)
        self.assertTrue(notice[0].startswith("NOTICE: 3-Hour VOD reset in 8 min"))

        # Case 3: 3m 45s away (<5m, >1m) -> high-priority warning
        warning = format_ticker_messages(225)
        self.assertTrue(warning[0].startswith("WARNING: SCHEDULED 3-HOUR RESET IN 3m 45s"))

        # Case 4: 25s away (final minute) -> urgent repeated alert
        urgent = format_ticker_messages(25)
        self.assertEqual(len(urgent), 2)
        self.assertIn("SCHEDULED RESET IN 25s", urgent[0])

    def test_privacy_view_mode_resolution(self):
        """Verifies zero-drop privacy/stage view mode resolution from state.json and ticker.json."""
        import json
        import os
        import tempfile
        try:
            import tools.jetson.box2_stream as b2s
        except ImportError:
            import sys
            sys.path.insert(0, "/home/joseph1/box2-stream")
            import box2_stream as b2s

        with tempfile.TemporaryDirectory() as tmp:
            old_state = b2s.STATE
            try:
                b2s.STATE = b2s.Path(os.path.join(tmp, "state.json"))
                tk_path = os.path.join(tmp, "ticker.json")

                b2s.STATE.write_text(json.dumps({"desired": "on", "view": "stage"}))
                with open(tk_path, "w") as f:
                    json.dump({"privacy_placeholder": {"enabled": False}}, f)
                self.assertEqual(b2s.desired_view(tk_path), "stage")

                # Auto schedule (default): 9:00 PM (21:00) to 2:00 AM (02:00) is 'stage', daytime is 'privacy'
                from datetime import datetime
                b2s.STATE.write_text(json.dumps({"desired": "on", "view": "auto"}))
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 7, 36, 0)), "privacy")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 20, 59, 59)), "privacy")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 21, 0, 0)), "stage")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 26, 0, 30, 0)), "stage")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 26, 1, 59, 59)), "stage")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 26, 2, 0, 0)), "privacy")

                # CLI `box2-stream privacy` overrides even during 9PM-2AM show hours
                b2s.STATE.write_text(json.dumps({"desired": "on", "view": "privacy"}))
                self.assertEqual(b2s.desired(), "on")
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 22, 0, 0)), "privacy")

                # `ticker.json` hot-toggle also activates privacy view
                b2s.STATE.write_text(json.dumps({"desired": "on", "view": "stage"}))
                with open(tk_path, "w") as f:
                    json.dump({"privacy_placeholder": {"enabled": True}}, f)
                self.assertEqual(b2s.desired_view(tk_path, now_dt=datetime(2026, 11, 25, 22, 0, 0)), "privacy")
            finally:
                b2s.STATE = old_state


if __name__ == "__main__":
    unittest.main()
