"""
.gdlk binary format encoder/decoder.

File layout:
  [4]   magic: b'GDLK'
  [2]   version_major (uint16 LE)
  [2]   version_minor (uint16 LE)
  [4]   toc_offset from file start (uint32 LE)
  [4]   section_count (uint32 LE)
  [8]   created_timestamp_ms (int64 LE)
  [4]   flags (uint32): bit0=lz4-compressed (unused in Phase 0)
  [36]  reserved
  --- 64 bytes total header ---

  Table of Contents (at toc_offset):
    Per section, 24 bytes:
      [8]  section_id (uint64 LE)
      [8]  byte_offset from file start (uint64 LE)
      [8]  byte_length (uint64 LE)

  Sections (in order after TOC):
    0x01  METADATA       — JSON bytes (city name, bbox, version, etc.)
    0x02  NODES          — packed fixed-width node records
    0x03  EDGES          — packed fixed-width edge records
    0x04  TRANSIT_STOPS  — packed stop records
    0x05  TRANSIT_ROUTES — JSON bytes (variable-length routes)
    0x06  DEMAND_ZONES   — JSON bytes
    0x07  CENSUS_TRACTS  — JSON bytes
    0x08  VALIDATION     — JSON bytes
    0x09  STRINGS        — null-terminated string pool
"""

from __future__ import annotations

import io
import json
import struct
from datetime import datetime, timezone

from gridlock.models.city_package import CityPackage, ValidationStats
from gridlock.models.graph import RoadEdge, RoadNode

MAGIC = b"GDLK"
VERSION_MAJOR = 1
VERSION_MINOR = 0
HEADER_SIZE = 64
TOC_ENTRY_SIZE = 24

# Section IDs
SEC_METADATA       = 0x01
SEC_NODES          = 0x02
SEC_EDGES          = 0x03
SEC_TRANSIT_STOPS  = 0x04
SEC_TRANSIT_ROUTES = 0x05
SEC_DEMAND_ZONES   = 0x06
SEC_CENSUS_TRACTS  = 0x07
SEC_VALIDATION     = 0x08
SEC_STRINGS        = 0x09

# Enum for highway_type → uint8
HIGHWAY_ENUM: dict[str, int] = {
    "motorway": 0, "motorway_link": 1, "trunk": 2, "trunk_link": 3,
    "primary": 4, "primary_link": 5, "secondary": 6, "secondary_link": 7,
    "tertiary": 8, "tertiary_link": 9, "residential": 10,
    "living_street": 11, "service": 12, "unclassified": 13,
}
HIGHWAY_ENUM_INV: dict[int, str] = {v: k for k, v in HIGHWAY_ENUM.items()}

# Node record: 48 bytes
# Q(8) node_id | d(8) x | d(8) y | f(4) elev | B(1) is_intersection | 19x pad
NODE_FMT = "<QddfB19x"
NODE_SIZE = struct.calcsize(NODE_FMT)  # 48

# Edge record: 80 bytes
# I(4) edge_id | Q(8) u | Q(8) v | Q(8) osm_way_id |
# H(2) name_offset | B(1) hw_enum | B(1) lanes |
# f(4) speed_kph | f(4) length_m | f(4) t0_sec | f(4) capacity |
# f(4) volume | f(4) congestion | f(4) travel_time | f(4) equity |
# B(1) has_bus_lane | 11x pad
EDGE_FMT = "<IQQQHBBffffffffB7x"
EDGE_SIZE = struct.calcsize(EDGE_FMT)

# Transit stop record: 32 bytes
# H(2) stop_id_offset | H(2) name_offset | d(8) x | d(8) y | f(4) radius | 8x pad
STOP_FMT = "<HHddf8x"
STOP_SIZE = struct.calcsize(STOP_FMT)  # 32


class GdlkWriter:
    def __init__(self) -> None:
        self._pool: list[str] = [""]       # index 0 = empty
        self._index: dict[str, int] = {"": 0}

    def _intern(self, s: str) -> int:
        s = s or ""
        if s not in self._index:
            self._index[s] = len(self._pool)
            self._pool.append(s)
        return self._index[s]

    def write(self, package: CityPackage, output_path: str) -> None:
        """Serialize CityPackage → .gdlk file."""
        # Build sections (order matters for string pool: pool grows as sections build)
        sections: list[tuple[int, bytes]] = [
            (SEC_METADATA,       self._sec_metadata(package)),
            (SEC_NODES,          self._sec_nodes(package)),
            (SEC_EDGES,          self._sec_edges(package)),
            (SEC_TRANSIT_STOPS,  self._sec_transit_stops(package)),
            (SEC_TRANSIT_ROUTES, self._sec_transit_routes(package)),
            (SEC_DEMAND_ZONES,   self._sec_demand_zones(package)),
            (SEC_CENSUS_TRACTS,  self._sec_census_tracts(package)),
            (SEC_VALIDATION,     self._sec_validation(package)),
            # String pool last (grows as other sections are built)
            (SEC_STRINGS,        self._sec_strings()),
        ]

        toc_offset = HEADER_SIZE
        data_start = HEADER_SIZE + TOC_ENTRY_SIZE * len(sections)

        # Compute byte offsets
        toc: list[tuple[int, int, int]] = []
        offset = data_start
        for sec_id, data in sections:
            toc.append((sec_id, offset, len(data)))
            offset += len(data)

        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        with open(output_path, "wb") as f:
            # Header (64 bytes)
            f.write(MAGIC)
            f.write(struct.pack("<HH", VERSION_MAJOR, VERSION_MINOR))
            f.write(struct.pack("<II", toc_offset, len(sections)))
            f.write(struct.pack("<q", ts_ms))
            f.write(struct.pack("<I", 0))   # flags
            f.write(b"\x00" * 36)           # reserved

            # TOC
            for sec_id, sec_offset, sec_len in toc:
                f.write(struct.pack("<QQQ", sec_id, sec_offset, sec_len))

            # Section data
            for _, data in sections:
                f.write(data)

    # ---- Section builders ----

    def _sec_metadata(self, pkg: CityPackage) -> bytes:
        d = {
            "city_name":        pkg.city_name,
            "city_slug":        pkg.city_slug,
            "pipeline_version": pkg.pipeline_version,
            "created_at":       pkg.created_at,
            "crs_epsg":         pkg.crs_epsg,
            "bbox":             list(pkg.bbox),
            "node_count":       len(pkg.road_graph.nodes) if pkg.road_graph else 0,
            "edge_count":       len(pkg.road_graph.edges) if pkg.road_graph else 0,
        }
        return json.dumps(d).encode()

    def _sec_nodes(self, pkg: CityPackage) -> bytes:
        buf = io.BytesIO()
        if pkg.road_graph:
            for node in pkg.road_graph.nodes.values():
                buf.write(struct.pack(
                    NODE_FMT,
                    node.node_id,
                    node.x,
                    node.y,
                    node.elevation_m,
                    1 if node.is_intersection else 0,
                ))
        return buf.getvalue()

    def _sec_edges(self, pkg: CityPackage) -> bytes:
        buf = io.BytesIO()
        if pkg.road_graph:
            for edge in pkg.road_graph.edges.values():
                name_off = self._intern(edge.name)
                hw_enum = HIGHWAY_ENUM.get(edge.highway_type, 13)
                buf.write(struct.pack(
                    EDGE_FMT,
                    edge.edge_id,
                    edge.u,
                    edge.v,
                    edge.osm_way_id,
                    name_off,
                    hw_enum,
                    edge.lanes,
                    edge.speed_kph,
                    edge.length_m,
                    edge.t0_sec,
                    float(edge.capacity_veh_hr),
                    edge.volume_veh_hr,
                    edge.congestion_ratio,
                    edge.travel_time_sec,
                    edge.equity_weight,
                    1 if edge.has_bus_lane else 0,
                ))
        return buf.getvalue()

    def _sec_transit_stops(self, pkg: CityPackage) -> bytes:
        buf = io.BytesIO()
        if pkg.transit_network:
            for stop in pkg.transit_network.stops.values():
                sid_off = self._intern(stop.stop_id)
                name_off = self._intern(stop.name)
                buf.write(struct.pack(
                    STOP_FMT,
                    sid_off,
                    name_off,
                    stop.x,
                    stop.y,
                    stop.accessibility_radius_m,
                ))
        return buf.getvalue()

    def _sec_transit_routes(self, pkg: CityPackage) -> bytes:
        if not pkg.transit_network:
            return b"[]"
        routes = []
        for r in pkg.transit_network.routes.values():
            routes.append({
                "route_id":       r.route_id,
                "short_name":     r.short_name,
                "long_name":      r.long_name,
                "route_type":     r.route_type,
                "headway_min":    r.headway_minutes,
                "stop_ids":       r.stop_ids[:200],
                "edge_ids":       r.edge_ids_on_route[:500],
            })
        return json.dumps(routes).encode()

    def _sec_demand_zones(self, pkg: CityPackage) -> bytes:
        zones = []
        for z in pkg.demand_zones:
            try:
                coords = [list(c) for c in z.geometry.exterior.coords[:200]]
            except Exception:
                coords = []
            zones.append({
                "zone_id":            z.zone_id,
                "centroid_x":         z.centroid_x,
                "centroid_y":         z.centroid_y,
                "land_use_class":     z.land_use_class,
                "trip_gen_rate":      z.trip_generation_rate,
                "nearest_node_id":    z.nearest_node_id,
                "equity_score":       z.equity_score,
                "polygon":            coords,
            })
        return json.dumps(zones).encode()

    def _sec_census_tracts(self, pkg: CityPackage) -> bytes:
        tracts = [{
            "geoid":           t.geoid,
            "population":      t.population,
            "median_income":   t.median_income,
            "pct_zero_vehicle": t.pct_zero_vehicle,
            "pct_minority":    t.pct_minority,
            "equity_score":    t.equity_score,
        } for t in pkg.census_tracts]
        return json.dumps(tracts).encode()

    def _sec_validation(self, pkg: CityPackage) -> bytes:
        if not pkg.validation:
            return b"{}"
        v = pkg.validation
        return json.dumps({
            "modeled_vmt_daily":           v.modeled_vmt_daily,
            "target_vmt_daily":            v.target_vmt_daily,
            "modeled_transit_ridership":   v.modeled_transit_ridership,
            "target_transit_ridership":    v.target_transit_ridership,
            "vmt_error_pct":               v.vmt_error_pct,
            "transit_error_pct":           v.transit_error_pct,
            "passed":                      v.passed,
        }).encode()

    def _sec_strings(self) -> bytes:
        buf = io.BytesIO()
        for s in self._pool:
            buf.write(s.encode("utf-8"))
            buf.write(b"\x00")
        return buf.getvalue()


class GdlkReader:
    """Reads header and metadata sections from a .gdlk file."""

    def read_header(self, path: str) -> dict:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != MAGIC:
                raise ValueError(f"Not a .gdlk file: magic={magic!r}")

            major, minor = struct.unpack("<HH", f.read(4))
            toc_offset, section_count = struct.unpack("<II", f.read(8))
            ts_ms = struct.unpack("<q", f.read(8))[0]

            # Read TOC
            f.seek(toc_offset)
            toc: dict[int, tuple[int, int]] = {}
            for _ in range(section_count):
                sec_id, sec_off, sec_len = struct.unpack("<QQQ", f.read(TOC_ENTRY_SIZE))
                toc[sec_id] = (sec_off, sec_len)

            # Read METADATA section
            metadata = {}
            if SEC_METADATA in toc:
                off, length = toc[SEC_METADATA]
                f.seek(off)
                metadata = json.loads(f.read(length))

            return {
                "magic":        magic.decode(),
                "version":      f"{major}.{minor}",
                "timestamp_ms": ts_ms,
                "sections":     sorted(toc.keys()),
                "metadata":     metadata,
            }

    def read_validation(self, path: str) -> dict:
        with open(path, "rb") as f:
            f.read(4)   # magic
            struct.unpack("<HH", f.read(4))
            toc_offset, section_count = struct.unpack("<II", f.read(8))
            f.seek(toc_offset)
            toc = {}
            for _ in range(section_count):
                sec_id, off, length = struct.unpack("<QQQ", f.read(TOC_ENTRY_SIZE))
                toc[sec_id] = (off, length)
            if SEC_VALIDATION not in toc:
                return {}
            off, length = toc[SEC_VALIDATION]
            f.seek(off)
            return json.loads(f.read(length))
