"""Unit tests for JetsonFramePipeline (Milestone 7)."""
from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

try:
    import cv2
    import numpy as np
    HAS_CV2_NUMPY = True
except ImportError:
    cv2 = None
    np = None
    HAS_CV2_NUMPY = False

from stage_director.core import BookingSnapshot, CaptureLifecycle
from stage_director.geometry import BoundingBox
from stage_director.jetson_pipeline import JetsonFramePipeline, PipelineSummary
from stage_director.obs_transform import OBSProposal


class JetsonPipelineSliceTests(unittest.TestCase):
    """Verifies crop slice calculation and clamping invariants in pure Python."""

    def setUp(self) -> None:
        self.pipeline = JetsonFramePipeline(
            output_width=1920,
            output_height=1080,
            source_width=3840,
            source_height=2160,
            target_fps=30,
        )

    def _make_proposal(
        self,
        camera_action: str = "track_face",
        mode: str = "live",
        capture_lifecycle: str = "live_public",
        obs_crop=None,
        framing=None,
    ) -> OBSProposal:
        return OBSProposal(
            schema_version="1.0",
            timestamp_utc="2026-11-10T00:00:00Z",
            monotonic_seconds=1000.0,
            mode=mode,
            camera_action=camera_action,
            tracking_state="tracking",
            subject_lost=False,
            source_resolution={"width": 3840, "height": 2160},
            obs_crop=obs_crop,
            framing=framing,
            events=[],
            capture_lifecycle=capture_lifecycle,
        )

    def test_calculate_crop_slice_default_and_capture_off(self) -> None:
        """Capture off and none crop return full source frame coordinates."""
        proposal_off = self._make_proposal(camera_action="capture_off", obs_crop=None)
        slice_coords = self.pipeline.calculate_crop_slice(proposal_off)
        self.assertEqual(slice_coords, (0, 0, 3840, 2160))

        proposal_no_crop = self._make_proposal(camera_action="stage_wide", obs_crop=None)
        slice_coords = self.pipeline.calculate_crop_slice(proposal_no_crop)
        self.assertEqual(slice_coords, (0, 0, 3840, 2160))

    def test_calculate_crop_slice_active_crop_and_clamping(self) -> None:
        """Active crop produces valid 16:9 pixel bounds clamped within source resolution."""
        proposal_valid = self._make_proposal(
            camera_action="track_face",
            framing={"zoom_factor": 1.5, "center_x": 1920, "center_y": 1080},
            obs_crop={"left": 640, "top": 360, "right": 640, "bottom": 360},
        )
        x1, y1, x2, y2 = self.pipeline.calculate_crop_slice(proposal_valid)
        self.assertEqual((x1, y1, x2, y2), (640, 360, 3200, 1800))
        self.assertEqual(x2 - x1, 2560)
        self.assertEqual(y2 - y1, 1440)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 16.0 / 9.0, places=4)

        # Extreme crop clamping
        proposal_extreme = self._make_proposal(
            camera_action="track_face",
            framing={"zoom_factor": 4.0, "center_x": 1920, "center_y": 1080},
            obs_crop={"left": 4000, "top": 3000, "right": 4000, "bottom": 3000},
        )
        ex1, ey1, ex2, ey2 = self.pipeline.calculate_crop_slice(proposal_extreme)
        self.assertGreaterEqual(ex1, 0)
        self.assertGreaterEqual(ey1, 0)
        self.assertLessEqual(ex2, 3840)
        self.assertLessEqual(ey2, 2160)
        self.assertGreater(ex2, ex1)
        self.assertGreater(ey2, ey1)


@unittest.skipUnless(HAS_CV2_NUMPY, "OpenCV and NumPy required for Jetson frame transformation tests")
class JetsonPipelineTransformTests(unittest.TestCase):
    """Verifies cropping, scaling, fail-closed blackouts, and pipeline execution invariants with NumPy/OpenCV."""

    def setUp(self) -> None:
        self.pipeline = JetsonFramePipeline(
            output_width=1920,
            output_height=1080,
            source_width=3840,
            source_height=2160,
            target_fps=30,
        )

    def _make_proposal(
        self,
        camera_action: str = "track_face",
        mode: str = "live",
        capture_lifecycle: str = "live_public",
        obs_crop=None,
        framing=None,
    ) -> OBSProposal:
        return OBSProposal(
            schema_version="1.0",
            timestamp_utc="2026-11-10T00:00:00Z",
            monotonic_seconds=1000.0,
            mode=mode,
            camera_action=camera_action,
            tracking_state="tracking",
            subject_lost=False,
            source_resolution={"width": 3840, "height": 2160},
            obs_crop=obs_crop,
            framing=framing,
            events=[],
            capture_lifecycle=capture_lifecycle,
        )

    def test_crop_and_scale_frame_fail_closed_black_frame(self) -> None:
        """Capture off or emergency stop must yield a solid black frame (all zeros)."""
        bgr_frame = np.full((2160, 3840, 3), 128, dtype=np.uint8)
        yuv_frame = np.full((3240, 3840), 128, dtype=np.uint8)

        proposal_off = self._make_proposal(camera_action="capture_off", obs_crop=None)

        bgr_out = self.pipeline.crop_and_scale_frame(bgr_frame, proposal_off)
        self.assertEqual(bgr_out.shape, (1080, 1920, 3))
        self.assertEqual(np.count_nonzero(bgr_out), 0)

        yuv_out = self.pipeline.crop_and_scale_frame(yuv_frame, proposal_off)
        self.assertEqual(yuv_out.shape, (1620, 1920))
        self.assertEqual(np.count_nonzero(yuv_out), 0)

        # Emergency stop overrides active tracking
        proposal_track = self._make_proposal(
            camera_action="track_face",
            framing={"zoom_factor": 1.5, "center_x": 1920, "center_y": 1080},
            obs_crop={"left": 640, "top": 360, "right": 640, "bottom": 360},
        )
        self.pipeline.trigger_emergency_stop()
        bgr_emergency = self.pipeline.crop_and_scale_frame(bgr_frame, proposal_track)
        self.assertEqual(bgr_emergency.shape, (1080, 1920, 3))
        self.assertEqual(np.count_nonzero(bgr_emergency), 0)

    def test_crop_and_scale_frame_stage_wide_and_tracking(self) -> None:
        """Transforms active crops and stage-wide to strictly 1920x1080 canvas."""
        bgr_frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        bgr_frame[500:1500, 1000:2500] = 255

        # Stage wide
        proposal_wide = self._make_proposal(
            camera_action="stage_wide",
            framing={"zoom_factor": 1.0, "center_x": 1920, "center_y": 1080},
            obs_crop={"left": 0, "top": 0, "right": 0, "bottom": 0},
        )
        out_wide = self.pipeline.crop_and_scale_frame(bgr_frame, proposal_wide)
        self.assertEqual(out_wide.shape, (1080, 1920, 3))
        self.assertGreater(np.count_nonzero(out_wide), 0)

        # Active crop
        proposal_crop = self._make_proposal(
            camera_action="track_face",
            framing={"zoom_factor": 1.5, "center_x": 1920, "center_y": 1080},
            obs_crop={"left": 640, "top": 360, "right": 640, "bottom": 360},
        )
        out_crop = self.pipeline.crop_and_scale_frame(bgr_frame, proposal_crop)
        self.assertEqual(out_crop.shape, (1080, 1920, 3))
        self.assertGreater(np.count_nonzero(out_crop), 0)

    @patch("subprocess.Popen")
    def test_run_offline_simulation_host_start_and_shutdown(self, mock_popen: MagicMock) -> None:
        """Verifies genuine host-start, live framing, and emergency shutdown."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.closed = False
        mock_popen.return_value = mock_proc

        events = [
            (0.0, [BoundingBox(1800, 800, 200, 260)], None),              # armed, waiting host start
            (0.1, [BoundingBox(1800, 800, 200, 260)], "host_start"),       # host confirms set start
            (0.2, [BoundingBox(1820, 800, 200, 260)], "confirm_first"),     # confirms face
            (0.3, [BoundingBox(1840, 800, 200, 260)], None),              # live tracking
            (0.4, [], "emergency_stop"),                                   # emergency stop
            (0.5, [BoundingBox(1840, 800, 200, 260)], None),              # stopped post-event
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.mp4")

            def mock_wait(*args, **kwargs):
                with open(output_path, "wb") as f:
                    f.write(b"mock_mp4_content")
                return 0

            mock_proc.wait.side_effect = mock_wait

            summary = self.pipeline.run_offline_simulation(
                timeline_events=events,
                output_mp4_path=output_path,
                preset="veryfast",
                realtime_pacing=False,
            )

            self.assertEqual(summary.total_frames_processed, 6)
            self.assertEqual(summary.output_resolution, (1920, 1080))
            self.assertTrue(summary.pts_monotonic)
            self.assertGreater(summary.output_size_bytes, 0)
            self.assertEqual(len(self.pipeline.metrics), 6)

            # Before host start: armed
            self.assertEqual(self.pipeline.metrics[0].mode, "armed")
            self.assertEqual(self.pipeline.metrics[0].camera_action, "stage_wide")
            self.assertEqual(self.pipeline.metrics[0].capture_lifecycle, "armed_public")

            # After host start: live
            self.assertEqual(self.pipeline.metrics[1].mode, "live")
            self.assertEqual(self.pipeline.metrics[1].capture_lifecycle, "live_public")

            # After emergency stop: stopped
            self.assertEqual(self.pipeline.metrics[4].camera_action, "capture_off")
            self.assertEqual(self.pipeline.metrics[4].capture_lifecycle, "stopped")

            # Post-stop iteration 5 had zero reads/writes
            self.assertGreater(summary.dropped_unauthorized_reads, 0)
            self.assertGreater(summary.dropped_unauthorized_writes, 0)

    @patch("subprocess.Popen")
    def test_private_booking_causes_zero_reads_and_writes(self, mock_popen: MagicMock) -> None:
        """A private booking must fail closed immediately with 0 reads and 0 writes."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.closed = False
        mock_popen.return_value = mock_proc

        events = [
            (0.0, [BoundingBox(1800, 800, 200, 260)], "host_start"),
            (0.1, [BoundingBox(1820, 800, 200, 260)], None),
            (0.2, [BoundingBox(1840, 800, 200, 260)], None),
        ]

        t0 = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
        private_booking = BookingSnapshot(
            booking_id="private-session-proof",
            revision=1,
            slot_start_utc=t0,
            slot_end_utc=t0 + timedelta(minutes=15),
            issued_at_utc=t0 - timedelta(seconds=30),
            expires_at_utc=t0 + timedelta(minutes=16),
            stage_seconds=300,
            privacy_class="private",
            checked_in=True,
            live_consent=False,
            tracking_consent=False,
            capture_verified=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "private_test.mp4")

            def mock_wait(*args, **kwargs):
                with open(output_path, "wb") as f:
                    f.write(b"")
                return 0

            mock_proc.wait.side_effect = mock_wait

            summary = self.pipeline.run_offline_simulation(
                timeline_events=events,
                output_mp4_path=output_path,
                booking=private_booking,
                realtime_pacing=False,
            )

            # Private session must cause ZERO source reads and ZERO sink writes
            self.assertEqual(summary.source_reads_count, 0)
            self.assertEqual(summary.sink_writes_count, 0)
            self.assertEqual(summary.dropped_unauthorized_reads, 3)
            self.assertEqual(summary.dropped_unauthorized_writes, 3)
            self.assertEqual(summary.capture_lifecycle, "stopped")

    @patch("subprocess.Popen")
    def test_revoked_consent_terminates_media_immediately(self, mock_popen: MagicMock) -> None:
        """Revoking consent mid-stream immediately halts acquisition and closes sink (0 reads/writes after)."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.closed = False
        mock_popen.return_value = mock_proc

        events = [
            (0.0, [BoundingBox(1800, 800, 200, 260)], "host_start"),
            (0.1, [BoundingBox(1820, 800, 200, 260)], "confirm_first"),
            (0.2, [BoundingBox(1840, 800, 200, 260)], "revoke_consent"),
            (0.3, [BoundingBox(1860, 800, 200, 260)], None),
            (0.4, [BoundingBox(1880, 800, 200, 260)], None),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "revoke_test.mp4")

            def mock_wait(*args, **kwargs):
                with open(output_path, "wb") as f:
                    f.write(b"revoked_output")
                return 0

            mock_proc.wait.side_effect = mock_wait

            summary = self.pipeline.run_offline_simulation(
                timeline_events=events,
                output_mp4_path=output_path,
                realtime_pacing=False,
            )

            # Exact frame count verification:
            # Frames 0 and 1 were authorized (2 reads, 2 writes).
            # Frame 2 commanded revoke_consent -> stopped immediately.
            # Frames 2, 3, 4 had 0 reads, 0 writes.
            self.assertEqual(summary.source_reads_count, 2)
            self.assertEqual(summary.sink_writes_count, 2)
            self.assertEqual(summary.dropped_unauthorized_reads, 3)
            self.assertEqual(summary.dropped_unauthorized_writes, 3)
            self.assertEqual(summary.capture_lifecycle, "stopped")

            # Verify audit event log records media shutdown
            event_types = [e["event_type"] for e in summary.event_log]
            self.assertIn("media_shutdown", event_types)


if __name__ == "__main__":
    unittest.main()
