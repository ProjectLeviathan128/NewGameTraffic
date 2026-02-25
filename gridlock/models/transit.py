from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TransitStop:
    stop_id: str
    name: str
    lon: float
    lat: float
    x: float                        # Projected
    y: float
    accessibility_radius_m: float = 417.0   # 5-min walk at 5 km/h
    catchment_polygon: Any = None           # Shapely Polygon
    nearest_node_id: int = 0               # Snapped road node


@dataclass
class TransitRoute:
    route_id: str
    short_name: str
    long_name: str
    route_type: int                 # GTFS: 0=tram,1=subway,2=rail,3=bus,4=ferry
    stop_ids: list[str] = field(default_factory=list)
    headway_minutes: float = 15.0
    reliability_score: float = 1.0
    edge_ids_on_route: list[int] = field(default_factory=list)

    @property
    def mode_label(self) -> str:
        return {0: "tram", 1: "subway", 2: "rail", 3: "bus", 4: "ferry"}.get(
            self.route_type, "bus"
        )


@dataclass
class TransitNetwork:
    stops: dict[str, TransitStop]
    routes: dict[str, TransitRoute]
    service_date: str = ""
