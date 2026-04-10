"""
Canonical stop derivation and stop-index building for transited.

Builds per-route stop sequences from GTFS data, resolving SEPTA's
directional stop-ID duplicates via name matching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import railroaded as rr

from ..config import AgencyConfig, RouteConfig, StopMatchingConfig
from ..geo import fuzzy_match, haversine


@dataclass
class StopInfo:
    """A single stop with display and geographic information."""
    stop_id:   str
    name:      str       # shortened display name
    full_name: str       # original GTFS stop_name
    lat:       Optional[float] = None
    lon:       Optional[float] = None


@dataclass
class RouteData:
    """Canonical stop sequence and stop-index for one route."""
    agency_name: str
    route_cfg:   RouteConfig
    stops:       list[StopInfo]         # canonical order
    stop_index:  dict[str, int]         # stop_id (any variant) -> canonical idx
    # Shape polyline [(lat, lon), ...] for heading interpolation (optional).
    shape_points: Optional[list[tuple[float, float]]] = None


# ---------------------------------------------------------------------------
# Name abbreviation
# ---------------------------------------------------------------------------

_ABBREV = {
    'Street': 'St', 'Avenue': 'Ave', 'Boulevard': 'Blvd',
    'Station': 'Sta', 'Center': 'Ctr', 'Transportation': 'Trans',
    'Terminal': 'Term', 'Square': 'Sq', 'Transit': 'Tran',
}
MAX_NAME_LEN = 14


def shorten(name: str) -> str:
    """Abbreviate common words then hard-truncate."""
    if len(name) <= MAX_NAME_LEN:
        return name
    short = ' '.join(_ABBREV.get(w, w) for w in name.split())
    if len(short) <= MAX_NAME_LEN:
        return short
    return name[:MAX_NAME_LEN - 1] + '\u2026'


# ---------------------------------------------------------------------------
# Canonical stop derivation
# ---------------------------------------------------------------------------

def derive_canonical_stops(
    gtfs: rr.GTFS,
    route_id: str,
) -> list[StopInfo]:
    """Return the ordered stop list for the longest trip on *route_id*."""
    trips = gtfs.on_route(route_id).trips.trips
    if not trips:
        return []
    best = max(trips, key=lambda t: len(t.timetable.stops))
    result: list[StopInfo] = []
    for st in best.timetable.stops:
        if st.stop_id is None:
            continue
        stop = gtfs.stops[st.stop_id]
        if stop:
            result.append(StopInfo(
                stop_id=st.stop_id,
                name=shorten(stop.name),
                full_name=stop.name,
                lat=stop.lat,
                lon=stop.lon,
            ))
        else:
            result.append(StopInfo(
                stop_id=st.stop_id,
                name=st.stop_id,
                full_name=st.stop_id,
            ))
    return result


def build_stop_index(
    gtfs: rr.GTFS,
    canonical_stops: list[StopInfo],
    route_ids: list[str],
) -> dict[str, int]:
    """
    Build a stop_id -> canonical_index mapping.

    Scans all trips on *route_ids* and adds any stop whose name matches
    a canonical stop (picks up directional platform variants).
    """
    name_to_idx: dict[str, int] = {s.full_name: i for i, s in enumerate(canonical_stops)}
    stop_index: dict[str, int] = {s.stop_id: i for i, s in enumerate(canonical_stops)}

    for rid in route_ids:
        for trip in gtfs.on_route(rid).trips.trips:
            for st in trip.timetable.stops:
                if st.stop_id is None or st.stop_id in stop_index:
                    continue
                stop = gtfs.stops[st.stop_id]
                if stop:
                    idx = name_to_idx.get(stop.name)
                    if idx is not None:
                        stop_index[st.stop_id] = idx
    return stop_index


def _resolve_color(
    gtfs: rr.GTFS,
    route_cfg: RouteConfig,
) -> tuple[int, int, int]:
    """Resolve route color: YAML override > GTFS route_color > grey fallback."""
    if route_cfg.color is not None:
        return route_cfg.color
    route = gtfs.routes[route_cfg.id]
    if route and route.color and route.color != 'FFFFFF':
        c = route.color.lstrip('#')
        if len(c) == 6:
            try:
                return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
            except ValueError:
                pass
    return (180, 180, 180)


def _best_shape_polyline(
    gtfs: rr.GTFS,
    route_id: str,
) -> Optional[list[tuple[float, float]]]:
    """Extract the longest shape polyline for *route_id*, or None."""
    if gtfs.shapes is None or not gtfs.shapes.ids:
        return None
    trips = gtfs.on_route(route_id).trips.trips
    best_shape = None
    best_len = 0
    for trip in trips:
        if not trip.shape_id:
            continue
        shape = gtfs.shapes[trip.shape_id]
        if shape and len(shape.points) > best_len:
            best_shape = shape
            best_len = len(shape.points)
    if best_shape is None:
        return None
    return [(pt.lat, pt.lon) for pt in best_shape.points]


def build_route_data(
    gtfs: rr.GTFS,
    agency_name: str,
    route_cfg: RouteConfig,
    all_route_ids: list[str],
) -> RouteData:
    """Build a RouteData for one route, including name-based aliasing."""
    resolved_color = _resolve_color(gtfs, route_cfg)
    resolved_cfg = RouteConfig(
        id=route_cfg.id,
        label=route_cfg.label,
        color=resolved_color,
    )

    stops = derive_canonical_stops(gtfs, route_cfg.id)
    idx = build_stop_index(gtfs, stops, all_route_ids)
    shape_pts = _best_shape_polyline(gtfs, route_cfg.id)
    return RouteData(
        agency_name=agency_name,
        route_cfg=resolved_cfg,
        stops=stops,
        stop_index=idx,
        shape_points=shape_pts,
    )


# ---------------------------------------------------------------------------
# Cross-agency stop matching
# ---------------------------------------------------------------------------

@dataclass
class MatchedStopGroup:
    """A group of stops from different agencies at the same physical station."""
    refs: list[tuple[str, str, str]]  # (agency_name, route_id, stop_id)
    lat: float                        # centroid latitude
    lon: float                        # centroid longitude
    name: str                         # representative display name


def match_stops_across_agencies(
    route_data_list: list[RouteData],
    config: Optional[StopMatchingConfig] = None,
) -> list[MatchedStopGroup]:
    """
    Find stops from different agencies that represent the same physical
    station, using geographic proximity + fuzzy name matching.

    Algorithm
    ---------
    1. Collect all stops with coordinates, tagged by agency.
    2. For each pair of stops from DIFFERENT agencies:
       - If distance < 50m: auto-match (same entrance).
       - If distance < proximity_meters AND name similarity > threshold: match.
    3. Transitive closure via union-find to group chains.
    """
    if config is None:
        config = StopMatchingConfig()

    # Collect all stops with coords, keyed by a unique ID.
    @dataclass
    class _Entry:
        key: int
        agency: str
        route_id: str
        stop_id: str
        name: str
        lat: float
        lon: float

    entries: list[_Entry] = []
    seen: set[tuple[str, str]] = set()  # (agency, stop_id) dedup
    for rd in route_data_list:
        for s in rd.stops:
            if s.lat is None or s.lon is None:
                continue
            k = (rd.agency_name, s.stop_id)
            if k in seen:
                continue
            seen.add(k)
            entries.append(_Entry(
                key=len(entries),
                agency=rd.agency_name,
                route_id=rd.route_cfg.id,
                stop_id=s.stop_id,
                name=s.full_name,
                lat=s.lat,
                lon=s.lon,
            ))

    if len(entries) < 2:
        return []

    # Union-find.
    parent = list(range(len(entries)))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    # Pairwise comparison (only across different agencies).
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i], entries[j]
            if a.agency == b.agency:
                continue
            dist = haversine(a.lat, a.lon, b.lat, b.lon)
            if dist < 50:
                _union(i, j)
            elif dist < config.proximity_meters:
                sim = fuzzy_match(a.name, b.name)
                if sim >= config.fuzzy_threshold:
                    _union(i, j)

    # Group by root.
    groups: dict[int, list[_Entry]] = {}
    for e in entries:
        root = _find(e.key)
        groups.setdefault(root, []).append(e)

    # Only keep groups with stops from multiple agencies.
    result: list[MatchedStopGroup] = []
    for members in groups.values():
        agencies = set(m.agency for m in members)
        if len(agencies) < 2:
            continue
        lat = sum(m.lat for m in members) / len(members)
        lon = sum(m.lon for m in members) / len(members)
        result.append(MatchedStopGroup(
            refs=[(m.agency, m.route_id, m.stop_id) for m in members],
            lat=lat,
            lon=lon,
            name=members[0].name,
        ))

    return result
