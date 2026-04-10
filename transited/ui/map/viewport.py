"""
Pan/zoom viewport state machine for the map renderer.

Supports mouse drag (pan), scroll wheel (zoom), and idle snap-back
to the default fit-all overview after a configurable timeout.
"""
from __future__ import annotations

import time as _time
from typing import Optional

import pygame

from .projection import BoundingBox, MapProjection

ZOOM_FACTOR = 1.15     # per scroll tick
MIN_SCALE = 100.0
MAX_SCALE = 1_000_000.0


class ViewportState:
    """Manages pan/zoom interaction and idle snap-back."""

    def __init__(
        self,
        projection: MapProjection,
        home_bbox: BoundingBox,
        idle_timeout: float = 30.0,
    ) -> None:
        self._proj = projection
        self._home_bbox = home_bbox
        self._idle_timeout = idle_timeout

        # Snap-back animation state.
        self._home_cx = projection._center_x
        self._home_cy = projection._center_y
        self._home_scale = projection._scale
        self._animating = False
        self._anim_progress = 0.0

        # Interaction tracking.
        self._dragging = False
        self._drag_last: Optional[tuple[int, int]] = None
        self._last_interaction = 0.0
        self._dirty = True

    @property
    def projection(self) -> MapProjection:
        return self._proj

    @property
    def dirty(self) -> bool:
        """True if the viewport changed since last read."""
        d = self._dirty
        self._dirty = False
        return d

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._dragging = True
            self._drag_last = event.pos
            self._animating = False
            self._touch()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False
            self._drag_last = None
        elif event.type == pygame.MOUSEMOTION and self._dragging:
            if self._drag_last is not None:
                dx = event.pos[0] - self._drag_last[0]
                dy = event.pos[1] - self._drag_last[1]
                self._proj.pan(dx, dy)
                self._drag_last = event.pos
                self._dirty = True
                self._touch()
        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if event.y > 0:
                factor = ZOOM_FACTOR
            elif event.y < 0:
                factor = 1.0 / ZOOM_FACTOR
            else:
                return
            new_scale = self._proj.scale * factor
            if MIN_SCALE <= new_scale <= MAX_SCALE:
                self._proj.zoom_at(mx, my, factor)
                self._dirty = True
                self._animating = False
                self._touch()

    def tick(self, dt: float) -> None:
        now = _time.monotonic()

        # Check idle timeout -> start snap-back.
        if (
            not self._animating
            and not self._dragging
            and self._last_interaction > 0
            and now - self._last_interaction >= self._idle_timeout
        ):
            self._animating = True
            self._anim_progress = 0.0

        # Animate snap-back.
        if self._animating:
            self._anim_progress = min(1.0, self._anim_progress + dt * 2.0)
            t = _ease_out(self._anim_progress)
            self._proj._center_x += (self._home_cx - self._proj._center_x) * t * 0.1
            self._proj._center_y += (self._home_cy - self._proj._center_y) * t * 0.1
            self._proj._scale += (self._home_scale - self._proj._scale) * t * 0.1
            self._dirty = True
            if self._anim_progress >= 1.0:
                # Snap exactly to home.
                self._proj._center_x = self._home_cx
                self._proj._center_y = self._home_cy
                self._proj._scale = self._home_scale
                self._animating = False
                self._last_interaction = 0.0

    def _touch(self) -> None:
        self._last_interaction = _time.monotonic()


def _ease_out(t: float) -> float:
    """Ease-out cubic for smooth snap-back."""
    return 1.0 - (1.0 - t) ** 3
