"""
Tests for cross-agency stop matching.
"""
from __future__ import annotations

import pytest

from transited.config import RouteConfig, StopMatchingConfig
from transited.static.stops import (
    MatchedStopGroup,
    RouteData,
    StopInfo,
    match_stops_across_agencies,
)


def _make_rd(agency: str, route_id: str, stops: list[StopInfo]) -> RouteData:
    return RouteData(
        agency_name=agency,
        route_cfg=RouteConfig(id=route_id),
        stops=stops,
        stop_index={s.stop_id: i for i, s in enumerate(stops)},
    )


class TestStopMatching:
    def test_same_location_different_agency_matches(self):
        """Stops < 50m apart from different agencies should auto-match."""
        s1 = StopInfo('A1', '8th Mkt', '8th and Market', lat=39.9525, lon=-75.1554)
        s2 = StopInfo('B1', '8th Mkt', '8th and Market', lat=39.9526, lon=-75.1555)
        rds = [
            _make_rd('SEPTA', 'L1', [s1]),
            _make_rd('PATCO', '2', [s2]),
        ]
        groups = match_stops_across_agencies(rds)
        assert len(groups) == 1
        assert len(groups[0].refs) == 2
        agencies = {r[0] for r in groups[0].refs}
        assert agencies == {'SEPTA', 'PATCO'}

    def test_same_agency_does_not_match(self):
        """Stops from the same agency should not form a cross-agency group."""
        s1 = StopInfo('A1', '8th', '8th', lat=39.95, lon=-75.15)
        s2 = StopInfo('A2', '8th-2', '8th', lat=39.95, lon=-75.15)
        rds = [_make_rd('SEPTA', 'L1', [s1, s2])]
        groups = match_stops_across_agencies(rds)
        assert len(groups) == 0

    def test_distant_stops_do_not_match(self):
        """Stops > 200m apart should not match."""
        s1 = StopInfo('A1', 'Lind', 'Lindenwold', lat=39.8365, lon=-74.9828)
        s2 = StopInfo('B1', 'Fern', 'Fern Rock', lat=40.0413, lon=-75.1133)
        rds = [
            _make_rd('PATCO', '2', [s1]),
            _make_rd('SEPTA', 'B1', [s2]),
        ]
        groups = match_stops_across_agencies(rds)
        assert len(groups) == 0

    def test_nearby_with_similar_names_matches(self):
        """Stops within 200m with similar names should match."""
        s1 = StopInfo('A1', 'City Hall', 'City Hall', lat=39.9525, lon=-75.1635)
        s2 = StopInfo('B1', 'City Hall', 'City Hall Station', lat=39.9527, lon=-75.1632)
        rds = [
            _make_rd('SEPTA', 'B1', [s1]),
            _make_rd('PATCO', '2', [s2]),
        ]
        groups = match_stops_across_agencies(rds)
        assert len(groups) == 1

    def test_nearby_with_different_names_no_match(self):
        """Stops within 200m but with very different names should NOT match
        (unless < 50m)."""
        # ~150m apart, different names
        s1 = StopInfo('A1', 'Walnut', 'Walnut-Locust', lat=39.9490, lon=-75.1640)
        s2 = StopInfo('B1', 'Lombard', 'Lombard-South', lat=39.9475, lon=-75.1640)
        rds = [
            _make_rd('SEPTA', 'B1', [s1]),
            _make_rd('PATCO', '2', [s2]),
        ]
        groups = match_stops_across_agencies(rds)
        assert len(groups) == 0

    def test_configurable_threshold(self):
        """A tighter threshold should reduce matches."""
        s1 = StopInfo('A1', 'City H', 'City Hall', lat=39.9525, lon=-75.1635)
        s2 = StopInfo('B1', 'City H', 'City Hall Station', lat=39.9532, lon=-75.1630)
        rds = [
            _make_rd('SEPTA', 'B1', [s1]),
            _make_rd('PATCO', '2', [s2]),
        ]
        # Default should match (~89m, similar names after normalization).
        assert len(match_stops_across_agencies(rds)) == 1
        # Very tight proximity threshold should not (89m > 50m, names not exact).
        tight = StopMatchingConfig(proximity_meters=50.0, fuzzy_threshold=0.99)
        assert len(match_stops_across_agencies(rds, tight)) == 0

    def test_transitive_closure(self):
        """If A matches B and B matches C, all three should group."""
        s1 = StopInfo('A1', '8th', '8th and Market', lat=39.9525, lon=-75.1554)
        s2 = StopInfo('B1', '8th', '8th and Market', lat=39.9526, lon=-75.1555)
        s3 = StopInfo('C1', '8th', '8th & Market St', lat=39.9524, lon=-75.1553)
        rds = [
            _make_rd('AgencyA', 'R1', [s1]),
            _make_rd('AgencyB', 'R2', [s2]),
            _make_rd('AgencyC', 'R3', [s3]),
        ]
        groups = match_stops_across_agencies(rds)
        assert len(groups) == 1
        assert len(groups[0].refs) == 3

    def test_empty_input(self):
        assert match_stops_across_agencies([]) == []

    def test_centroid_computed(self):
        s1 = StopInfo('A1', '8th', '8th', lat=40.0, lon=-75.0)
        s2 = StopInfo('B1', '8th', '8th', lat=40.0, lon=-75.0)
        rds = [
            _make_rd('X', 'R1', [s1]),
            _make_rd('Y', 'R2', [s2]),
        ]
        groups = match_stops_across_agencies(rds)
        assert len(groups) == 1
        assert groups[0].lat == pytest.approx(40.0)
        assert groups[0].lon == pytest.approx(-75.0)
