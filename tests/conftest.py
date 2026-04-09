"""
Pytest fixtures for transited tests.

The PATCO fixture downloads the Speedline GTFS on the first run and writes
a local mGTFS JSON cache so subsequent runs skip the network download.
"""
from __future__ import annotations

import os

import pytest
import railroaded as rr


PATCO_URI   = (
    'https://rapid.nationalrtap.org'
    '/GTFSFileManagement/UserUploadFiles/13562/PATCO_GTFS.zip'
)
PATCO_CACHE = os.path.join(os.path.dirname(__file__), 'patco_cache.json')


@pytest.fixture(scope='session')
def patco_gtfs() -> rr.GTFS:
    """
    Session-scoped PATCO GTFS fixture.  Downloads on the first run and
    caches as mGTFS JSON; subsequent runs load from the cache.
    """
    return rr.GTFS.read(
        name       = 'PATCO',
        gtfs_uri   = PATCO_URI,
        mgtfs_path = PATCO_CACHE,
    )
