"""
Stage 4: Census tract demographics → equity weights

Joins census tract geometries with ACS demographic data,
computes a composite equity score, and assigns per-edge equity weights.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from gridlock.models.graph import RoadGraph
from gridlock.models.zones import CensusTract

log = logging.getLogger(__name__)


def apply_demographic_weights(
    road_graph: RoadGraph,
    census_path: str,
    crs_epsg: int = 32610,
) -> tuple[RoadGraph, list[CensusTract]]:
    """
    Load census tract data, compute equity scores, and assign edge weights.

    Args:
        road_graph: Stage 1-3 output (modified in-place).
        census_path: Path to shapefile or GeoJSON with census tracts.
                     Expected columns: geometry, GEOID, population,
                     median_income, pct_zero_vehicle, pct_minority.
        crs_epsg: Projected CRS.

    Returns:
        (road_graph with equity_weight on each edge, list[CensusTract])
    """
    import geopandas as gpd
    from shapely.geometry import Point

    log.info(f"Stage 4: Loading census data from {census_path}")
    gdf = gpd.read_file(census_path).to_crs(epsg=crs_epsg)
    gdf = _compute_equity_score(gdf)

    # Build edge midpoint GeoDataFrame for spatial join
    records = []
    for edge in road_graph.edges.values():
        if edge.u in road_graph.nodes and edge.v in road_graph.nodes:
            nu = road_graph.nodes[edge.u]
            nv = road_graph.nodes[edge.v]
            mx, my = (nu.x + nv.x) / 2, (nu.y + nv.y) / 2
            records.append({"edge_id": edge.edge_id, "geometry": Point(mx, my)})

    if not records:
        log.warning("  No edges to join; skipping demographic weighting")
        return road_graph, []

    edges_gdf = gpd.GeoDataFrame(records, crs=f"EPSG:{crs_epsg}")
    joined = gpd.sjoin(
        edges_gdf,
        gdf[["equity_score", "geometry"]],
        how="left",
        predicate="within",
    ).drop_duplicates(subset="edge_id")

    equity_map = dict(zip(joined["edge_id"], joined["equity_score"]))
    for edge in road_graph.edges.values():
        score = equity_map.get(edge.edge_id)
        edge.equity_weight = float(score) if (score is not None and score == score) else 1.0

    # Build CensusTract list
    tracts: list[CensusTract] = []
    for _, row in gdf.iterrows():
        tracts.append(CensusTract(
            geoid=str(row.get("GEOID", row.get("geoid", ""))),
            geometry=row.geometry,
            population=int(row.get("population", row.get("B01003_001E", 0))),
            median_income=float(row.get("median_income", row.get("B19013_001E", 0.0))),
            pct_zero_vehicle=float(row.get("pct_zero_vehicle", 0.0)),
            pct_minority=float(row.get("pct_minority", 0.0)),
            equity_score=float(row.get("equity_score", 0.5)),
        ))

    log.info(f"Stage 4 complete: {len(tracts)} tracts, equity weights applied")
    return road_graph, tracts


def _compute_equity_score(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    """
    Composite equity score (0–1). Higher = greater transit need.

      equity = 0.4 * pct_zero_vehicle
             + 0.3 * pct_minority
             + 0.3 * (1 - norm_income)

    All components normalized to [0, 1] within the dataset.
    """
    df = gdf.copy()

    def norm(col: str, default: float = 0.0) -> pd.Series:
        if col not in df.columns:
            return pd.Series(default, index=df.index)
        s = df[col].fillna(default).astype(float)
        mn, mx = s.min(), s.max()
        return (s - mn) / (mx - mn) if mx > mn else pd.Series(0.5, index=df.index)

    df["equity_score"] = (
        0.4 * norm("pct_zero_vehicle")
        + 0.3 * norm("pct_minority")
        + 0.3 * (1.0 - norm("median_income", default=50000.0))
    ).clip(0.0, 1.0)

    return df
