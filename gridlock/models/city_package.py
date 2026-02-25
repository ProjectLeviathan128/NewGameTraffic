from __future__ import annotations
from dataclasses import dataclass, field
from gridlock.models.graph import RoadGraph
from gridlock.models.transit import TransitNetwork
from gridlock.models.zones import DemandZone, CensusTract


@dataclass
class ValidationStats:
    modeled_vmt_daily: float = 0.0
    target_vmt_daily: float = 0.0
    modeled_transit_ridership: float = 0.0
    target_transit_ridership: float = 0.0
    vmt_error_pct: float = 0.0
    transit_error_pct: float = 0.0
    passed: bool = False


@dataclass
class CityPackage:
    city_name: str
    city_slug: str
    pipeline_version: str = "0.1.0"
    created_at: str = ""
    crs_epsg: int = 4326
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # S,W,N,E
    road_graph: RoadGraph | None = None
    transit_network: TransitNetwork | None = None
    demand_zones: list[DemandZone] = field(default_factory=list)
    census_tracts: list[CensusTract] = field(default_factory=list)
    validation: ValidationStats | None = None
    metadata: dict = field(default_factory=dict)
