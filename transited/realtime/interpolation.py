"""
Pure timetable interpolation kernel for transited.

This module contains the core position-interpolation algorithm, unchanged
from v0.0.1.  It has no dependencies on railroaded types and is fully
unit-testable with synthetic data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class VehiclePosition:
    """Estimated position of one vehicle."""
    lat:        float
    lon:        float
    route_id:   str
    color:      tuple[int, int, int]
    forward:    bool = True
    heading:    Optional[float] = None


def positions_from_points(
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


def time_to_secs(t) -> int:
    """Convert a ``datetime.time`` to integer seconds from midnight."""
    return t.hour * 3600 + t.minute * 60 + t.second
