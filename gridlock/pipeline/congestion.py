"""
Stage 3: Congestion calibration (BPR)

Assigns V/C ratios and BPR travel times to all road edges using:
  1. NPMRDS observed speeds (if available), or
  2. Synthetic OD matrix via all-or-nothing assignment, or
  3. Highway-type synthetic V/C baseline fallback.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from gridlock.bpr import (
    BPR_ALPHA,
    BPR_BETA,
    SYNTHETIC_VC_BASELINE,
    bpr_travel_time_vectorized,
)
from gridlock.models.graph import RoadGraph
from gridlock.models.zones import DemandZone

log = logging.getLogger(__name__)


def calibrate_congestion(
    road_graph: RoadGraph,
    npmrds_path: str | None = None,
    od_matrix: pd.DataFrame | None = None,
) -> RoadGraph:
    """
    Assign traffic volumes and compute BPR travel times for all edges.

    Priority: NPMRDS > OD matrix > synthetic V/C baseline.
    Modifies road_graph in-place and returns it.
    """
    log.info("Stage 3: Calibrating congestion (BPR)")

    if npmrds_path:
        log.info(f"  Using NPMRDS data from {npmrds_path}")
        _apply_npmrds(road_graph, npmrds_path)
    elif od_matrix is not None and not od_matrix.empty:
        log.info("  Using OD matrix for flow assignment")
        _apply_od_matrix(road_graph, od_matrix)
    else:
        log.info("  Applying synthetic V/C baseline by highway type")
        _apply_synthetic_baseline(road_graph)

    # Vectorized BPR pass over all edges
    edges = list(road_graph.edges.values())
    t0_arr = np.array([e.t0_sec for e in edges], dtype=float)
    vol_arr = np.array([e.volume_veh_hr for e in edges], dtype=float)
    cap_arr = np.array([float(e.capacity_veh_hr) for e in edges], dtype=float)

    t_arr = bpr_travel_time_vectorized(t0_arr, vol_arr, cap_arr)

    for i, edge in enumerate(edges):
        edge.travel_time_sec = float(t_arr[i])
        edge.congestion_ratio = float(vol_arr[i] / max(1.0, cap_arr[i]))

    log.info(f"Stage 3 complete: {len(edges)} edges calibrated")
    return road_graph


def _apply_synthetic_baseline(road_graph: RoadGraph) -> None:
    for edge in road_graph.edges.values():
        vc = SYNTHETIC_VC_BASELINE.get(edge.highway_type, 0.45)
        edge.volume_veh_hr = edge.capacity_veh_hr * vc


def _apply_od_matrix(road_graph: RoadGraph, od_matrix: pd.DataFrame) -> None:
    """
    All-or-nothing traffic assignment from an OD matrix.

    For each OD pair, loads flow onto the shortest path.
    Phase 0 approximation; Phase 1 should use user-equilibrium Frank-Wolfe
    (or delegate to AequilibraE).
    """
    import networkx as nx
    G = road_graph.nx_graph
    if G is None:
        log.warning("  No networkx graph; falling back to synthetic baseline")
        _apply_synthetic_baseline(road_graph)
        return

    uv_to_edge = {(e.u, e.v): e for e in road_graph.edges.values()}
    flows: dict[tuple, float] = {}

    req_cols = {"origin_zone", "dest_zone", "trips"}
    if not req_cols.issubset(od_matrix.columns):
        log.warning(f"  OD matrix missing columns {req_cols - set(od_matrix.columns)}; using baseline")
        _apply_synthetic_baseline(road_graph)
        return

    for _, row in od_matrix.iterrows():
        origin = int(row["origin_zone"])
        dest = int(row["dest_zone"])
        trips = float(row["trips"])
        if trips <= 0 or origin == dest:
            continue
        try:
            path = nx.shortest_path(G, origin, dest, weight="length")
            for a, b in zip(path[:-1], path[1:]):
                flows[(a, b)] = flows.get((a, b), 0.0) + trips
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue

    for (u, v), flow in flows.items():
        edge = uv_to_edge.get((u, v))
        if edge:
            edge.volume_veh_hr = flow

    # Edges with no flow assignment get baseline
    for edge in road_graph.edges.values():
        if edge.volume_veh_hr == 0.0:
            edge.volume_veh_hr = edge.capacity_veh_hr * SYNTHETIC_VC_BASELINE.get(
                edge.highway_type, 0.45
            )


def _apply_npmrds(road_graph: RoadGraph, npmrds_path: str) -> None:
    """
    Back-calculate volume from observed speed ratio.

    NPMRDS gives speed_mph (observed) and ref_speed_mph (free-flow).
    t/t0 = ref_speed / speed
    From BPR: t/t0 = 1 + alpha*(V/C)^beta
    Solving for V: V = C * ((t/t0 - 1) / alpha)^(1/beta)

    Phase 0: name-based road matching (approximate).
    Phase 1: proper TMC spatial join.
    """
    log.warning("  NPMRDS TMC matching is approximate in Phase 0; using speed ratio back-calc")
    try:
        df = pd.read_csv(npmrds_path)
        if "speed_mph" not in df.columns or "ref_speed_mph" not in df.columns:
            raise ValueError("NPMRDS CSV must have speed_mph and ref_speed_mph columns")

        # Build name-to-row index
        name_map: dict[str, float] = {}
        if "road" in df.columns:
            for _, row in df.iterrows():
                name = str(row.get("road", "")).lower().strip()
                if name:
                    ratio = float(row["ref_speed_mph"]) / max(1.0, float(row["speed_mph"]))
                    name_map[name] = ratio

        matched = 0
        for edge in road_graph.edges.values():
            ename = edge.name.lower().strip()
            ratio = name_map.get(ename)
            if ratio and ratio > 1.0:
                vc = ((ratio - 1.0) / BPR_ALPHA) ** (1.0 / BPR_BETA)
                edge.volume_veh_hr = edge.capacity_veh_hr * vc
                matched += 1
            else:
                edge.volume_veh_hr = edge.capacity_veh_hr * SYNTHETIC_VC_BASELINE.get(
                    edge.highway_type, 0.45
                )
        log.info(f"  NPMRDS: {matched}/{len(road_graph.edges)} edges matched by name")
    except Exception as e:
        log.warning(f"  NPMRDS processing failed ({e}); using synthetic baseline")
        _apply_synthetic_baseline(road_graph)


def generate_synthetic_od_matrix(
    road_graph: RoadGraph,
    demand_zones: list[DemandZone],
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate a gravity-model OD matrix from demand zones.

    T_ij = rate_i * rate_j / dist_ij^2  (inverse-distance gravity)

    Returns DataFrame with columns [origin_zone, dest_zone, trips].
    """
    rng = np.random.default_rng(seed)
    records = []
    n = len(demand_zones)
    for i in range(n):
        oz = demand_zones[i]
        for j in range(n):
            if i == j:
                continue
            dz = demand_zones[j]
            dx = oz.centroid_x - dz.centroid_x
            dy = oz.centroid_y - dz.centroid_y
            dist = max(100.0, (dx**2 + dy**2) ** 0.5)
            trips = (oz.trip_generation_rate * dz.trip_generation_rate) / (dist**2)
            if trips > 0.001:
                records.append({
                    "origin_zone": oz.nearest_node_id,
                    "dest_zone":   dz.nearest_node_id,
                    "trips":       trips,
                })
    return pd.DataFrame(records)
