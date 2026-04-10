"""
Main display loop for transited.

Owns the pygame window, manages animation state (snapshots + per-frame
interpolation), priority-based update scheduling, and delegates rendering
to the active :class:`Renderer` implementation.
"""
from __future__ import annotations

import math
import os
import platform
import time as _time
from datetime import datetime, timedelta
from typing import Optional

import pygame

from ..config import AppConfig
from ..log import LOG
from ..realtime.interpolation import VehiclePosition
from ..realtime.manager import DataSource, compute_positions, last_data_source
from ..static.loader import AgencyData
from ..static.stops import RouteData
from .animation import RouteSnapshot, interpolate_snapshot, update_snapshot
from .renderer import Renderer

# Scheduling constants.
LIVE_UPDATE_SECS = 3.0       # routes with live data
SCHEDULE_UPDATE_SECS = 8.0   # routes using schedule interpolation
MIN_UPDATE_GAP = 0.05        # minimum seconds between any two GTFS queries


def _setup_sdl() -> None:
    if platform.system() == 'Linux' and not os.environ.get('DISPLAY'):
        os.environ.setdefault('SDL_VIDEODRIVER', 'KMSDRM')
        os.environ.setdefault('SDL_FBDEV', '/dev/fb0')


def _detect_screen_size() -> tuple[int, int]:
    info = pygame.display.Info()
    w = info.current_w if info.current_w > 0 else 1280
    h = info.current_h if info.current_h > 0 else 720
    return w, h


class TransitedDisplay:
    """
    Main application display.

    Manages the pygame window, animation snapshots, priority-based update
    scheduling, and delegates rendering to a :class:`Renderer`.
    """

    def __init__(
        self,
        config: AppConfig,
        agency_data: list[AgencyData],
        route_data: list[RouteData],
        renderer: Renderer,
        sim_time: Optional[datetime] = None,
        zoom: float = 1.0,
    ) -> None:
        self._config = config
        self._agency_data = agency_data
        self._route_data = route_data
        self._renderer = renderer
        self._sim_base = sim_time
        self._sim_wall_start = _time.monotonic() if sim_time else None
        self._zoom = max(zoom, 1.0)

        n = len(route_data)

        # Per-route animation snapshots.
        self._snapshots: list[RouteSnapshot] = [RouteSnapshot() for _ in range(n)]

        # Per-route scheduling: next_update_at (monotonic time).
        self._next_update: list[float] = [0.0] * n
        # Per-route update intervals (adjusted based on data source).
        self._intervals: list[float] = [SCHEDULE_UPDATE_SECS] * n
        # Track whether each route has live data config.
        self._has_live: list[bool] = [False] * n
        for i, rd in enumerate(route_data):
            ad = self._find_agency(rd.agency_name)
            if ad and ad.config.live_data:
                self._has_live[i] = True
                self._intervals[i] = LIVE_UPDATE_SECS

        self._last_query_time: float = 0.0  # for MIN_UPDATE_GAP enforcement

    def run(self) -> None:
        _setup_sdl()
        pygame.init()
        pygame.display.set_caption('transited')

        screen_w, screen_h = _detect_screen_size()
        screen = pygame.display.set_mode((screen_w, screen_h), pygame.FULLSCREEN)

        # When zoom > 1, render to a smaller virtual surface and scale up.
        virt_w = int(screen_w / self._zoom)
        virt_h = int(screen_h / self._zoom)
        if self._zoom > 1.0:
            virt_screen = pygame.Surface((virt_w, virt_h))
        else:
            virt_screen = screen
        self._renderer.setup(virt_screen, virt_w, virt_h)

        bg = pygame.Surface((virt_w, virt_h))

        # Initial full refresh.
        now_mono = _time.monotonic()
        now_dt = self._sim_base or datetime.now()
        for i in range(len(self._route_data)):
            self._do_update(i, now_dt, now_mono)
        # Stagger future updates so they don't all fire at once.
        for i in range(len(self._route_data)):
            self._next_update[i] = now_mono + (i * self._intervals[i] / len(self._route_data))

        clock = pygame.time.Clock()
        running = True
        prev_t = now_mono

        while running:
            now_mono = _time.monotonic()
            dt = now_mono - prev_t
            prev_t = now_mono

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                else:
                    self._renderer.handle_event(event)

            self._renderer.tick(dt)

            # Compute sim time.
            if self._sim_base is not None:
                elapsed = now_mono - self._sim_wall_start
                now_dt = self._sim_base + timedelta(seconds=elapsed)
            else:
                now_dt = datetime.now()

            # Priority-based update: find the most overdue route (at most 1 per frame).
            if now_mono - self._last_query_time >= MIN_UPDATE_GAP:
                most_overdue_idx = -1
                most_overdue_by = 0.0
                for i in range(len(self._route_data)):
                    overdue = now_mono - self._next_update[i]
                    if overdue > most_overdue_by:
                        most_overdue_by = overdue
                        most_overdue_idx = i
                if most_overdue_idx >= 0 and most_overdue_by >= 0:
                    self._do_update(most_overdue_idx, now_dt, now_mono)
                    self._next_update[most_overdue_idx] = now_mono + self._intervals[most_overdue_idx]
                    self._last_query_time = now_mono

            # Produce interpolated positions for this frame.
            interpolated = self._interpolated_positions(now_mono)

            # Render.
            if self._renderer.needs_bg_redraw():
                self._renderer.render_background(bg)
            virt_screen.blit(bg, (0, 0))
            self._renderer.render_vehicles(virt_screen, interpolated)
            self._draw_status_indicator(virt_screen, virt_w)
            if self._zoom > 1.0:
                pygame.transform.scale(virt_screen, (screen_w, screen_h), screen)
            pygame.display.flip()
            clock.tick(self._config.display.fps)

        pygame.quit()

    # ------------------------------------------------------------------
    # Position updates
    # ------------------------------------------------------------------

    def _do_update(self, idx: int, now_dt: datetime, now_mono: float) -> None:
        """Compute fresh positions for route *idx* and update its snapshot."""
        if idx >= len(self._route_data):
            return
        rd = self._route_data[idx]
        ad = self._find_agency(rd.agency_name)
        if ad is None:
            return

        live_cfg = ad.config.live_data if self._sim_base is None else None
        effective_now = now_dt if self._sim_base is not None else None
        new_positions = compute_positions(
            ad.gtfs, rd, effective_now or datetime.now(), live_cfg=live_cfg,
        )

        update_snapshot(self._snapshots[idx], new_positions, now_mono)

        # Adjust interval based on what data source was used.
        from ..realtime import manager as _mgr
        if _mgr.last_data_source in (DataSource.GTFS_RT, DataSource.ADAPTER):
            self._intervals[idx] = LIVE_UPDATE_SECS
        else:
            self._intervals[idx] = SCHEDULE_UPDATE_SECS

    def _interpolated_positions(self, now_mono: float) -> list[list[VehiclePosition]]:
        """Produce per-frame interpolated positions from all snapshots."""
        return [
            interpolate_snapshot(snap, now_mono)
            for snap in self._snapshots
        ]

    def _find_agency(self, agency_name: str) -> Optional[AgencyData]:
        for ad in self._agency_data:
            if ad.config.name == agency_name:
                return ad
        return None

    # ------------------------------------------------------------------
    # Status indicator
    # ------------------------------------------------------------------

    def _draw_status_indicator(self, screen: pygame.Surface, screen_w: int) -> None:
        from ..realtime import manager as _mgr
        is_live = _mgr.last_data_source in (DataSource.GTFS_RT, DataSource.ADAPTER)
        color = (0, 200, 80) if is_live else (200, 60, 60)

        size = 32
        margin = 10
        cx = screen_w - margin - size // 2
        cy = margin + size // 2
        alpha = 160

        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        s_cx, s_cy = size // 2, size // 2
        for r in (14, 10, 6):
            arc_rect = pygame.Rect(s_cx - r, s_cy - r, r * 2, r * 2)
            pygame.draw.arc(surf, (*color, alpha), arc_rect,
                            math.radians(30), math.radians(150), 2)
        pygame.draw.circle(surf, (*color, alpha), (s_cx, s_cy + 2), 3)
        screen.blit(surf, (cx - size // 2, cy - size // 2))
