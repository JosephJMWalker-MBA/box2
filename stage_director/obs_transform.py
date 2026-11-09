"""OBS crop and transform proposals emitted as JSON.

Standard library only. Emits recommendations only; does not connect to OBS.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class OBSProposal:
    """A single OBS crop and scene item transform proposal."""
    schema_version: str
    timestamp_utc: str
    monotonic_seconds: float
    mode: str
    camera_action: str
    tracking_state: str
    subject_lost: bool
    source_resolution: Dict[str, int]
    obs_crop: Optional[Dict[str, int]]
    framing: Optional[Dict[str, Any]]
    events: List[str]
    cue: Optional[str] = None
    remaining_seconds: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)
