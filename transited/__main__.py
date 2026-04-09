"""
Entry point for ``python -m transited``.

Options
-------
--sim-time DATETIME
    Pretend the current time is DATETIME instead of the wall clock.
    Accepts ISO format (``2026-04-09 16:00:00``) or time-only
    (``16:00:00``, assumes today's date).  Forces timetable-interpolation
    mode (no live-feed attempts).

Environment Variables
---------------------
TRANSITED_DPI
    Override the default display DPI (96).  Affects font sizes and row
    heights.

SDL_VIDEODRIVER / SDL_FBDEV
    Set these for Raspberry Pi framebuffer usage.  ``ui.py`` sets them
    automatically when ``$DISPLAY`` is unset on Linux.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time

from .static import compute_all_layouts, load_line_data, resolve_connectors
from .ui import TransitedDisplay


def _parse_sim_time(raw: str) -> datetime:
    """Parse an ISO datetime or time-only string into a datetime."""
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    # Try time-only (e.g. "16:00:00" or "16:00").
    try:
        t = time.fromisoformat(raw)
        return datetime.combine(date.today(), t)
    except ValueError:
        pass
    raise ValueError(
        f'Cannot parse --sim-time {raw!r}.  '
        f'Expected "YYYY-MM-DD HH:MM:SS" or "HH:MM:SS".'
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='transited',
        description='Minimal rail/metro line visualisation.',
    )
    parser.add_argument(
        '--sim-time',
        default=None,
        help=(
            'Simulate at a fixed time (ISO: "2026-04-09 16:00:00" '
            'or time-only: "16:00:00").  Disables live data.'
        ),
    )
    args = parser.parse_args()

    sim_time = None
    if args.sim_time:
        try:
            sim_time = _parse_sim_time(args.sim_time)
        except ValueError as exc:
            print(f'Error: {exc}', file=sys.stderr)
            sys.exit(1)
        print(f'Simulation time: {sim_time}', flush=True)

    print('transited \u2014 loading GTFS data\u2026', flush=True)
    print(
        '  (First run downloads and caches feeds; '
        'the SEPTA bus feed may take several minutes.)',
        flush=True,
    )
    try:
        line_data = load_line_data()
    except Exception as exc:
        print(f'Fatal: failed to load GTFS data \u2014 {exc}', file=sys.stderr)
        sys.exit(1)

    layouts = compute_all_layouts(line_data)
    connectors = resolve_connectors(layouts)
    print(f'Ready. Displaying {len(layouts)} line(s).', flush=True)

    TransitedDisplay(layouts, sim_time=sim_time, connectors=connectors).run()


if __name__ == '__main__':
    main()
