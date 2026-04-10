"""
Geographic layout computation for transited's map renderer.

Computes bounding boxes and route polylines from stop coordinates
and (optionally) GTFS shapes.txt data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import railroaded as rr

from ..config import AgencyConfig
from .loader import AgencyData
from .stops import RouteData


@dataclass
class RouteGeometry:
    """Geographic path for one route — used by the map renderer."""
    route_data: RouteData
    # Ordered polyline points [(lat, lon), ...].
    # From shapes.txt if available, otherwise straight lines between stops.
    polyline: list[tuple[float, float]]
    # Stop positions [(lat, lon), ...] in canonical order.
    stop_points: list[tuple[float, float]]


def _route_polyline_from_shapes(
    gtfs: rr.GTFS,
    route_id: str,
) -> Optional[list[tuple[float, float]]]:
    """
    Extract the polyline for *route_id* from shapes.txt data.

    Uses the shape_id from the trip with the most shape points.
    Returns None if shapes are not loaded or no shapes match.
    """
    if gtfs.shapes is None or not gtfs.shapes.ids:
        return None

    trips = gtfs.on_route(route_id).trips.trips
    if not trips:
        return None

    # Find the trip with the longest shape.
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


def _route_polyline_from_stops(rd: RouteData) -> list[tuple[float, float]]:
    """Fallback: straight lines between canonical stop positions."""
    pts: list[tuple[float, float]] = []
    for s in rd.stops:
        if s.lat is not None and s.lon is not None:
            pts.append((s.lat, s.lon))
    return pts


def build_route_geometries(
    agency_data: list[AgencyData],
    route_data_list: list[RouteData],
) -> list[RouteGeometry]:
    """
    Build geographic geometry for every route.

    Uses shapes.txt polylines when available, falling back to
    straight lines between stop positions.
    """
    # Index agencies by name for lookup.
    gtfs_by_agency: dict[str, rr.GTFS] = {
        ad.config.name: ad.gtfs for ad in agency_data
    }

    result: list[RouteGeometry] = []
    for rd in route_data_list:
        gtfs = gtfs_by_agency.get(rd.agency_name)

        # Try shapes first.
        polyline = None
        if gtfs:
            polyline = _route_polyline_from_shapes(gtfs, rd.route_cfg.id)
        if not polyline:
            polyline = _route_polyline_from_stops(rd)

        stop_points = [
            (s.lat, s.lon) for s in rd.stops
            if s.lat is not None and s.lon is not None
        ]

        result.append(RouteGeometry(
            route_data=rd,
            polyline=polyline,
            stop_points=stop_points,
        ))

    return result


def compute_bounding_box(
    geometries: list[RouteGeometry],
    padding: float = 0.1,
) -> Optional[tuple[float, float, float, float]]:
    """
    Compute the bounding box (min_lat, min_lon, max_lat, max_lon) across
    all route geometries, with fractional padding.

    Returns None if no points exist.
    """
    all_points: list[tuple[float, float]] = []
    for geo in geometries:
        all_points.extend(geo.stop_points)

    if not all_points:
        return None

    lats = [p[0] for p in all_points]
    lons = [p[1] for p in all_points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    dlat = (max_lat - min_lat) * padding or 0.001
    dlon = (max_lon - min_lon) * padding or 0.001
    return (min_lat - dlat, min_lon - dlon, max_lat + dlat, max_lon + dlon)
