"""
Shared vehicle icon drawing with two-tier sprite caching.

Instead of creating and rotating a surface every frame, icons are
pre-rendered at quantized heading angles and cached.  Per-frame cost
is a dict lookup + blit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pygame


# Icon geometry.
TRAIN_W: int = 28
TRAIN_H: int = 14
BORDER_W: int = 1

# Heading quantization: cache every N degrees (72 entries per icon).
_HEADING_STEP: int = 5

# Two-tier cache.
_base_cache: dict[tuple[tuple[int, int, int], str], pygame.Surface] = {}
_rotated_cache: dict[tuple[tuple[int, int, int], str, int], pygame.Surface] = {}

_label_font: Optional[pygame.font.Font] = None


@dataclass
class VehicleIcon:
    """Screen-space vehicle ready for drawing."""
    x: int
    y: int
    color:         tuple[int, int, int]
    forward:       bool = True
    heading_deg:   Optional[float] = None
    service_label: str = ''


def _get_label_font() -> pygame.font.Font:
    global _label_font
    if _label_font is None:
        _label_font = pygame.font.Font(None, 12)
    return _label_font


def _quantize_heading(heading_deg: Optional[float], forward: bool) -> int:
    """Quantize heading to the nearest _HEADING_STEP degrees."""
    if heading_deg is not None:
        return round(heading_deg / _HEADING_STEP) * _HEADING_STEP % 360
    return 90 if forward else 270


def _build_base(
    color: tuple[int, int, int],
    label: str,
    w: int,
    h: int,
) -> pygame.Surface:
    """Build the unrotated icon surface (pointing right = heading 90)."""
    surf = pygame.Surface((w + 2, h + 2), pygame.SRCALPHA)
    # Black border.
    pygame.draw.rect(surf, (0, 0, 0), pygame.Rect(0, 0, w + 2, h + 2), border_radius=4)
    # Colored fill.
    pygame.draw.rect(surf, color, pygame.Rect(BORDER_W, BORDER_W, w, h), border_radius=3)
    # Service label.
    if label:
        font = _get_label_font()
        lbl = font.render(label, True, (255, 255, 255))
        surf.blit(lbl, lbl.get_rect(center=(w // 2 + BORDER_W, h // 2 + BORDER_W)))
    return surf


def _get_rotated(
    color: tuple[int, int, int],
    label: str,
    q_heading: int,
    w: int = TRAIN_W,
    h: int = TRAIN_H,
) -> pygame.Surface:
    """Get or build a cached rotated sprite."""
    key = (color, label, q_heading)
    surf = _rotated_cache.get(key)
    if surf is not None:
        return surf

    # Get or build the base (unrotated) surface.
    base_key = (color, label)
    base = _base_cache.get(base_key)
    if base is None:
        base = _build_base(color, label, w, h)
        _base_cache[base_key] = base

    # Rotate. Unrotated icon points right (= heading 90).
    # pygame rotation is CCW, so angle = 90 - heading.
    angle = 90.0 - q_heading
    if angle == 0.0:
        rotated = base
    else:
        rotated = pygame.transform.rotate(base, angle)

    _rotated_cache[key] = rotated
    return rotated


def draw_vehicle(
    screen: pygame.Surface,
    icon: VehicleIcon,
    w: int = TRAIN_W,
    h: int = TRAIN_H,
) -> None:
    """Draw a vehicle icon using the sprite cache (lookup + blit)."""
    q = _quantize_heading(icon.heading_deg, icon.forward)
    surf = _get_rotated(icon.color, icon.service_label, q, w, h)
    rect = surf.get_rect(center=(icon.x, icon.y))
    screen.blit(surf, rect)
