"""
Entry point for ``python -m transited``.

Options
-------
--sim-time DATETIME
    Simulate at a time that advances in real-time from the given start.
--simple
    Use the horizontal schematic renderer instead of the geographic map.
--config PATH
    Path to a YAML config file (default: ``config.yaml`` in project root).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time

from .config import load_config
from .log import LOG, setup_logging
from .static.loader import load_agencies
from .static.stops import build_route_data


def _parse_sim_time(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
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
    setup_logging()

    parser = argparse.ArgumentParser(
        prog='transited',
        description='Transit line visualisation.',
    )
    parser.add_argument(
        '--sim-time', default=None,
        help='Simulate at a fixed start time (ISO or HH:MM:SS).',
    )
    parser.add_argument(
        '--simple', action='store_true',
        help='Use horizontal schematic renderer instead of geographic map.',
    )
    parser.add_argument(
        '--config', default=None,
        help='Path to YAML config file (default: config.yaml).',
    )
    args = parser.parse_args()

    sim_time = None
    if args.sim_time:
        try:
            sim_time = _parse_sim_time(args.sim_time)
        except ValueError as exc:
            print(f'Error: {exc}', file=sys.stderr)
            sys.exit(1)
        LOG.info('Simulation time: %s', sim_time)

    # Load config.
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f'Config error: {exc}', file=sys.stderr)
        sys.exit(1)

    # Load GTFS data.
    LOG.info('transited -- loading GTFS data ...')
    load_shapes = not args.simple
    try:
        agency_data = load_agencies(
            config.agencies,
            load_shapes=load_shapes,
        )
    except Exception as exc:
        LOG.error('Failed to load GTFS data: %s', exc)
        sys.exit(1)

    # Build per-route data (canonical stops + stop index).
    from .static.stops import RouteData
    route_data_list: list[RouteData] = []
    for ad in agency_data:
        all_route_ids = [r.id for r in ad.config.routes]
        for rc in ad.config.routes:
            rd = build_route_data(ad.gtfs, ad.config.name, rc, all_route_ids)
            LOG.info('  %s/%s: %d stops, %d index entries',
                     ad.config.name, rc.id, len(rd.stops), len(rd.stop_index))
            route_data_list.append(rd)

    # Create renderer.
    if args.simple:
        from .ui.simple.renderer import SimpleRenderer
        from .ui.simple.layout import compute_simple_layouts
        renderer = SimpleRenderer(dpi=config.display.dpi)
        layouts = compute_simple_layouts(route_data_list)
        renderer.set_layouts(layouts)
    else:
        from .static.layout import build_route_geometries
        from .ui.map.renderer import MapRenderer
        geometries = build_route_geometries(agency_data, route_data_list)
        renderer = MapRenderer(
            geometries,
            dpi=config.display.dpi,
            idle_timeout=config.display.idle_timeout_secs,
            tile_style=config.display.map_tiles,
            bg_color=config.display.background_color,
        )

    LOG.info('Ready. Displaying %d route(s).', len(route_data_list))

    # Run the display loop.
    from .ui.display import TransitedDisplay
    display = TransitedDisplay(
        config=config,
        agency_data=agency_data,
        route_data=route_data_list,
        renderer=renderer,
        sim_time=sim_time,
    )
    display.run()


if __name__ == '__main__':
    main()
