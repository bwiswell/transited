# transited

Visualise public transit lines with real-time vehicle positions on a geographic map.

## Overview

transited renders transit routes on a tiled geographic map (CARTO basemaps) or horizontal schematic display, with animated vehicle positions from live GTFS-RT feeds, agency REST APIs, or schedule interpolation. Configured via a simple YAML file — works with any GTFS-compatible transit agency.

### Features

- **Geographic map** (default) with CARTO Dark Matter/Positron basemap tiles, route polylines from GTFS shapes.txt, and adaptive tile zoom on user zoom-in
- **Horizontal schematic** (`--simple`) for small-screen devices
- **Smooth vehicle animation** with client-side position interpolation, sprite caching, heading rotation, and priority-based update scheduling
- **Live data** via GTFS-RT protobuf or agency-specific adapters (SEPTA TrainView), with connection status indicator
- **Schedule interpolation** fallback using shape polyline geometry for accurate paths and headings
- **Cross-agency stop matching** via geographic proximity + fuzzy name matching
- **YAML config** — add any transit agency by providing a GTFS URL and route IDs
- **Route colors from GTFS** — automatic, with optional overrides
- **GTFS route stripping** for fast cached loads
- **Simulation mode** (`--sim-time`) with running clock for off-hours testing
- **DPI-aware** fullscreen auto-detection
- **Pan/zoom** with touch support and idle snap-back to overview

### Default configuration

| Agency | Routes | Live Data |
|--------|--------|-----------|
| SEPTA Subway | MFL (L1), BSL (B1, B2, B3) | Schedule interpolation |
| SEPTA Regional Rail | 13 lines (AIR, CHE, CHW, CYN, FOX, LAN, MED, NOR, PAO, TRE, WAR, WIL, WTR) | SEPTA TrainView API |
| PATCO | Speedline (2) | Schedule interpolation |

## Quick start

```sh
poetry install
python -m transited                              # geographic map, fullscreen
python -m transited --simple                     # horizontal schematic
python -m transited --sim-time "16:00:00"        # simulate 4 PM today
python -m transited --config my_config.yaml      # custom config
```

### Raspberry Pi

```sh
SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 TRANSITED_DPI=160 python -m transited
```

## Configuration

Edit `config.yaml` to add agencies and routes:

```yaml
agencies:
  - name: My Transit Agency
    gtfs_url: https://example.com/gtfs.zip
    routes:
      - id: "1"
        label: Red Line
    live_data:
      adapter: my_adapter  # optional
```

Options: `display.map_tiles` (`dark`/`light`/`none`), `stop_matching.proximity_meters`, `display.idle_timeout_secs`. See `config.yaml` for the full schema.

## Dependencies

- Python 3.11+
- [railroaded](https://github.com/bwiswell/railroaded) (GTFS parsing with opt-in shapes.txt)
- [pygame-ce](https://pypi.org/project/pygame-ce/) (rendering)
- [PyYAML](https://pypi.org/project/PyYAML/) (configuration)
- Optional: `gtfs-realtime-bindings` + `protobuf` for GTFS-RT live feeds

## Testing

```sh
poetry run pytest tests/ -v
```

82 tests (all offline after initial GTFS cache).

## Creating custom live data adapters

See [`transited/realtime/adapters/AGENT.md`](transited/realtime/adapters/AGENT.md) for a guide on building adapters for your transit agency's API.
