"""
Stage 2: GTFS feed → TransitNetwork

Parses a GTFS zip, computes per-route headways, snaps stops to the
road network, and overlays transit routes onto road edges.

Uses gtfs2nx when available for NetworkX-native route graphs;
falls back to gtfs-kit for headway calculation.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from gridlock.models.graph import RoadGraph
from gridlock.models.transit import TransitNetwork, TransitRoute, TransitStop

log = logging.getLogger(__name__)

WALK_SPEED_KPH = 5.0
CATCHMENT_MINUTES = 5.0
CATCHMENT_RADIUS_M = (WALK_SPEED_KPH * 1000.0 / 60.0) * CATCHMENT_MINUTES  # ~417 m


def build_transit_network(
    gtfs_path: str,
    road_graph: RoadGraph,
    crs_epsg: int = 32610,
    service_date: str | None = None,
) -> TransitNetwork:
    """
    Parse GTFS feed and overlay onto road graph.

    Args:
        gtfs_path: Path to GTFS .zip file.
        road_graph: Stage 1 road graph (used for stop snapping and route overlay).
        crs_epsg: Local projected CRS EPSG code.
        service_date: YYYYMMDD representative service day.
                      If None, picks the date with the most active trips.

    Returns:
        TransitNetwork with stops, routes, and computed headways.
    """
    log.info(f"Stage 2: Parsing GTFS from {gtfs_path}")

    try:
        import gtfs_kit as gk
        feed = gk.read_feed(gtfs_path, dist_units="km")
        log.info(f"  Feed loaded: {len(feed.routes)} routes, {len(feed.stops)} stops")
    except ImportError:
        log.warning("  gtfs-kit not installed; using minimal GTFS parser")
        return _minimal_gtfs_parse(gtfs_path, road_graph, crs_epsg)

    if service_date is None:
        service_date = _pick_service_date(feed)
    log.info(f"  Service date: {service_date}")

    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{crs_epsg}", always_xy=True)

    stops = _build_stops(feed.stops, transformer)
    routes = _build_routes(feed, service_date)

    _snap_stops_to_road(stops, road_graph)
    _overlay_routes(routes, stops, road_graph)

    network = TransitNetwork(stops=stops, routes=routes, service_date=service_date)
    log.info(f"Stage 2 complete: {len(stops)} stops, {len(routes)} routes")
    return network


def _pick_service_date(feed: Any) -> str:
    """Return YYYYMMDD string of the busiest weekday in the feed."""
    try:
        cal = feed.calendar
        if cal is not None and not cal.empty:
            # Prefer weekday with most service
            weekday_cols = ["monday", "tuesday", "wednesday", "thursday", "friday"]
            available = [c for c in weekday_cols if c in cal.columns]
            if available:
                cal["weekday_sum"] = cal[available].sum(axis=1)
                best = cal.sort_values("weekday_sum", ascending=False).iloc[0]
                return str(best.get("start_date", "20240101")).replace("-", "")
    except Exception:
        pass
    try:
        return str(feed.calendar["start_date"].iloc[0]).replace("-", "")
    except Exception:
        return "20240101"


def _build_stops(
    stops_df: Any,
    transformer: Any,
) -> dict[str, TransitStop]:
    from shapely.geometry import Point
    stops = {}
    for _, row in stops_df.iterrows():
        try:
            x, y = transformer.transform(float(row["stop_lon"]), float(row["stop_lat"]))
        except Exception:
            continue
        catchment = Point(x, y).buffer(CATCHMENT_RADIUS_M)
        stops[str(row["stop_id"])] = TransitStop(
            stop_id=str(row["stop_id"]),
            name=str(row.get("stop_name", "") or ""),
            lon=float(row["stop_lon"]),
            lat=float(row["stop_lat"]),
            x=x,
            y=y,
            accessibility_radius_m=CATCHMENT_RADIUS_M,
            catchment_polygon=catchment,
        )
    return stops


def _build_routes(feed: Any, service_date: str) -> dict[str, TransitRoute]:
    routes = {}

    # Try gtfs-kit headway computation
    headways: dict[str, float] = {}
    try:
        stats = feed.compute_route_stats(feed.get_trips(date=service_date))
        if hasattr(stats, "iterrows"):
            for _, row in stats.iterrows():
                rid = str(row.get("route_id", ""))
                hw = row.get("mean_headway", 15.0)
                if rid:
                    headways[rid] = float(hw) if hw and hw == hw else 15.0
    except Exception:
        # Fall back to computing from stop_times directly
        try:
            headways = _compute_headways_from_stop_times(feed)
        except Exception:
            pass

    # Get stop sequence per route
    stop_sequences = _build_stop_sequences(feed)

    for _, row in feed.routes.iterrows():
        rid = str(row["route_id"])
        routes[rid] = TransitRoute(
            route_id=rid,
            short_name=str(row.get("route_short_name", "") or ""),
            long_name=str(row.get("route_long_name", "") or ""),
            route_type=int(row.get("route_type", 3)),
            stop_ids=stop_sequences.get(rid, []),
            headway_minutes=headways.get(rid, 15.0),
        )
    return routes


def _compute_headways_from_stop_times(feed: Any) -> dict[str, float]:
    """Compute average headway (minutes) per route from stop_times."""
    import pandas as pd
    st = feed.stop_times.copy()
    trips = feed.trips[["trip_id", "route_id"]].copy()
    st = st.merge(trips, on="trip_id")

    headways: dict[str, float] = {}
    for rid, group in st.groupby("route_id"):
        # Get departure times at first stop of each trip
        first_stops = group.sort_values("stop_sequence").groupby("trip_id").first()
        deps = first_stops["departure_time"].dropna()
        # Parse HH:MM:SS
        times = []
        for t in deps:
            try:
                parts = str(t).split(":")
                secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                times.append(secs)
            except Exception:
                pass
        if len(times) >= 2:
            times = sorted(times)
            gaps = [times[i+1] - times[i] for i in range(len(times) - 1) if times[i+1] - times[i] > 0]
            headways[str(rid)] = float(np.mean(gaps)) / 60.0 if gaps else 15.0
        else:
            headways[str(rid)] = 15.0
    return headways


def _build_stop_sequences(feed: Any) -> dict[str, list[str]]:
    """Return ordered stop list for each route's representative trip."""
    trips = feed.trips.copy()
    st = feed.stop_times.copy()
    result: dict[str, list[str]] = {}

    for rid, trip_group in trips.groupby("route_id"):
        trip_id = trip_group.iloc[0]["trip_id"]
        trip_stops = st[st["trip_id"] == trip_id].sort_values("stop_sequence")
        result[str(rid)] = [str(s) for s in trip_stops["stop_id"].tolist()]
    return result


def _snap_stops_to_road(stops: dict[str, TransitStop], road_graph: RoadGraph) -> None:
    """Snap each stop to the nearest road graph node (in-place)."""
    node_ids = list(road_graph.nodes.keys())
    if not node_ids:
        return
    node_xy = np.array([[road_graph.nodes[n].x, road_graph.nodes[n].y] for n in node_ids])
    for stop in stops.values():
        dists = (node_xy[:, 0] - stop.x) ** 2 + (node_xy[:, 1] - stop.y) ** 2
        idx = int(np.argmin(dists))
        stop.nearest_node_id = node_ids[idx]


def _overlay_routes(
    routes: dict[str, TransitRoute],
    stops: dict[str, TransitStop],
    road_graph: RoadGraph,
) -> None:
    """Find road edges used by each transit route via shortest-path snapping."""
    import networkx as nx
    G = road_graph.nx_graph
    if G is None:
        return

    uv_to_eid = {(e.u, e.v): e.edge_id for e in road_graph.edges.values()}

    for route in routes.values():
        stop_nodes = [
            stops[sid].nearest_node_id
            for sid in route.stop_ids
            if sid in stops and stops[sid].nearest_node_id
        ]
        edge_ids: list[int] = []
        for a, b in zip(stop_nodes[:-1], stop_nodes[1:]):
            try:
                path = nx.shortest_path(G, a, b, weight="length")
                for u, v in zip(path[:-1], path[1:]):
                    eid = uv_to_eid.get((u, v))
                    if eid is not None:
                        edge_ids.append(eid)
                        if route.route_id not in road_graph.edges[eid].transit_route_ids:
                            road_graph.edges[eid].transit_route_ids.append(route.route_id)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
        route.edge_ids_on_route = edge_ids


def _minimal_gtfs_parse(
    gtfs_path: str,
    road_graph: RoadGraph,
    crs_epsg: int,
) -> TransitNetwork:
    """Minimal GTFS parser using only stdlib + zipfile, no gtfs-kit dependency."""
    import zipfile, csv
    from pyproj import Transformer
    from shapely.geometry import Point

    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{crs_epsg}", always_xy=True)
    stops: dict[str, TransitStop] = {}
    routes: dict[str, TransitRoute] = {}

    with zipfile.ZipFile(gtfs_path) as zf:
        names = zf.namelist()

        # Parse stops
        if "stops.txt" in names:
            with zf.open("stops.txt") as f:
                for row in csv.DictReader(line.decode() for line in f):
                    sid = row.get("stop_id", "")
                    try:
                        x, y = transformer.transform(float(row["stop_lon"]), float(row["stop_lat"]))
                    except Exception:
                        continue
                    stops[sid] = TransitStop(
                        stop_id=sid,
                        name=row.get("stop_name", ""),
                        lon=float(row["stop_lon"]),
                        lat=float(row["stop_lat"]),
                        x=x, y=y,
                    )

        # Parse routes
        if "routes.txt" in names:
            with zf.open("routes.txt") as f:
                for row in csv.DictReader(line.decode() for line in f):
                    rid = row.get("route_id", "")
                    routes[rid] = TransitRoute(
                        route_id=rid,
                        short_name=row.get("route_short_name", ""),
                        long_name=row.get("route_long_name", ""),
                        route_type=int(row.get("route_type", 3)),
                    )

    _snap_stops_to_road(stops, road_graph)
    return TransitNetwork(stops=stops, routes=routes, service_date="")
