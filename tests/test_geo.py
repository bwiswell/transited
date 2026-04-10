"""
Tests for geographic and text-matching utilities.
"""
from __future__ import annotations

import pytest

from transited.geo import fuzzy_match, haversine, normalize_stop_name


class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine(40.0, -75.0, 40.0, -75.0) == pytest.approx(0.0)

    def test_known_distance(self):
        # Philadelphia City Hall to Lindenwold NJ ~18 km
        d = haversine(39.9526, -75.1635, 39.8365, -74.9828)
        assert 15_000 < d < 25_000

    def test_short_distance(self):
        # Two points ~100m apart
        d = haversine(39.9526, -75.1635, 39.9535, -75.1635)
        assert 50 < d < 200


class TestNormalize:
    def test_strips_station(self):
        assert 'fern rock' in normalize_stop_name('Fern Rock Station')

    def test_strips_transit_center(self):
        assert 'transit center' not in normalize_stop_name('Frankford Transit Center')

    def test_strips_direction(self):
        assert 'nb' not in normalize_stop_name('NB Broad & Vine')

    def test_lowercase(self):
        assert normalize_stop_name('8th-Market') == '8th-market'


class TestFuzzyMatch:
    def test_exact_match(self):
        assert fuzzy_match('8th and Market', '8th and Market') == pytest.approx(1.0)

    def test_similar_names(self):
        score = fuzzy_match('8th and Market', '8th-Market')
        assert score > 0.7

    def test_different_names(self):
        score = fuzzy_match('Lindenwold', 'Fern Rock')
        assert score < 0.4

    def test_station_suffix_ignored(self):
        score = fuzzy_match('City Hall Station', 'City Hall')
        assert score > 0.9
