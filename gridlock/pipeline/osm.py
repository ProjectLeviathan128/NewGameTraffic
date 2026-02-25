"""
Stage 1: OSM road network → RoadGraph

Downloads (or loads from file) OSM data for a bounding box,
projects to local CRS, and builds a RoadGraph with BPR attributes.
"""

from __future__ import annotations

import logging
from typing import Any

from gridlock.models.graph import (
    RoadEdge,
    RoadGraph,
    RoadNode,
    compute_edge_capacity,
    compute_free_flow_time,
    FREEFLOW_SPEED_KPH,
)

log = logging.getLogger(__name__)


def build_road_graph(
    bbox: tuple[float, float, float, float],
    crs_epsg: int = 32610,
    network_type: str = "drive",
    simplify: bool = True,
    pbf_path: str | None = None,
) -> RoadGraph:
    """
    Build a RoadGraph from OSM data.

    Args:
        bbox: (south, west, north, east) in WGS84 degrees.
        crs_epsg: Target projected CRS (default 32610 = UTM Zone 10N for Portland).
        network_type: osmnx network type ('drive', 'walk', 'bike', 'all').
        simplify: Consolidate close intersections (removes roundabout clutter).
        pbf_path: Path to local .osm.pbf file. If None, downloads from Overpass.

    Returns:
        RoadGraph with all edges attributed with BPR parameters.
    """
    import osmnx as ox

    south, west, north, east = bbox
    log.info(f"Stage 1: Fetching road graph bbox=({south:.3f},{west:.3f},{north:.3f},{east:.3f})")

    if pbf_path:
        G = ox.graph_from_xml(pbf_path, simplify=False, retain_all=False)
        G = ox.truncate.truncate_graph_bbox(G, north=north, south=south, east=east, west=west)
        if simplify:
            G = ox.simplify_graph(G)
    else:
        G = ox.graph_from_bbox(
            bbox=(north, south, east, west),
            network_type=network_type,
            simplify=simplify,
            retain_all=False,
        )

    log.info(f"  Raw graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Project to local CRS
    G_proj = ox.projection.project_graph(G, to_crs=f"EPSG:{crs_epsg}")

    if simplify:
        try:
            G_proj = ox.consolidate_intersections(
                G_proj, tolerance=10, rebuild_graph=True, dead_ends=False
            )
        except Exception as e:
            log.warning(f"  Intersection consolidation skipped: {e}")

    log.info(f"  Projected+simplified: {G_proj.number_of_nodes()} nodes, {G_proj.number_of_edges()} edges")

    nodes, edges = _extract_nodes_edges(G_proj)
    graph = RoadGraph(nodes=nodes, edges=edges, nx_graph=G_proj, crs_epsg=crs_epsg, bbox=bbox)
    log.info(f"Stage 1 complete: {len(nodes)} nodes, {len(edges)} edges")
    return graph


def _extract_nodes_edges(
    G: Any,
) -> tuple[dict[int, RoadNode], dict[int, RoadEdge]]:
    nodes: dict[int, RoadNode] = {}
    edges: dict[int, RoadEdge] = {}
    edge_counter = 0

    for node_id, data in G.nodes(data=True):
        nodes[node_id] = RoadNode(
            node_id=node_id,
            lon=float(data.get("lon", data.get("x", 0.0))),
            lat=float(data.get("lat", data.get("y", 0.0))),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
        )

    for u, v, _key, data in G.edges(data=True, keys=True):
        highway = data.get("highway", "unclassified")
        if isinstance(highway, list):
            highway = highway[0]
        highway = str(highway)

        lanes_raw = data.get("lanes", 1)
        if isinstance(lanes_raw, list):
            lanes_raw = lanes_raw[0]
        try:
            lanes = max(1, int(lanes_raw))
        except (ValueError, TypeError):
            lanes = 1

        speed_kph = _parse_speed_kph(data.get("maxspeed"), highway)
        length_m = float(data.get("length", 0.0))
        t0 = compute_free_flow_time(length_m, highway, speed_kph)
        capacity = compute_edge_capacity(highway, lanes)

        edges[edge_counter] = RoadEdge(
            edge_id=edge_counter,
            u=u,
            v=v,
            osm_way_id=int(data.get("osmid", 0)) if not isinstance(data.get("osmid"), list) else 0,
            name=str(data.get("name", "") or ""),
            highway_type=highway,
            lanes=lanes,
            speed_kph=speed_kph,
            length_m=length_m,
            t0_sec=t0,
            capacity_veh_hr=capacity,
            travel_time_sec=t0,
        )
        edge_counter += 1

    return nodes, edges


def _parse_speed_kph(maxspeed_raw: Any, highway_type: str) -> float:
    if maxspeed_raw is None:
        return FREEFLOW_SPEED_KPH.get(highway_type, 40.0)
    if isinstance(maxspeed_raw, list):
        maxspeed_raw = maxspeed_raw[0]
    s = str(maxspeed_raw).strip().lower().split(";")[0].strip()
    if "mph" in s:
        try:
            return float(s.replace("mph", "").strip()) * 1.60934
        except ValueError:
            pass
    try:
        return float(s)
    except ValueError:
        return FREEFLOW_SPEED_KPH.get(highway_type, 40.0)
