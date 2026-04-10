"""
Geographic and text-matching utilities for transited.

Provides haversine distance, fuzzy station name matching, and
transit-specific name normalization.
"""
from __future__ import annotations

import difflib
import math
import re


# ---------------------------------------------------------------------------
# Geographic distance
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_000  # metres


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in metres between two points."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Transit name normalization
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(
    r'\b(Station|Stop|Transit Center|Transportation Center|TC|Terminal)\b',
    re.IGNORECASE,
)
_DIR_RE = re.compile(r'\b(NB|SB|EB|WB|Northbound|Southbound|Eastbound|Westbound)\b', re.IGNORECASE)
_WS_RE = re.compile(r'\s+')


def normalize_stop_name(name: str) -> str:
    """Normalize a transit stop name for fuzzy comparison."""
    s = _STRIP_RE.sub('', name)
    s = _DIR_RE.sub('', s)
    s = _WS_RE.sub(' ', s).strip().lower()
    return s


def fuzzy_match(name_a: str, name_b: str) -> float:
    """Return a similarity ratio (0-1) between two stop names after normalization."""
    a = normalize_stop_name(name_a)
    b = normalize_stop_name(name_b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()
