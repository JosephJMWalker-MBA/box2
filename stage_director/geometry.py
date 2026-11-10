"""Geometry primitives for stage areas and face bounding boxes.

Standard library only. All coordinates in pixels or normalized units.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence, Tuple


@dataclass(frozen=True)
class BoundingBox:
    """Bounding box representing a detected object or face.

    Coordinates represent top-left (x, y) and dimensions (width, height).
    """
    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0

    @property
    def center(self) -> Tuple[float, float]:
        return (self.center_x, self.center_y)

    @property
    def area(self) -> float:
        return self.width * self.height

    def iou(self, other: BoundingBox) -> float:
        """Compute Intersection-over-Union (IoU) with another bounding box."""
        ix1 = max(self.left, other.left)
        iy1 = max(self.top, other.top)
        ix2 = min(self.right, other.right)
        iy2 = min(self.bottom, other.bottom)

        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        intersection = iw * ih

        if intersection <= 0.0:
            return 0.0

        union = self.area + other.area - intersection
        if union <= 0.0:
            return 0.0
        return intersection / union

    def distance_to(self, other: BoundingBox) -> float:
        """Euclidean distance between bounding box centers."""
        dx = self.center_x - other.center_x
        dy = self.center_y - other.center_y
        return math.hypot(dx, dy)


@dataclass(frozen=True)
class StagePolygon:
    """2D polygon enclosing the authorized physical performance stage.

    Any detection outside this polygon is considered an offstage bystander
    or audience member and must be excluded from performer tracking.
    """
    vertices: Tuple[Tuple[float, float], ...]

    def __init__(self, vertices: Sequence[Tuple[float, float]]) -> None:
        if len(vertices) < 3:
            raise ValueError("A stage polygon must have at least 3 vertices")
        object.__setattr__(self, "vertices", tuple(vertices))

    def contains_point(self, x: float, y: float) -> bool:
        """Ray-casting algorithm to test if point (x, y) is inside the polygon."""
        inside = False
        n = len(self.vertices)
        for i in range(n):
            x1, y1 = self.vertices[i]
            x2, y2 = self.vertices[(i + 1) % n]
            # Check if horizontal ray from (x, y) crosses edge (x1, y1)-(x2, y2)
            if (y1 > y) != (y2 > y):
                # Calculate X coordinate where edge crosses horizontal line y
                edge_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                if x < edge_x:
                    inside = not inside
        return inside

    def contains_box(self, box: BoundingBox, *, anchor: str = "center") -> bool:
        """Test if a bounding box is within the stage polygon using the chosen anchor."""
        if anchor == "center":
            return self.contains_point(box.center_x, box.center_y)
        if anchor == "bottom":
            return self.contains_point(box.center_x, box.bottom)
        if anchor == "top":
            return self.contains_point(box.center_x, box.top)
        raise ValueError(f"Unknown anchor: {anchor}; expected 'center', 'bottom', or 'top'")

    @classmethod
    def default_stage(cls, canvas_width: float = 3840.0,
                      canvas_height: float = 2160.0) -> StagePolygon:
        """Standard default stage trapezoid within a 16:9 canvas."""
        return cls([
            (canvas_width * 0.15, canvas_height * 0.20),
            (canvas_width * 0.85, canvas_height * 0.20),
            (canvas_width * 0.92, canvas_height * 0.95),
            (canvas_width * 0.08, canvas_height * 0.95),
        ])
