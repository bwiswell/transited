# Creating a Custom Live Data Adapter

This directory contains live data adapters that fetch real-time vehicle
positions from transit agency APIs.  Each adapter implements the
`LiveDataAdapter` interface and can be registered for use in `config.yaml`.

## Quick Start

To create an adapter for your transit agency, follow this pattern:

### 1. Create the adapter file

Create a new Python file in this directory (e.g. `my_agency.py`):

```python
"""
My Agency live data adapter.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from ...log import LOG
from .base import LiveDataAdapter, LiveVehicle

_TIMEOUT = 5  # seconds


class MyAgencyAdapter(LiveDataAdapter):
    """Adapter for My Agency's REST API."""

    def __init__(self, api_url: str = 'https://api.myagency.com/vehicles') -> None:
        self._url = api_url

    def fetch(self) -> Optional[list[LiveVehicle]]:
        """Fetch current vehicle positions.

        Return a list of LiveVehicle on success, or None on any failure.
        Returning None triggers the fallback to schedule interpolation.
        """
        try:
            req = urllib.request.Request(self._url)
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as exc:
            LOG.warning('My Agency fetch failed: %s', exc)
            return None

        vehicles: list[LiveVehicle] = []
        for entry in data:
            try:
                vehicles.append(LiveVehicle(
                    lat=float(entry['latitude']),
                    lon=float(entry['longitude']),
                    route_id=str(entry['route_id']),
                    heading=float(entry.get('bearing', 0)) or None,
                    speed=float(entry.get('speed', 0)) or None,
                    trip_id=str(entry.get('trip_id', '')),
                ))
            except (KeyError, ValueError, TypeError):
                continue

        return vehicles

    def supports_route(self, route_id: str) -> bool:
        return True
```

### 2. Register the adapter

In `transited/realtime/manager.py`, add your adapter to the `_ADAPTERS` dict:

```python
from .adapters.my_agency import MyAgencyAdapter

_ADAPTERS: dict[str, type] = {
    'septa_trainview': SeptaTrainViewAdapter,
    'my_agency': MyAgencyAdapter,           # <-- add this
}
```

### 3. Configure in YAML

In your `config.yaml`, add a `live_data` section to the agency:

```yaml
agencies:
  - name: My Agency
    gtfs_url: https://example.com/gtfs.zip
    live_data:
      adapter: my_agency
      adapter_config:
        api_url: https://api.myagency.com/vehicles
    routes:
      - id: "1"
        label: Red Line
```

## Interface Reference

Every adapter must implement two methods from `LiveDataAdapter` (defined
in `base.py`):

### `fetch() -> Optional[list[LiveVehicle]]`

- Fetch current vehicle positions from the agency's API.
- Return a list of `LiveVehicle` on success.
- Return `None` on any failure (network error, timeout, parse error).
  Returning `None` triggers the fallback chain (schedule interpolation).
- The method should have a timeout (recommend 5 seconds).
- Do NOT raise exceptions — catch them and return `None`.

### `supports_route(route_id: str) -> bool`

- Return `True` if this adapter provides data for the given GTFS route ID.
- Return `True` for all routes if the adapter covers the entire agency.

## LiveVehicle Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `lat` | float | Yes | Latitude |
| `lon` | float | Yes | Longitude |
| `route_id` | str | Yes | Must match a GTFS route_id from config.yaml |
| `heading` | float | No | Bearing in degrees (0=north, 90=east) |
| `speed` | float | No | Speed (any unit — for display only) |
| `trip_id` | str | No | GTFS trip_id for schedule correlation |
| `timestamp` | float | No | Unix timestamp of the position report |

## Route ID Mapping

If the agency's API uses different identifiers than GTFS route_ids
(like SEPTA TrainView which uses line names instead of codes), your
adapter can implement a `set_route_mapping(gtfs_routes)` method that
will be called automatically after GTFS data loads.  See
`septa.py:SeptaTrainViewAdapter.set_route_mapping()` for an example.

## Fallback Chain

transited uses this priority order for vehicle positions:

1. **GTFS-RT protobuf** (`live_data.gtfs_rt_url` in config) — standard protocol
2. **Agency adapter** (`live_data.adapter` in config) — your custom adapter
3. **Schedule interpolation** — always available as a fallback

If your adapter returns `None`, transited automatically falls back to
schedule interpolation for that refresh cycle.  If the network recovers,
live data resumes on the next cycle.

## Tips

- Keep the HTTP timeout short (5s) to avoid blocking the render loop.
- The adapter is called once per route per refresh cycle (about every
  1-2 seconds per route in round-robin).  Cache results if the API
  returns data for all routes in one call.
- Log warnings on failure but never raise — the fallback chain depends
  on `None` returns to work correctly.
- Test your adapter standalone before integrating:
  ```python
  adapter = MyAgencyAdapter()
  vehicles = adapter.fetch()
  print(f'{len(vehicles)} vehicles' if vehicles else 'fetch failed')
  ```
