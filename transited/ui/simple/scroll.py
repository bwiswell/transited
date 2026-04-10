"""
Vertical scroll state machine for the simple schematic renderer.

Supports auto-scroll with touch/mouse override and idle snap-back.
"""
from __future__ import annotations

import time as _time
from typing import Optional

import pygame

SCROLL_SPEED: float = 28.0   # px/s
PAUSE_SECS: float = 2.0      # pause at top/bottom
RESUME_SECS: float = 3.0     # inactivity before auto-scroll resumes


class ScrollState:
    """Manages vertical auto-scroll with touch override."""

    def __init__(self, canvas_h: int, screen_h: int) -> None:
        self.canvas_h = canvas_h
        self.screen_h = screen_h
        self.offset = 0.0
        self._dir = 1
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
        if now - self._last_touch_t < RESUME_SECS:
            return
        if now < self._paused_until:
            return

        self.offset += self._dir * SCROLL_SPEED * dt
        if self.offset >= self.max_offset:
            self.offset = self.max_offset
            self._dir = -1
            self._paused_until = now + PAUSE_SECS
        elif self.offset <= 0:
            self.offset = 0.0
            self._dir = 1
            self._paused_until = now + PAUSE_SECS
