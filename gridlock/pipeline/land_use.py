"""
Stage 5: Land use → DemandZone generation

Reads land use polygons and assigns ITE-based trip generation rates.
Snaps zone centroids to road network nodes.
"""

from __future__ import annotations

import logging

import numpy as np

from gridlock.models.graph import RoadGraph
from gridlock.models.zones import DemandZone

log = logging.getLogger(__name__)

# ITE Trip Generation Handbook rates (trips/acre/peak-hour)
# Based on ITE 11th Edition
TRIP_RATE: dict[str, float] = {
    "residential_single":  0.26,
    "residential_multi":   0.50,
    "commercial_retail":   3.80,
    "commercial_office":   1.45,
    "industrial":          0.75,
    "institutional":       0.90,
    "mixed":               1.20,
    "open_space":          0.05,
}

M2_PER_ACRE = 4046.86


def build_demand_zones(
    land_use_path: str,
    road_graph: RoadGraph,
    crs_epsg: int = 32610,
    min_area_m2: float = 500.0,
) -> list[DemandZone]:
    """
    Build DemandZone objects from a land use shapefile or GeoJSON.

    Args:
        land_use_path: Path to file with land use polygons.
                       Must have a geometry column and ideally a
                       'land_use_class' column (or mappable equivalent).
        road_graph: For snapping centroids to network nodes.
        crs_epsg: Projected CRS.
        min_area_m2: Ignore parcels smaller than this (noise filter).

    Returns:
        List of DemandZone objects with trip generation rates.
    """
    import geopandas as gpd

    log.info(f"Stage 5: Loading land use from {land_use_path}")
    gdf = gpd.read_file(land_use_path).to_crs(epsg=crs_epsg)
    gdf = gdf[gdf.geometry.area >= min_area_m2].copy()
    log.info(f"  {len(gdf)} parcels after area filter (>= {min_area_m2} m²)")

    node_ids = list(road_graph.nodes.keys())
    if not node_ids:
        return []
    node_xy = np.array([[road_graph.nodes[n].x, road_graph.nodes[n].y] for n in node_ids])

    zones: list[DemandZone] = []
    for zone_id, row in enumerate(gdf.itertuples(index=False)):
        geom = row.geometry
        centroid = geom.centroid

        # Map raw land use class to canonical key
        raw = str(getattr(row, "land_use_class", getattr(row, "LUSE", "mixed"))).lower()
        lu_class = _map_class(raw)

        area_acres = geom.area / M2_PER_ACRE
        rate = TRIP_RATE.get(lu_class, 1.0)

        dists = (node_xy[:, 0] - centroid.x) ** 2 + (node_xy[:, 1] - centroid.y) ** 2
        nearest_node = node_ids[int(np.argmin(dists))]

        zones.append(DemandZone(
            zone_id=zone_id,
            geometry=geom,
            centroid_x=float(centroid.x),
            centroid_y=float(centroid.y),
            land_use_class=lu_class,
            trip_generation_rate=float(rate * area_acres),
            nearest_node_id=nearest_node,
        ))

    log.info(f"Stage 5 complete: {len(zones)} demand zones")
    return zones


def _map_class(raw: str) -> str:
    if any(k in raw for k in ("single", "sfr", "single_family", "sfh")):
        return "residential_single"
    if any(k in raw for k in ("multi", "apartment", "mfr", "condo", "mf")):
        return "residential_multi"
    if any(k in raw for k in ("retail", "shopping", "comm_r", "commercial_r")):
        return "commercial_retail"
    if any(k in raw for k in ("office", "comm_o", "commercial_o")):
        return "commercial_office"
    if any(k in raw for k in ("industrial", "warehouse", "manufactur")):
        return "industrial"
    if any(k in raw for k in ("school", "hospital", "civic", "institutional", "church")):
        return "institutional"
    if any(k in raw for k in ("park", "open", "recreation", "cemetery", "golf")):
        return "open_space"
    return "mixed"
