"""
Geographic map renderer for transited.

Renders a tiled map background (CARTO basemap) with transit route
polylines, stop dots, station labels, and vehicle icons.  Supports
pan/zoom with idle snap-back.
"""
from __future__ import annotations

from typing import Any, Optional

import pygame

from ...log import LOG
from ...realtime.interpolation import VehiclePosition
from ...static.layout import RouteGeometry
from ...static.tiles import (
    compute_zoom,
    ensure_tiles,
    render_tiles_projected,
)
from ..fonts import make_font
from ..renderer import Renderer
from ..vehicle import VehicleIcon, draw_vehicle
from .projection import BoundingBox, MapProjection
from .viewport import ViewportState

# Visual constants.
FONT_LABEL_PT = 10
FONT_STOP_PT = 8
ROUTE_LINE_W = 3
STOP_RADIUS = 5
STOP_OUTLINE = 2
BG_COLOR = (15, 15, 20)
LABEL_COLOR = (200, 200, 210)

# Default data directory for tile cache.
import os
_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data'))


class MapRenderer(Renderer):
    """Geographic map renderer implementing the Renderer ABC."""

    def __init__(
        self,
        geometries: list[RouteGeometry],
        dpi: int = 96,
        idle_timeout: float = 30.0,
        tile_style: str = 'dark',
        bg_color: tuple[int, int, int] = BG_COLOR,
        data_dir: str = _DATA_DIR,
    ) -> None:
        self._geometries = geometries
        self._dpi = dpi
        self._idle_timeout = idle_timeout
        self._tile_style = tile_style
        self._bg_color = bg_color
        self._data_dir = data_dir

        self._proj: Optional[MapProjection] = None
        self._viewport: Optional[ViewportState] = None
        self._font_label: Optional[pygame.font.Font] = None
        self._font_stop: Optional[pygame.font.Font] = None
        self._screen_w = 0
        self._screen_h = 0
        self._bbox: Optional[BoundingBox] = None
        self._zoom: int = 12

    # ---- Renderer interface ----

    def setup(
        self,
        screen: pygame.Surface,
        screen_w: int,
        screen_h: int,
    ) -> None:
        self._screen_w = screen_w
        self._screen_h = screen_h

        self._font_label = make_font(FONT_LABEL_PT, self._dpi, bold=True)
        self._font_stop = make_font(FONT_STOP_PT, self._dpi)

        # Compute bounding box across all stops.
        all_pts: list[tuple[float, float]] = []
        for geo in self._geometries:
            all_pts.extend(geo.stop_points)
        if not all_pts:
            all_pts = [(39.95, -75.16)]

        self._bbox = BoundingBox.from_points(all_pts, padding=0.15)
        self._proj = MapProjection(screen_w, screen_h)
        self._proj.fit(self._bbox)

        self._viewport = ViewportState(
            self._proj, self._bbox, idle_timeout=self._idle_timeout,
        )

        # Compute zoom and download tiles.
        self._zoom = compute_zoom(
            self._bbox.min_lat, self._bbox.min_lon,
            self._bbox.max_lat, self._bbox.max_lon,
            screen_w, screen_h,
        )

        if self._tile_style != 'none':
            LOG.info('Downloading map tiles (style=%s, zoom=%d) ...',
                     self._tile_style, self._zoom)
            ensure_tiles(
                self._bbox.min_lat, self._bbox.min_lon,
                self._bbox.max_lat, self._bbox.max_lon,
                self._zoom,
                self._data_dir,
                style=self._tile_style,
            )
            LOG.info('Map tiles ready.')

    def apply_zoom(self, factor: float) -> None:
        if self._proj is not None:
            cx = self._screen_w // 2
            cy = self._screen_h // 2
            self._proj.zoom_at(cx, cy, factor)
            if self._viewport is not None:
                # Update home state so snap-back returns to zoomed view.
                self._viewport._home_cx = self._proj._center_x
                self._viewport._home_cy = self._proj._center_y
                self._viewport._home_scale = self._proj._scale
                self._viewport._dirty = True

    def apply_pan(self, dx: int, dy: int) -> None:
        if self._proj is not None:
            self._proj.pan(dx, dy)
            if self._viewport is not None:
                self._viewport._home_cx = self._proj._center_x
                self._viewport._home_cy = self._proj._center_y
                self._viewport._dirty = True

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._viewport:
            self._viewport.handle_event(event)

    def tick(self, dt: float) -> None:
        if self._viewport:
            self._viewport.tick(dt)

    def needs_bg_redraw(self) -> bool:
        if self._viewport:
            return self._viewport.dirty
        return True

    def render_background(self, surface: pygame.Surface) -> None:
        if self._proj is None:
            surface.fill(self._bg_color)
            return

        # Render map tiles aligned to the current projection (zoom-aware).
        if self._tile_style != 'none':
            render_tiles_projected(
                surface, self._proj, self._zoom,
                self._data_dir, style=self._tile_style,
                bg_color=self._bg_color,
            )
        else:
            surface.fill(self._bg_color)

        # Draw route polylines on top of tiles.
        for geo in self._geometries:
            color = geo.route_data.route_cfg.color
            if color:
                self._draw_polyline(surface, geo.polyline, color)

        # Draw stops.
        for geo in self._geometries:
            color = geo.route_data.route_cfg.color or (180, 180, 180)
            for lat, lon in geo.stop_points:
                px, py = self._proj.project(lat, lon)
                pygame.draw.circle(surface, (255, 255, 255), (px, py), STOP_RADIUS)
                pygame.draw.circle(surface, color, (px, py), STOP_RADIUS, STOP_OUTLINE)

        # Draw stop labels.
        self._draw_labels(surface)

    def render_vehicles(
        self,
        screen: pygame.Surface,
        positions: list[Any],
    ) -> None:
        if self._proj is None:
            return
        for route_positions in positions:
            for vp in route_positions:
                if vp.lat is None or vp.lon is None:
                    continue
                px, py = self._proj.project(vp.lat, vp.lon)
                draw_vehicle(screen, VehicleIcon(
                    x=px, y=py,
                    color=vp.color,
                    forward=vp.forward,
                    heading_deg=vp.heading,
                    service_label=vp.route_id,
                ))

    # ---- Private helpers ----

    def _draw_polyline(
        self,
        surface: pygame.Surface,
        points: list[tuple[float, float]],
        color: tuple[int, int, int],
    ) -> None:
        if len(points) < 2:
            return
        projected = [self._proj.project(lat, lon) for lat, lon in points]
        for i in range(len(projected) - 1):
            pygame.draw.line(
                surface, color,
                projected[i], projected[i + 1],
                ROUTE_LINE_W,
            )

    def _draw_labels(self, surface: pygame.Surface) -> None:
        placed: list[pygame.Rect] = []
        for geo in self._geometries:
            for stop in geo.route_data.stops:
                if stop.lat is None or stop.lon is None:
                    continue
                px, py = self._proj.project(stop.lat, stop.lon)
                label = self._font_stop.render(stop.name, True, LABEL_COLOR)
                rect = label.get_rect(midleft=(px + STOP_RADIUS + 3, py))
                if rect.right < 0 or rect.left > self._screen_w:
                    continue
                if rect.bottom < 0 or rect.top > self._screen_h:
                    continue
                if any(rect.colliderect(r) for r in placed):
                    continue
                surface.blit(label, rect)
                placed.append(rect)
