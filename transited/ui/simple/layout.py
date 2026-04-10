"""
Schematic horizontal layout for the simple renderer.

Computes evenly-spaced x-fractions for each route's canonical stops.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...static.stops import RouteData


@dataclass
class SimpleRouteLayout:
    """Layout for one route in the simple schematic view."""
    route_data:  RouteData
    stop_x_fracs: list[float]     # per-stop position in [0, 1]

    def canonical_to_x_frac(self, frac: float) -> float:
        """Map a [0, 1] canonical fraction to this route's x-frac space."""
        return frac  # even spacing: identity mapping


def compute_simple_layouts(
    route_data_list: list[RouteData],
) -> list[SimpleRouteLayout]:
    """
    Compute evenly-spaced x-fractions for each route.

    Each route gets independent [0, 1] spacing — no cross-route alignment
    in the simple view.
    """
    result: list[SimpleRouteLayout] = []
    for rd in route_data_list:
        n = len(rd.stops)
        if n <= 1:
            xf = [0.5] if n == 1 else []
        else:
            xf = [i / (n - 1) for i in range(n)]
        result.append(SimpleRouteLayout(route_data=rd, stop_x_fracs=xf))
    return result
