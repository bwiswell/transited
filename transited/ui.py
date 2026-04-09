"""
Pygame-based display for transited.

Key design points
-----------------
* **DPI-aware fonts** — point sizes from ``config`` are converted to pixels
  via ``DISPLAY_DPI``.
* **Angled stop names** — rotated to ``STOP_NAME_ANGLE_DEG`` so dense stop
  sequences (MFL has 28 stops) remain legible.
* **Vertical scrolling** — when the total canvas height exceeds the screen,
  a slow automatic scroll runs.  Touch/mouse drag overrides it; after a
  configurable pause auto-scroll resumes.
* **Per-service train colours** — B1 local, B2 express, and B3 spur trains
  each render in their own colour.
* **Per-line track extents** — short lines (B3 spur, PATCO) only draw their
  track between the leftmost and rightmost stop positions.

Raspberry Pi framebuffer
~~~~~~~~~~~~~~~~~~~~~~~~
::

    SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 python -m transited
"""
from __future__ import annotations

import math
import os
import platform
import time as _time
from datetime import datetime, timedelta
from typing import Optional

import pygame

from .config import (
    BG_COLOR,
    DIM_COLOR,
    DIVIDER_COL,
    FONT_LABEL_PT,
    FONT_STOP_PT,
    FPS,
    LABEL_W,
    MERGE_TAPER_PX,
    REFRESH_SECS,
    SCREEN_H as _CFG_SCREEN_H,
    SCREEN_W as _CFG_SCREEN_W,
    SCROLL_PAUSE_S,
    SCROLL_RESUME_S,
    SCROLL_SPEED_PX_S,
    STOP_NAME_ANGLE_DEG,
    TICK_COLOR,
    TICK_HALF,
    TRACK_COLOR,
    TRACK_GAUGE,
    TRACK_PAIR_GAP,
    TRAIN_H,
    TRAIN_OFFSET,
    TRAIN_W,
)
from .realtime import VehiclePosition, get_branch_positions, get_positions
from .static import BranchLayout, LineLayout, ResolvedConnector, pt_to_px

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_sdl() -> None:
    if platform.system() == 'Linux' and not os.environ.get('DISPLAY'):
        os.environ.setdefault('SDL_VIDEODRIVER', 'fbcon')
        os.environ.setdefault('SDL_FBDEV', '/dev/fb0')


def _make_font(pt: int, bold: bool = False) -> pygame.font.Font:
    px = pt_to_px(pt)
    candidates = [
        'segoeui', 'calibri',
        'dejavusans', 'liberationsans', 'notosans', 'freesans',
        'sans',
    ]
    for name in candidates:
        f = pygame.font.SysFont(name, px, bold=bold)
        if f is not None:
            return f
    return pygame.font.Font(None, px + 4)


def _detect_screen_size() -> tuple[int, int]:
    """Return (width, height) from pygame display info, or config fallback."""
    info = pygame.display.Info()
    w = info.current_w if info.current_w > 0 else 0
    h = info.current_h if info.current_h > 0 else 0
    # Use config overrides if set (non-zero).
    if _CFG_SCREEN_W > 0:
        w = _CFG_SCREEN_W
    if _CFG_SCREEN_H > 0:
        h = _CFG_SCREEN_H
    # Absolute fallback.
    if w <= 0:
        w = 1480
    if h <= 0:
        h = 320
    return w, h


# ---------------------------------------------------------------------------
# Scroll state machine
# ---------------------------------------------------------------------------

class _ScrollState:
    """Manages auto-scroll with touch override."""

    def __init__(self, canvas_h: int, screen_h: int) -> None:
        self.canvas_h  = canvas_h
        self.screen_h  = screen_h
        self.offset    = 0.0          # pixels scrolled (0 = top visible)
        self._dir      = 1            # +1 = scrolling down, -1 = scrolling up
        self._paused_until = 0.0
        self._touch_active = False
        self._touch_last_y: Optional[int] = None
        self._last_touch_t = 0.0

    @property
    def max_offset(self) -> float:
        return max(0.0, self.canvas_h - self.screen_h)

    @property
    def needs_scroll(self) -> bool:
        return self.canvas_h > self.screen_h

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._touch_active = True
            self._touch_last_y = event.pos[1]
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._touch_active = False
            self._touch_last_y = None
            self._last_touch_t = _time.monotonic()
        elif event.type == pygame.MOUSEMOTION and self._touch_active:
            if self._touch_last_y is not None:
                dy = event.pos[1] - self._touch_last_y
                self.offset = max(0.0, min(self.max_offset, self.offset - dy))
                self._touch_last_y = event.pos[1]

    def tick(self, dt: float) -> None:
        if not self.needs_scroll:
            self.offset = 0.0
            return
        if self._touch_active:
            return
        now = _time.monotonic()
        if now - self._last_touch_t < SCROLL_RESUME_S:
            return
        if now < self._paused_until:
            return

        self.offset += self._dir * SCROLL_SPEED_PX_S * dt
        if self.offset >= self.max_offset:
            self.offset = self.max_offset
            self._dir = -1
            self._paused_until = now + SCROLL_PAUSE_S
        elif self.offset <= 0:
            self.offset = 0.0
            self._dir = 1
            self._paused_until = now + SCROLL_PAUSE_S


# ---------------------------------------------------------------------------
# Main display class
# ---------------------------------------------------------------------------

class TransitedDisplay:
    def __init__(
        self,
        layouts: list[LineLayout],
        sim_time: Optional[datetime] = None,
        connectors: Optional[list[ResolvedConnector]] = None,
    ) -> None:
        self._layouts    = layouts
        self._connectors = connectors or []
        self._sim_base   = sim_time
        self._sim_wall_start = _time.monotonic() if sim_time else None
        self._positions: list[list[VehiclePosition]] = [[] for _ in layouts]
        # Per-layout, per-branch positions: _branch_positions[i][j] = positions for layout i, branch j
        self._branch_positions: list[list[list[VehiclePosition]]] = [
            [[] for _ in lay.branches] for lay in layouts
        ]
        self._last_refresh = datetime.min

        self._screen:     Optional[pygame.Surface]   = None
        self._font_label: Optional[pygame.font.Font] = None
        self._font_stop:  Optional[pygame.font.Font] = None
        self._row_h: int = 80  # recalculated after font init
        self._scroll: Optional[_ScrollState] = None

        # Screen geometry — set during run() after pygame.init().
        self._screen_w: int = 0
        self._screen_h: int = 0
        self._track_x0: int = 0
        self._track_w:  int = 0

        # Pre-rendered background (tracks, ticks, names, labels, connectors).
        self._bg_surface: Optional[pygame.Surface] = None
        self._bg_scroll_y: float = -1.0

        # Incremental update: round-robin index into layouts.
        self._update_idx: int = 0
        self._update_interval: float = 2.0

    def _frac_to_px(self, frac: float) -> int:
        """Map a [0, 1] x-fraction to a pixel x-coordinate."""
        return self._track_x0 + int(frac * self._track_w)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        _setup_sdl()
        pygame.init()
        pygame.display.set_caption('transited')

        # Detect screen size and go fullscreen.
        self._screen_w, self._screen_h = _detect_screen_size()
        pad_x = self._screen_w // 10          # 10% of screen width
        self._track_x0 = LABEL_W + pad_x
        self._track_w  = self._screen_w - pad_x - self._track_x0

        self._screen     = pygame.display.set_mode(
            (self._screen_w, self._screen_h), pygame.FULLSCREEN,
        )
        self._font_label = _make_font(FONT_LABEL_PT, bold=True)
        self._font_stop  = _make_font(FONT_STOP_PT)

        self._row_h = self._compute_row_height()
        canvas_h = self._row_h * len(self._layouts)
        self._scroll = _ScrollState(canvas_h, self._screen_h)

        # Spread updates so each layout refreshes every
        # (n_layouts * _update_interval) seconds total.
        n = len(self._layouts)
        self._update_interval = max(1.0, REFRESH_SECS / n) if n else REFRESH_SECS

        clock   = pygame.time.Clock()
        running = True
        prev_t  = _time.monotonic()
        last_incremental = prev_t

        # Initial full refresh so trains appear immediately.
        if self._sim_base is not None:
            now_dt = self._sim_base
        else:
            now_dt = datetime.now()
        self._refresh_all(now_dt)

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
                    self._scroll.handle_event(event)

            self._scroll.tick(dt)

            if self._sim_base is not None:
                elapsed = now_mono - self._sim_wall_start
                now_dt = self._sim_base + timedelta(seconds=elapsed)
            else:
                now_dt = datetime.now()

            # Incremental update: one layout per interval, round-robin.
            if now_mono - last_incremental >= self._update_interval:
                self._refresh_one(now_dt, self._update_idx)
                self._update_idx = (self._update_idx + 1) % max(1, len(self._layouts))
                last_incremental = now_mono

            self._draw()
            pygame.display.flip()
            clock.tick(FPS)

        pygame.quit()

    # ------------------------------------------------------------------
    # Private — data
    # ------------------------------------------------------------------

    def _refresh_all(self, now: datetime) -> None:
        """Update positions for every layout (used at startup)."""
        for i in range(len(self._layouts)):
            self._refresh_one(now, i)

    def _refresh_one(self, now: datetime, idx: int) -> None:
        """Update positions for a single layout (incremental update)."""
        if idx >= len(self._layouts):
            return
        sim = now if self._sim_base is not None else None
        layout = self._layouts[idx]
        self._positions[idx] = get_positions(layout, sim)
        for j, branch in enumerate(layout.branches):
            self._branch_positions[idx][j] = get_branch_positions(
                branch, layout.line_data.gtfs, sim,
            )

    def _compute_row_height(self) -> int:
        """Pixel-accurate row height using actual font metrics."""
        dummy = self._font_stop.render('M' * MAX_NAME_CHARS, True, (0, 0, 0))
        angle_rad = math.radians(abs(STOP_NAME_ANGLE_DEG))
        rotated_h = int(
            dummy.get_width() * math.sin(angle_rad)
            + dummy.get_height() * math.cos(angle_rad)
        )
        above = max(rotated_h, TRAIN_OFFSET + TRAIN_H // 2) + 4
        below = max(rotated_h, TRAIN_OFFSET + TRAIN_H // 2) + 4
        base = above + 2 * TICK_HALF + below + 8
        # Account for the tallest branch offset across all layouts.
        max_branch = 0
        for lay in self._layouts:
            for br in lay.branches:
                # Branch needs its own tick/name space below the offset.
                branch_h = br.y_offset_px + TICK_HALF + rotated_h + 4
                max_branch = max(max_branch, branch_h)
        if max_branch > below:
            base += max_branch - below
        return base

    # ------------------------------------------------------------------
    # Private — drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        scroll_y = int(self._scroll.offset)

        # Re-render the background surface when scroll changes.
        if self._bg_surface is None or self._bg_scroll_y != scroll_y:
            self._render_background(scroll_y)
            self._bg_scroll_y = scroll_y

        # Blit cached background, then overlay trains.
        self._screen.blit(self._bg_surface, (0, 0))
        self._draw_all_trains(scroll_y)

    def _render_background(self, scroll_y: int) -> None:
        """Render tracks, ticks, names, labels, and connectors to ``_bg_surface``."""
        if self._bg_surface is None:
            self._bg_surface = pygame.Surface((self._screen_w, self._screen_h))
        self._bg_surface.fill(BG_COLOR)

        for i, layout in enumerate(self._layouts):
            row_y = i * self._row_h - scroll_y
            if row_y + self._row_h < 0 or row_y > self._screen_h:
                continue
            row = pygame.Rect(0, row_y, self._screen_w, self._row_h)
            self._draw_row_bg(row, layout)
            if i > 0:
                pygame.draw.line(
                    self._bg_surface, DIVIDER_COL,
                    (0, row_y), (self._screen_w, row_y), 1,
                )
        for conn in self._connectors:
            self._draw_connector_on(self._bg_surface, conn, scroll_y)

    def _draw_all_trains(self, scroll_y: int) -> None:
        """Draw all train icons on the screen (over the cached background)."""
        for i, (layout, positions) in enumerate(zip(self._layouts, self._positions)):
            row_y = i * self._row_h - scroll_y
            if row_y + self._row_h < 0 or row_y > self._screen_h:
                continue
            cy = row_y + self._row_h // 2
            for pos in positions:
                self._draw_train(pos, cy, layout)
            # Branch trains.
            for bi, branch in enumerate(layout.branches):
                bcy = cy + branch.y_offset_px
                b_positions = self._branch_positions[i][bi] if bi < len(self._branch_positions[i]) else []
                for pos in b_positions:
                    self._draw_branch_train(pos, bcy)

    def _draw_connector_on(
        self, surf: pygame.Surface, conn: ResolvedConnector, scroll_y: int,
    ) -> None:
        """Draw a diagonal 2-track connector between two display rows onto *surf*."""
        from_cy = conn.from_line_idx * self._row_h - scroll_y + self._row_h // 2
        to_cy   = conn.to_line_idx   * self._row_h - scroll_y + self._row_h // 2
        from_px = self._frac_to_px(conn.from_x_frac)
        to_px   = self._frac_to_px(conn.to_x_frac)

        dx = to_px - from_px
        dy = to_cy - from_cy
        length = math.hypot(dx, dy)
        if length < 1:
            return
        nx, ny = -dy / length, dx / length
        half_g = TRACK_GAUGE / 2
        for sign in (-1, 1):
            ox, oy = nx * half_g * sign, ny * half_g * sign
            pygame.draw.line(
                surf, TRACK_COLOR,
                (int(from_px + ox), int(from_cy + oy)),
                (int(to_px + ox),   int(to_cy + oy)),
                1,
            )

    def _draw_row_bg(
        self,
        row: pygame.Rect,
        layout: LineLayout,
    ) -> None:
        """Draw the static parts of a row (tracks, ticks, names, branches) to _bg_surface."""
        surf = self._bg_surface
        cy = row.y + row.h // 2
        ld = layout.line_data
        n  = len(ld.stops)
        tc = ld.spec.track_color

        # ---- label (top-left of row) ----
        label = self._font_label.render(ld.spec.short_name, True, tc)
        surf.blit(label, label.get_rect(topleft=(6, row.y + 2)))

        # ---- multi-track lines ----
        self._draw_tracks_on(surf, layout, cy)

        # ---- ticks + names ----
        for idx in range(n):
            sx = self._frac_to_px(layout.stop_x_fracs[idx])
            tick_h = self._tick_half_for(layout, layout.stop_x_fracs[idx])
            pygame.draw.line(
                surf, TICK_COLOR,
                (sx, cy - tick_h), (sx, cy + tick_h), 2,
            )
            self._draw_angled_name_on(surf, ld.stops[idx].name, sx, cy, idx, row)

        # ---- branches (static parts only: tracks, ticks, names, connector) ----
        for branch in layout.branches:
            self._draw_branch_bg(surf, branch, cy, row)

    def _draw_angled_name_on(
        self, surf: pygame.Surface,
        name: str, sx: int, cy: int, idx: int, row: pygame.Rect,
    ) -> None:
        raw = self._font_stop.render(name, True, DIM_COLOR)
        rotated = pygame.transform.rotate(raw, -STOP_NAME_ANGLE_DEG)
        if idx % 2 == 0:
            rect = rotated.get_rect(midbottom=(sx, cy - TICK_HALF - 3))
        else:
            rect = rotated.get_rect(midtop=(sx, cy + TICK_HALF + 3))
        if rect.left < self._track_x0:
            rect.left = self._track_x0
        if rect.right > self._screen_w:
            rect.right = self._screen_w
        surf.blit(rotated, rect)

    # ------------------------------------------------------------------
    # Branch rendering
    # ------------------------------------------------------------------

    def _draw_branch_bg(
        self,
        surf: pygame.Surface,
        branch: BranchLayout,
        main_cy: int,
        row: pygame.Rect,
    ) -> None:
        """Draw the static parts of a branch spur onto *surf*."""
        bcy = main_cy + branch.y_offset_px
        tc  = branch.branch_spec.track_color
        n   = len(branch.stops)

        # ---- diagonal connector from junction to first branch stop ----
        jx = self._frac_to_px(branch.junction_x_frac)
        if n > 0:
            first_x = self._frac_to_px(branch.stop_x_fracs[0])
            dx, dy = first_x - jx, bcy - main_cy
            length = math.hypot(dx, dy)
            if length > 0:
                nx, ny = -dy / length, dx / length
                hg = TRACK_GAUGE / 2
                for sign in (-1, 1):
                    ox, oy = nx * hg * sign, ny * hg * sign
                    pygame.draw.line(
                        surf, TRACK_COLOR,
                        (int(jx + ox), int(main_cy + oy)),
                        (int(first_x + ox), int(bcy + oy)),
                        1,
                    )

        # ---- branch track (2-track, horizontal) ----
        if n > 0:
            bx0 = self._frac_to_px(branch.stop_x_fracs[0])
            bx1 = self._frac_to_px(branch.stop_x_fracs[-1]) if n > 1 else bx0 + 40
            for dy in self._track_y_offsets(2):
                pygame.draw.line(
                    surf, TRACK_COLOR,
                    (bx0, bcy + dy), (bx1, bcy + dy), 1,
                )

        # ---- ticks + names ----
        for idx, stop in enumerate(branch.stops):
            sx = self._frac_to_px(branch.stop_x_fracs[idx])
            pygame.draw.line(
                surf, TICK_COLOR,
                (sx, bcy - TICK_HALF), (sx, bcy + TICK_HALF), 2,
            )
            self._draw_angled_name_on(surf, stop.name, sx, bcy, idx, row)

        # ---- branch label ----
        lbl = self._font_stop.render(branch.branch_spec.name, True, tc)
        if n > 0:
            lx = self._frac_to_px(branch.stop_x_fracs[0])
            surf.blit(lbl, lbl.get_rect(bottomleft=(lx, bcy - TICK_HALF - 2)))

    def _draw_branch_train(self, pos: VehiclePosition, bcy: int) -> None:
        """Draw a single train icon on a branch track."""
        vx = self._frac_to_px(pos.track_frac)
        g = TRACK_GAUGE
        rail_y = -(g // 2) if pos.forward else (g // 2)
        vy = bcy + rail_y
        rect = pygame.Rect(vx - TRAIN_W // 2, vy - TRAIN_H // 2, TRAIN_W, TRAIN_H)
        pygame.draw.rect(self._screen, pos.color, rect, border_radius=4)
        a = 5
        mid_y = vy
        if pos.forward:
            pts = [(rect.right + a, mid_y), (rect.right, mid_y - a // 2), (rect.right, mid_y + a // 2)]
        else:
            pts = [(rect.left - a, mid_y), (rect.left, mid_y - a // 2), (rect.left, mid_y + a // 2)]
        pygame.draw.polygon(self._screen, pos.color, pts)

    # ------------------------------------------------------------------
    # Multi-track rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _track_y_offsets(n_tracks: int) -> list[int]:
        """
        Return y-offsets from ``cy`` for each rail line.

        2-track: ``[-TRACK_GAUGE//2, +TRACK_GAUGE//2]``
        4-track: outer pair then inner pair (top-to-bottom).
        """
        g = TRACK_GAUGE
        p = TRACK_PAIR_GAP
        if n_tracks == 4:
            return [
                -(p // 2 + g),      # outer top
                -(p // 2),          # inner top
                +(p // 2),          # inner bottom
                +(p // 2 + g),      # outer bottom
            ]
        return [-(g // 2), +(g // 2)]

    def _draw_tracks_on(self, surf: pygame.Surface, layout: LineLayout, cy: int) -> None:
        """Draw parallel track lines and merge tapers for *layout* onto *surf*."""
        segs = layout.track_segments
        for si, seg in enumerate(segs):
            x0 = self._frac_to_px(seg.start_x_frac)
            x1 = self._frac_to_px(seg.end_x_frac)
            for dy in self._track_y_offsets(seg.n_tracks):
                pygame.draw.line(
                    surf, TRACK_COLOR,
                    (x0, cy + dy), (x1, cy + dy), 1,
                )

            # Draw taper where this segment meets the next.
            if si + 1 < len(segs):
                next_seg = segs[si + 1]
                if seg.n_tracks != next_seg.n_tracks:
                    self._draw_taper_on(surf, cy, x1, seg.n_tracks, next_seg.n_tracks)

    def _draw_taper_on(
        self, surf: pygame.Surface, cy: int, boundary_x: int,
        n_left: int, n_right: int,
    ) -> None:
        """Draw diagonal taper lines at a 4-to-2 track boundary onto *surf*.

        The wider-side y-offsets are drawn AT ``boundary_x`` (the station),
        and the diagonals extend toward the narrower side by
        ``MERGE_TAPER_PX`` pixels.
        """
        offsets_wide   = self._track_y_offsets(max(n_left, n_right))
        offsets_narrow = self._track_y_offsets(min(n_left, n_right))

        for wy in offsets_wide:
            ny = min(offsets_narrow, key=lambda n: abs(n - wy))
            if wy == ny:
                continue
            if n_left > n_right:
                pygame.draw.line(
                    surf, TRACK_COLOR,
                    (boundary_x, cy + wy),
                    (boundary_x + MERGE_TAPER_PX, cy + ny), 1,
                )
            else:
                pygame.draw.line(
                    surf, TRACK_COLOR,
                    (boundary_x, cy + ny),
                    (boundary_x + MERGE_TAPER_PX, cy + wy), 1,
                )

    def _tick_half_for(self, layout: LineLayout, x_frac: float) -> int:
        """Return the tick half-height appropriate for the track count at *x_frac*."""
        n = layout.n_tracks_at_x(x_frac)
        if n == 4:
            return TRACK_PAIR_GAP // 2 + TRACK_GAUGE + 2
        return TICK_HALF

    def _train_y(
        self, cy: int, layout: LineLayout,
        pos: VehiclePosition,
    ) -> int:
        """Compute the y coordinate for a train icon.

        The icon is centred directly ON the appropriate rail line so
        that the train appears to run on the track.
        """
        n = layout.n_tracks_at_x(pos.track_frac)
        g = TRACK_GAUGE
        p = TRACK_PAIR_GAP
        if n == 4:
            if pos.track_pair == 'inner':
                rail_y = -(p // 2) if pos.forward else (p // 2)
            else:  # outer
                rail_y = -(p // 2 + g) if pos.forward else (p // 2 + g)
        else:
            # 2-track: forward on upper rail, reverse on lower rail.
            rail_y = -(g // 2) if pos.forward else (g // 2)
        return cy + rail_y

    def _draw_train(
        self, pos: VehiclePosition, cy: int, layout: LineLayout,
    ) -> None:
        vx = self._frac_to_px(pos.track_frac)
        vy = self._train_y(cy, layout, pos)
        rect = pygame.Rect(vx - TRAIN_W // 2, vy - TRAIN_H // 2, TRAIN_W, TRAIN_H)
        pygame.draw.rect(self._screen, pos.color, rect, border_radius=4)
        # direction arrow
        mid_y = vy
        a = 5
        if pos.forward:
            pts = [(rect.right + a, mid_y), (rect.right, mid_y - a // 2), (rect.right, mid_y + a // 2)]
        else:
            pts = [(rect.left - a, mid_y), (rect.left, mid_y - a // 2), (rect.left, mid_y + a // 2)]
        pygame.draw.polygon(self._screen, pos.color, pts)


# Approximate upper bound on characters in a shortened stop name.
MAX_NAME_CHARS = 14
