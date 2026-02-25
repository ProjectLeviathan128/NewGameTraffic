"""
SimulationRunner — wraps the UXsim mesoscopic model and city package.

Loads a .gdlk file, initializes the simulation state, and produces
SimSnapshot objects for the WebSocket stream.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from gridlock.bpr import bpr_travel_time, los_color, level_of_service
from gridlock.gdlk_format import GdlkReader
from gridlock.models.city_package import CityPackage
from gridlock.models.graph import RoadGraph
from gridlock.models.transit import TransitNetwork

log = logging.getLogger(__name__)

# Rush-hour volume multipliers by in-game hour
RUSH_HOUR_MULTIPLIERS: dict[int, float] = {
    6:  0.60, 7:  0.85, 8:  1.00, 9:  0.90,
    10: 0.70, 11: 0.65, 12: 0.70, 13: 0.65,
    14: 0.70, 15: 0.80, 16: 0.95, 17: 1.00,
    18: 0.90, 19: 0.75, 20: 0.60, 21: 0.50,
    22: 0.40, 23: 0.30,  0: 0.20,  1: 0.15,
    2:  0.15,  3: 0.15,  4: 0.20,  5: 0.40,
}

OPERATING_HOURS = 16
VEHICLE_CAPACITY = 60
AVG_LOAD_FACTOR = 0.35


class SimulationRunner:
    """
    Loads a .gdlk package and maintains real-time simulation state.

    The simulation ticks forward as the server sends snapshots.
    Interventions mutate road_graph and transit_network in-place.
    """

    def __init__(self, gdlk_path: str) -> None:
        log.info(f"SimulationRunner: loading {gdlk_path}")
        self._gdlk_path = gdlk_path
        self._package = self._load_package(gdlk_path)
        self.road_graph: RoadGraph = self._package.road_graph
        self.transit_network: TransitNetwork | None = self._package.transit_network
        self.city_slug: str = self._package.city_slug
        self._tick_hour: int = 8       # Start at 8 AM
        self.political_capital: int = 100
        log.info(f"  Loaded: {len(self.road_graph.nodes)} nodes, {len(self.road_graph.edges)} edges")

    def set_hour(self, hour: int) -> None:
        self._tick_hour = hour % 24

    def advance_tick(self) -> None:
        self._tick_hour = (self._tick_hour + 1) % 24

    def snapshot(self) -> "SimSnapshot":
        """Build a SimSnapshot from current simulation state."""
        from gridlock.server.app import (
            CityMetrics, EdgeState, RouteState, SimSnapshot
        )

        mult = RUSH_HOUR_MULTIPLIERS.get(self._tick_hour, 0.5)

        edges: list[EdgeState] = []
        total_commute = 0.0
        total_vmt = 0.0
        for edge in self.road_graph.edges.values():
            vol = edge.volume_veh_hr * mult
            cap = float(edge.capacity_veh_hr)
            t = bpr_travel_time(max(0.01, edge.t0_sec), vol, max(1.0, cap)) if edge.t0_sec > 0 else edge.t0_sec
            vc = vol / max(1.0, cap)
            los = level_of_service(vc)
            color = los_color(vc)
            total_commute += t
            total_vmt += vol * OPERATING_HOURS * edge.length_m / 1000.0

            edges.append(EdgeState(
                edge_id=edge.edge_id,
                congestion_ratio=round(vc, 3),
                travel_time_sec=round(t, 2),
                volume_veh_hr=round(vol, 1),
                los=los,
                has_bus_lane=edge.has_bus_lane,
                color=color,
            ))

        avg_commute = (total_commute / max(1, len(edges))) / 60.0  # seconds → minutes

        routes: list[RouteState] = []
        total_ridership = 0.0
        if self.transit_network:
            for route in self.transit_network.routes.values():
                trips_per_hr = 60.0 / max(1.0, route.headway_minutes)
                ridership = trips_per_hr * OPERATING_HOURS * VEHICLE_CAPACITY * AVG_LOAD_FACTOR * mult
                total_ridership += ridership
                routes.append(RouteState(
                    route_id=route.route_id,
                    headway_minutes=route.headway_minutes,
                    ridership_estimate=round(ridership, 0),
                ))

        equity_scores = [e.equity_weight for e in self.road_graph.edges.values()]
        equity = sum(equity_scores) / max(1, len(equity_scores))

        # CO2: car trips × 180 g/km, bus trips × 80 g/seat-km (rough GHG estimate)
        vmt_km = total_vmt / 2.0
        co2 = (vmt_km * 180.0 + total_ridership * 0.5 * 80.0) / max(1, total_ridership + len(edges))

        metrics = CityMetrics(
            avg_commute_min=round(avg_commute, 1),
            vmt_daily=round(vmt_km, 0),
            transit_ridership=round(total_ridership, 0),
            equity_score=round(equity, 3),
            co2_g_per_commuter_km=round(co2, 1),
            political_capital=self.political_capital,
        )

        return SimSnapshot(
            city_slug=self.city_slug,
            tick_hour=self._tick_hour,
            edges=edges,
            routes=routes,
            metrics=metrics,
        )

    def _load_package(self, gdlk_path: str) -> CityPackage:
        """
        Load a CityPackage from a .gdlk file.

        Phase 0: Reads metadata and reconstruct a minimal CityPackage from
        the header. The full node/edge binary parsing is implemented here.
        """
        import json, struct
        from gridlock.gdlk_format import (
            MAGIC, NODE_FMT, NODE_SIZE, EDGE_FMT, EDGE_SIZE,
            SEC_METADATA, SEC_NODES, SEC_EDGES,
            SEC_TRANSIT_ROUTES, SEC_STRINGS, TOC_ENTRY_SIZE, HIGHWAY_ENUM_INV
        )
        from gridlock.models.graph import RoadNode, RoadEdge, RoadGraph
        from gridlock.models.transit import TransitRoute, TransitNetwork
        from gridlock.models.city_package import CityPackage

        with open(gdlk_path, "rb") as f:
            magic = f.read(4)
            if magic != MAGIC:
                raise ValueError(f"Not a .gdlk file")
            struct.unpack("<HH", f.read(4))     # version
            toc_offset, section_count = struct.unpack("<II", f.read(8))
            struct.unpack("<q", f.read(8))       # timestamp
            f.read(40)                           # flags + reserved

            f.seek(toc_offset)
            toc: dict[int, tuple[int, int]] = {}
            for _ in range(section_count):
                sid, off, length = struct.unpack("<QQQ", f.read(TOC_ENTRY_SIZE))
                toc[sid] = (off, length)

            # Metadata
            meta = {}
            if SEC_METADATA in toc:
                off, length = toc[SEC_METADATA]
                f.seek(off); meta = json.loads(f.read(length))

            # String pool
            strings: list[str] = [""]
            if SEC_STRINGS in toc:
                off, length = toc[SEC_STRINGS]
                f.seek(off)
                raw = f.read(length)
                strings = [s.decode("utf-8", errors="replace") for s in raw.split(b"\x00")]

            # Nodes
            nodes: dict[int, RoadNode] = {}
            if SEC_NODES in toc:
                off, length = toc[SEC_NODES]
                f.seek(off)
                count = length // NODE_SIZE
                for _ in range(count):
                    nid, x, y, elev, is_int = struct.unpack(NODE_FMT, f.read(NODE_SIZE))
                    nodes[nid] = RoadNode(node_id=nid, lon=0.0, lat=0.0, x=x, y=y,
                                          elevation_m=elev, is_intersection=bool(is_int))

            # Edges
            edges: dict[int, RoadEdge] = {}
            if SEC_EDGES in toc:
                off, length = toc[SEC_EDGES]
                f.seek(off)
                count = length // EDGE_SIZE
                for _ in range(count):
                    (eid, u, v, osm, name_off, hw_enum, lanes,
                     speed, length_m, t0, cap, vol, vc, tt, eq, bus_lane
                     ) = struct.unpack(EDGE_FMT, f.read(EDGE_SIZE))
                    name = strings[name_off] if name_off < len(strings) else ""
                    hw = HIGHWAY_ENUM_INV.get(hw_enum, "unclassified")
                    edges[eid] = RoadEdge(
                        edge_id=eid, u=u, v=v, osm_way_id=osm,
                        name=name, highway_type=hw, lanes=lanes,
                        speed_kph=speed, length_m=length_m, t0_sec=t0,
                        capacity_veh_hr=int(cap), volume_veh_hr=vol,
                        congestion_ratio=vc, travel_time_sec=tt,
                        equity_weight=eq, has_bus_lane=bool(bus_lane),
                    )

            # Transit routes (JSON section)
            routes: dict[str, TransitRoute] = {}
            if SEC_TRANSIT_ROUTES in toc:
                off, length = toc[SEC_TRANSIT_ROUTES]
                f.seek(off)
                route_data = json.loads(f.read(length))
                for r in route_data:
                    rid = r["route_id"]
                    routes[rid] = TransitRoute(
                        route_id=rid,
                        short_name=r.get("short_name", ""),
                        long_name=r.get("long_name", ""),
                        route_type=r.get("route_type", 3),
                        stop_ids=r.get("stop_ids", []),
                        headway_minutes=r.get("headway_min", 15.0),
                        edge_ids_on_route=r.get("edge_ids", []),
                    )

        graph = RoadGraph(
            nodes=nodes, edges=edges,
            crs_epsg=meta.get("crs_epsg", 4326),
            bbox=tuple(meta.get("bbox", [0, 0, 0, 0])),
        )
        transit = TransitNetwork(stops={}, routes=routes) if routes else None
        pkg = CityPackage(
            city_name=meta.get("city_name", "Unknown"),
            city_slug=meta.get("city_slug", "unknown"),
            crs_epsg=meta.get("crs_epsg", 4326),
            bbox=tuple(meta.get("bbox", [0, 0, 0, 0])),
            road_graph=graph,
            transit_network=transit,
        )
        return pkg
