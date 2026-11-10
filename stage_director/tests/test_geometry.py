"""Unit tests for geometry primitives and stage polygon containment."""
import unittest

from stage_director.geometry import BoundingBox, StagePolygon


class GeometryTests(unittest.TestCase):
    def test_bounding_box_properties(self):
        box = BoundingBox(x=100.0, y=200.0, width=50.0, height=80.0, confidence=0.9)
        self.assertEqual(box.left, 100.0)
        self.assertEqual(box.top, 200.0)
        self.assertEqual(box.right, 150.0)
        self.assertEqual(box.bottom, 280.0)
        self.assertEqual(box.center_x, 125.0)
        self.assertEqual(box.center_y, 240.0)
        self.assertEqual(box.center, (125.0, 240.0))
        self.assertEqual(box.area, 4000.0)

    def test_bounding_box_validation(self):
        with self.assertRaises(ValueError):
            BoundingBox(x=0, y=0, width=-10, height=50)
        with self.assertRaises(ValueError):
            BoundingBox(x=0, y=0, width=50, height=0)
        with self.assertRaises(ValueError):
            BoundingBox(x=0, y=0, width=50, height=50, confidence=1.5)

    def test_bounding_box_iou(self):
        b1 = BoundingBox(x=0, y=0, width=100, height=100)
        b2 = BoundingBox(x=50, y=50, width=100, height=100)
        # Intersection: 50x50 = 2500
        # Union: 10000 + 10000 - 2500 = 17500
        # IoU: 2500 / 17500 = 1 / 7 ~= 0.142857
        self.assertAlmostEqual(b1.iou(b2), 2500.0 / 17500.0, places=5)

        # Disjoint boxes
        b3 = BoundingBox(x=200, y=200, width=50, height=50)
        self.assertEqual(b1.iou(b3), 0.0)

    def test_stage_polygon_containment(self):
        # Trapezoid stage:
        # Top edge from (200, 200) to (800, 200)
        # Bottom edge from (100, 900) to (900, 900)
        poly = StagePolygon([
            (200.0, 200.0),
            (800.0, 200.0),
            (900.0, 900.0),
            (100.0, 900.0),
        ])

        # Stage center is inside
        self.assertTrue(poly.contains_point(500.0, 500.0))
        # Point far left offstage
        self.assertFalse(poly.contains_point(50.0, 500.0))
        # Point far right offstage
        self.assertFalse(poly.contains_point(950.0, 500.0))
        # Point above stage
        self.assertFalse(poly.contains_point(500.0, 100.0))
        # Point below stage
        self.assertFalse(poly.contains_point(500.0, 950.0))

    def test_stage_polygon_box_anchors(self):
        poly = StagePolygon.default_stage(3840.0, 2160.0)
        # Performer center stage
        center_face = BoundingBox(x=1870.0, y=700.0, width=100.0, height=120.0)
        self.assertTrue(poly.contains_box(center_face, anchor="center"))

        # Bystander offstage in audience / side wing
        bystander = BoundingBox(x=100.0, y=1000.0, width=100.0, height=120.0)
        self.assertFalse(poly.contains_box(bystander, anchor="center"))


if __name__ == "__main__":
    unittest.main()
