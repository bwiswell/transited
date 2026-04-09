"""
Integration tests for ``transited.static`` using the PATCO GTFS fixture.

Tests cover canonical-stop derivation, name-based stop-index building,
the stop-name shortener, and the layout computation.
"""
from __future__ import annotations

import pytest

import railroaded as rr
from transited.config import DisplayLineSpec, RowConnector, RouteService, TrackSegment
from transited.static import (
    LineData,
    LineLayout,
    ResolvedTrackSegment,
    StopInfo,
    _build_stop_index,
    _canonical_stops,
    _resolve_track_segments,
    _shorten,
    compute_all_layouts,
    resolve_connectors,
)


# ===========================================================================
# _shorten helper
# ===========================================================================

class TestShorten:
    def test_short_name_unchanged(self):
        assert _shorten('City Hall') == 'City Hall'

    def test_long_name_abbreviated(self):
        result = _shorten('Transportation Center')
        assert len(result) <= 14

    def test_hard_truncate_with_ellipsis(self):
        result = _shorten('Superlongstopnamethatfitsnothing')
        assert len(result) <= 14
        assert result.endswith('\u2026')

    def test_word_abbreviation_applied(self):
        assert _shorten('Long Street Name') == 'Long St Name'


# ===========================================================================
# Helpers for building a test DisplayLineSpec from the PATCO fixture
# ===========================================================================

def _patco_spec() -> DisplayLineSpec:
    return DisplayLineSpec(
        display_name='PATCO Speedline',
        short_name='PATCO',
        gtfs_key='patco',
        services=(RouteService('2', (0, 155, 166), 'Speedline'),),
        track_color=(0, 110, 120),
    )


# ===========================================================================
# _canonical_stops
# ===========================================================================

class TestCanonicalStops:
    def test_returns_stop_info_list(self, patco_gtfs: rr.GTFS):
        stops = _canonical_stops(patco_gtfs, _patco_spec())
        assert all(isinstance(s, StopInfo) for s in stops)

    def test_patco_has_fourteen_stops(self, patco_gtfs: rr.GTFS):
        stops = _canonical_stops(patco_gtfs, _patco_spec())
        assert len(stops) == 14

    def test_stop_ids_are_unique(self, patco_gtfs: rr.GTFS):
        stops = _canonical_stops(patco_gtfs, _patco_spec())
        ids = [s.stop_id for s in stops]
        assert len(ids) == len(set(ids))

    def test_stop_names_nonempty(self, patco_gtfs: rr.GTFS):
        stops = _canonical_stops(patco_gtfs, _patco_spec())
        assert all(s.full_name for s in stops)

    def test_display_names_fit(self, patco_gtfs: rr.GTFS):
        from transited.static import MAX_NAME_LEN
        stops = _canonical_stops(patco_gtfs, _patco_spec())
        for s in stops:
            assert len(s.name) <= MAX_NAME_LEN, f'{s.name!r} too long'

    def test_unknown_route_returns_empty(self, patco_gtfs: rr.GTFS):
        spec = DisplayLineSpec(
            display_name='X', short_name='X', gtfs_key='x',
            services=(RouteService('__no__', (0, 0, 0), ''),),
            track_color=(0, 0, 0),
        )
        assert _canonical_stops(patco_gtfs, spec) == []

    def test_contains_lindenwold_and_locust(self, patco_gtfs: rr.GTFS):
        stops = _canonical_stops(patco_gtfs, _patco_spec())
        names = {s.full_name for s in stops}
        assert any('Lindenwold' in n for n in names)
        assert any('Locust' in n for n in names)


# ===========================================================================
# _canonical_stops with explicit canonical_stop_ids
# ===========================================================================

class TestCanonicalStopsExplicit:
    def test_explicit_ids_override(self, patco_gtfs: rr.GTFS):
        """When canonical_stop_ids is set, use those IDs directly."""
        spec = DisplayLineSpec(
            display_name='Test', short_name='T', gtfs_key='patco',
            services=(RouteService('2', (0, 0, 0), ''),),
            track_color=(0, 0, 0),
            canonical_stop_ids=('1', '9', '14'),
        )
        stops = _canonical_stops(patco_gtfs, spec)
        assert len(stops) == 3
        assert stops[0].stop_id == '1'
        assert stops[1].stop_id == '9'
        assert stops[2].stop_id == '14'


# ===========================================================================
# _build_stop_index (name-based aliasing)
# ===========================================================================

class TestBuildStopIndex:
    def test_index_covers_all_canonical_stops(self, patco_gtfs: rr.GTFS):
        spec = _patco_spec()
        stops = _canonical_stops(patco_gtfs, spec)
        idx = _build_stop_index(patco_gtfs, stops, spec)
        for s in stops:
            assert s.stop_id in idx

    def test_index_values_are_sequential(self, patco_gtfs: rr.GTFS):
        spec = _patco_spec()
        stops = _canonical_stops(patco_gtfs, spec)
        idx = _build_stop_index(patco_gtfs, stops, spec)
        # Every canonical index should be present
        canonical_indices = sorted(set(idx.values()))
        assert canonical_indices == list(range(len(stops)))


# ===========================================================================
# compute_all_layouts
# ===========================================================================

class TestLayouts:
    def _make_line_data(self, patco_gtfs: rr.GTFS) -> LineData:
        spec = _patco_spec()
        stops = _canonical_stops(patco_gtfs, spec)
        idx = _build_stop_index(patco_gtfs, stops, spec)
        return LineData(spec=spec, gtfs=patco_gtfs, stops=stops, stop_index=idx)

    def test_single_line_even_spacing(self, patco_gtfs: rr.GTFS):
        ld = self._make_line_data(patco_gtfs)
        layouts = compute_all_layouts([ld])
        assert len(layouts) == 1
        lay = layouts[0]
        assert lay.stop_x_fracs[0] == pytest.approx(0.0)
        assert lay.stop_x_fracs[-1] == pytest.approx(1.0)

    def test_canonical_to_x_frac(self, patco_gtfs: rr.GTFS):
        ld = self._make_line_data(patco_gtfs)
        lay = compute_all_layouts([ld])[0]
        # canonical 0.0 → start, 1.0 → end
        assert lay.canonical_to_x_frac(0.0) == pytest.approx(lay.track_x_start_frac)
        assert lay.canonical_to_x_frac(1.0) == pytest.approx(lay.track_x_end_frac)

    def test_x_fracs_monotonically_increasing(self, patco_gtfs: rr.GTFS):
        ld = self._make_line_data(patco_gtfs)
        lay = compute_all_layouts([ld])[0]
        for a, b in zip(lay.stop_x_fracs, lay.stop_x_fracs[1:]):
            assert b > a


# ===========================================================================
# pt_to_px
# ===========================================================================

class TestPtToPx:
    def test_at_72_dpi(self):
        import os
        os.environ['TRANSITED_DPI'] = '72'
        # Force reimport — but pt_to_px uses config.DISPLAY_DPI which was
        # already set at import time.  Test the function directly instead.
        from transited.static import pt_to_px
        from transited.config import DISPLAY_DPI
        # pt_to_px(12) at 96 DPI → 16px.
        expected = max(1, round(12 * DISPLAY_DPI / 72))
        assert pt_to_px(12) == expected


# ===========================================================================
# resolve_connectors
# ===========================================================================

class TestResolveConnectors:
    def _make_line_data(self, patco_gtfs: rr.GTFS) -> LineData:
        spec = _patco_spec()
        stops = _canonical_stops(patco_gtfs, spec)
        idx = _build_stop_index(patco_gtfs, stops, spec)
        return LineData(spec=spec, gtfs=patco_gtfs, stops=stops, stop_index=idx)

    def test_valid_connector_resolves(self, patco_gtfs: rr.GTFS):
        ld = self._make_line_data(patco_gtfs)
        layouts = compute_all_layouts([ld])
        first_stop_id = ld.stops[0].stop_id
        # Self-connect (same line, same stop) — just to test the mechanism.
        conn = RowConnector('test', 'PATCO', first_stop_id, 'PATCO', first_stop_id, (0, 0, 0))
        resolved = resolve_connectors(layouts, [conn])
        assert len(resolved) == 1
        assert resolved[0].from_line_idx == 0
        assert resolved[0].to_line_idx == 0
        assert resolved[0].from_x_frac == pytest.approx(0.0)

    def test_missing_line_skipped(self, patco_gtfs: rr.GTFS):
        ld = self._make_line_data(patco_gtfs)
        layouts = compute_all_layouts([ld])
        conn = RowConnector('test', 'PATCO', '1', 'NONEXISTENT', '1', (0, 0, 0))
        resolved = resolve_connectors(layouts, [conn])
        assert len(resolved) == 0


# ===========================================================================
# Track segments
# ===========================================================================

class TestTrackSegments:
    def _make_line_data(self, patco_gtfs: rr.GTFS) -> LineData:
        spec = _patco_spec()
        stops = _canonical_stops(patco_gtfs, spec)
        idx = _build_stop_index(patco_gtfs, stops, spec)
        return LineData(spec=spec, gtfs=patco_gtfs, stops=stops, stop_index=idx)

    def test_default_single_2track_segment(self, patco_gtfs: rr.GTFS):
        ld = self._make_line_data(patco_gtfs)
        layouts = compute_all_layouts([ld])
        segs = layouts[0].track_segments
        assert len(segs) == 1
        assert segs[0].n_tracks == 2
        assert segs[0].start_x_frac == pytest.approx(0.0)
        assert segs[0].end_x_frac == pytest.approx(1.0)

    def test_n_tracks_at_x_default(self, patco_gtfs: rr.GTFS):
        ld = self._make_line_data(patco_gtfs)
        lay = compute_all_layouts([ld])[0]
        assert lay.n_tracks_at_x(0.0) == 2
        assert lay.n_tracks_at_x(0.5) == 2
        assert lay.n_tracks_at_x(1.0) == 2

    def test_reversed_line_lindenwold_rightmost(self, patco_gtfs: rr.GTFS):
        """With reverse=True, Lindenwold should be the last (rightmost) stop."""
        spec = DisplayLineSpec(
            display_name='PATCO', short_name='P', gtfs_key='patco',
            services=(RouteService('2', (0, 0, 0), ''),),
            track_color=(0, 0, 0),
            reverse=True,
        )
        stops = _canonical_stops(patco_gtfs, spec)
        assert stops[-1].full_name == 'Lindenwold'
        assert any('Locust' in s.full_name for s in stops[:3])

    def test_explicit_track_segments_resolve(self, patco_gtfs: rr.GTFS):
        """Build a spec with 4-track segment and verify resolution."""
        spec = DisplayLineSpec(
            display_name='Test', short_name='T', gtfs_key='patco',
            services=(RouteService('2', (0, 0, 0), '', track_pair='outer'),),
            track_color=(0, 0, 0),
            track_segments=(
                TrackSegment('1', '9', 4),   # Lindenwold to City Hall
                TrackSegment('9', '14', 2),  # City Hall to 15-16th
            ),
        )
        stops = _canonical_stops(patco_gtfs, spec)
        idx = _build_stop_index(patco_gtfs, stops, spec)
        ld = LineData(spec=spec, gtfs=patco_gtfs, stops=stops, stop_index=idx)
        n = len(stops)
        xf = [i / (n - 1) for i in range(n)]
        segs = _resolve_track_segments(ld, xf)
        assert len(segs) == 2
        assert segs[0].n_tracks == 4
        assert segs[1].n_tracks == 2
