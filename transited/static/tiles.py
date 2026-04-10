"""
Map tile downloading and caching for transited.

Downloads XYZ map tiles (OpenStreetMap-compatible) for a bounding box
at a computed zoom level, caching them locally in ``data/tiles/``.

Default: CARTO Dark Matter (dark theme, no API key required).
Optional: CARTO Positron (light theme) via config.

Tile URL templates:
  dark:  https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png
  light: https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png
"""
from __future__ import annotations

import math
import os
import urllib.request
from typing import Optional

import pygame

from ..log import LOG

# Tile constants.
TILE_SIZE = 256  # pixels per tile

# URL templates.
_TILE_URLS = {
    'dark':  'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
    'light': 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
}
_SUBDOMAINS = ('a', 'b', 'c', 'd')
_TIMEOUT = 10
_USER_AGENT = 'transited/0.1.0 (transit visualisation)'


# ---------------------------------------------------------------------------
# Tile math (slippy map conventions)
# ---------------------------------------------------------------------------

def lon_to_tile_x(lon: float, zoom: int) -> int:
    """Convert longitude to tile x index at the given zoom level."""
    return int((lon + 180) / 360 * (1 << zoom))


def lat_to_tile_y(lat: float, zoom: int) -> int:
    """Convert latitude to tile y index at the given zoom level."""
    lat_rad = math.radians(lat)
    n = 1 << zoom
    return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)


def tile_x_to_lon(x: int, zoom: int) -> float:
    """Convert tile x index to longitude (west edge of the tile)."""
    return x / (1 << zoom) * 360.0 - 180.0


def tile_y_to_lat(y: int, zoom: int) -> float:
    """Convert tile y index to latitude (north edge of the tile)."""
    n = math.pi - 2.0 * math.pi * y / (1 << zoom)
    return math.degrees(math.atan(math.sinh(n)))


def compute_zoom(
    min_lat: float, min_lon: float,
    max_lat: float, max_lon: float,
    screen_w: int, screen_h: int,
) -> int:
    """Compute the zoom level that fits the bounding box in the screen."""
    for z in range(18, 0, -1):
        x0 = lon_to_tile_x(min_lon, z)
        x1 = lon_to_tile_x(max_lon, z)
        y0 = lat_to_tile_y(max_lat, z)  # note: y0 < y1 because lat is inverted
        y1 = lat_to_tile_y(min_lat, z)
        w_tiles = (x1 - x0 + 1) * TILE_SIZE
        h_tiles = (y1 - y0 + 1) * TILE_SIZE
        if w_tiles <= screen_w * 1.5 and h_tiles <= screen_h * 1.5:
            return z
    return 1


# ---------------------------------------------------------------------------
# Tile caching
# ---------------------------------------------------------------------------

def _tile_cache_path(cache_dir: str, style: str, z: int, x: int, y: int) -> str:
    return os.path.join(cache_dir, 'tiles', style, str(z), str(x), f'{y}.png')


def _download_tile(url: str, path: str) -> bool:
    """Download a single tile to *path*. Returns True on success."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = resp.read()
        with open(path, 'wb') as f:
            f.write(data)
        return True
    except Exception as exc:
        LOG.warning('Tile download failed %s: %s', url, exc)
        return False


def ensure_tiles(
    min_lat: float, min_lon: float,
    max_lat: float, max_lon: float,
    zoom: int,
    cache_dir: str,
    style: str = 'dark',
) -> int:
    """
    Download any missing tiles for the bounding box at the given zoom.

    Returns the number of tiles downloaded (0 if all were cached).
    """
    url_template = _TILE_URLS.get(style, _TILE_URLS['dark'])

    x0 = lon_to_tile_x(min_lon, zoom)
    x1 = lon_to_tile_x(max_lon, zoom)
    y0 = lat_to_tile_y(max_lat, zoom)
    y1 = lat_to_tile_y(min_lat, zoom)

    downloaded = 0
    total = (x1 - x0 + 1) * (y1 - y0 + 1)
    sub_idx = 0

    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            path = _tile_cache_path(cache_dir, style, zoom, tx, ty)
            if os.path.exists(path):
                continue
            s = _SUBDOMAINS[sub_idx % len(_SUBDOMAINS)]
            sub_idx += 1
            url = url_template.format(s=s, z=zoom, x=tx, y=ty)
            if _download_tile(url, path):
                downloaded += 1

    if downloaded > 0:
        LOG.info('Downloaded %d/%d map tiles (zoom %d)', downloaded, total, zoom)
    return downloaded


# ---------------------------------------------------------------------------
# Tile compositing
# ---------------------------------------------------------------------------

def composite_tiles(
    min_lat: float, min_lon: float,
    max_lat: float, max_lon: float,
    zoom: int,
    screen_w: int, screen_h: int,
    cache_dir: str,
    style: str = 'dark',
    bg_color: tuple[int, int, int] = (15, 15, 20),
) -> Optional[pygame.Surface]:
    """
    Build a screen-sized surface compositing cached tiles for the
    bounding box.

    Tiles are placed relative to the center of the bounding box,
    matching the MapProjection's Mercator math.
    """
    x0 = lon_to_tile_x(min_lon, zoom)
    x1 = lon_to_tile_x(max_lon, zoom)
    y0 = lat_to_tile_y(max_lat, zoom)
    y1 = lat_to_tile_y(min_lat, zoom)

    # Total pixel size of the tile grid.
    grid_w = (x1 - x0 + 1) * TILE_SIZE
    grid_h = (y1 - y0 + 1) * TILE_SIZE

    # Build the tile grid surface.
    grid = pygame.Surface((grid_w, grid_h))
    grid.fill(bg_color)

    tiles_loaded = 0
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            path = _tile_cache_path(cache_dir, style, zoom, tx, ty)
            if not os.path.exists(path):
                continue
            try:
                tile_surf = pygame.image.load(path)
                px = (tx - x0) * TILE_SIZE
                py = (ty - y0) * TILE_SIZE
                grid.blit(tile_surf, (px, py))
                tiles_loaded += 1
            except Exception:
                continue

    if tiles_loaded == 0:
        return None

    # Compute the center of the bbox in tile-pixel space.
    # The MapProjection centers on the bbox center, so we need to
    # find where that center falls in the tile grid and align.
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2

    # Fractional tile position of the center.
    n = 1 << zoom
    cx_tile = (center_lon + 180) / 360 * n
    cy_tile = (1.0 - math.asinh(math.tan(math.radians(center_lat))) / math.pi) / 2.0 * n

    # Pixel position of center in the grid.
    cx_px = (cx_tile - x0) * TILE_SIZE
    cy_px = (cy_tile - y0) * TILE_SIZE

    # Build output surface: center the grid so bbox center = screen center.
    output = pygame.Surface((screen_w, screen_h))
    output.fill(bg_color)
    offset_x = int(screen_w / 2 - cx_px)
    offset_y = int(screen_h / 2 - cy_px)
    output.blit(grid, (offset_x, offset_y))

    return output


# ---------------------------------------------------------------------------
# Projection-aware tile rendering
# ---------------------------------------------------------------------------

# Cache loaded tile surfaces to avoid re-reading PNG from disk each frame.
_tile_surface_cache: dict[str, Optional[pygame.Surface]] = {}


def _lazy_download_visible(
    x0: int, x1: int, y0: int, y1: int,
    zoom: int, cache_dir: str, style: str,
) -> None:
    """Download any missing tiles in the visible range (non-blocking best-effort)."""
    url_template = _TILE_URLS.get(style, _TILE_URLS['dark'])
    sub_idx = 0
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            path = _tile_cache_path(cache_dir, style, zoom, tx, ty)
            if os.path.exists(path):
                continue
            s = _SUBDOMAINS[sub_idx % len(_SUBDOMAINS)]
            sub_idx += 1
            url = url_template.format(s=s, z=zoom, x=tx, y=ty)
            _download_tile(url, path)


def _effective_zoom(projection, base_zoom: int) -> int:
    """Compute the best tile zoom level for the current projection scale.

    Compares the projection's pixels-per-radian to the tile zoom's
    pixels-per-radian and picks the closest match, clamped to
    [base_zoom, base_zoom + 4] to limit tile downloads.
    """
    # At tile zoom z, there are 2^z tiles across 2*pi radians,
    # each TILE_SIZE pixels wide => pixels_per_radian = 2^z * TILE_SIZE / (2*pi).
    proj_scale = projection.scale  # pixels per radian
    best_z = base_zoom
    best_diff = float('inf')
    for z in range(base_zoom, min(base_zoom + 5, 19)):
        tile_scale = (1 << z) * TILE_SIZE / (2 * math.pi)
        diff = abs(proj_scale - tile_scale)
        if diff < best_diff:
            best_diff = diff
            best_z = z
    return best_z


def render_tiles_projected(
    surface: pygame.Surface,
    projection,
    base_zoom: int,
    cache_dir: str,
    style: str = 'dark',
    bg_color: tuple[int, int, int] = (15, 15, 20),
) -> None:
    """
    Render map tiles onto *surface* using the current *projection* state.

    Automatically selects the best tile zoom level for the current
    projection scale (up to ``base_zoom + 4``), downloading higher-
    resolution tiles on demand when the user zooms in.
    """
    surface.fill(bg_color)
    screen_w, screen_h = surface.get_size()

    # Pick the best tile zoom for the current projection scale.
    zoom = _effective_zoom(projection, base_zoom)

    # Determine which tiles are visible by unprojecting screen corners.
    corners = [
        projection.unproject(0, 0),
        projection.unproject(screen_w, 0),
        projection.unproject(0, screen_h),
        projection.unproject(screen_w, screen_h),
    ]
    lats = [c[0] for c in corners]
    lons = [c[1] for c in corners]
    vis_min_lat, vis_max_lat = min(lats), max(lats)
    vis_min_lon, vis_max_lon = min(lons), max(lons)

    x0 = lon_to_tile_x(vis_min_lon, zoom)
    x1 = lon_to_tile_x(vis_max_lon, zoom)
    y0 = lat_to_tile_y(vis_max_lat, zoom)
    y1 = lat_to_tile_y(vis_min_lat, zoom)

    # Download any missing tiles for the visible area at this zoom.
    # This is lazy: only downloads what's needed for the current view.
    _lazy_download_visible(x0, x1, y0, y1, zoom, cache_dir, style)

    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            # Geographic bounds of this tile.
            tile_north = tile_y_to_lat(ty, zoom)
            tile_south = tile_y_to_lat(ty + 1, zoom)
            tile_west = tile_x_to_lon(tx, zoom)
            tile_east = tile_x_to_lon(tx + 1, zoom)

            # Project tile corners to screen pixels.
            px_nw = projection.project(tile_north, tile_west)
            px_se = projection.project(tile_south, tile_east)

            dest_x = px_nw[0]
            dest_y = px_nw[1]
            dest_w = px_se[0] - px_nw[0]
            dest_h = px_se[1] - px_nw[1]

            if dest_w <= 0 or dest_h <= 0:
                continue
            # Skip tiles entirely off-screen.
            if dest_x + dest_w < 0 or dest_x > screen_w:
                continue
            if dest_y + dest_h < 0 or dest_y > screen_h:
                continue

            # Load tile surface (cached in memory).
            path = _tile_cache_path(cache_dir, style, zoom, tx, ty)
            tile_surf = _tile_surface_cache.get(path)
            if tile_surf is None:
                if os.path.exists(path):
                    try:
                        tile_surf = pygame.image.load(path).convert()
                        _tile_surface_cache[path] = tile_surf
                    except Exception:
                        _tile_surface_cache[path] = None
                        continue
                else:
                    _tile_surface_cache[path] = None
                    continue
            if tile_surf is None:
                continue

            # Scale tile to match the projected size.
            if dest_w != TILE_SIZE or dest_h != TILE_SIZE:
                scaled = pygame.transform.scale(tile_surf, (int(dest_w), int(dest_h)))
            else:
                scaled = tile_surf

            surface.blit(scaled, (int(dest_x), int(dest_y)))
