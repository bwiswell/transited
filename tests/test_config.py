"""
Tests for YAML configuration loading.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from transited.config import AppConfig, load_config


class TestLoadConfig:
    def test_loads_default_config(self):
        """The shipped config.yaml should parse without error."""
        config = load_config()
        assert isinstance(config, AppConfig)
        assert len(config.agencies) >= 1

    def test_has_septa_agency(self):
        config = load_config()
        names = [a.name for a in config.agencies]
        assert 'SEPTA' in names

    def test_has_patco_agency(self):
        config = load_config()
        names = [a.name for a in config.agencies]
        assert 'PATCO' in names

    def test_septa_has_routes(self):
        config = load_config()
        septa = next(a for a in config.agencies if a.name == 'SEPTA')
        route_ids = [r.id for r in septa.routes]
        assert 'L1' in route_ids
        assert 'B1' in route_ids

    def test_display_defaults(self):
        config = load_config()
        assert config.display.fps == 30
        assert config.display.dpi > 0

    def test_stop_matching_defaults(self):
        config = load_config()
        assert config.stop_matching.proximity_meters == 200.0
        assert 0 < config.stop_matching.fuzzy_threshold <= 1.0

    def test_route_colors_none_or_tuples(self):
        """Colors are None (use GTFS) or explicit RGB tuples."""
        config = load_config()
        for agency in config.agencies:
            for route in agency.routes:
                assert route.color is None or (
                    isinstance(route.color, tuple) and len(route.color) == 3
                )


class TestMinimalConfig:
    def test_minimal_yaml_parses(self):
        yaml_str = '''
agencies:
  - name: Test
    gtfs_url: https://example.com/gtfs.zip
    routes:
      - id: "1"
'''
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(yaml_str)
            tmp = f.name
        try:
            config = load_config(tmp)
            assert len(config.agencies) == 1
            assert config.agencies[0].name == 'Test'
            assert config.agencies[0].routes[0].id == '1'
            # Defaults applied
            assert config.display.fps == 30
            assert config.stop_matching.proximity_meters == 200.0
        finally:
            os.unlink(tmp)

    def test_missing_agencies_raises(self):
        yaml_str = 'display:\n  fps: 60\n'
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(yaml_str)
            tmp = f.name
        try:
            with pytest.raises(ValueError, match='agencies'):
                load_config(tmp)
        finally:
            os.unlink(tmp)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config('/nonexistent/path.yaml')


class TestColorParsing:
    def test_hex_color(self):
        yaml_str = '''
agencies:
  - name: Test
    gtfs_url: https://example.com/gtfs.zip
    routes:
      - id: "1"
        color: "#FF8800"
'''
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(yaml_str)
            tmp = f.name
        try:
            config = load_config(tmp)
            assert config.agencies[0].routes[0].color == (255, 136, 0)
        finally:
            os.unlink(tmp)
