"""
Tests for client-side animation: vehicle matching, interpolation,
and heading smoothing.
"""
from __future__ import annotations

import pytest

from transited.realtime.interpolation import VehiclePosition
from transited.ui.animation import (
    RouteSnapshot,
    interpolate_snapshot,
    lerp_heading,
    match_vehicles,
    update_snapshot,
)


def _vp(lat=40.0, lon=-75.0, rid='R1', fwd=True, hdg=90.0) -> VehiclePosition:
    return VehiclePosition(lat=lat, lon=lon, route_id=rid, color=(255, 0, 0),
                           forward=fwd, heading=hdg)


# ---------------------------------------------------------------------------
# match_vehicles
# ---------------------------------------------------------------------------

class TestMatchVehicles:
    def test_empty_prev_returns_all_unmatched(self):
        curr = [_vp(), _vp(lat=40.1)]
        matches, unmatched = match_vehicles([], curr)
        assert matches == []
        assert unmatched == [0, 1]

    def test_exact_match_by_position(self):
        prev = [_vp(lat=40.0, lon=-75.0)]
        curr = [_vp(lat=40.001, lon=-75.001)]
        matches, unmatched = match_vehicles(prev, curr)
        assert len(matches) == 1
        assert matches[0] == (0, 0)
        assert unmatched == []

    def test_no_match_different_direction(self):
        prev = [_vp(fwd=True)]
        curr = [_vp(fwd=False)]
        matches, unmatched = match_vehicles(prev, curr)
        assert matches == []
        assert unmatched == [0]

    def test_no_match_different_route(self):
        prev = [_vp(rid='A')]
        curr = [_vp(rid='B')]
        matches, unmatched = match_vehicles(prev, curr)
        assert matches == []
        assert unmatched == [0]

    def test_multiple_vehicles_nearest_wins(self):
        prev = [_vp(lat=40.0), _vp(lat=40.5)]
        curr = [_vp(lat=40.1), _vp(lat=40.4)]
        matches, _ = match_vehicles(prev, curr)
        # 40.1 should match 40.0, 40.4 should match 40.5
        assert (0, 0) in matches
        assert (1, 1) in matches

    def test_new_vehicle_is_unmatched(self):
        prev = [_vp(lat=40.0)]
        curr = [_vp(lat=40.0), _vp(lat=41.0)]
        matches, unmatched = match_vehicles(prev, curr)
        assert len(matches) == 1
        assert len(unmatched) == 1


# ---------------------------------------------------------------------------
# lerp_heading
# ---------------------------------------------------------------------------

class TestLerpHeading:
    def test_same_heading(self):
        assert lerp_heading(90.0, 90.0, 0.5) == pytest.approx(90.0)

    def test_simple_lerp(self):
        assert lerp_heading(0.0, 90.0, 0.5) == pytest.approx(45.0)

    def test_wraparound_short_arc(self):
        # 350 -> 10 should go through 0, not through 180.
        result = lerp_heading(350.0, 10.0, 0.5)
        assert result == pytest.approx(0.0, abs=0.1)

    def test_wraparound_reverse(self):
        result = lerp_heading(10.0, 350.0, 0.5)
        assert result == pytest.approx(0.0, abs=0.1)

    def test_none_a(self):
        assert lerp_heading(None, 90.0, 0.5) == 90.0

    def test_none_b(self):
        assert lerp_heading(45.0, None, 0.5) == 45.0

    def test_both_none(self):
        assert lerp_heading(None, None, 0.5) is None

    def test_t_zero(self):
        assert lerp_heading(30.0, 60.0, 0.0) == pytest.approx(30.0)

    def test_t_one(self):
        assert lerp_heading(30.0, 60.0, 1.0) == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# update_snapshot + interpolate_snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_first_update(self):
        snap = RouteSnapshot()
        positions = [_vp(lat=40.0, hdg=90.0)]
        update_snapshot(snap, positions, 100.0)
        assert len(snap.curr) == 1
        assert snap.curr_time == 100.0

    def test_second_update_creates_matches(self):
        snap = RouteSnapshot()
        update_snapshot(snap, [_vp(lat=40.0)], 100.0)
        update_snapshot(snap, [_vp(lat=40.01)], 105.0)
        assert len(snap.matches) == 1
        assert snap.prev_time == 100.0
        assert snap.curr_time == 105.0

    def test_interpolate_at_curr_time(self):
        snap = RouteSnapshot()
        update_snapshot(snap, [_vp(lat=40.0, lon=-75.0, hdg=90.0)], 100.0)
        update_snapshot(snap, [_vp(lat=40.1, lon=-75.1, hdg=180.0)], 105.0)
        result = interpolate_snapshot(snap, 105.0)
        assert len(result) == 1
        assert result[0].lat == pytest.approx(40.1, abs=0.01)
        assert result[0].lon == pytest.approx(-75.1, abs=0.01)

    def test_interpolate_midpoint(self):
        # Use positions ~300m apart (realistic 8-second train movement).
        snap = RouteSnapshot()
        update_snapshot(snap, [_vp(lat=40.0000, lon=-75.0000)], 100.0)
        update_snapshot(snap, [_vp(lat=40.003, lon=-75.003)], 110.0)
        # Midpoint: t = (105 - 110) / (110 - 100) + 1 = 0.5
        result = interpolate_snapshot(snap, 105.0)
        assert len(result) == 1
        assert result[0].lat == pytest.approx(40.0015, abs=0.001)
        assert result[0].lon == pytest.approx(-75.0015, abs=0.001)

    def test_interpolate_past_curr_clamps(self):
        snap = RouteSnapshot()
        update_snapshot(snap, [_vp(lat=40.0)], 100.0)
        update_snapshot(snap, [_vp(lat=40.1)], 105.0)
        # Way past curr_time — should clamp to curr position.
        result = interpolate_snapshot(snap, 200.0)
        assert result[0].lat == pytest.approx(40.1, abs=0.01)

    def test_empty_snapshot(self):
        snap = RouteSnapshot()
        assert interpolate_snapshot(snap, 100.0) == []

    def test_unmatched_appear_instantly(self):
        snap = RouteSnapshot()
        update_snapshot(snap, [_vp(lat=40.0, rid='A')], 100.0)
        # New vehicle with different route_id — won't match.
        update_snapshot(snap, [_vp(lat=40.0, rid='A'), _vp(lat=41.0, rid='B')], 105.0)
        result = interpolate_snapshot(snap, 102.5)
        assert len(result) == 2
