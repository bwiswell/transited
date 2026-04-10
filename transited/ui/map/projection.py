"""
Web Mercator projection for transited's geographic map renderer.

Converts lat/lon to screen pixels and back, with support for zoom
levels, panning, and bounding-box fitting.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class BoundingBox:
    """Geographic bounding box."""
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @staticmethod
    def from_points(points: list[tuple[float, float]], padding: float = 0.1) -> BoundingBox:
        """Create a bounding box from (lat, lon) pairs with fractional padding."""
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        dlat = (max_lat - min_lat) * padding or 0.001
        dlon = (max_lon - min_lon) * padding or 0.001
        return BoundingBox(
            min_lat=min_lat - dlat,
            min_lon=min_lon - dlon,
            max_lat=max_lat + dlat,
            max_lon=max_lon + dlon,
        )

    @property
    def center(self) -> tuple[float, float]:
        return (
            (self.min_lat + self.max_lat) / 2,
            (self.min_lon + self.max_lon) / 2,
        )


def _lat_to_merc_y(lat: float) -> float:
    """Convert latitude to Mercator y (radians-based, increases northward)."""
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _merc_y_to_lat(y: float) -> float:
    """Convert Mercator y back to latitude."""
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


class MapProjection:
    """
    Web Mercator projection with pan and zoom.

    The projection maps geographic coordinates to pixel positions on a
    screen of given dimensions.  It supports:

    - ``project(lat, lon)`` → ``(px_x, px_y)``
    - ``unproject(px_x, px_y)`` → ``(lat, lon)``
    - ``fit(bbox)`` — set zoom/center to show a bounding box
    - ``pan(dx, dy)`` — shift the view by pixel amounts
    - ``zoom_at(px, py, factor)`` — zoom toward a screen point
    """

    def __init__(self, screen_w: int, screen_h: int) -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h
        # Center in Mercator coordinates.
        self._center_x = 0.0  # longitude in radians
        self._center_y = 0.0  # Mercator y
        # Pixels per radian at current zoom.
        self._scale = 1000.0

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(self, bbox: BoundingBox) -> None:
        """Set zoom and center to fit *bbox* within the screen."""
        cx_lon = (bbox.min_lon + bbox.max_lon) / 2
        self._center_x = math.radians(cx_lon)
        self._center_y = (
            _lat_to_merc_y(bbox.min_lat) + _lat_to_merc_y(bbox.max_lat)
        ) / 2

        # Compute scale to fit both dimensions.
        merc_w = abs(math.radians(bbox.max_lon) - math.radians(bbox.min_lon))
        merc_h = abs(_lat_to_merc_y(bbox.max_lat) - _lat_to_merc_y(bbox.min_lat))

        if merc_w > 0 and merc_h > 0:
            scale_x = self.screen_w / merc_w
            scale_y = self.screen_h / merc_h
            self._scale = min(scale_x, scale_y)
        elif merc_w > 0:
            self._scale = self.screen_w / merc_w
        elif merc_h > 0:
            self._scale = self.screen_h / merc_h

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def project(self, lat: float, lon: float) -> tuple[int, int]:
        """Convert (lat, lon) to screen pixel (x, y)."""
        mx = math.radians(lon)
        my = _lat_to_merc_y(lat)
        px = self.screen_w / 2 + (mx - self._center_x) * self._scale
        py = self.screen_h / 2 - (my - self._center_y) * self._scale
        return (int(px), int(py))

    def unproject(self, px: int, py: int) -> tuple[float, float]:
        """Convert screen pixel (x, y) to (lat, lon)."""
        mx = self._center_x + (px - self.screen_w / 2) / self._scale
        my = self._center_y - (py - self.screen_h / 2) / self._scale
        return (_merc_y_to_lat(my), math.degrees(mx))

    # ------------------------------------------------------------------
    # Pan / zoom
    # ------------------------------------------------------------------

    def pan(self, dx_px: float, dy_px: float) -> None:
        """Shift the view by (dx, dy) pixels."""
        self._center_x -= dx_px / self._scale
        self._center_y += dy_px / self._scale

    def zoom_at(self, px: int, py: int, factor: float) -> None:
        """Zoom by *factor* centered on screen point (px, py)."""
        # The Mercator coordinate under (px, py).
        mx = self._center_x + (px - self.screen_w / 2) / self._scale
        my = self._center_y - (py - self.screen_h / 2) / self._scale
        # Scale.
        self._scale *= factor
        # Adjust center so (mx, my) still maps to (px, py).
        self._center_x = mx - (px - self.screen_w / 2) / self._scale
        self._center_y = my + (py - self.screen_h / 2) / self._scale

    @property
    def scale(self) -> float:
        """Current pixels-per-radian scale."""
        return self._scale
