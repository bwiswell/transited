"""
Horizontal schematic renderer for small-screen devices.

Renders each route as a horizontal track with station ticks, angled
labels, and vehicle icons.  Activated via ``--simple`` CLI flag.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import pygame

from ...realtime.interpolation import VehiclePosition
from ..fonts import make_font
from ..renderer import Renderer
from ..vehicle import VehicleIcon, draw_vehicle
from .layout import SimpleRouteLayout, compute_simple_layouts
from .scroll import ScrollState

# Visual constants.
FONT_LABEL_PT = 13
FONT_STOP_PT = 8
STOP_ANGLE_DEG = -45.0
TICK_HALF = 7
TRACK_GAUGE = 10
TRACK_COLOR = (48, 48, 56)
TICK_COLOR = (150, 150, 158)
DIM_COLOR = (185, 185, 195)
DIVIDER_COLOR = (32, 32, 40)
BG_COLOR = (15, 15, 20)


class SimpleRenderer(Renderer):
    """Horizontal schematic renderer implementing the Renderer ABC."""

    def __init__(self, dpi: int = 96) -> None:
        self._dpi = dpi
        self._layouts: list[SimpleRouteLayout] = []
        self._screen_w = 0
        self._screen_h = 0
        self._track_x0 = 0
        self._track_w = 0
        self._row_h = 80
        self._scroll: Optional[ScrollState] = None
        self._font_label: Optional[pygame.font.Font] = None
        self._font_stop: Optional[pygame.font.Font] = None
        self._bg_dirty = True

    # ---- Renderer interface ----

    def setup(
        self,
        screen: pygame.Surface,
        screen_w: int,
        screen_h: int,
    ) -> None:
        self._screen_w = screen_w
        self._screen_h = screen_h
        pad_x = screen_w // 10
        self._track_x0 = pad_x
        self._track_w = screen_w - 2 * pad_x

        self._font_label = make_font(FONT_LABEL_PT, self._dpi, bold=True)
        self._font_stop = make_font(FONT_STOP_PT, self._dpi)
        self._row_h = self._compute_row_height()

        canvas_h = self._row_h * len(self._layouts)
        self._scroll = ScrollState(canvas_h, screen_h)
        self._bg_dirty = True

    def set_layouts(self, layouts: list[SimpleRouteLayout]) -> None:
        """Set the route layouts (called before setup or when data changes)."""
        self._layouts = layouts

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._scroll:
            self._scroll.handle_event(event)

    def tick(self, dt: float) -> None:
        if self._scroll:
            old = self._scroll.offset
            self._scroll.tick(dt)
            if self._scroll.offset != old:
                self._bg_dirty = True

    def needs_bg_redraw(self) -> bool:
        return self._bg_dirty

    def render_background(self, surface: pygame.Surface) -> None:
        surface.fill(BG_COLOR)
        scroll_y = int(self._scroll.offset) if self._scroll else 0

        for i, layout in enumerate(self._layouts):
            row_y = i * self._row_h - scroll_y
            if row_y + self._row_h < 0 or row_y > self._screen_h:
                continue
            self._draw_row_bg(surface, layout, row_y)
            if i > 0:
                pygame.draw.line(
                    surface, DIVIDER_COLOR,
                    (0, row_y), (self._screen_w, row_y), 1,
                )
        self._bg_dirty = False

    def render_vehicles(
        self,
        screen: pygame.Surface,
        positions: list[Any],
    ) -> None:
        scroll_y = int(self._scroll.offset) if self._scroll else 0
        # positions is list[list[VehiclePosition]], one per layout.
        for i, (layout, route_positions) in enumerate(
            zip(self._layouts, positions)
        ):
            row_y = i * self._row_h - scroll_y
            if row_y + self._row_h < 0 or row_y > self._screen_h:
                continue
            cy = row_y + self._row_h // 2
            for vp in route_positions:
                self._draw_vehicle(screen, vp, layout, cy)

    # ---- Private helpers ----

    def _frac_to_px(self, frac: float) -> int:
        return self._track_x0 + int(frac * self._track_w)

    def _compute_row_height(self) -> int:
        dummy = self._font_stop.render('M' * 14, True, (0, 0, 0))
        angle_rad = math.radians(abs(STOP_ANGLE_DEG))
        rotated_h = int(
            dummy.get_width() * math.sin(angle_rad)
            + dummy.get_height() * math.cos(angle_rad)
        )
        above = max(rotated_h, TRACK_GAUGE + 10) + 4
        below = max(rotated_h, TRACK_GAUGE + 10) + 4
        return above + 2 * TICK_HALF + below + 8

    def _draw_row_bg(
        self,
        surf: pygame.Surface,
        layout: SimpleRouteLayout,
        row_y: int,
    ) -> None:
        cy = row_y + self._row_h // 2
        rd = layout.route_data
        n = len(rd.stops)
        tc = rd.route_cfg.color

        # Label (top-left).
        label_text = rd.route_cfg.label or rd.route_cfg.id
        label = self._font_label.render(label_text, True, tc)
        surf.blit(label, label.get_rect(topleft=(6, row_y + 2)))

        # Track (2 parallel lines).
        tx0 = self._frac_to_px(0.0)
        tx1 = self._frac_to_px(1.0) if n > 1 else tx0 + 40
        g = TRACK_GAUGE // 2
        pygame.draw.line(surf, TRACK_COLOR, (tx0, cy - g), (tx1, cy - g), 1)
        pygame.draw.line(surf, TRACK_COLOR, (tx0, cy + g), (tx1, cy + g), 1)

        # Ticks + angled names.
        for idx in range(n):
            sx = self._frac_to_px(layout.stop_x_fracs[idx])
            pygame.draw.line(
                surf, TICK_COLOR,
                (sx, cy - TICK_HALF), (sx, cy + TICK_HALF), 2,
            )
            self._draw_angled_name(surf, rd.stops[idx].name, sx, cy, idx)

    def _draw_angled_name(
        self,
        surf: pygame.Surface,
        name: str,
        sx: int,
        cy: int,
        idx: int,
    ) -> None:
        raw = self._font_stop.render(name, True, DIM_COLOR)
        rotated = pygame.transform.rotate(raw, -STOP_ANGLE_DEG)
        if idx % 2 == 0:
            rect = rotated.get_rect(midbottom=(sx, cy - TICK_HALF - 3))
        else:
            rect = rotated.get_rect(midtop=(sx, cy + TICK_HALF + 3))
        if rect.left < self._track_x0:
            rect.left = self._track_x0
        if rect.right > self._screen_w:
            rect.right = self._screen_w
        surf.blit(rotated, rect)

    def _draw_vehicle(
        self,
        screen: pygame.Surface,
        vp: VehiclePosition,
        layout: SimpleRouteLayout,
        cy: int,
    ) -> None:
        # Convert lat/lon back to canonical fraction for x-position.
        # Use the stop sequence to find the closest segment.
        canon_frac = self._latlon_to_canon_frac(vp, layout)
        if canon_frac is None:
            return

        x = self._frac_to_px(canon_frac)
        g = TRACK_GAUGE // 2
        y = cy - g if vp.forward else cy + g

        # In schematic mode, heading is just left/right.
        hdg = 90.0 if vp.forward else 270.0
        draw_vehicle(screen, VehicleIcon(
            x=x, y=y,
            color=vp.color,
            forward=vp.forward,
            heading_deg=hdg,
            service_label=vp.route_id,
        ))

    def _latlon_to_canon_frac(
        self,
        vp: VehiclePosition,
        layout: SimpleRouteLayout,
    ) -> Optional[float]:
        """Convert a vehicle's lat/lon to a canonical fraction along the route."""
        stops = layout.route_data.stops
        n = len(stops)
        if n < 2 or vp.lat is None or vp.lon is None:
            return None

        # Find the closest stop and compute fractional position.
        best_dist = float('inf')
        best_idx = 0
        for i, s in enumerate(stops):
            if s.lat is None or s.lon is None:
                continue
            d = (s.lat - vp.lat) ** 2 + (s.lon - vp.lon) ** 2
            if d < best_dist:
                best_dist = d
                best_idx = i

        # Refine: interpolate between the two closest stops.
        s = stops[best_idx]
        if s.lat is None or s.lon is None:
            return best_idx / (n - 1)

        # Check neighbors to find the segment.
        for neighbor in (best_idx - 1, best_idx + 1):
            if 0 <= neighbor < n:
                nb = stops[neighbor]
                if nb.lat is None or nb.lon is None:
                    continue
                # Project onto segment.
                seg_lat = nb.lat - s.lat
                seg_lon = nb.lon - s.lon
                seg_len2 = seg_lat ** 2 + seg_lon ** 2
                if seg_len2 > 0:
                    t = max(0.0, min(1.0,
                        ((vp.lat - s.lat) * seg_lat + (vp.lon - s.lon) * seg_lon) / seg_len2
                    ))
                    a = min(best_idx, neighbor)
                    b = max(best_idx, neighbor)
                    frac_along = t if neighbor > best_idx else (1.0 - t)
                    return (a + frac_along) / (n - 1)

        return best_idx / (n - 1)
