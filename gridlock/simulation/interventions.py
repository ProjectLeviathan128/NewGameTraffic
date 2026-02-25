"""
Intervention system — the core gameplay mechanics.

Each function takes a city's current state and returns the updated state
plus the Political Capital (PC) cost of the intervention.

PC values are per the GDD:
  Bus lane conversion:     high PC drain / high gain if speeds improve
  Frequency boost:         low cost / medium PC drain
  Congestion pricing:      zero infra cost / very high PC drain
  Remove parking:          zero cost / medium PC drain
  BRT conversion:          medium cost / medium PC drain
  Light rail extension:    very high cost / low PC drain (politically popular)
"""

from __future__ import annotations

import copy
import logging

from gridlock.bpr import bpr_travel_time, induced_demand_factor
from gridlock.models.graph import RoadGraph, compute_edge_capacity, compute_free_flow_time
from gridlock.models.transit import TransitNetwork

log = logging.getLogger(__name__)

# Political Capital costs (positive = cost, negative = gain)
PC_COSTS = {
    "bus_lane":            15,   # per block
    "frequency_boost":      8,   # per route
    "congestion_pricing":  40,   # per zone
    "remove_parking":      12,   # per block
    "brt_conversion":      20,   # per corridor
    "light_rail":           5,   # politically popular despite high $
    "tod_upzoning":        18,   # transit-oriented development
    "speed_limit":          6,
    "road_diet":           10,
}


def convert_to_bus_lane(
    road_graph: RoadGraph,
    edge_id: int,
    transit_network: TransitNetwork,
) -> tuple[RoadGraph, TransitNetwork, int]:
    """
    Convert one general-purpose lane to a dedicated bus lane on an edge.

    Effect:
    - Reduces edge lanes by 1 (minimum 1 GP lane remains)
    - Reduces edge capacity proportionally
    - Marks edge as has_bus_lane = True
    - Transit routes on this edge get a 15% speed bonus (dedicated lane)

    Returns:
        (updated road_graph, updated transit_network, PC cost)

    Raises:
        KeyError: If edge_id not in road_graph.
        ValueError: If edge already has a bus lane or has only 1 lane.
    """
    if edge_id not in road_graph.edges:
        raise KeyError(f"edge_id {edge_id} not found")
    edge = road_graph.edges[edge_id]
    if edge.has_bus_lane:
        raise ValueError(f"Edge {edge_id} already has a bus lane")
    if edge.lanes <= 1:
        raise ValueError(f"Edge {edge_id} has only 1 lane; cannot convert")

    # Deep copy to avoid mutating shared state
    graph = _copy_graph(road_graph)
    e = graph.edges[edge_id]
    e.lanes -= 1
    e.capacity_veh_hr = compute_edge_capacity(e.highway_type, e.lanes)
    e.has_bus_lane = True
    # Recalculate BPR travel time with new capacity
    e.travel_time_sec = bpr_travel_time(e.t0_sec, e.volume_veh_hr, e.capacity_veh_hr)
    e.congestion_ratio = e.volume_veh_hr / max(1.0, e.capacity_veh_hr)

    # Transit speed bonus: reduce effective travel time on this edge by 15%
    net = _copy_transit(transit_network)
    for route in net.routes.values():
        if edge_id in route.edge_ids_on_route:
            # Speed bonus is implicit; handled by simulation tick
            pass

    pc = PC_COSTS["bus_lane"]
    log.info(f"Intervention: bus lane on edge {edge_id} (PC cost: {pc})")
    return graph, net, pc


def boost_frequency(
    transit_network: TransitNetwork,
    route_id: str,
    new_headway_min: float,
) -> tuple[TransitNetwork, int]:
    """
    Reduce headway (increase frequency) on a transit route.

    Args:
        transit_network: Current transit network.
        route_id: ID of the route to boost.
        new_headway_min: New headway in minutes (must be < current headway).

    Returns:
        (updated transit_network, PC cost)

    Raises:
        KeyError: If route_id not found.
        ValueError: If new_headway_min >= current headway.
    """
    if route_id not in transit_network.routes:
        raise KeyError(f"route_id {route_id!r} not found")
    route = transit_network.routes[route_id]
    if new_headway_min >= route.headway_minutes:
        raise ValueError(
            f"new_headway_min ({new_headway_min}) must be less than current "
            f"({route.headway_minutes})"
        )

    net = _copy_transit(transit_network)
    net.routes[route_id].headway_minutes = new_headway_min
    pc = PC_COSTS["frequency_boost"]
    log.info(
        f"Intervention: frequency boost route {route_id!r}: "
        f"{route.headway_minutes:.0f} → {new_headway_min:.0f} min (PC: {pc})"
    )
    return net, pc


def apply_congestion_pricing(
    road_graph: RoadGraph,
    zone_node_ids: list[int],
    toll_usd: float = 5.0,
) -> tuple[RoadGraph, int]:
    """
    Apply congestion pricing to all edges whose endpoints are within the zone.

    Demand reduction is modeled as: volume *= (1 - elasticity * toll_fraction)
    where elasticity = 0.3 (price elasticity of vehicle demand).
    Recalculates BPR travel times after demand reduction.

    Args:
        road_graph: Current road graph.
        zone_node_ids: Set of node IDs defining the pricing zone (cordon).
        toll_usd: Toll in USD. Higher tolls reduce volume more.

    Returns:
        (updated road_graph, PC cost)
    """
    zone_set = set(zone_node_ids)
    PRICE_ELASTICITY = 0.3
    MAX_TOLL_USD = 20.0
    toll_fraction = min(1.0, toll_usd / MAX_TOLL_USD)
    demand_reduction = PRICE_ELASTICITY * toll_fraction

    graph = _copy_graph(road_graph)
    affected = 0
    for edge in graph.edges.values():
        if edge.u in zone_set and edge.v in zone_set:
            edge.volume_veh_hr *= (1.0 - demand_reduction)
            edge.travel_time_sec = bpr_travel_time(
                edge.t0_sec, edge.volume_veh_hr, edge.capacity_veh_hr
            )
            edge.congestion_ratio = edge.volume_veh_hr / max(1.0, edge.capacity_veh_hr)
            affected += 1

    pc = PC_COSTS["congestion_pricing"]
    log.info(f"Intervention: congestion pricing (${toll_usd:.2f}) on {affected} edges (PC: {pc})")
    return graph, pc


def remove_parking(
    road_graph: RoadGraph,
    edge_id: int,
) -> tuple[RoadGraph, int]:
    """
    Remove on-street parking on an edge, freeing ~0.3 effective lanes of capacity.

    This models the elimination of parking-search traffic and the conversion
    of the parking lane to a travel or bike lane.
    """
    if edge_id not in road_graph.edges:
        raise KeyError(f"edge_id {edge_id} not found")

    graph = _copy_graph(road_graph)
    e = graph.edges[edge_id]
    # Parking removal increases effective capacity by ~15% (eliminates search traffic)
    e.capacity_veh_hr = int(e.capacity_veh_hr * 1.15)
    e.travel_time_sec = bpr_travel_time(e.t0_sec, e.volume_veh_hr, e.capacity_veh_hr)
    e.congestion_ratio = e.volume_veh_hr / max(1.0, e.capacity_veh_hr)

    pc = PC_COSTS["remove_parking"]
    log.info(f"Intervention: remove parking on edge {edge_id} (PC: {pc})")
    return graph, pc


def apply_road_diet(
    road_graph: RoadGraph,
    edge_id: int,
) -> tuple[RoadGraph, int]:
    """
    Convert a 4-lane undivided road to 3-lane (with center turn lane + bike lanes).

    Typically applied to arterials with AADT < 20,000. Reduces capacity
    but improves safety and bus stop dwell times (fewer weaving conflicts).
    """
    if edge_id not in road_graph.edges:
        raise KeyError(f"edge_id {edge_id} not found")
    edge = road_graph.edges[edge_id]
    if edge.lanes < 4:
        raise ValueError(f"Road diet requires >= 4 lanes; edge {edge_id} has {edge.lanes}")

    graph = _copy_graph(road_graph)
    e = graph.edges[edge_id]
    e.lanes = 3
    e.capacity_veh_hr = compute_edge_capacity(e.highway_type, lanes=3)
    # Speed slightly reduced (tighter geometry) — update free-flow time
    new_speed = e.speed_kph * 0.9
    e.speed_kph = new_speed
    e.t0_sec = compute_free_flow_time(e.length_m, e.highway_type, new_speed)
    e.travel_time_sec = bpr_travel_time(e.t0_sec, e.volume_veh_hr, e.capacity_veh_hr)
    e.congestion_ratio = e.volume_veh_hr / max(1.0, e.capacity_veh_hr)

    pc = PC_COSTS["road_diet"]
    log.info(f"Intervention: road diet on edge {edge_id} (PC: {pc})")
    return graph, pc


def apply_speed_limit_reduction(
    road_graph: RoadGraph,
    edge_id: int,
    new_speed_kph: float,
) -> tuple[RoadGraph, int]:
    """Reduce speed limit on a road segment."""
    if edge_id not in road_graph.edges:
        raise KeyError(f"edge_id {edge_id} not found")
    e = road_graph.edges[edge_id]
    if new_speed_kph >= e.speed_kph:
        raise ValueError("new_speed_kph must be less than current speed")

    graph = _copy_graph(road_graph)
    e2 = graph.edges[edge_id]
    e2.speed_kph = new_speed_kph
    e2.t0_sec = compute_free_flow_time(e2.length_m, e2.highway_type, new_speed_kph)
    e2.travel_time_sec = bpr_travel_time(e2.t0_sec, e2.volume_veh_hr, e2.capacity_veh_hr)

    pc = PC_COSTS["speed_limit"]
    return graph, pc


def get_intervention_cost(intervention_type: str) -> int:
    """Return the PC cost for a named intervention type."""
    return PC_COSTS.get(intervention_type, 10)


# ---- Shallow copy helpers ----

def _copy_graph(road_graph: RoadGraph) -> RoadGraph:
    """Return a copy of the graph with deep-copied edges (nodes shared)."""
    from gridlock.models.graph import RoadEdge
    import dataclasses
    new_edges = {
        eid: dataclasses.replace(e, transit_route_ids=list(e.transit_route_ids))
        for eid, e in road_graph.edges.items()
    }
    return RoadGraph(
        nodes=road_graph.nodes,
        edges=new_edges,
        nx_graph=road_graph.nx_graph,
        crs_epsg=road_graph.crs_epsg,
        bbox=road_graph.bbox,
    )


def _copy_transit(net: TransitNetwork) -> TransitNetwork:
    """Return a copy with deep-copied routes (stops shared)."""
    import dataclasses
    new_routes = {
        rid: dataclasses.replace(r, stop_ids=list(r.stop_ids), edge_ids_on_route=list(r.edge_ids_on_route))
        for rid, r in net.routes.items()
    }
    return TransitNetwork(stops=net.stops, routes=new_routes, service_date=net.service_date)
