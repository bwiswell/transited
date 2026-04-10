"""
Abstract renderer interface for transited.

Both the geographic map renderer and the simplified schematic renderer
implement this interface, allowing the display loop to be renderer-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pygame


class Renderer(ABC):
    """Base class for all transited renderers."""

    @abstractmethod
    def setup(
        self,
        screen: pygame.Surface,
        screen_w: int,
        screen_h: int,
    ) -> None:
        """Initialize renderer state after pygame.init() and screen creation."""
        ...

    @abstractmethod
    def handle_event(self, event: pygame.event.Event) -> None:
        """Process a pygame input event (mouse, touch, keyboard)."""
        ...

    @abstractmethod
    def tick(self, dt: float) -> None:
        """Advance time-dependent state (scroll, pan/zoom animation)."""
        ...

    @abstractmethod
    def needs_bg_redraw(self) -> bool:
        """Return True if the background surface needs re-rendering."""
        ...

    @abstractmethod
    def render_background(self, surface: pygame.Surface) -> None:
        """Render static elements (tracks/map, stops, labels) to *surface*."""
        ...

    @abstractmethod
    def render_vehicles(
        self,
        screen: pygame.Surface,
        positions: list[Any],
    ) -> None:
        """Render vehicle icons over the background on *screen*."""
        ...
