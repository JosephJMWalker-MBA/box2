"""BOX2 Stage Director: offline, privacy-gated decision and framing prototype."""
from .core import BookingSnapshot, CameraAction, Cue, Decision, Mode, StageDirector
from .geometry import BoundingBox, StagePolygon
from .framing import FramingConfig, FramingEngine, FramingWindow
from .tracking import PerformerTracker, TrackingResult, TrackingState
from .obs_transform import OBSProposal
from .adapter import StageFramingAdapter

__all__ = [
    "BookingSnapshot",
    "CameraAction",
    "Cue",
    "Decision",
    "Mode",
    "StageDirector",
    "BoundingBox",
    "StagePolygon",
    "FramingConfig",
    "FramingEngine",
    "FramingWindow",
    "PerformerTracker",
    "TrackingResult",
    "TrackingState",
    "OBSProposal",
    "StageFramingAdapter",
]
