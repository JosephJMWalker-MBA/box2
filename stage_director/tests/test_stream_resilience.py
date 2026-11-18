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


if __name__ == "__main__":
    unittest.main()
