"""
Vehicle-position computation for transited.

Provides two paths for determining where vehicles are:

1. **Live GTFS-RT** (not yet available for MFL / BSL / PATCO) — will be
   attempted first when a feed URL is configured.  On any network error the
   system silently falls back to path 2.
2. **Timetable interpolation** — linearly interpolates between scheduled
   stop times for every trip that is currently en route.

Public API
----------
get_positions(layout, sim_time=None) -> list[VehiclePosition]
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from .static import LineLayout


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class VehiclePosition:
    """Estimated position of one vehicle."""
    track_frac:  float                 # in the layout's x-frac coordinate space
    forward:     bool                  # True = left → right on display
    color:       tuple[int, int, int]  # from the RouteService
    track_pair:  str = 'outer'         # 'outer' or 'inner' (for 4-track sections)


# ---------------------------------------------------------------------------
# Pure interpolation kernel (no railroaded types — easy to unit-test)
# ---------------------------------------------------------------------------

def _positions_from_points(
    points: list[tuple[int, int]],
    now_secs: int,
    n_stops: int,
) -> Optional[tuple[float, bool]]:
    """
    Compute ``(canonical_frac, forward)`` from a pre-processed timetable.

    Parameters
    ----------
    points : list of (canonical_index, time_seconds)
        Sorted ascending by time_seconds.
    now_secs : int
        Current time in seconds from midnight (may exceed 86 400).
    n_stops : int
        Total canonical stops on this display line.

    Returns ``None`` when the trip has not started or has already finished.
    """
    if len(points) < 2 or n_stops <= 1:
        return None

    first_t, last_t = points[0][1], points[-1][1]
    if now_secs < first_t or now_secs > last_t:
        return None

    for i in range(len(points) - 1):
        ci_a, t_a = points[i]
        ci_b, t_b = points[i + 1]
        if t_a <= now_secs <= t_b:
            seg = (now_secs - t_a) / (t_b - t_a) if t_b > t_a else 0.5
            raw = (ci_a + seg * (ci_b - ci_a)) / (n_stops - 1)
            return (max(0.0, min(1.0, raw)), ci_b >= ci_a)

    return None


# ---------------------------------------------------------------------------
# Trip → points extraction
# ---------------------------------------------------------------------------

def _time_to_secs(t) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _trip_points(trip, stop_index: dict[str, int]) -> list[tuple[int, int]]:
    """Extract ``(canonical_idx, time_secs)`` pairs from a railroaded Trip."""
    pts: list[tuple[int, int]] = []
    for st in trip.timetable.stops:
        if st.stop_id is None or st.stop_id not in stop_index:
            continue
        t = _time_to_secs(st.start_time)
        if st.start_offset:
            t += 86400
        pts.append((stop_index[st.stop_id], t))
    return pts


# ---------------------------------------------------------------------------
# Live feed stub (no lines currently have GTFS-RT feeds)
# ---------------------------------------------------------------------------

def _try_live_positions(
    layout: LineLayout,
    now: datetime,
) -> Optional[list[VehiclePosition]]:
    """
    Attempt to fetch GTFS-RT vehicle positions for *layout*.

    Returns *None* to signal "fall back to interpolation".
    Currently always returns *None* because MFL, BSL, and PATCO lack
    public GTFS-RT vehicle position feeds.
    """
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_positions(
    layout: LineLayout,
    sim_time: Optional[datetime] = None,
) -> list[VehiclePosition]:
    """
    Return estimated positions for all trips currently en route.

    Parameters
    ----------
    layout : LineLayout
        Fully positioned display line.
    sim_time : datetime, optional
        If provided, pretend it is this time (for visual testing).
        Disables live-feed attempts.
    """
    now = sim_time or datetime.now()

    # Try live positions (skipped when simulating).
    if sim_time is None:
        live = _try_live_positions(layout, now)
        if live is not None:
            return live

    # Fall back to timetable interpolation.
    ld = layout.line_data
    n_stops = len(ld.stops)
    if n_stops <= 1:
        return []

    # Build route_id → colour lookup.
    svc_colors: dict[str, tuple[int, int, int]] = {
        svc.route_id: svc.color for svc in ld.spec.services
    }
    default_color = ld.spec.track_color

    positions: list[VehiclePosition] = []

    for service_date in (now.date() - timedelta(days=1), now.date()):
        # Compute now_secs relative to the service_date.
        now_secs = _time_to_secs(now.time())
        if service_date < now.date():
            now_secs += 86400

        active_trips = ld.gtfs.on_date(service_date)
        for svc in ld.spec.services:
            route_trips = active_trips.on_route(svc.route_id)
            color = svc_colors.get(svc.route_id, default_color)

            for trip in route_trips.trips.trips:
                pts = _trip_points(trip, ld.stop_index)
                result = _positions_from_points(pts, now_secs, n_stops)
                if result is not None:
                    canon_frac, fwd = result
                    positions.append(VehiclePosition(
                        track_frac=layout.canonical_to_x_frac(canon_frac),
                        forward=fwd,
                        color=color,
                        track_pair=svc.track_pair,
                    ))

    return positions


def get_branch_positions(
    branch,          # BranchLayout
    gtfs,            # rr.GTFS
    sim_time: Optional[datetime] = None,
) -> list[VehiclePosition]:
    """Return positions for trips on a branch's service routes."""
    now = sim_time or datetime.now()
    n_stops = len(branch.stops)
    if n_stops <= 1:
        return []

    positions: list[VehiclePosition] = []
    for service_date in (now.date() - timedelta(days=1), now.date()):
        now_secs = _time_to_secs(now.time())
        if service_date < now.date():
            now_secs += 86400
        active = gtfs.on_date(service_date)
        for svc in branch.branch_spec.services:
            route_trips = active.on_route(svc.route_id)
            for trip in route_trips.trips.trips:
                pts = _trip_points(trip, branch.stop_index)
                result = _positions_from_points(pts, now_secs, n_stops)
                if result is not None:
                    canon_frac, fwd = result
                    positions.append(VehiclePosition(
                        track_frac=branch.canonical_to_x_frac(canon_frac),
                        forward=fwd,
                        color=svc.color,
                    ))
    return positions
