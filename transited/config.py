"""
YAML-driven configuration for transited.

Loads a ``config.yaml`` file and produces typed dataclasses that the rest
of the application consumes.  All display/layout constants that were
previously hardcoded now live in the YAML file or have sensible defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Dataclasses — produced by load_config()
# ---------------------------------------------------------------------------

@dataclass
class RouteConfig:
    """One GTFS route to display."""
    id:    str
    label: str = ''
    color: Optional[tuple[int, int, int]] = None  # None = use GTFS route_color


@dataclass
class LiveDataConfig:
    """Live-data source for an agency."""
    gtfs_rt_url:    Optional[str] = None
    adapter:        Optional[str] = None
    adapter_config: dict = field(default_factory=dict)


@dataclass
class AgencyConfig:
    """One transit agency and its routes."""
    name:            str
    gtfs_url:        str
    routes:          list[RouteConfig]
    gtfs_sub:        Optional[str] = None
    strip_to_routes: Optional[list[str]] = None
    live_data:       Optional[LiveDataConfig] = None


@dataclass
class DisplayConfig:
    """Global display settings."""
    fps:                int = 30
    dpi:                int = int(os.environ.get('TRANSITED_DPI', '96'))
    background_color:   tuple[int, int, int] = (15, 15, 20)
    idle_timeout_secs:  float = 30.0
    map_tiles:          str = 'dark'   # 'dark', 'light', or 'none'


@dataclass
class StopMatchingConfig:
    """Cross-agency stop matching parameters."""
    proximity_meters: float = 200.0
    fuzzy_threshold:  float = 0.85


@dataclass
class AppConfig:
    """Top-level application configuration."""
    agencies:       list[AgencyConfig]
    display:        DisplayConfig = field(default_factory=DisplayConfig)
    stop_matching:  StopMatchingConfig = field(default_factory=StopMatchingConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config.yaml'


def _parse_color(raw) -> tuple[int, int, int]:
    """Convert a YAML color (list of 3 ints or hex string) to an RGB tuple."""
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        return (int(raw[0]), int(raw[1]), int(raw[2]))
    if isinstance(raw, str) and raw.startswith('#') and len(raw) == 7:
        return (int(raw[1:3], 16), int(raw[3:5], 16), int(raw[5:7], 16))
    return (180, 180, 180)


def load_config(path: Optional[str] = None) -> AppConfig:
    """
    Load and validate configuration from a YAML file.

    Parameters
    ----------
    path : str, optional
        Path to the YAML config file.  Defaults to ``config.yaml`` in the
        project root.

    Returns
    -------
    AppConfig
    """
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f'Config file not found: {config_path}')

    with open(config_path, 'r') as f:
        raw = yaml.safe_load(f)

    if not raw or 'agencies' not in raw:
        raise ValueError('Config must contain an "agencies" list')

    # Parse display settings.
    d = raw.get('display', {}) or {}
    display = DisplayConfig(
        fps=int(d.get('fps', 30)),
        dpi=int(os.environ.get('TRANSITED_DPI', d.get('dpi', 96))),
        background_color=_parse_color(d.get('background_color', [15, 15, 20])),
        idle_timeout_secs=float(d.get('idle_timeout_secs', 30.0)),
        map_tiles=str(d.get('map_tiles', 'dark')),
    )

    # Parse stop matching.
    sm = raw.get('stop_matching', {}) or {}
    stop_matching = StopMatchingConfig(
        proximity_meters=float(sm.get('proximity_meters', 200.0)),
        fuzzy_threshold=float(sm.get('fuzzy_threshold', 0.85)),
    )

    # Parse agencies.
    agencies: list[AgencyConfig] = []
    for a in raw['agencies']:
        routes: list[RouteConfig] = []
        for r in a.get('routes', []):
            routes.append(RouteConfig(
                id=str(r['id']),
                label=r.get('label', ''),
                color=_parse_color(r.get('color')) if r.get('color') else None,
            ))

        live = None
        if a.get('live_data'):
            ld = a['live_data']
            live = LiveDataConfig(
                gtfs_rt_url=ld.get('gtfs_rt_url'),
                adapter=ld.get('adapter'),
                adapter_config=ld.get('adapter_config', {}),
            )

        agencies.append(AgencyConfig(
            name=a['name'],
            gtfs_url=a['gtfs_url'],
            routes=routes,
            gtfs_sub=a.get('gtfs_sub'),
            strip_to_routes=a.get('strip_to_routes'),
            live_data=live,
        ))

    return AppConfig(
        agencies=agencies,
        display=display,
        stop_matching=stop_matching,
    )
