# transited — Codebase Reference

> Last updated: 2026-04-09 | Branch: main | Version: **0.0.1**

---

## What This Project Does

`transited` is a Python visualisation tool for public transit rail and metro services. It displays user-specified lines as horizontal schematic tracks with station tick marks and animated vehicle graphics showing current (or schedule-interpolated) train positions in real time.

**Primary use case:** Render a minimal, at-a-glance view of the PATCO Speedline, SEPTA Market-Frankford Line, and SEPTA Broad Street Line (local, express, and Broad-Ridge Spur) on a fullscreen DPI-aware display with angled station labels, multi-track rendering, automatic vertical scrolling, and touch support.

---

## Tech Stack

| Language | Key Dependencies | Build Tool |
|----------|-----------------|------------|
| Python 3.11+ | `railroaded` (local path dep, `../railroaded/python`), `pygame-ce ^2.5` | Poetry |

**Dev dependencies:** `pytest ^8.0`

**Platform targets:** Windows (development) and Raspberry Pi / Raspbian (deployment).

---

## Architecture

```
transited/__main__.py    (argparse CLI: --sim-time; loads data, starts display)
    ├── static.py        (GTFS loading + route stripping, canonical stops,
    │                     name-based stop aliasing, cross-line layout, branches)
    │       ├── LineData   → LineLayout (with BranchLayouts)
    │       └── railroaded.GTFS.read / _strip_gtfs / GTFS.save
    ├── realtime.py      (timetable interpolation + live-feed stub → VehiclePosition)
    ├── config.py        (all hardcoded specs: lines, routes, colours, track geometry)
    └── ui.py            (pygame fullscreen: auto-detect screen, DPI fonts,
                          angled text, multi-track, scroll, pre-rendered background)
```

### Key types

| Type | Module | Description |
|------|--------|-------------|
| `RouteService` | `config.py` | Frozen: `route_id`, `color`, `label`, `track_pair` (`'outer'`/`'inner'`) |
| `TrackSegment` | `config.py` | Frozen: `start_stop_id`, `end_stop_id`, `n_tracks` (2 or 4) |
| `BranchSpec` | `config.py` | Frozen: spur within a parent row (`canonical_stop_ids`, `junction_stop_id`, `y_offset_px`) |
| `DisplayLineSpec` | `config.py` | Frozen: name, GTFS key, services, `track_color`, `track_segments`, `branches`, `reverse` |
| `SharedStop` | `config.py` | Cross-line anchor: `(line_short_name, canonical_stop_id)` pairs |
| `RowConnector` | `config.py` | Cross-row visual link (currently unused; intra-row branches use `BranchLayout` instead) |
| `StopInfo` | `static.py` | `stop_id`, display `name` (<=14 chars), `full_name` |
| `LineData` | `static.py` | `spec`, `gtfs`, ordered `stops`, `stop_index` (with directional aliases) |
| `ResolvedTrackSegment` | `static.py` | Resolved from `TrackSegment` with canonical indices and x-fracs |
| `BranchLayout` | `static.py` | Positioned branch: stops, `stop_x_fracs`, `stop_index`, `junction_x_frac`, `y_offset_px` |
| `LineLayout` | `static.py` | `line_data`, `stop_x_fracs`, track bounds, `track_segments`, `branches`, `canonical_to_x_frac()`, `n_tracks_at_x()` |
| `ResolvedConnector` | `static.py` | Pixel-ready cross-row connector (`from/to_line_idx`, `from/to_x_frac`, `color`) |
| `VehiclePosition` | `realtime.py` | `track_frac` (layout x-frac space), `forward`, `color`, `track_pair` |

### Display lines

| Line | Short | Services | Notes |
|------|-------|----------|-------|
| Market-Frankford Line | MFL | L1 | 28 stops, even spacing |
| Broad Street Line | BSL | B1 (local/outer), B2 (express/inner), B3 (spur/inner on trunk) | 22 main stops; 4-track Fern Rock-Lombard-South, 2-track Lombard-South-NRG; Broad-Ridge Spur as intra-row branch |
| PATCO Speedline | PATCO | 2 | 14 stops, reversed (Lindenwold rightmost); scaled to align 8th & Market with MFL |

---

## File Structure

```
transited/
├── CODEBASE.md
├── pyproject.toml           # Python 3.11+, version 0.0.1
├── poetry.lock
├── .gitignore
├── data/                    # mGTFS JSON cache (gitignored, created at runtime)
│   ├── septa_bus.json       #   stripped to L1/B1/B2/B3 routes only (~5 MB)
│   └── patco.json           #   full PATCO feed (~1 MB)
├── transited/
│   ├── __init__.py          # version string
│   ├── __main__.py          # argparse CLI: --sim-time; loads GTFS, computes layouts, starts display
│   ├── config.py            # RouteService, TrackSegment, BranchSpec, DisplayLineSpec, SharedStop, colours, geometry
│   ├── static.py            # load_line_data(), _strip_gtfs(), _canonical_stops(), _build_stop_index(),
│   │                        # compute_all_layouts(), resolve_connectors(), BranchLayout, LineLayout
│   ├── realtime.py          # get_positions(), get_branch_positions(), _positions_from_points(), _try_live_positions() stub
│   └── ui.py                # TransitedDisplay, _ScrollState, fullscreen auto-detect, DPI fonts, angled text,
│                            # multi-track + taper, pre-rendered background, incremental train updates
└── tests/
    ├── conftest.py          # session-scoped patco_gtfs fixture
    ├── patco_cache.json     # mGTFS cache (gitignored)
    ├── test_realtime.py     # 20 unit tests (no network)
    └── test_static.py       # 24 integration tests (PATCO fixture)
```

---

## Key Concepts

### Fullscreen auto-detection

The display opens fullscreen at the native resolution detected by `pygame.display.Info()`. `SCREEN_W` and `SCREEN_H` in `config.py` default to `0` (auto-detect); set them to non-zero values to override. Horizontal track padding is computed as 10% of the detected screen width. DPI is set via the `TRANSITED_DPI` environment variable (default 96).

### DPI-aware fonts

Font sizes are specified in typographic points (`FONT_LABEL_PT`, `FONT_STOP_PT`). At runtime, `pt_to_px(pt)` converts: `round(pt * DISPLAY_DPI / 72)`.

### Angled stop names

Station names are rendered, then rotated by `STOP_NAME_ANGLE_DEG` (default -45). Even-indexed stops above the track, odd-indexed below.

### Multi-track rendering

Each `DisplayLineSpec` can declare `track_segments` defining how many physical tracks exist per section:

- 2-track: two parallel lines at `cy +/- TRACK_GAUGE/2`
- 4-track: outer pair at `cy +/- (TRACK_PAIR_GAP/2 + TRACK_GAUGE)`, inner pair at `cy +/- TRACK_GAUGE/2`

At a 4-to-2 boundary (e.g. Lombard-South on BSL), diagonal taper lines extend rightward from the boundary station by `MERGE_TAPER_PX` pixels. `RouteService.track_pair` (`'inner'` for B2/B3, `'outer'` for B1) determines which tracks a train icon renders on.

### BSL Broad-Ridge Spur (intra-row branch)

The B3 spur (Chinatown, 8th-Market) is rendered within the BSL row as a `BranchLayout`, positioned below the main track at `y_offset_px=48`. A diagonal 2-track connector links BSL Fairmount to Chinatown (the branch's first stop). B3 trains appear on the BSL main track while on the shared trunk (Fern Rock to Fairmount), then on the branch track after diverging. Fairmount is NOT duplicated on the branch.

### SEPTA directional stop-ID aliasing

SEPTA's GTFS uses different `stop_id` values for northbound vs southbound platforms. `_build_stop_index` resolves this by matching on `stop_name`: every trip on every service route is scanned, and any `stop_id` whose name matches a canonical stop is added to `stop_index` at that canonical index.

### Cross-line alignment

`compute_all_layouts()` positions stops to respect shared-station constraints:

| Anchor | Lines | Mechanism |
|--------|-------|-----------|
| 8th & Market | MFL, PATCO | PATCO scaled so stop `'11'` aligns with MFL stop `'2457'`; Lindenwold reaches x=1.0 |
| Fairmount | BSL, B3 branch | B3 branch starts one BSL stop-spacing past Fairmount's x-position |

### PATCO display direction

PATCO is displayed reversed (`reverse=True`): Center City (15-16th and Locust) on the left, Lindenwold (NJ) on the right.

### mGTFS caching and route stripping

GTFS feeds are downloaded once and cached as mGTFS JSON in `data/`. When a source declares `strip_to_routes` (e.g. `('L1', 'B1', 'B2', 'B3')` for `septa_bus`), the full feed is stripped to only those routes' trips/stops/schedules via `_strip_gtfs()` before saving. This reduces the SEPTA bus cache from ~450 MB to < 5 MB. Delete `data/septa_bus.json` to force a rebuild.

### Vehicle position strategy

All current lines lack public GTFS-RT vehicle position feeds. Positions are **interpolated from the scheduled timetable**. `_try_live_positions()` is a documented stub that returns `None`, triggering fallback to interpolation. The system operates fully offline when the mGTFS cache exists.

### Simulation mode (--sim-time) with running clock

```sh
python -m transited --sim-time "2026-04-09 16:00:00"
python -m transited --sim-time "16:00:00"    # uses today's date
```

The display starts at the given time and advances in real-time (wall-clock seconds = simulated seconds). Live-feed attempts are disabled in sim mode.

### Pre-rendered background and incremental updates

Static elements (tracks, ticks, station names, labels, branch connectors, dividers) are rendered once to a background surface (`_bg_surface`) and only re-rendered when the scroll position changes. Each frame blits the background, then overlays train icons.

Train position updates are spread across frames via round-robin: one layout updates per `REFRESH_SECS / n_layouts` interval, preventing a single-frame computation spike.

### Vertical scrolling

When canvas height exceeds screen height, auto-scroll bounces at `SCROLL_SPEED_PX_S` px/s with `SCROLL_PAUSE_S` at each end. Touch/mouse drag overrides; auto-scroll resumes after `SCROLL_RESUME_S` of inactivity.

### Raspberry Pi / framebuffer

```sh
SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 TRANSITED_DPI=160 python -m transited
```

`ui._setup_sdl()` auto-sets these when `$DISPLAY` is unset on Linux.

---

## Testing

```sh
poetry install
poetry run pytest tests/ -v
```

44 tests: 20 in `test_realtime.py` (offline, pure unit tests) and 24 in `test_static.py` (PATCO GTFS session-scoped fixture).

### Test classes

| File | Class | Coverage |
|------|-------|----------|
| `test_realtime.py` | `TestNoPosition` | None-returns for edge cases |
| | `TestBoundary` | Exact start, exact end, clamping |
| | `TestPosition` | Midpoint, quarter, multi-segment |
| | `TestDirection` | Forward / reverse at start, end, midpoint |
| | `TestRobustness` | Zero-duration segment, overnight times |
| `test_static.py` | `TestShorten` | Name abbreviation and truncation |
| | `TestCanonicalStops` | PATCO: 14 stops, uniqueness, fit, terminals |
| | `TestCanonicalStopsExplicit` | `canonical_stop_ids` override |
| | `TestBuildStopIndex` | Name-based aliasing completeness |
| | `TestLayouts` | Even spacing, `canonical_to_x_frac`, monotonicity |
| | `TestPtToPx` | DPI-aware point-to-pixel conversion |
| | `TestResolveConnectors` | Valid connector resolves, missing line skipped |
| | `TestTrackSegments` | Default 2-track, `n_tracks_at_x`, PATCO reversal, explicit 4/2-track resolution |

---

## Bug History

| Version | Location | Description | Root Cause |
|---------|----------|-------------|------------|
| 0.0.1 | `static.py:_stop_x_frac` | Diagonal connector between BSL and B3 spur failed to resolve | `_stop_x_frac` searched only canonical stop IDs, not the full `stop_index` (which includes directional aliases). BSL canonical Fairmount was `1278`, but the connector config referenced `32146`. Fixed by using `stop_index.get()`. |
| 0.0.1 | `static.py:_resolve_track_segments` | BSL 4-track/2-track boundary did not resolve when configured stop IDs differed from canonical | Used only canonical stop IDs for lookup. Fixed by using the full `stop_index` (with name-based aliases). |

---

## Known Limitations

- **Lines hardcoded** to MFL, BSL (B1+B2+B3 with Broad-Ridge Spur branch), PATCO. Configurable line selection is deferred.
- **No real-time feeds** — all lines lack public GTFS-RT vehicle position APIs. `_try_live_positions()` is a stub.
- **SEPTA bus GTFS first download is slow** — the initial download parses the full feed before stripping; subsequent loads use the stripped cache and are fast.
- **BSL B3 spur 8th-Market does not align with MFL 8th-Market** — BSL runs N-S and MFL runs E-W, making the geometric constraint infeasible without compressing the spur to < 40 px.
- **Train icons overlap** when vehicles are close together.
- **Font sizes may need per-device tuning** — set `TRANSITED_DPI` to match the physical display.
- **`pygame-ce` arm64 wheels** — on older Raspberry Pi OS, may need building from source.
