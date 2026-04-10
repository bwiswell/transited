"""
Vehicle position manager with fallback chain.

Fallback order:
1. GTFS-RT protobuf feed (if URL configured)
2. Agency-specific adapter (if adapter name configured)
3. Schedule interpolation (always available)

Check ``last_data_source`` after calling ``compute_positions()`` to see
which source was used.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import railroaded as rr

import math

from ..config import LiveDataConfig
from ..log import LOG
from ..static.stops import RouteData
from .adapters.base import LiveDataAdapter, LiveVehicle
from .adapters.septa import SeptaTrainViewAdapter
from .gtfs_rt import fetch_gtfs_rt_vehicles
from .interpolation import VehiclePosition, positions_from_points, time_to_secs


class DataSource(Enum):
    """Which data source was used for the most recent position computation."""
    GTFS_RT = 'gtfs_rt'
    ADAPTER = 'adapter'
    SCHEDULE = 'schedule'


# Module-level: set by compute_positions() on each call.
last_data_source: DataSource = DataSource.SCHEDULE


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type] = {
    'septa_trainview': SeptaTrainViewAdapter,
}

# Cache adapter instances by agency name to avoid re-creating each call.
_adapter_cache: dict[str, Optional[LiveDataAdapter]] = {}


def _get_adapter(
    agency_name: str,
    live_cfg: LiveDataConfig,
    gtfs: Optional[rr.GTFS] = None,
) -> Optional[LiveDataAdapter]:
    """Get or create an adapter for an agency, caching the instance."""
    if agency_name in _adapter_cache:
        return _adapter_cache[agency_name]

    if not live_cfg or not live_cfg.adapter:
        _adapter_cache[agency_name] = None
        return None

    cls = _ADAPTERS.get(live_cfg.adapter)
    if cls is None:
        LOG.warning('Unknown adapter: %s', live_cfg.adapter)
        _adapter_cache[agency_name] = None
        return None

    kwargs = live_cfg.adapter_config or {}
    adapter = cls(**kwargs)

    # If the adapter supports route mapping and we have GTFS, set it up.
    if gtfs and hasattr(adapter, 'set_route_mapping'):
        adapter.set_route_mapping(list(gtfs.routes.routes))
        LOG.info('  Configured %s adapter with %d route mappings',
                 live_cfg.adapter, len(getattr(adapter, '_name_map', {})))

    _adapter_cache[agency_name] = adapter
    return adapter


# ---------------------------------------------------------------------------
# Position computation
# ---------------------------------------------------------------------------

def compute_positions(
    gtfs: rr.GTFS,
    route_data: RouteData,
    now: Optional[datetime] = None,
    live_cfg: Optional[LiveDataConfig] = None,
) -> list[VehiclePosition]:
    """
    Compute vehicle positions for one route, using the fallback chain.

    Parameters
    ----------
    gtfs : rr.GTFS
        The GTFS feed for this agency.
    route_data : RouteData
        Canonical stops + stop_index for this route.
    now : datetime, optional
        Current time (or simulated time). None = use wall clock.
    live_cfg : LiveDataConfig, optional
        Live data source config for this agency.  If None or if live
        sources fail, falls back to schedule interpolation.
    """
    global last_data_source
    now = now or datetime.now()

    # --- Attempt 1: GTFS-RT feed ---
    if live_cfg and live_cfg.gtfs_rt_url:
        vehicles = fetch_gtfs_rt_vehicles(live_cfg.gtfs_rt_url)
        if vehicles is not None:
            result = _filter_live(vehicles, route_data)
            if result:
                last_data_source = DataSource.GTFS_RT
                return result

    # --- Attempt 2: Agency adapter ---
    if live_cfg:
        adapter = _get_adapter(route_data.agency_name, live_cfg, gtfs)
        if adapter:
            vehicles = adapter.fetch()
            if vehicles is not None:
                result = _filter_live(vehicles, route_data)
                if result:
                    last_data_source = DataSource.ADAPTER
                    return result

    # --- Attempt 3: Schedule interpolation ---
    last_data_source = DataSource.SCHEDULE
    return _interpolate(gtfs, route_data, now)


def _filter_live(
    vehicles: list[LiveVehicle],
    route_data: RouteData,
) -> list[VehiclePosition]:
    """Convert LiveVehicles to VehiclePositions, filtering by route."""
    rid = route_data.route_cfg.id
    color = route_data.route_cfg.color
    result: list[VehiclePosition] = []
    for v in vehicles:
        if v.route_id == rid:
            result.append(VehiclePosition(
                lat=v.lat,
                lon=v.lon,
                route_id=rid,
                color=color,
                forward=True,  # live data doesn't easily give schematic direction
                heading=v.heading,
            ))
    return result


def _interpolate(
    gtfs: rr.GTFS,
    route_data: RouteData,
    now: datetime,
) -> list[VehiclePosition]:
    """Timetable interpolation fallback."""
    n_stops = len(route_data.stops)
    if n_stops <= 1:
        return []

    positions: list[VehiclePosition] = []
    color = route_data.route_cfg.color

    for service_date in (now.date() - timedelta(days=1), now.date()):
        now_secs = time_to_secs(now.time())
        if service_date < now.date():
            now_secs += 86400

        active = gtfs.on_date(service_date).on_route(route_data.route_cfg.id)
        for trip in active.trips.trips:
            pts: list[tuple[int, int]] = []
            for st in trip.timetable.stops:
                if st.stop_id is None or st.stop_id not in route_data.stop_index:
                    continue
                t = time_to_secs(st.start_time)
                if st.start_offset:
                    t += 86400
                pts.append((route_data.stop_index[st.stop_id], t))

            result = positions_from_points(pts, now_secs, n_stops)
            if result is None:
                continue
            canon_frac, forward = result

            lat, lon, heading = _interpolate_position(route_data, canon_frac, forward)
            if lat is not None and lon is not None:
                positions.append(VehiclePosition(
                    lat=lat, lon=lon,
                    route_id=route_data.route_cfg.id,
                    color=color,
                    forward=forward,
                    heading=heading,
                ))

    return positions


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute bearing in degrees (0=north, 90=east) from point 1 to point 2."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlon = rlon2 - rlon1
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two points."""
    R = 6_371_000
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _interpolate_on_polyline(
    polyline: list[tuple[float, float]],
    frac: float,
    forward: bool,
) -> tuple[float, float, float]:
    """Interpolate lat/lon/heading along a shape polyline at fractional position.

    *frac* is in [0, 1] representing canonical progress along the route.
    The polyline represents one direction; for reverse trips (*forward=False*),
    we walk the polyline from end to start.
    """
    n = len(polyline)
    if n < 2:
        return (polyline[0][0], polyline[0][1], 0.0)

    # Compute cumulative distances using haversine (not flat lat/lon).
    dists = [0.0]
    for i in range(1, n):
        d = _haversine_m(polyline[i-1][0], polyline[i-1][1],
                         polyline[i][0], polyline[i][1])
        dists.append(dists[-1] + d)
    total = dists[-1]
    if total == 0:
        return (polyline[0][0], polyline[0][1], 0.0)

    # For reverse trips, flip the fractional position so frac=0 maps to the
    # end of the polyline and frac=1 maps to the start.
    if not forward:
        frac = 1.0 - frac

    target = frac * total

    # Find the segment containing the target distance.
    for i in range(1, n):
        if dists[i] >= target:
            seg_len = dists[i] - dists[i-1]
            seg_frac = (target - dists[i-1]) / seg_len if seg_len > 0 else 0.5
            a_lat, a_lon = polyline[i-1]
            b_lat, b_lon = polyline[i]
            lat = a_lat + seg_frac * (b_lat - a_lat)
            lon = a_lon + seg_frac * (b_lon - a_lon)
            # Heading follows the segment direction.
            hdg = _bearing(a_lat, a_lon, b_lat, b_lon)
            # Reverse trips travel the opposite direction along the polyline.
            if not forward:
                hdg = (hdg + 180) % 360
            return (lat, lon, hdg)

    # Fallback: end of polyline.
    lat, lon = polyline[-1]
    hdg = _bearing(polyline[-2][0], polyline[-2][1], lat, lon)
    if not forward:
        hdg = (hdg + 180) % 360
    return (lat, lon, hdg)


def _interpolate_position(
    rd: RouteData,
    canon_frac: float,
    forward: bool,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Interpolate lat/lon/heading from a canonical fraction along the route.

    Uses the shape polyline if available for accurate path geometry and
    heading. Falls back to linear interpolation between stop coordinates.
    """
    # If shape data is available, interpolate along the polyline.
    if rd.shape_points and len(rd.shape_points) >= 2:
        lat, lon, hdg = _interpolate_on_polyline(rd.shape_points, canon_frac, forward)
        return (lat, lon, hdg)

    # Fallback: linear interpolation between canonical stops.
    n = len(rd.stops)
    if n < 2:
        return (None, None, None)

    pos = canon_frac * (n - 1)
    idx_a = int(pos)
    idx_b = min(idx_a + 1, n - 1)
    frac = pos - idx_a

    a = rd.stops[idx_a]
    b = rd.stops[idx_b]

    if a.lat is None or a.lon is None or b.lat is None or b.lon is None:
        return (None, None, None)

    lat = a.lat + frac * (b.lat - a.lat)
    lon = a.lon + frac * (b.lon - a.lon)

    if idx_a != idx_b:
        hdg = _bearing(a.lat, a.lon, b.lat, b.lon)
        if not forward:
            hdg = (hdg + 180) % 360
    else:
        hdg = 0.0

    return (lat, lon, hdg)
