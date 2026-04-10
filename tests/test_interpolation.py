"""
Unit tests for the vehicle-position interpolation kernel.

Moved from test_realtime.py — tests the pure ``positions_from_points``
function with no network or GTFS dependencies.
"""
from __future__ import annotations

import pytest

from transited.realtime.interpolation import positions_from_points


# ---------------------------------------------------------------------------
# Edge cases — should return None
# ---------------------------------------------------------------------------

class TestNoPosition:
    def test_empty_points(self):
        assert positions_from_points([], now_secs=1000, n_stops=4) is None

    def test_single_point(self):
        assert positions_from_points([(0, 1000)], now_secs=1000, n_stops=4) is None

    def test_trip_not_yet_started(self):
        pts = [(0, 3600), (3, 7200)]
        assert positions_from_points(pts, now_secs=3599, n_stops=4) is None

    def test_trip_already_finished(self):
        pts = [(0, 3600), (3, 7200)]
        assert positions_from_points(pts, now_secs=7201, n_stops=4) is None

    def test_n_stops_zero(self):
        assert positions_from_points([(0, 100), (1, 200)], 150, n_stops=0) is None

    def test_n_stops_one(self):
        assert positions_from_points([(0, 100), (1, 200)], 150, n_stops=1) is None


class TestBoundary:
    def test_exactly_at_first_stop(self):
        r = positions_from_points([(0, 3600), (3, 7200)], 3600, n_stops=4)
        assert r is not None
        frac, fwd = r
        assert frac == pytest.approx(0.0)

    def test_exactly_at_last_stop(self):
        r = positions_from_points([(0, 3600), (3, 7200)], 7200, n_stops=4)
        assert r is not None
        frac, _ = r
        assert frac == pytest.approx(1.0)

    def test_track_frac_always_clamped_to_01(self):
        r = positions_from_points([(0, 0), (10, 1000)], 500, n_stops=5)
        if r is not None:
            assert 0.0 <= r[0] <= 1.0


class TestPosition:
    def test_midpoint_two_stops(self):
        r = positions_from_points([(0, 0), (3, 1000)], 500, n_stops=4)
        assert r is not None
        assert r[0] == pytest.approx(0.5, abs=0.01)

    def test_quarter_point(self):
        r = positions_from_points([(0, 0), (4, 4000)], 1000, n_stops=5)
        assert r is not None
        assert r[0] == pytest.approx(0.25, abs=0.01)

    def test_multi_segment_correct_segment(self):
        pts = [(0, 0), (1, 1000), (2, 2000), (3, 3000)]
        r = positions_from_points(pts, 1500, n_stops=4)
        assert r is not None
        assert r[0] == pytest.approx(0.5, abs=0.01)

    def test_first_segment(self):
        pts = [(0, 0), (1, 1000), (2, 2000), (3, 3000)]
        r = positions_from_points(pts, 500, n_stops=4)
        assert r is not None
        assert r[0] == pytest.approx(0.5 / 3, abs=0.01)

    def test_last_segment(self):
        pts = [(0, 0), (1, 1000), (2, 2000), (3, 3000)]
        r = positions_from_points(pts, 2500, n_stops=4)
        assert r is not None
        assert r[0] == pytest.approx(2.5 / 3, abs=0.01)


class TestDirection:
    def test_forward_trip(self):
        r = positions_from_points([(0, 0), (3, 3000)], 0, n_stops=4)
        assert r is not None and r[1] is True

    def test_reverse_trip_at_start(self):
        r = positions_from_points([(3, 0), (0, 3000)], 0, n_stops=4)
        assert r is not None
        assert r[1] is False
        assert r[0] == pytest.approx(1.0)

    def test_reverse_trip_at_end(self):
        r = positions_from_points([(3, 0), (0, 3000)], 3000, n_stops=4)
        assert r is not None
        assert r[1] is False
        assert r[0] == pytest.approx(0.0)

    def test_reverse_trip_midpoint(self):
        r = positions_from_points([(3, 0), (0, 3000)], 1500, n_stops=4)
        assert r is not None
        assert r[1] is False
        assert r[0] == pytest.approx(0.5, abs=0.01)


class TestRobustness:
    def test_zero_duration_segment(self):
        r = positions_from_points([(0, 1000), (1, 1000), (2, 2000)], 1000, n_stops=3)
        assert r is not None

    def test_overnight_times_above_86400(self):
        first = 23 * 3600
        last = 25 * 3600
        mid = (first + last) // 2
        r = positions_from_points([(0, first), (3, last)], mid, n_stops=4)
        assert r is not None
        assert r[0] == pytest.approx(0.5, abs=0.01)
