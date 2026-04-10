"""
Abstract interface for live transit data adapters.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LiveVehicle:
    """A vehicle position from a live data source."""
    lat:       float
    lon:       float
    route_id:  str
    heading:   Optional[float] = None
    speed:     Optional[float] = None
    trip_id:   Optional[str] = None
    timestamp: Optional[float] = None


class LiveDataAdapter(ABC):
    """Base class for agency-specific live data adapters."""

    @abstractmethod
    def fetch(self) -> Optional[list[LiveVehicle]]:
        """
        Fetch current vehicle positions.

        Returns a list of LiveVehicle on success, or None on any failure
        (network error, timeout, parse error).  Returning None triggers
        the fallback chain.
        """
        ...

    @abstractmethod
    def supports_route(self, route_id: str) -> bool:
        """Whether this adapter provides data for the given route."""
        ...
