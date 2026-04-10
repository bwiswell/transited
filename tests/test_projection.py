"""
Tests for the Web Mercator projection.
"""
from __future__ import annotations

import pytest

from transited.ui.map.projection import BoundingBox, MapProjection


class TestBoundingBox:
    def test_from_points_basic(self):
        pts = [(39.95, -75.16), (39.83, -74.98)]
        bb = BoundingBox.from_points(pts, padding=0.0)
        # With padding=0.0 and distinct points, min fallback padding applies.
        assert bb.min_lat <= 39.83
        assert bb.max_lat >= 39.95
        assert bb.min_lon <= -75.16
        assert bb.max_lon >= -74.98

    def test_from_points_with_padding(self):
        pts = [(40.0, -75.0), (40.0, -75.0)]  # single point
        bb = BoundingBox.from_points(pts, padding=0.1)
        assert bb.min_lat < 40.0
        assert bb.max_lat > 40.0

    def test_center(self):
        bb = BoundingBox(min_lat=39.0, min_lon=-76.0, max_lat=41.0, max_lon=-74.0)
        lat, lon = bb.center
        assert lat == pytest.approx(40.0)
        assert lon == pytest.approx(-75.0)


class TestProjectionRoundTrip:
    """project() and unproject() should round-trip."""

    def test_center_projects_to_screen_center(self):
        proj = MapProjection(1000, 800)
        bb = BoundingBox(min_lat=39.8, min_lon=-75.2, max_lat=40.0, max_lon=-75.0)
        proj.fit(bb)
        cx, cy = proj.project(*bb.center)
        assert abs(cx - 500) < 2
        assert abs(cy - 400) < 2

    def test_round_trip_accuracy(self):
        proj = MapProjection(1920, 1080)
        bb = BoundingBox(min_lat=39.8, min_lon=-75.3, max_lat=40.1, max_lon=-74.9)
        proj.fit(bb)
        # Test several points.
        for lat, lon in [(39.9, -75.1), (40.0, -75.0), (39.85, -75.2)]:
            px, py = proj.project(lat, lon)
            rlat, rlon = proj.unproject(px, py)
            assert rlat == pytest.approx(lat, abs=0.001)
            assert rlon == pytest.approx(lon, abs=0.001)

    def test_corners_are_on_screen(self):
        proj = MapProjection(800, 600)
        bb = BoundingBox(min_lat=39.8, min_lon=-75.2, max_lat=40.0, max_lon=-75.0)
        proj.fit(bb)
        # All corners of the bbox should project inside the screen.
        for lat in (bb.min_lat, bb.max_lat):
            for lon in (bb.min_lon, bb.max_lon):
                px, py = proj.project(lat, lon)
                assert -50 < px < 850
                assert -50 < py < 650


class TestPanZoom:
    def test_pan_shifts_projection(self):
        proj = MapProjection(800, 600)
        bb = BoundingBox(min_lat=39.8, min_lon=-75.2, max_lat=40.0, max_lon=-75.0)
        proj.fit(bb)
        lat, lon = bb.center
        px1, py1 = proj.project(lat, lon)
        proj.pan(100, 0)  # shift right 100px
        px2, py2 = proj.project(lat, lon)
        assert px2 == pytest.approx(px1 + 100, abs=1)
        assert py2 == pytest.approx(py1, abs=1)

    def test_zoom_changes_scale(self):
        proj = MapProjection(800, 600)
        bb = BoundingBox(min_lat=39.8, min_lon=-75.2, max_lat=40.0, max_lon=-75.0)
        proj.fit(bb)
        old_scale = proj.scale
        proj.zoom_at(400, 300, 2.0)
        assert proj.scale == pytest.approx(old_scale * 2.0)

    def test_zoom_at_keeps_point_fixed(self):
        proj = MapProjection(800, 600)
        bb = BoundingBox(min_lat=39.8, min_lon=-75.2, max_lat=40.0, max_lon=-75.0)
        proj.fit(bb)
        # Pick an off-center point.
        lat, lon = 39.9, -75.15
        px_before, py_before = proj.project(lat, lon)
        proj.zoom_at(px_before, py_before, 1.5)
        px_after, py_after = proj.project(lat, lon)
        assert abs(px_after - px_before) < 2
        assert abs(py_after - py_before) < 2
