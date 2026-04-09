"""
Static GTFS data loading and layout computation for transited.

Responsibilities
----------------
1. Download / cache each unique GTFS source as mGTFS JSON.
2. Derive the canonical ordered stop list for each display line.
3. Build a name-based stop_index that maps **every** directional variant
   of a station to the same canonical index (SEPTA uses different stop_ids
   for northbound vs southbound platforms).
4. Compute per-stop x-fractions that respect cross-line alignment anchors.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import railroaded as rr

from .config import (
    BranchSpec,
    DISPLAY_DPI,
    FONT_LABEL_PT,
    FONT_STOP_PT,
    GTFS_SOURCES,
    LINES,
    ROW_CONNECTORS,
    STOP_NAME_ANGLE_DEG,
    TICK_HALF,
    TRAIN_H,
    TRAIN_OFFSET,
    DisplayLineSpec,
    RowConnector,
)

# Project-level data directory (alongside pyproject.toml).
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))

# ---------------------------------------------------------------------------
# Name abbreviation
# ---------------------------------------------------------------------------
_ABBREV = {
    'Street':         'St',
    'Avenue':         'Ave',
    'Boulevard':      'Blvd',
    'Station':        'Sta',
    'Center':         'Ctr',
    'Transportation': 'Trans',
    'Terminal':       'Term',
    'Square':         'Sq',
    'Transit':        'Tran',
}

MAX_NAME_LEN = 14


def _shorten(name: str) -> str:
    """Abbreviate common words then hard-truncate to *MAX_NAME_LEN* chars."""
    if len(name) <= MAX_NAME_LEN:
        return name
    short = ' '.join(_ABBREV.get(w, w) for w in name.split())
    if len(short) <= MAX_NAME_LEN:
        return short
    return name[:MAX_NAME_LEN - 1] + '\u2026'


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------

@dataclass
class StopInfo:
    """A single stop in a line's canonical sequence."""
    stop_id:   str
    name:      str     # display name (already shortened)
    full_name: str     # original GTFS stop_name


@dataclass
class LineData:
    """All static data needed for one display line before layout."""
    spec:       DisplayLineSpec
    gtfs:       rr.GTFS
    stops:      list[StopInfo]         # canonical order, left → right
    stop_index: dict[str, int]         # stop_id (any variant) → canonical idx


@dataclass
class ResolvedTrackSegment:
    """A contiguous section with a known number of physical tracks."""
    start_idx:    int     # canonical stop index
    end_idx:      int
    n_tracks:     int     # 2 or 4
    start_x_frac: float
    end_x_frac:   float


@dataclass
class BranchLayout:
    """A branch rendered within its parent row (e.g. Broad-Ridge Spur)."""
    branch_spec:   BranchSpec
    stops:         list[StopInfo]
    stop_x_fracs:  list[float]
    stop_index:    dict[str, int]       # stop_id (any variant) -> branch canonical idx
    junction_x_frac: float              # x of junction on main line
    y_offset_px:   int                  # px below main track centreline

    def canonical_to_x_frac(self, canonical_frac: float) -> float:
        s = self.stop_x_fracs[0] if self.stop_x_fracs else 0.0
        e = self.stop_x_fracs[-1] if self.stop_x_fracs else 1.0
        return s + canonical_frac * (e - s)


@dataclass
class LineLayout:
    """Fully positioned display line — ready for rendering."""
    line_data:          LineData
    stop_x_fracs:       list[float]
    track_x_start_frac: float
    track_x_end_frac:   float
    track_segments:     list[ResolvedTrackSegment]
    branches:           list[BranchLayout]          # may be empty

    def canonical_to_x_frac(self, canonical_frac: float) -> float:
        """Map a [0, 1] canonical fraction to the layout's x-frac space."""
        s, e = self.track_x_start_frac, self.track_x_end_frac
        return s + canonical_frac * (e - s)

    def n_tracks_at_x(self, x_frac: float) -> int:
        """Return the number of physical tracks at a given x-frac."""
        for seg in self.track_segments:
            if seg.start_x_frac <= x_frac <= seg.end_x_frac:
                return seg.n_tracks
        return 2  # default


# ---------------------------------------------------------------------------
# Canonical stop derivation
# ---------------------------------------------------------------------------

def _canonical_stops(gtfs: rr.GTFS, spec: DisplayLineSpec) -> list[StopInfo]:
    """
    Return the ordered canonical stop list for *spec*.

    If *spec.canonical_stop_ids* is set, those stop IDs are used directly.
    Otherwise the longest trip on ``services[0].route_id`` is used.
    If *spec.reverse* is ``True`` the list is reversed (flips left ↔ right).
    """
    if spec.canonical_stop_ids:
        result: list[StopInfo] = []
        for sid in spec.canonical_stop_ids:
            stop = gtfs.stops[sid]
            full = stop.name if stop else sid
            result.append(StopInfo(stop_id=sid, name=_shorten(full), full_name=full))
        if spec.reverse:
            result.reverse()
        return result

    primary = spec.services[0].route_id
    trips = gtfs.on_route(primary).trips.trips
    if not trips:
        return []
    best = max(trips, key=lambda t: len(t.timetable.stops))
    result: list[StopInfo] = []
    for st in best.timetable.stops:
        if st.stop_id is None:
            continue
        stop = gtfs.stops[st.stop_id]
        full = stop.name if stop else st.stop_id
        result.append(StopInfo(stop_id=st.stop_id, name=_shorten(full), full_name=full))
    if spec.reverse:
        result.reverse()
    return result


# ---------------------------------------------------------------------------
# Name-based stop_index builder
# ---------------------------------------------------------------------------

def _build_stop_index(
    gtfs: rr.GTFS,
    canonical_stops: list[StopInfo],
    spec: DisplayLineSpec,
) -> dict[str, int]:
    """
    Build a ``stop_id → canonical_index`` mapping.

    Starts with the canonical stop IDs, then scans **all** trips on every
    route in *spec.services* and adds any stop whose station name matches a
    canonical stop.  This picks up SEPTA's directional platform IDs
    automatically.
    """
    name_to_idx: dict[str, int] = {s.full_name: i for i, s in enumerate(canonical_stops)}
    stop_index:  dict[str, int] = {s.stop_id: i for i, s in enumerate(canonical_stops)}

    # Pre-load explicit aliases from config.
    for alias_id, canon_id in spec.stop_aliases:
        if canon_id in stop_index:
            stop_index[alias_id] = stop_index[canon_id]

    # Scan every trip on every service route.
    for svc in spec.services:
        for trip in gtfs.on_route(svc.route_id).trips.trips:
            for st in trip.timetable.stops:
                if st.stop_id is None or st.stop_id in stop_index:
                    continue
                stop = gtfs.stops[st.stop_id]
                if stop:
                    idx = name_to_idx.get(stop.name)
                    if idx is not None:
                        stop_index[st.stop_id] = idx
    return stop_index


# ---------------------------------------------------------------------------
# GTFS loading entry point
# ---------------------------------------------------------------------------

def _strip_gtfs(gtfs: rr.GTFS, route_ids: tuple[str, ...]) -> rr.GTFS:
    """
    Return a copy of *gtfs* containing only trips on *route_ids* and
    only the stops/routes/schedules those trips reference.

    This dramatically reduces the mGTFS file size when the source feed
    covers many routes (SEPTA bus GTFS has hundreds of bus routes but we
    only need L1, B1, B2, B3).
    """
    from railroaded.tables import Routes, Stops, Schedules, Trips

    keep_routes = set(route_ids)

    # Filter trips.
    kept_trips: dict[str, object] = {}
    kept_stop_ids: set[str] = set()
    kept_service_ids: set[str] = set()
    for trip in gtfs.trips.trips:
        if trip.route_id in keep_routes:
            kept_trips[trip.id] = trip
            kept_service_ids.add(trip.service_id)
            for st in trip.timetable.stops:
                if st.stop_id:
                    kept_stop_ids.add(st.stop_id)

    # Filter routes.
    kept_route_data = {rid: gtfs.routes[rid] for rid in keep_routes
                       if gtfs.routes[rid] is not None}

    # Filter stops.
    kept_stop_data = {sid: gtfs.stops[sid] for sid in kept_stop_ids
                      if gtfs.stops[sid] is not None}

    # Filter schedules.
    kept_sched_data = {sid: gtfs.schedules[sid] for sid in kept_service_ids
                       if gtfs.schedules[sid] is not None}

    return rr.GTFS(
        name=gtfs.name,
        feed=gtfs.feed,
        agencies=gtfs.agencies,
        routes=Routes(kept_route_data),
        schedules=Schedules(kept_sched_data),
        stops=Stops(kept_stop_data),
        trips=Trips(kept_trips),
    )


def load_line_data(data_dir: str = DATA_DIR) -> list[LineData]:
    """
    Download / cache GTFS feeds and build a :class:`LineData` for each
    configured display line.
    """
    os.makedirs(data_dir, exist_ok=True)

    gtfs_cache: dict[str, rr.GTFS] = {}
    for key, src in GTFS_SOURCES.items():
        cache_path = os.path.join(data_dir, f'{key}.json')
        strip_routes = src.get('strip_to_routes')

        if os.path.exists(cache_path):
            # Fast path: load cached (already stripped).
            print(f'  Loading {src["name"]} GTFS from cache ...', flush=True)
            gtfs_cache[key] = rr.GTFS.read(
                name=src['name'],
                mgtfs_path=cache_path,
            )
        else:
            # Slow path: download full feed, strip, then cache.
            print(f'  Downloading {src["name"]} GTFS (key={key}) ...', flush=True)
            full = rr.GTFS.read(
                name=src['name'],
                gtfs_uri=src.get('gtfs_uri'),
                gtfs_sub=src.get('gtfs_sub'),
            )
            if strip_routes:
                print(f'    Stripping to routes {strip_routes} ...', flush=True)
                full = _strip_gtfs(full, strip_routes)
            rr.GTFS.save(full, cache_path)
            gtfs_cache[key] = full

    result: list[LineData] = []
    for spec in LINES:
        gtfs = gtfs_cache[spec.gtfs_key]
        stops = _canonical_stops(gtfs, spec)
        stop_index = _build_stop_index(gtfs, stops, spec)
        result.append(LineData(spec=spec, gtfs=gtfs, stops=stops, stop_index=stop_index))
        if stops:
            print(
                f'  {spec.short_name}: {len(stops)} stops, '
                f'{len(stop_index)} index entries '
                f'({stops[0].full_name} -> {stops[-1].full_name})',
                flush=True,
            )
    return result


# ---------------------------------------------------------------------------
# Layout computation (cross-line alignment)
# ---------------------------------------------------------------------------

def _find_stop_idx(stops: list[StopInfo], query: str) -> Optional[int]:
    """Return the canonical index of the first stop whose full_name contains *query*."""
    for i, s in enumerate(stops):
        if query in s.full_name:
            return i
    return None


def _resolve_track_segments(
    ld: LineData,
    stop_x_fracs: list[float],
) -> list[ResolvedTrackSegment]:
    """Convert config TrackSegments to resolved segments with x-fracs.

    Uses the full ``stop_index`` (which includes name-based aliases)
    so that TrackSegment stop IDs from any directional variant resolve
    correctly.
    """
    if not ld.spec.track_segments:
        # Default: single 2-track segment covering the full line.
        return [ResolvedTrackSegment(
            0, max(0, len(ld.stops) - 1), 2,
            stop_x_fracs[0] if stop_x_fracs else 0.0,
            stop_x_fracs[-1] if stop_x_fracs else 1.0,
        )]

    # Use the full stop_index (includes directional aliases).
    idx = ld.stop_index
    last = max(0, len(ld.stops) - 1)
    result: list[ResolvedTrackSegment] = []
    for ts in ld.spec.track_segments:
        si = idx.get(ts.start_stop_id, 0)
        ei = idx.get(ts.end_stop_id, last)
        result.append(ResolvedTrackSegment(
            si, ei, ts.n_tracks,
            stop_x_fracs[si] if si < len(stop_x_fracs) else 0.0,
            stop_x_fracs[ei] if ei < len(stop_x_fracs) else 1.0,
        ))
    return result


def compute_all_layouts(line_data_list: list[LineData]) -> list[LineLayout]:
    """
    Compute per-stop x-fractions for every display line.

    * **MFL** and **BSL** get natural even spacing across [0, 1].
    * **PATCO** is uniformly scaled so that its *8th and Market* stop aligns
      with MFL's *8th-Market* stop.
    * **B3 spur** is anchored at BSL's *Fairmount* x-position and extends
      rightward with BSL stop spacing.
    """
    by_name: dict[str, LineData] = {ld.spec.short_name: ld for ld in line_data_list}
    layouts: dict[str, LineLayout] = {}

    def _even(ld: LineData) -> LineLayout:
        n = len(ld.stops)
        xf = [i / (n - 1) if n > 1 else 0.5 for i in range(n)]
        segs = _resolve_track_segments(ld, xf)
        return LineLayout(ld, xf, 0.0, 1.0, segs, branches=[])

    # ---- Phase 1: MFL and BSL with natural even spacing -------------------
    for name in ('MFL', 'BSL'):
        if name in by_name:
            layouts[name] = _even(by_name[name])

    # ---- Phase 2: Build branches (e.g. Broad-Ridge Spur within BSL) --------
    for name, layout in list(layouts.items()):
        ld = layout.line_data
        if not ld.spec.branches:
            continue
        gtfs = ld.gtfs
        n_main = len(ld.stops)
        spacing = 1.0 / (n_main - 1) if n_main > 1 else 0.1
        for bs in ld.spec.branches:
            # Build branch canonical stops.
            branch_stops: list[StopInfo] = []
            for sid in bs.canonical_stop_ids:
                stop = gtfs.stops[sid]
                full = stop.name if stop else sid
                branch_stops.append(StopInfo(stop_id=sid, name=_shorten(full), full_name=full))

            # Build branch stop_index (name-based aliasing).
            b_name_to_idx = {s.full_name: i for i, s in enumerate(branch_stops)}
            b_stop_index: dict[str, int] = {s.stop_id: i for i, s in enumerate(branch_stops)}
            for svc in bs.services:
                for trip in gtfs.on_route(svc.route_id).trips.trips:
                    for st in trip.timetable.stops:
                        if st.stop_id is None or st.stop_id in b_stop_index:
                            continue
                        sobj = gtfs.stops[st.stop_id]
                        if sobj:
                            idx = b_name_to_idx.get(sobj.name)
                            if idx is not None:
                                b_stop_index[st.stop_id] = idx

            # Position: junction x on main line, first branch stop one spacing past.
            junc_x = _stop_x_frac(layout, bs.junction_stop_id)
            if junc_x is None:
                junc_x = 0.5
            start_x = junc_x + spacing
            xf = [start_x + i * spacing for i in range(len(branch_stops))]

            layout.branches.append(BranchLayout(
                branch_spec=bs,
                stops=branch_stops,
                stop_x_fracs=xf,
                stop_index=b_stop_index,
                junction_x_frac=junc_x,
                y_offset_px=bs.y_offset_px,
            ))

    # ---- Phase 3: PATCO scaled to align 8th & Market with MFL -------------
    # After reversal, PATCO is: 15-16th(0) … 8th-Mkt(3) … Lindenwold(13).
    # We solve for (offset, spread) so that 8th-Market lands at MFL's
    # 8th-Market x and Lindenwold (rightmost) reaches x = 1.0.
    if 'PATCO' in by_name:
        ld_p = by_name['PATCO']
        mfl_layout = layouts.get('MFL')
        if mfl_layout:
            mfl_8th = _find_stop_idx(mfl_layout.line_data.stops, '8th')
            pat_8th = _find_stop_idx(ld_p.stops, '8th')
            n_mfl = len(mfl_layout.line_data.stops)
            n_pat = len(ld_p.stops)
            if mfl_8th is not None and pat_8th is not None and n_mfl > 1 and n_pat > 1:
                mfl_x = mfl_8th / (n_mfl - 1)
                pat_anchor_nat = pat_8th / (n_pat - 1)  # anchor's natural frac
                # Two constraints:
                #   offset + pat_anchor_nat * spread = mfl_x
                #   offset + 1.0 * spread             = rightmost_x (≤ 1.0)
                # Solve with rightmost_x = 1.0:
                if pat_anchor_nat < 1.0:
                    spread = (1.0 - mfl_x) / (1.0 - pat_anchor_nat)
                    offset = mfl_x - pat_anchor_nat * spread
                else:
                    spread = 1.0
                    offset = 0.0
                xf = [offset + i / (n_pat - 1) * spread for i in range(n_pat)]
                segs = _resolve_track_segments(ld_p, xf)
                layouts['PATCO'] = LineLayout(
                    ld_p, xf,
                    track_x_start_frac=min(xf),
                    track_x_end_frac=max(xf),
                    track_segments=segs,
                    branches=[],
                )
            else:
                layouts['PATCO'] = _even(ld_p)
        else:
            layouts['PATCO'] = _even(ld_p)

    # ---- Build output in display order ------------------------------------
    result: list[LineLayout] = []
    for ld in line_data_list:
        name = ld.spec.short_name
        result.append(layouts.get(name, _even(ld)))
    return result


# ---------------------------------------------------------------------------
# Cross-row connectors
# ---------------------------------------------------------------------------

@dataclass
class ResolvedConnector:
    """Pixel-ready connector between two display rows."""
    from_line_idx: int
    from_x_frac:  float
    to_line_idx:  int
    to_x_frac:    float
    color:        tuple[int, int, int]


def resolve_connectors(
    layouts: list[LineLayout],
    connectors: list[RowConnector] = ROW_CONNECTORS,
) -> list[ResolvedConnector]:
    """Look up line indices and x-fracs for each configured RowConnector."""
    name_to_idx: dict[str, int] = {
        lay.line_data.spec.short_name: i for i, lay in enumerate(layouts)
    }
    result: list[ResolvedConnector] = []
    for c in connectors:
        fi = name_to_idx.get(c.from_line)
        ti = name_to_idx.get(c.to_line)
        if fi is None or ti is None:
            continue
        # Locate the stop's x-frac in each layout.
        from_lay = layouts[fi]
        to_lay   = layouts[ti]
        fx = _stop_x_frac(from_lay, c.from_stop_id)
        tx = _stop_x_frac(to_lay, c.to_stop_id)
        if fx is not None and tx is not None:
            result.append(ResolvedConnector(fi, fx, ti, tx, c.color))
    return result


def _stop_x_frac(layout: LineLayout, stop_id: str) -> Optional[float]:
    """Return the x-frac of *stop_id* in *layout*, or None.

    Uses the full ``stop_index`` (which includes directional aliases)
    so that any variant of a stop ID resolves correctly.
    """
    idx = layout.line_data.stop_index.get(stop_id)
    if idx is not None and idx < len(layout.stop_x_fracs):
        return layout.stop_x_fracs[idx]
    return None


# ---------------------------------------------------------------------------
# Pixel helpers used by ui.py
# ---------------------------------------------------------------------------

def pt_to_px(pt: int) -> int:
    """Convert typographic points to pixels at the configured DPI."""
    return max(1, round(pt * DISPLAY_DPI / 72))


def compute_row_height() -> int:
    """
    Estimate the pixel height of one display row (track + labels + padding).

    This is computed from DPI-scaled font sizes and the track geometry.
    Callers should invoke this **after** ``pygame.font.init()`` if they need
    pixel-accurate glyph metrics, but this function gives a close estimate
    without pygame.
    """
    import math
    label_px   = pt_to_px(FONT_LABEL_PT)
    stop_px    = pt_to_px(FONT_STOP_PT)
    # Rotated stop name bounding-box height (rough estimate):
    # A 12-char label at *stop_px* height has width ≈ stop_px * 6.
    name_w_est = stop_px * 6
    angle_rad  = math.radians(abs(STOP_NAME_ANGLE_DEG))
    angled_h   = int(name_w_est * math.sin(angle_rad) + stop_px * math.cos(angle_rad))

    above = max(angled_h, TRAIN_OFFSET + TRAIN_H // 2) + 4
    below = max(angled_h, TRAIN_OFFSET + TRAIN_H // 2) + 4
    return above + 2 * TICK_HALF + below + 8
