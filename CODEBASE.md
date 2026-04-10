# transited — Codebase Reference

> Last updated: 2026-04-09 | Branch: version/0.1.0 | Version: **0.1.0**

---

## What This Project Does

`transited` is a Python visualisation tool for public transit rail and metro services. It renders transit routes on a geographic map with tiled basemap background (CARTO Dark Matter / Positron) or a horizontal schematic display, with animated vehicle positions from live GTFS-RT feeds, agency-specific APIs, or schedule interpolation.

**Primary use case:** Display any GTFS-compatible transit network on a fullscreen display with real-time vehicle tracking, smooth animation, and adaptive map tile zoom — configured via a simple YAML file.

---

## Tech Stack

| Language | Key Dependencies | Build Tool |
|----------|-----------------|------------|
| Python 3.11+ | `railroaded ^0.3.0`, `pygame-ce ^2.5`, `pyyaml ^6.0` | Poetry |

**Optional:** `gtfs-realtime-bindings` + `protobuf` for GTFS-RT live feeds.

**Platform targets:** Windows (development) and Raspberry Pi / Raspbian (deployment).

---

## Architecture

```
__main__.py           CLI: --sim-time, --simple, --config
    |
    ├── config.py             YAML loader -> AppConfig dataclasses
    ├── geo.py                haversine, fuzzy name matching
    ├── log.py                structured logging
    |
    ├── static/
    │   ├── loader.py         GTFS download/cache/strip -> AgencyData
    │   ├── stops.py          canonical stops, stop index, cross-agency matching, shape polylines
    │   ├── layout.py         geographic route geometry (polylines from shapes/stops)
    │   └── tiles.py          map tile download/cache/adaptive-zoom rendering
    |
    ├── realtime/
    │   ├── interpolation.py  pure timetable interpolation kernel
    │   ├── manager.py        fallback chain: GTFS-RT -> adapter -> interpolation
    │   ├── gtfs_rt.py        GTFS-RT protobuf parser
    │   └── adapters/         agency-specific live data (SEPTA TrainView)
    |
    └── ui/
        ├── display.py        pygame loop, animation snapshots, priority scheduling
        ├── animation.py      client-side lerp between position updates
        ├── renderer.py       abstract Renderer ABC
        ├── vehicle.py        sprite-cached vehicle icons with heading rotation
        ├── fonts.py          DPI-aware font helpers
        ├── map/              geographic map renderer (default)
        │   ├── renderer.py   tiled background + route polylines + stops + labels
        │   ├── projection.py Web Mercator lat/lon <-> pixel
        │   └── viewport.py   pan/zoom/idle-snap state machine
        └── simple/           horizontal schematic renderer (--simple)
            ├── renderer.py   tracks, ticks, angled labels
            ├── layout.py     even-spaced x-fraction layout
            └── scroll.py     vertical auto-scroll
```

**82 tests** across 6 test files (all offline after initial GTFS cache).

---

## File Structure

```
transited/
├── config.yaml             # user-editable YAML config (default: SEPTA + PATCO)
├── pyproject.toml          # version 0.1.0; deps: railroaded, pygame-ce, pyyaml
├── data/                   # mGTFS JSON + tile caches (gitignored)
│   ├── septa.json, septa_regional_rail.json, patco.json
│   └── tiles/dark/{z}/{x}/{y}.png
├── transited/              # 30 Python source files, ~3400 LOC
└── tests/                  # 7 test files, 82 tests, ~720 LOC
```

---

## Key Concepts

### YAML Configuration

All agency/route configuration in `config.yaml`. Agency-agnostic: any GTFS feed works. Route colors auto-resolve from GTFS `route_color` unless overridden. Config options: `display.map_tiles` (`dark`/`light`/`none`), `stop_matching` thresholds, `live_data` per agency.

### Dual Renderer

`--simple` activates horizontal schematic for small screens. Default is the geographic map with tiled basemap. Both share the same data pipeline, animation system, and vehicle icon drawing.

### Map Tile Background

CARTO basemap tiles (Dark Matter or Positron) downloaded at the overview zoom level during startup, cached in `data/tiles/`. **Adaptive tile zoom**: when the user zooms in, `_effective_zoom()` selects higher-resolution tile zoom levels and lazy-downloads the visible tiles on demand. Tiles are rendered through the current `MapProjection` each frame so they pan/zoom in lockstep with routes.

### Smooth Vehicle Animation

Four-layer system:
1. **Client-side interpolation** (`animation.py`): Stores prev/curr position snapshots per route. Each frame, lerps lat/lon/heading between them. Distance-clamped to prevent corner-cutting on curves.
2. **Sprite caching** (`vehicle.py`): Two-tier cache by (color, label, quantized_heading). Per-frame cost is dict lookup + blit.
3. **Priority scheduling** (`display.py`): Live-data routes update every 3s, schedule routes every 8s. At most one GTFS query per frame.
4. **Heading smoothing**: Shortest-arc angular lerp handles 0/360 wraparound.

### Live Data Fallback Chain

1. GTFS-RT protobuf feed (if `gtfs_rt_url` configured)
2. Agency adapter (e.g. SEPTA TrainView JSON — auto-maps line names to GTFS route IDs)
3. Schedule interpolation (always available)

`DataSource` enum tracks which source was used; WiFi indicator shows green/red accordingly.

### Shape-Based Interpolation

Vehicle positions interpolate along GTFS shapes.txt polylines (via railroaded's opt-in `shapes=True`) using haversine-based cumulative distance. Heading computed from the polyline segment direction. Reverse trips walk the polyline backward. Falls back to stop-to-stop linear interpolation when shapes unavailable.

### Cross-Agency Stop Matching

Geographic proximity (default 200m) + fuzzy name matching (SequenceMatcher after transit-name normalization). Transitive closure via union-find.

---

## Testing

```sh
poetry install
poetry run pytest tests/ -v
```

82 tests: animation (22), config (11), geo (11), interpolation (20), projection (9), stop matching (9).

---

## Bug History

| Version | Location | Description | Root Cause |
|---------|----------|-------------|------------|
| 0.1.0 | `manager._interpolate_on_polyline` | Vehicles positioned on wrong polyline segment; odd heading angles | Used flat `math.hypot(dlat, dlon)` instead of haversine for cumulative distance. Also, reverse trips didn't flip `frac` on the polyline. Fixed with `_haversine_m()` and `frac = 1.0 - frac` for reverse. |
| 0.1.0 | `animation.interpolate_snapshot` | Vehicles visibly deviating from drawn routes during lerp | Straight-line lat/lon lerp cuts corners on curved routes. Fixed with distance threshold: snap to current position when prev/curr are > ~1km apart. |

---

## Known Limitations

- **Tile download blocks the render thread** — first zoom-in to a new level pauses briefly while tiles download. Could be moved to a background thread.
- **GTFS-RT requires optional packages** (`gtfs-realtime-bindings` + `protobuf`).
- **SEPTA MFL/BSL/PATCO lack public GTFS-RT feeds** — schedule interpolation only.
- **Stop label collision avoidance** in map mode is basic (first-come-first-served).
- **Pan/zoom doesn't re-download tiles at lower zoom levels** when zooming out beyond the base.
- **No loading screen** during initial GTFS download / tile fetch.
