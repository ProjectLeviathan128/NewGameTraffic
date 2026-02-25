"""Shared pytest fixtures."""

import pytest
import networkx as nx

from gridlock.models.graph import RoadGraph, RoadNode, RoadEdge
from gridlock.models.transit import TransitNetwork, TransitRoute, TransitStop
from gridlock.models.zones import DemandZone
from gridlock.models.city_package import CityPackage, ValidationStats


@pytest.fixture
def tiny_graph() -> RoadGraph:
    """4-node square road graph for unit tests."""
    nodes = {
        1: RoadNode(1, lon=-122.60, lat=45.50, x=0.0,   y=0.0),
        2: RoadNode(2, lon=-122.59, lat=45.50, x=100.0, y=0.0),
        3: RoadNode(3, lon=-122.59, lat=45.51, x=100.0, y=100.0),
        4: RoadNode(4, lon=-122.60, lat=45.51, x=0.0,   y=100.0),
    }
    edges = {
        0: RoadEdge(0, u=1, v=2, highway_type="primary",     lanes=2, speed_kph=60.0, length_m=100.0, t0_sec=6.0,  capacity_veh_hr=3200, volume_veh_hr=2000.0, congestion_ratio=0.625, travel_time_sec=7.0),
        1: RoadEdge(1, u=2, v=3, highway_type="residential", lanes=1, speed_kph=40.0, length_m=100.0, t0_sec=9.0,  capacity_veh_hr=600,  volume_veh_hr=150.0,  congestion_ratio=0.25,  travel_time_sec=9.1),
        2: RoadEdge(2, u=3, v=4, highway_type="secondary",   lanes=1, speed_kph=50.0, length_m=100.0, t0_sec=7.2,  capacity_veh_hr=1200, volume_veh_hr=660.0,  congestion_ratio=0.55,  travel_time_sec=7.5),
        3: RoadEdge(3, u=4, v=1, highway_type="tertiary",    lanes=1, speed_kph=45.0, length_m=100.0, t0_sec=8.0,  capacity_veh_hr=900,  volume_veh_hr=360.0,  congestion_ratio=0.40,  travel_time_sec=8.1),
    }
    G = nx.MultiDiGraph()
    for nid, n in nodes.items():
        G.add_node(nid, x=n.x, y=n.y)
    G.add_edge(1, 2, length=100.0)
    G.add_edge(2, 3, length=100.0)
    G.add_edge(3, 4, length=100.0)
    G.add_edge(4, 1, length=100.0)
    return RoadGraph(nodes=nodes, edges=edges, nx_graph=G, crs_epsg=32610,
                     bbox=(45.43, -122.84, 45.65, -122.47))


@pytest.fixture
def tiny_transit(tiny_graph) -> TransitNetwork:
    stops = {
        "S1": TransitStop("S1", "Stop 1", lon=-122.60, lat=45.50, x=0.0,   y=0.0,   nearest_node_id=1),
        "S2": TransitStop("S2", "Stop 2", lon=-122.59, lat=45.51, x=100.0, y=100.0, nearest_node_id=3),
    }
    routes = {
        "R1": TransitRoute("R1", "14", "Line 14", route_type=3,
                           stop_ids=["S1", "S2"], headway_minutes=12.0,
                           edge_ids_on_route=[0, 1]),
    }
    return TransitNetwork(stops=stops, routes=routes, service_date="20240101")


@pytest.fixture
def minimal_package(tiny_graph, tiny_transit) -> CityPackage:
    return CityPackage(
        city_name="Test City",
        city_slug="test_city",
        crs_epsg=32610,
        bbox=(45.43, -122.84, 45.65, -122.47),
        road_graph=tiny_graph,
        transit_network=tiny_transit,
        validation=ValidationStats(
            modeled_vmt_daily=500_000, target_vmt_daily=600_000,
            modeled_transit_ridership=100_000, target_transit_ridership=120_000,
            vmt_error_pct=16.7, transit_error_pct=16.7, passed=True,
        ),
    )
