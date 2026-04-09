"""
Hardcoded configuration for the transited display.

All layout constants are intentionally hardcoded for the first implementation
pass.  Screen size, line selection, DPI, and GTFS source URLs will be made
configurable in a future revision.

Key decisions captured here
----------------------------
* DPI is read from the ``TRANSITED_DPI`` environment variable (default 96).
  Adjust it to match the physical display so that fonts and track heights
  scale correctly.
* Lines are shown top-to-bottom in the order they appear in ``LINES``.
* The BSL Broad-Ridge Spur is a separate display entry that shares its
  left anchor with the BSL main line at Fairmount station.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Screen  (auto-detected at runtime; these are fallbacks only)
# ---------------------------------------------------------------------------
SCREEN_W: int = 0   # 0 = auto-detect from display at runtime
SCREEN_H: int = 0   # 0 = auto-detect from display at runtime
FPS: int = 30

# ---------------------------------------------------------------------------
# DPI  — override with TRANSITED_DPI environment variable
# ---------------------------------------------------------------------------
DISPLAY_DPI: int = int(os.environ.get('TRANSITED_DPI', '96'))

# ---------------------------------------------------------------------------
# Font sizes (points — scaled to pixels at runtime via DISPLAY_DPI)
# ---------------------------------------------------------------------------
FONT_LABEL_PT: int = 13   # short line-name label on the left
FONT_STOP_PT:  int = 8    # station names (rendered angled)

STOP_NAME_ANGLE_DEG: float = -45.0   # CCW degrees; −45° = ↗ slope

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
LABEL_W: int     = 0      # no dedicated label column; labels overlay the top-left
TICK_HALF: int   = 7      # half-height of station tick marks (px)
TRAIN_W: int     = 20     # train icon width (px)
TRAIN_H: int     = 10     # train icon height (px)
TRAIN_OFFSET: int = 14    # px from track centreline to train centre
                          # (forward trains above, reverse trains below)

# Multi-track rendering
TRACK_GAUGE: int     = 10  # px between the 2 rails of one direction pair
TRACK_PAIR_GAP: int  = 8   # px between inner and outer pairs (4-track sections)
MERGE_TAPER_PX: int  = 30  # px width of the 4→2 track taper at boundaries

# ---------------------------------------------------------------------------
# Scrolling
# ---------------------------------------------------------------------------
SCROLL_SPEED_PX_S: float  = 28.0   # auto-scroll speed (pixels per second)
SCROLL_PAUSE_S: float     = 2.0    # pause at top/bottom before reversing
SCROLL_RESUME_S: float    = 3.0    # inactivity delay before resuming auto-scroll

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
REFRESH_SECS: int = 1   # seconds between vehicle-position recomputations

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
BG_COLOR    = (15,  15,  20)
TEXT_COLOR  = (210, 210, 215)
DIM_COLOR   = (100, 100, 108)
TRACK_COLOR = (48,  48,  56)
TICK_COLOR  = (150, 150, 158)
DIVIDER_COL = (32,  32,  40)


# ---------------------------------------------------------------------------
# Route / display-line specifications
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteService:
    """One GTFS route displayed on a single line (may share a line with others)."""
    route_id:    str
    color:       tuple[int, int, int]
    label:       str                    # short human label, e.g. 'Local', 'Express'
    track_pair:  str = 'outer'          # 'outer' or 'inner' (relevant in 4-track sections)


@dataclass(frozen=True)
class TrackSegment:
    """A contiguous section of track with a specific number of physical tracks."""
    start_stop_id: str    # canonical stop_id at segment start
    end_stop_id:   str    # canonical stop_id at segment end
    n_tracks:      int    # 2 or 4


@dataclass(frozen=True)
class BranchSpec:
    """A short spur/branch rendered within the same row as the main line."""
    name:               str                       # label for the branch
    services:           tuple[RouteService, ...]
    track_color:        tuple[int, int, int]
    canonical_stop_ids: tuple[str, ...]           # explicit stop IDs (display order)
    junction_stop_id:   str                       # stop on the MAIN line where this branch diverges
    y_offset_px:        int = 20                  # px below the main track centreline


@dataclass(frozen=True)
class DisplayLineSpec:
    """
    Describes one horizontal track in the display.

    A DisplayLine may carry multiple RouteServices (e.g. BSL local + express)
    whose trains appear in different colours on the same track.
    """
    display_name: str
    short_name:   str
    gtfs_key:     str                       # key into GTFS_SOURCES
    services:     tuple[RouteService, ...]
    track_color:  tuple[int, int, int]

    # Optional: explicit canonical stop IDs (in display order, left → right).
    # If omitted, canonical stops are derived from the longest trip on
    # services[0].route_id.
    canonical_stop_ids: tuple[str, ...] = ()

    # Additional stop_id → canonical_stop_id aliases (directional duplicates).
    # Populated automatically by name-matching in static.py; list here if known
    # a priori to speed up the scan.
    stop_aliases: tuple[tuple[str, str], ...] = ()

    # Physical track structure.  Empty = uniform 2-track.
    track_segments: tuple[TrackSegment, ...] = ()

    # If True, reverse the auto-derived canonical stop order (left ↔ right).
    reverse: bool = False

    # Branches rendered within this same row (e.g. Broad-Ridge Spur on BSL).
    branches: tuple[BranchSpec, ...] = ()


# ---------------------------------------------------------------------------
# Lines displayed top-to-bottom.
# ---------------------------------------------------------------------------
LINES: list[DisplayLineSpec] = [
    # ---- SEPTA Market-Frankford Line (L1) ----------------------------------
    DisplayLineSpec(
        display_name='Market-Frankford Line',
        short_name='MFL',
        gtfs_key='septa_bus',
        services=(
            RouteService('L1', (0, 112, 192), 'L'),
        ),
        track_color=(0, 80, 150),
    ),

    # ---- SEPTA Broad Street Line (B1 local + B2 express + B3 spur) ---------
    # All BSL services share one display row.  The Broad-Ridge Spur is a
    # branch within the same row, diverging at Fairmount.
    DisplayLineSpec(
        display_name='Broad Street Line',
        short_name='BSL',
        gtfs_key='septa_bus',
        services=(
            RouteService('B1', (243, 130,  32), 'Local',   track_pair='outer'),
            RouteService('B2', (255, 195, 100), 'Express', track_pair='inner'),
            RouteService('B3', (200,  80, 200), 'Spur',    track_pair='inner'),
        ),
        track_color=(180,  90,  10),
        track_segments=(
            TrackSegment('20965', '32139', 4),  # Fern Rock -> Lombard-South: 4 tracks
            TrackSegment('32139', '32134', 2),  # Lombard-South -> NRG: 2 tracks
        ),
        branches=(
            BranchSpec(
                name='Broad-Ridge Spur',
                services=(RouteService('B3', (200, 80, 200), 'Spur'),),
                track_color=(160, 50, 170),
                canonical_stop_ids=('32145', '32144'),   # Chinatown, 8th-Market
                junction_stop_id='32146',                # Fairmount (B1 ID)
                y_offset_px=48,
            ),
        ),
    ),

    # ---- PATCO Speedline ---------------------------------------------------
    # Reversed so Lindenwold (NJ) is rightmost, Center City is leftmost.
    DisplayLineSpec(
        display_name='PATCO Speedline',
        short_name='PATCO',
        gtfs_key='patco',
        services=(
            RouteService('2', (0, 155, 166), 'Speedline'),
        ),
        track_color=(0, 110, 120),
        reverse=True,
    ),
]

# ---------------------------------------------------------------------------
# GTFS sources
# ---------------------------------------------------------------------------
GTFS_SOURCES: dict[str, dict] = {
    'septa_bus': {
        'name':     'SEPTA',
        'gtfs_uri': 'https://www3.septa.org/developer/gtfs_public.zip',
        'gtfs_sub': 'google_bus',
        # Only keep trips on these routes when building the mGTFS cache.
        # This shrinks the cache from ~200 MB to < 5 MB and cuts load time
        # from minutes to seconds.
        'strip_to_routes': ('L1', 'B1', 'B2', 'B3'),
    },
    'patco': {
        'name':     'PATCO',
        'gtfs_uri': (
            'https://rapid.nationalrtap.org'
            '/GTFSFileManagement/UserUploadFiles/13562/PATCO_GTFS.zip'
        ),
    },
}

# ---------------------------------------------------------------------------
# Cross-line shared-stop anchors
# Used by compute_all_layouts() to align connected stations.
# Each tuple: (line_short_name, stop_id_in_canonical_sequence)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SharedStop:
    """A physical station served by stops on multiple display lines."""
    name: str
    refs: tuple[tuple[str, str], ...]   # (line_short_name, canonical_stop_id)


@dataclass(frozen=True)
class RowConnector:
    """A visual diagonal line connecting one display line to another."""
    name:          str
    from_line:     str                    # short_name of source display line
    from_stop_id:  str                    # canonical stop_id on source line
    to_line:       str                    # short_name of destination display line
    to_stop_id:    str                    # canonical stop_id on destination line
    color:         tuple[int, int, int]


ROW_CONNECTORS: list[RowConnector] = [
    # Intra-row connector drawn by the branch rendering system; not needed here.
]


SHARED_STOPS: list[SharedStop] = [
    SharedStop(
        name='8th & Market',
        refs=(
            ('MFL',   '2457'),   # SEPTA MFL  8th-Market
            ('B3',    '32144'),  # B3 spur    8th-Market
            ('PATCO', '11'),     # PATCO      8th and Market
        ),
    ),
    SharedStop(
        name='Fairmount',
        refs=(
            ('BSL', '32146'),   # BSL main   Fairmount (B1 canonical ID)
        ),
    ),
]
