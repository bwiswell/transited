"""
DPI-aware font helpers for transited.
"""
from __future__ import annotations

import pygame


def pt_to_px(pt: int, dpi: int) -> int:
    """Convert typographic points to pixels at the given DPI."""
    return max(1, round(pt * dpi / 72))


def make_font(pt: int, dpi: int, bold: bool = False) -> pygame.font.Font:
    """Return the best available system font at the requested point size."""
    px = pt_to_px(pt, dpi)
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
