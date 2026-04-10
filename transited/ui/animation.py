"""
Client-side animation state for smooth vehicle motion.

Stores position snapshots per route and interpolates between them each
frame, so vehicles move continuously between GTFS/live-data updates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..realtime.interpolation import VehiclePosition

# Maximum squared lat/lon distance for position lerp.
# Beyond this, snap to curr position (lerp would deviate from route).
# ~0.01 degrees ≈ ~1.1km at mid-latitudes.  Trains between 8-second
# updates typically travel 200-500m, so this threshold only triggers
# for large jumps (route reassignment, data glitch, initial appearance).
_MAX_LERP_SQ_DIST = 0.01 ** 2


# ---------------------------------------------------------------------------
# Snapshot state
# ---------------------------------------------------------------------------

@dataclass
class RouteSnapshot:
    """Two position snapshots for one route, enabling per-frame lerp."""
    prev: list[VehiclePosition] = field(default_factory=list)
    curr: list[VehiclePosition] = field(default_factory=list)
    prev_time: float = 0.0     # monotonic time of previous update
    curr_time: float = 0.0     # monotonic time of current update
    # Matched pairs: (prev_idx, curr_idx) for lerping.
    matches: list[tuple[int, int]] = field(default_factory=list)
    # Unmatched new vehicles (appear instantly).
    unmatched_curr: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Vehicle matching
# ---------------------------------------------------------------------------

def _sq_dist(a: VehiclePosition, b: VehiclePosition) -> float:
    """Squared lat/lon distance (cheap, no sqrt needed for comparison)."""
    if a.lat is None or b.lat is None or a.lon is None or b.lon is None:
        return float('inf')
    return (a.lat - b.lat) ** 2 + (a.lon - b.lon) ** 2


def match_vehicles(
    prev: list[VehiclePosition],
    curr: list[VehiclePosition],
) -> tuple[list[tuple[int, int]], list[int]]:
    """
    Match new vehicles to old vehicles by (route_id, forward, nearest position).

    Returns (matches, unmatched_curr) where:
    - matches: list of (prev_idx, curr_idx) pairs
    - unmatched_curr: indices into curr with no prev match
    """
    if not prev:
        return ([], list(range(len(curr))))

    used_prev: set[int] = set()
    matches: list[tuple[int, int]] = []
    unmatched: list[int] = []

    for ci, cv in enumerate(curr):
        best_pi: Optional[int] = None
        best_dist = float('inf')

        for pi, pv in enumerate(prev):
            if pi in used_prev:
                continue
            if pv.route_id != cv.route_id or pv.forward != cv.forward:
                continue
            d = _sq_dist(pv, cv)
            if d < best_dist:
                best_dist = d
                best_pi = pi

        if best_pi is not None:
            matches.append((best_pi, ci))
            used_prev.add(best_pi)
        else:
            unmatched.append(ci)

    return (matches, unmatched)


def update_snapshot(
    snap: RouteSnapshot,
    new_positions: list[VehiclePosition],
    now_mono: float,
) -> None:
    """Rotate a snapshot with new position data."""
    matches, unmatched = match_vehicles(snap.curr, new_positions)
    snap.prev = snap.curr
    snap.curr = new_positions
    snap.prev_time = snap.curr_time
    snap.curr_time = now_mono
    snap.matches = matches
    snap.unmatched_curr = unmatched


# ---------------------------------------------------------------------------
# Heading interpolation
# ---------------------------------------------------------------------------

def lerp_heading(
    a: Optional[float],
    b: Optional[float],
    t: float,
) -> Optional[float]:
    """Shortest-arc angular lerp between two headings in [0, 360)."""
    if a is None:
        return b
    if b is None:
        return a
    diff = (b - a + 180) % 360 - 180
    return (a + t * diff) % 360


# ---------------------------------------------------------------------------
# Per-frame interpolation
# ---------------------------------------------------------------------------

def interpolate_snapshot(
    snap: RouteSnapshot,
    now_mono: float,
) -> list[VehiclePosition]:
    """
    Produce interpolated vehicle positions for the current frame.

    Lerps between ``snap.prev`` and ``snap.curr`` based on elapsed time.
    """
    if not snap.curr:
        return []

    dt = snap.curr_time - snap.prev_time
    if dt <= 0:
        # No previous snapshot — return current positions as-is.
        return list(snap.curr)

    t = max(0.0, min(1.0, (now_mono - snap.curr_time) / dt + 1.0))
    # t=0 means we're at prev_time, t=1 means we're at curr_time,
    # t>1 means we're extrapolating past curr_time (clamped to 1.0 above
    # unless we want to predict — for now, clamp).
    # Actually: at now=curr_time, (now-curr)/dt+1 = 0/dt+1 = 1.0 ✓
    # At now=prev_time, (prev-curr)/dt+1 = (-dt)/dt+1 = 0.0 ✓
    # At now between: smooth 0-1 ✓
    # At now > curr_time: >1, clamped to 1.0 (hold at curr until next update)

    result: list[VehiclePosition] = []

    # Matched pairs: lerp between prev and curr.
    for pi, ci in snap.matches:
        pv = snap.prev[pi]
        cv = snap.curr[ci]

        # Only lerp position if the two points are close enough that a
        # straight line won't visibly deviate from the route geometry.
        sq_dist = _sq_dist_ll(pv.lat, pv.lon, cv.lat, cv.lon)
        if sq_dist <= _MAX_LERP_SQ_DIST:
            lat = _lerp(pv.lat, cv.lat, t)
            lon = _lerp(pv.lon, cv.lon, t)
        else:
            # Too far apart (curve or large jump) — snap to curr.
            lat = cv.lat
            lon = cv.lon

        # Always lerp heading smoothly regardless of distance.
        hdg = lerp_heading(pv.heading, cv.heading, t)

        result.append(VehiclePosition(
            lat=lat,
            lon=lon,
            route_id=cv.route_id,
            color=cv.color,
            forward=cv.forward,
            heading=hdg,
        ))

    # Unmatched new vehicles: appear at their current position.
    for ci in snap.unmatched_curr:
        result.append(snap.curr[ci])

    return result


def _lerp(a: Optional[float], b: Optional[float], t: float) -> Optional[float]:
    if a is None or b is None:
        return b
    return a + t * (b - a)


def _sq_dist_ll(
    lat1: Optional[float], lon1: Optional[float],
    lat2: Optional[float], lon2: Optional[float],
) -> float:
    """Squared lat/lon distance (cheap, for threshold comparison only)."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return float('inf')
    return (lat1 - lat2) ** 2 + (lon1 - lon2) ** 2
