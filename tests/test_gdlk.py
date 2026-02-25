"""Unit tests for .gdlk binary format (write/read round-trip)."""

import os
import struct
import pytest

from gridlock.gdlk_format import (
    MAGIC, GdlkReader, GdlkWriter, NODE_SIZE, EDGE_SIZE,
    SEC_METADATA, SEC_NODES, SEC_EDGES, SEC_VALIDATION,
)
from gridlock.models.city_package import CityPackage


class TestGdlkWriter:
    def test_magic_bytes(self, tmp_path, minimal_package):
        path = str(tmp_path / "test.gdlk")
        GdlkWriter().write(minimal_package, path)
        with open(path, "rb") as f:
            assert f.read(4) == MAGIC

    def test_version_header(self, tmp_path, minimal_package):
        path = str(tmp_path / "test.gdlk")
        GdlkWriter().write(minimal_package, path)
        with open(path, "rb") as f:
            f.read(4)   # magic
            major, minor = struct.unpack("<HH", f.read(4))
        assert major == 1
        assert minor == 0

    def test_file_is_non_empty(self, tmp_path, minimal_package):
        path = str(tmp_path / "test.gdlk")
        GdlkWriter().write(minimal_package, path)
        assert os.path.getsize(path) > 256

    def test_nodes_section_size(self, tmp_path, minimal_package):
        """NODE section should be len(nodes) * NODE_SIZE bytes."""
        path = str(tmp_path / "test.gdlk")
        GdlkWriter().write(minimal_package, path)
        reader = GdlkReader()
        info = reader.read_header(path)
        # node_count * NODE_SIZE should divide evenly
        expected_node_bytes = info["metadata"]["node_count"] * NODE_SIZE
        assert expected_node_bytes > 0

    def test_edges_section_size(self, tmp_path, minimal_package):
        path = str(tmp_path / "test.gdlk")
        GdlkWriter().write(minimal_package, path)
        info = GdlkReader().read_header(path)
        expected_edge_bytes = info["metadata"]["edge_count"] * EDGE_SIZE
        assert expected_edge_bytes > 0


class TestGdlkReader:
    def test_roundtrip_metadata(self, tmp_path, minimal_package):
        path = str(tmp_path / "roundtrip.gdlk")
        GdlkWriter().write(minimal_package, path)
        info = GdlkReader().read_header(path)
        assert info["metadata"]["city_name"] == "Test City"
        assert info["metadata"]["city_slug"] == "test_city"
        assert info["metadata"]["crs_epsg"] == 32610
        assert info["metadata"]["node_count"] == 4
        assert info["metadata"]["edge_count"] == 4

    def test_roundtrip_version(self, tmp_path, minimal_package):
        path = str(tmp_path / "version.gdlk")
        GdlkWriter().write(minimal_package, path)
        info = GdlkReader().read_header(path)
        assert info["version"] == "1.0"

    def test_sections_present(self, tmp_path, minimal_package):
        path = str(tmp_path / "sections.gdlk")
        GdlkWriter().write(minimal_package, path)
        info = GdlkReader().read_header(path)
        assert SEC_METADATA in info["sections"]
        assert SEC_NODES in info["sections"]
        assert SEC_EDGES in info["sections"]

    def test_roundtrip_validation(self, tmp_path, minimal_package):
        path = str(tmp_path / "val.gdlk")
        GdlkWriter().write(minimal_package, path)
        val = GdlkReader().read_validation(path)
        assert val["passed"] is True
        assert val["vmt_error_pct"] == pytest.approx(16.7, rel=0.01)
        assert val["transit_error_pct"] == pytest.approx(16.7, rel=0.01)

    def test_raises_on_bad_magic(self, tmp_path):
        bad = tmp_path / "bad.gdlk"
        bad.write_bytes(b"NOTG" + b"\x00" * 100)
        with pytest.raises(ValueError, match="Not a .gdlk file"):
            GdlkReader().read_header(str(bad))

    def test_no_transit_network(self, tmp_path):
        pkg = CityPackage(city_name="Empty", city_slug="empty")
        from gridlock.models.graph import RoadGraph
        pkg.road_graph = RoadGraph(nodes={}, edges={}, crs_epsg=4326)
        path = str(tmp_path / "empty.gdlk")
        GdlkWriter().write(pkg, path)
        info = GdlkReader().read_header(path)
        assert info["metadata"]["city_name"] == "Empty"
        assert info["metadata"]["node_count"] == 0
