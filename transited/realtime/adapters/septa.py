"""
SEPTA TrainView JSON API adapter.

Fetches real-time train positions from SEPTA's proprietary REST API.
Covers Regional Rail only (not MFL/BSL/PATCO).

The TrainView API returns line names like "Media/Wawa" rather than GTFS
route IDs like "MED".  This adapter builds the mapping automatically from
GTFS route long_name -> route_id by stripping the " Line" suffix.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from ...log import LOG
from .base import LiveDataAdapter, LiveVehicle

_DEFAULT_URL = 'https://www3.septa.org/api/TrainView/index.php'
_TIMEOUT = 5


class SeptaTrainViewAdapter(LiveDataAdapter):
    """Adapter for SEPTA's TrainView JSON API (Regional Rail only)."""

    def __init__(
        self,
        api_url: str = _DEFAULT_URL,
        route_ids: Optional[list[str]] = None,
        route_name_map: Optional[dict[str, str]] = None,
    ) -> None:
        self._url = api_url
        self._route_ids = set(route_ids) if route_ids else set()
        # Map TrainView "line" name -> GTFS route_id.
        # Built automatically if not provided.
        self._name_map: dict[str, str] = route_name_map or {}

    def set_route_mapping(self, gtfs_routes: list) -> None:
        """Build the line name -> route_id map from GTFS route objects.

        Call this after loading GTFS to populate the mapping automatically.
        Each GTFS route has a ``long_name`` like "Media/Wawa Line";
        TrainView uses "Media/Wawa" (without " Line").
        """
        for route in gtfs_routes:
            if route.long_name:
                api_name = route.long_name
                if api_name.endswith(' Line'):
                    api_name = api_name[:-5]
                self._name_map[api_name] = route.id

    def fetch(self) -> Optional[list[LiveVehicle]]:
        try:
            req = urllib.request.Request(self._url)
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as exc:
            LOG.warning('SEPTA TrainView fetch failed: %s', exc)
            return None

        if not isinstance(data, list):
            LOG.warning('SEPTA TrainView: unexpected response format')
            return None

        vehicles: list[LiveVehicle] = []
        for entry in data:
            try:
                lat = float(entry.get('lat', 0))
                lon = float(entry.get('lon', 0))
                if lat == 0 and lon == 0:
                    continue

                line_name = str(entry.get('line', ''))
                # Map TrainView line name to GTFS route_id.
                route_id = self._name_map.get(line_name, line_name)

                heading = None
                raw_heading = entry.get('heading')
                if raw_heading:
                    try:
                        heading = float(raw_heading)
                    except (ValueError, TypeError):
                        pass

                vehicles.append(LiveVehicle(
                    lat=lat,
                    lon=lon,
                    route_id=route_id,
                    heading=heading,
                    speed=None,
                    trip_id=str(entry.get('trainno', '')),
                ))
            except (ValueError, TypeError):
                continue

        LOG.debug('SEPTA TrainView: %d vehicles fetched', len(vehicles))
        return vehicles

    def supports_route(self, route_id: str) -> bool:
        if self._route_ids:
            return route_id in self._route_ids
        return True
