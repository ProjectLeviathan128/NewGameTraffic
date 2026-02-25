from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CensusTract:
    geoid: str                      # 11-digit FIPS
    geometry: Any                   # Shapely Polygon/MultiPolygon
    population: int = 0
    median_income: float = 0.0
    pct_zero_vehicle: float = 0.0
    pct_minority: float = 0.0
    equity_score: float = 0.5       # 0–1, higher = greater transit need


@dataclass
class DemandZone:
    zone_id: int
    geometry: Any                   # Shapely Polygon
    centroid_x: float = 0.0
    centroid_y: float = 0.0
    land_use_class: str = "mixed"   # residential_single/multi, commercial_retail/office,
                                    # industrial, institutional, open_space, mixed
    trip_generation_rate: float = 0.0   # trips/hour (ITE-based)
    nearest_node_id: int = 0
    census_tract_geoid: str = ""
    equity_score: float = 1.0
