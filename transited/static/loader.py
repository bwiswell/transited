"""
GTFS feed downloading, caching, and route stripping for transited.

Driven by :class:`~transited.config.AgencyConfig` from the YAML config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import railroaded as rr

from ..config import AgencyConfig
from ..log import LOG

# Project-level data directory (alongside pyproject.toml).
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))


@dataclass
class AgencyData:
    """A loaded GTFS feed and its config."""
    config: AgencyConfig
    gtfs:   rr.GTFS


def _strip_gtfs(gtfs: rr.GTFS, route_ids: list[str]) -> rr.GTFS:
    """Return a copy of *gtfs* containing only trips on *route_ids*."""
    from railroaded.tables import Routes, Stops, Schedules, Shapes, Trips

    keep = set(route_ids)

    kept_trips: dict[str, object] = {}
    kept_stop_ids: set[str] = set()
    kept_service_ids: set[str] = set()
    kept_shape_ids: set[str] = set()

    for trip in gtfs.trips.trips:
        if trip.route_id in keep:
            kept_trips[trip.id] = trip
            kept_service_ids.add(trip.service_id)
            if trip.shape_id:
                kept_shape_ids.add(trip.shape_id)
            for st in trip.timetable.stops:
                if st.stop_id:
                    kept_stop_ids.add(st.stop_id)

    kept_routes = {rid: gtfs.routes[rid] for rid in keep
                   if gtfs.routes[rid] is not None}
    kept_stops = {sid: gtfs.stops[sid] for sid in kept_stop_ids
                  if gtfs.stops[sid] is not None}
    kept_scheds = {sid: gtfs.schedules[sid] for sid in kept_service_ids
                   if gtfs.schedules[sid] is not None}

    # Strip shapes if they were loaded.
    kept_shapes: dict = {}
    if gtfs.shapes and gtfs.shapes.ids:
        kept_shapes = {sid: gtfs.shapes[sid] for sid in kept_shape_ids
                       if gtfs.shapes[sid] is not None}

    return rr.GTFS(
        name=gtfs.name,
        feed=gtfs.feed,
        agencies=gtfs.agencies,
        routes=Routes(kept_routes),
        schedules=Schedules(kept_scheds),
        stops=Stops(kept_stops),
        trips=Trips(kept_trips),
        shapes=Shapes(kept_shapes),
    )


def load_agencies(
    agencies: list[AgencyConfig],
    data_dir: str = DATA_DIR,
    load_shapes: bool = False,
) -> list[AgencyData]:
    """
    Download / cache GTFS feeds for each configured agency.

    Parameters
    ----------
    agencies : list[AgencyConfig]
        From the YAML config.
    data_dir : str
        Directory for mGTFS JSON caches.
    load_shapes : bool
        If True, pass ``shapes=True`` to ``GTFS.read()`` for map rendering.

    Returns
    -------
    list[AgencyData]
    """
    os.makedirs(data_dir, exist_ok=True)
    result: list[AgencyData] = []

    for ac in agencies:
        # Sanitize name for cache filename.
        safe_name = ac.name.lower().replace(' ', '_')
        cache_path = os.path.join(data_dir, f'{safe_name}.json')

        if os.path.exists(cache_path):
            LOG.info('Loading %s GTFS from cache ...', ac.name)
            gtfs = rr.GTFS.read(name=ac.name, mgtfs_path=cache_path)
            # Rebuild cache if shapes were requested but cache has none.
            if load_shapes and (gtfs.shapes is None or not gtfs.shapes.ids):
                LOG.info('  Cache lacks shapes; rebuilding ...')
                os.remove(cache_path)
                gtfs = None  # fall through to download below

        if not os.path.exists(cache_path):
            LOG.info('Downloading %s GTFS ...', ac.name)
            gtfs = rr.GTFS.read(
                name=ac.name,
                gtfs_uri=ac.gtfs_url,
                gtfs_sub=ac.gtfs_sub,
                shapes=load_shapes,
            )
            if ac.strip_to_routes:
                LOG.info('  Stripping to routes %s ...', ac.strip_to_routes)
                gtfs = _strip_gtfs(gtfs, ac.strip_to_routes)
            rr.GTFS.save(gtfs, cache_path)

        route_ids = [r.id for r in ac.routes]
        n_trips = sum(
            len(gtfs.on_route(rid).trips.ids) for rid in route_ids
        )
        LOG.info('  %s: %d routes, %d trips, %d stops',
                 ac.name, len(route_ids), n_trips, len(gtfs.stops.ids))

        result.append(AgencyData(config=ac, gtfs=gtfs))

    return result
