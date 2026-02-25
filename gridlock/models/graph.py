from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


# HCM 6th Edition capacity by OSM highway type (vehicles/hour/lane)
CAPACITY_PER_LANE: dict[str, int] = {
    "motorway":       2300,
    "motorway_link":  1500,
    "trunk":          2000,
    "trunk_link":     1200,
    "primary":        1600,
    "primary_link":    900,
    "secondary":      1200,
    "secondary_link":  700,
    "tertiary":        900,
    "tertiary_link":   600,
    "residential":     600,
    "living_street":   300,
    "unclassified":    700,
    "service":         400,
}

# Free-flow speed by OSM highway type (km/h) — Portland defaults
FREEFLOW_SPEED_KPH: dict[str, float] = {
    "motorway":       105.0,
    "motorway_link":   80.0,
    "trunk":           80.0,
    "trunk_link":      65.0,
    "primary":         60.0,
    "primary_link":    50.0,
    "secondary":       50.0,
    "secondary_link":  45.0,
    "tertiary":        45.0,
    "tertiary_link":   40.0,
    "residential":     40.0,
    "living_street":   20.0,
    "unclassified":    40.0,
    "service":         20.0,
}


@dataclass
class RoadNode:
    node_id: int
    lon: float
    lat: float
    x: float                   # Projected X (local CRS, meters)
    y: float                   # Projected Y (local CRS, meters)
    elevation_m: float = 0.0
    is_intersection: bool = True


@dataclass
class RoadEdge:
    edge_id: int
    u: int                     # Source node_id
    v: int                     # Target node_id
    osm_way_id: int = 0
    name: str = ""
    highway_type: str = "residential"
    lanes: int = 1
    speed_kph: float = 40.0
    length_m: float = 0.0
    t0_sec: float = 0.0        # Free-flow travel time (seconds)
    capacity_veh_hr: int = 600
    # BPR calibration outputs (set by Stage 3)
    volume_veh_hr: float = 0.0
    congestion_ratio: float = 0.0
    travel_time_sec: float = 0.0
    # Equity weighting (set by Stage 4)
    equity_weight: float = 1.0
    # Transit overlay (set by Stage 2)
    has_bus_lane: bool = False
    transit_route_ids: list[str] = field(default_factory=list)

    def level_of_service(self) -> str:
        vc = self.congestion_ratio
        if vc <= 0.20:
            return "A"
        elif vc <= 0.44:
            return "B"
        elif vc <= 0.64:
            return "C"
        elif vc <= 0.85:
            return "D"
        elif vc <= 1.00:
            return "E"
        return "F"


@dataclass
class RoadGraph:
    nodes: dict[int, RoadNode]
    edges: dict[int, RoadEdge]
    nx_graph: Any = None       # networkx.MultiDiGraph; not serialized to .gdlk
    crs_epsg: int = 4326
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # S,W,N,E


def compute_edge_capacity(highway_type: str, lanes: int = 1) -> int:
    per_lane = CAPACITY_PER_LANE.get(highway_type, 700)
    return per_lane * max(1, lanes)


def compute_free_flow_time(length_m: float, highway_type: str,
                           speed_kph: float | None = None) -> float:
    if not speed_kph or speed_kph <= 0:
        speed_kph = FREEFLOW_SPEED_KPH.get(highway_type, 40.0)
    speed_ms = speed_kph / 3.6
    if speed_ms <= 0 or length_m <= 0:
        return 0.0
    return length_m / speed_ms
