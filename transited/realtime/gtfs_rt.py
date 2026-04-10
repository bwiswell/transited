"""
GTFS-Realtime protobuf vehicle position parser.

Requires ``gtfs-realtime-bindings`` and ``protobuf`` packages.
If not installed, ``fetch()`` returns None (triggers fallback).
"""
from __future__ import annotations

import urllib.request
from typing import Optional

from ..log import LOG
from .adapters.base import LiveVehicle

_TIMEOUT = 5


def fetch_gtfs_rt_vehicles(url: str) -> Optional[list[LiveVehicle]]:
    """
    Fetch and parse a GTFS-RT VehiclePosition feed.

    Returns None if the protobuf libraries are not installed or on any
    network/parse error.
    """
    try:
        from google.transit import gtfs_realtime_pb2
    except ImportError:
        LOG.debug('gtfs-realtime-bindings not installed; skipping GTFS-RT')
        return None

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = resp.read()
    except Exception as exc:
        LOG.warning('GTFS-RT fetch failed (%s): %s', url, exc)
        return None

    try:
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(data)
    except Exception as exc:
        LOG.warning('GTFS-RT parse failed: %s', exc)
        return None

    vehicles: list[LiveVehicle] = []
    for entity in feed.entity:
        if not entity.HasField('vehicle'):
            continue
        v = entity.vehicle
        if not v.HasField('position'):
            continue
        pos = v.position

        route_id = ''
        trip_id = ''
        if v.HasField('trip'):
            route_id = v.trip.route_id or ''
            trip_id = v.trip.trip_id or ''

        vehicles.append(LiveVehicle(
            lat=pos.latitude,
            lon=pos.longitude,
            route_id=route_id,
            heading=pos.bearing if pos.bearing else None,
            speed=pos.speed if pos.speed else None,
            trip_id=trip_id,
            timestamp=v.timestamp if v.timestamp else None,
        ))

    return vehicles
