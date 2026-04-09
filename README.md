# transited

Simple Python app to visually display public transit lines.

## Overview

transited renders a fullscreen schematic display of rail and metro transit lines with animated train position indicators. Train positions are interpolated from GTFS static timetable data in real time.

### Currently displayed lines

| Line | Agency | Services |
|------|--------|----------|
| Market-Frankford Line (MFL) | SEPTA | L1 |
| Broad Street Line (BSL) | SEPTA | B1 (local), B2 (express), B3 (Broad-Ridge Spur) |
| PATCO Speedline | PATCO | Route 2 |

### Features

- **Multi-track rendering** with 4-track/2-track sections and visual taper transitions
- **Broad-Ridge Spur** rendered as an intra-row branch with diagonal connector
- **DPI-aware fonts** and fullscreen auto-detection
- **Angled station labels** to fit dense stop sequences
- **Automatic vertical scrolling** with touch/mouse override
- **GTFS route stripping** for fast cached loads (SEPTA bus feed stripped from ~450 MB to < 5 MB)
- **Simulation mode** (`--sim-time`) with running clock for off-hours testing
- **Cross-line alignment** (MFL and PATCO aligned at 8th & Market)
- **Pre-rendered background** with incremental train updates for smooth rendering

## Dependencies

- Python 3.11+
- [railroaded](https://github.com/bwiswell/railroaded) (GTFS parsing, via [seared](https://github.com/bwiswell/seared) serialisation)
- [pygame-ce](https://pypi.org/project/pygame-ce/) (rendering)

## Quick start

```sh
poetry install
python -m transited                              # live, fullscreen
python -m transited --sim-time "16:00:00"        # simulate 4 PM today
```

### Raspberry Pi / framebuffer

```sh
SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 TRANSITED_DPI=160 python -m transited
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRANSITED_DPI` | `96` | Display DPI for font scaling |
| `SDL_VIDEODRIVER` | (auto) | Set to `fbcon` for RPi framebuffer |
| `SDL_FBDEV` | (auto) | Framebuffer device path |

## Testing

```sh
poetry run pytest tests/ -v
```

44 tests (20 offline unit tests + 24 PATCO GTFS integration tests).
