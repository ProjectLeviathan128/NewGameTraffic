#!/usr/bin/env python3
"""
Enrich the bundled Portland static traffic dataset with measured PBOT counts.

Reads:
  web/public/data/portland_real_osm.json

Fetches:
  PBOT Traffic Volume points from ArcGIS layer:
  https://www.portlandmaps.com/arcgis/rest/services/Public/Transportation/MapServer/8

Writes:
  web/public/data/portland_real_osm.json (in-place)

Why this exists:
  The bundled dataset originally had real OSM geometry but synthetic traffic
  volumes by road class. This script anchors volumes to observed PBOT counts
  where possible, and infers remaining edges from observed class medians.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PBOT_LAYER_QUERY = (
    "https://www.portlandmaps.com/arcgis/rest/services/Public/Transportation/MapServer/8/query"
)

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "web" / "public" / "data" / "portland_real_osm.json"

# Roughly ~330m in Portland latitude.
MAX_MATCH_DIST_DEG = 0.003
# Grid size for midpoint spatial hashing (lon/lat degrees).
GRID_STEP_DEG = 0.003

# Mirrors pipeline defaults; used as structural prior where counts are sparse.
SYNTHETIC_VC_BASELINE: dict[str, float] = {
    "motorway": 0.75,
    "motorway_link": 0.65,
    "trunk": 0.70,
    "trunk_link": 0.60,
    "primary": 0.65,
    "primary_link": 0.55,
    "secondary": 0.55,
    "secondary_link": 0.45,
    "tertiary": 0.45,
    "tertiary_link": 0.35,
    "residential": 0.25,
    "living_street": 0.10,
    "unclassified": 0.40,
    "service": 0.20,
}


def vc_to_los(vc: float) -> str:
    if vc <= 0.20:
        return "A"
    if vc <= 0.44:
        return "B"
    if vc <= 0.64:
        return "C"
    if vc <= 0.85:
        return "D"
    if vc <= 1.00:
        return "E"
    return "F"


def vc_to_color(vc: float) -> str:
    if vc <= 0.25:
        return "#4CAF50"
    if vc <= 0.50:
        return "#FFC107"
    if vc <= 0.75:
        return "#FF9800"
    if vc <= 1.00:
        return "#F44336"
    return "#B71C1C"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _http_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{qs}",
        headers={"User-Agent": "gridlock-pbot-enrichment/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_pbot_volume_points() -> list[dict[str, Any]]:
    """
    Fetch normal-weekday traffic-volume point records with pagination.
    """
    where = "ExceptType = 'Normal Weekday' AND ADTVolume IS NOT NULL AND ADTVolume > 0"
    out_fields = ",".join(
        [
            "OBJECTID",
            "LocationID",
            "Bound",
            "StartDate",
            "ADTVolume",
            "AMPkHrVol",
            "PMPkHrVol",
            "AMPkHrFactor",
            "PMPkHrFactor",
            "LocationDesc",
            "CountType",
        ]
    )

    page_size = 4000
    offset = 0
    all_features: list[dict[str, Any]] = []

    while True:
        payload = _http_json(
            PBOT_LAYER_QUERY,
            {
                "f": "json",
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "true",
                "outSR": 4326,
                "orderByFields": "OBJECTID ASC",
                "resultOffset": offset,
                "resultRecordCount": page_size,
            },
        )
        features = payload.get("features", [])
        if not features:
            break

        all_features.extend(features)
        offset += len(features)
        if len(features) < page_size:
            break

        # Avoid hammering public API.
        time.sleep(0.08)

    return all_features


def dedupe_latest_point_counts(raw_features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Keep the most recent count for each (LocationID, Bound) pair.
    """
    latest: dict[tuple[str, str], dict[str, Any]] = {}

    for feat in raw_features:
        attrs = feat.get("attributes", {}) or {}
        geom = feat.get("geometry", {}) or {}

        lon = geom.get("x")
        lat = geom.get("y")
        if lon is None or lat is None:
            continue

        loc_id = str(attrs.get("LocationID") or attrs.get("LocationDesc") or "").strip()
        if not loc_id:
            continue
        bound = str(attrs.get("Bound") or "").strip()
        key = (loc_id, bound)

        start_date = float(attrs.get("StartDate") or 0.0)
        prev = latest.get(key)
        if prev is None or start_date > float(prev["start_date"]):
            latest[key] = {
                "lon": float(lon),
                "lat": float(lat),
                "start_date": start_date,
                "adt": float(attrs.get("ADTVolume") or 0.0),
                "am_peak": float(attrs.get("AMPkHrVol") or 0.0),
                "pm_peak": float(attrs.get("PMPkHrVol") or 0.0),
                "am_factor": float(attrs.get("AMPkHrFactor") or 0.0),
                "pm_factor": float(attrs.get("PMPkHrFactor") or 0.0),
                "count_type": str(attrs.get("CountType") or ""),
                "location_desc": str(attrs.get("LocationDesc") or ""),
            }

    return list(latest.values())


def estimate_peak_hour_volume(point: dict[str, Any]) -> float:
    """
    Derive peak-hour directional volume from PBOT count attributes.
    """
    am = max(0.0, float(point.get("am_peak", 0.0)))
    pm = max(0.0, float(point.get("pm_peak", 0.0)))
    adt = max(0.0, float(point.get("adt", 0.0)))

    peak = max(am, pm)
    if peak > 0:
        return peak

    # Fallback: convert ADT to a rough directional peak hour.
    # Typical K-factor in urban arterials is often around 8-10%.
    return adt * 0.09


def cell_for(lon: float, lat: float) -> tuple[int, int]:
    return (int(math.floor(lon / GRID_STEP_DEG)), int(math.floor(lat / GRID_STEP_DEG)))


def build_edge_spatial_index(edges: list[dict[str, Any]]) -> dict[tuple[int, int], list[int]]:
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for idx, edge in enumerate(edges):
        midpoint = edge.get("midpoint")
        if not isinstance(midpoint, list) or len(midpoint) < 2:
            path = edge.get("path")
            if isinstance(path, list) and path:
                midpoint = path[len(path) // 2]
            else:
                continue
        lon = float(midpoint[0])
        lat = float(midpoint[1])
        grid[cell_for(lon, lat)].append(idx)
    return grid


def nearest_edge_idx(
    lon: float,
    lat: float,
    edges: list[dict[str, Any]],
    grid: dict[tuple[int, int], list[int]],
) -> tuple[int | None, float]:
    """
    Return nearest edge index and squared distance in lon/lat degrees.
    """
    cx, cy = cell_for(lon, lat)
    best_idx: int | None = None
    best_d2 = float("inf")

    # Search nearby cells first; expand up to 2 rings.
    for ring in range(0, 3):
        found_any = False
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                bucket = grid.get((cx + dx, cy + dy))
                if not bucket:
                    continue
                found_any = True
                for idx in bucket:
                    midpoint = edges[idx].get("midpoint")
                    if not midpoint:
                        continue
                    ex = float(midpoint[0])
                    ey = float(midpoint[1])
                    d2 = (ex - lon) ** 2 + (ey - lat) ** 2
                    if d2 < best_d2:
                        best_d2 = d2
                        best_idx = idx
        if found_any and best_idx is not None and best_d2 <= MAX_MATCH_DIST_DEG**2:
            break

    return best_idx, best_d2


def class_tier(highway_type: str) -> str:
    hw = (highway_type or "").lower()
    if hw.startswith("motorway") or hw.startswith("trunk"):
        return "freeway"
    if hw.startswith("primary") or hw.startswith("secondary"):
        return "arterial"
    if hw.startswith("tertiary") or hw.startswith("unclassified"):
        return "collector"
    return "local"


def blend_weight(sample_count: int) -> float:
    """
    How much to trust observed medians vs structural baseline.
    """
    if sample_count >= 400:
        return 0.80
    if sample_count >= 150:
        return 0.65
    if sample_count >= 50:
        return 0.50
    if sample_count >= 20:
        return 0.35
    return 0.0


def enrich_dataset(dataset_path: Path) -> dict[str, Any]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    edges = payload.get("edges", [])
    if not isinstance(edges, list) or not edges:
        raise RuntimeError(f"Dataset has no edges: {dataset_path}")

    raw = fetch_pbot_volume_points()
    deduped = dedupe_latest_point_counts(raw)

    edge_grid = build_edge_spatial_index(edges)
    edge_observed: dict[int, list[float]] = defaultdict(list)
    match_d2: list[float] = []

    for p in deduped:
        peak = estimate_peak_hour_volume(p)
        if peak <= 0:
            continue
        idx, d2 = nearest_edge_idx(float(p["lon"]), float(p["lat"]), edges, edge_grid)
        if idx is None or d2 > MAX_MATCH_DIST_DEG**2:
            continue
        edge_observed[idx].append(peak)
        match_d2.append(d2)

    # Derive observed V/C medians per highway type and broader class tier.
    vc_by_type: dict[str, list[float]] = defaultdict(list)
    vc_by_tier: dict[str, list[float]] = defaultdict(list)
    global_vc: list[float] = []

    for idx, samples in edge_observed.items():
        edge = edges[idx]
        cap = max(1.0, float(edge.get("capacity", 1.0)))
        obs_peak = statistics.median(samples)
        vc = clamp(obs_peak / cap, 0.02, 2.5)
        hwy = str(edge.get("highway_type") or "unknown")
        vc_by_type[hwy].append(vc)
        vc_by_tier[class_tier(hwy)].append(vc)
        global_vc.append(vc)

    default_global_vc = statistics.median(global_vc) if global_vc else 0.52
    median_vc_by_type = {k: statistics.median(v) for k, v in vc_by_type.items() if v}
    median_vc_by_tier = {k: statistics.median(v) for k, v in vc_by_tier.items() if v}

    # Build per-type inference V/C with sample-size-aware blending.
    type_target_vc: dict[str, float] = {}
    for edge in edges:
        hwy = str(edge.get("highway_type") or "unclassified")
        if hwy in type_target_vc:
            continue

        baseline = SYNTHETIC_VC_BASELINE.get(hwy, 0.40)
        obs_samples = vc_by_type.get(hwy, [])
        obs_median = median_vc_by_type.get(hwy)
        w = blend_weight(len(obs_samples))

        if w > 0 and obs_median is not None:
            target = (w * obs_median) + ((1.0 - w) * baseline)
        else:
            tier = class_tier(hwy)
            tier_obs = median_vc_by_tier.get(tier)
            tier_n = len(vc_by_tier.get(tier, []))
            tier_w = min(0.45, blend_weight(tier_n) * 0.6)
            if tier_obs is not None and tier_w > 0:
                target = (tier_w * tier_obs) + ((1.0 - tier_w) * baseline)
            else:
                target = baseline

        # Keep inferred values in plausible game range.
        type_target_vc[hwy] = clamp(target, 0.10, 1.35)

    matched_edges = 0
    for idx, edge in enumerate(edges):
        cap = max(1.0, float(edge.get("capacity", 1.0)))
        hwy = str(edge.get("highway_type") or "unknown")

        if idx in edge_observed:
            obs_peak = statistics.median(edge_observed[idx])
            baseline = SYNTHETIC_VC_BASELINE.get(hwy, 0.40)
            # Prevent obviously implausible underestimation on sparse/misaligned matches.
            base = clamp(obs_peak, cap * baseline * 0.30, cap * 2.5)
            source = "pbot_observed"
            edge["pbot_sample_count"] = len(edge_observed[idx])
            matched_edges += 1
        else:
            vc = type_target_vc.get(hwy)
            if vc is None:
                vc = median_vc_by_tier.get(class_tier(hwy), default_global_vc)
            base = clamp(cap * vc, 20.0, cap * 2.5)
            source = "pbot_inferred"
            edge["pbot_sample_count"] = 0

        edge["base_volume"] = round(base, 2)
        edge["traffic_source"] = source

        ratio = base / cap
        edge["congestion_ratio"] = round(ratio, 3)
        edge["los"] = vc_to_los(ratio)
        edge["color"] = vc_to_color(ratio)

    source = payload.setdefault("source", {})
    source["traffic_counts"] = {
        "provider": "PBOT Traffic Counts",
        "layer_url": "https://www.portlandmaps.com/arcgis/rest/services/Public/Transportation/MapServer/8",
        "where": "ExceptType = 'Normal Weekday'",
        "records_fetched": len(raw),
        "records_deduped": len(deduped),
        "edges_matched_observed": matched_edges,
        "edges_total": len(edges),
        "class_sample_counts": {k: len(v) for k, v in vc_by_type.items()},
        "match_radius_deg": MAX_MATCH_DIST_DEG,
        "mean_match_distance_m_approx": round(
            (statistics.mean(match_d2) ** 0.5) * 111_000 if match_d2 else 0.0, 1
        ),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    payload["traffic_calibration_mode"] = "pbot_counts_plus_inference"
    return payload


def main() -> int:
    dataset = DEFAULT_DATASET
    if len(sys.argv) > 1:
        dataset = Path(sys.argv[1]).expanduser().resolve()

    if not dataset.exists():
        print(f"Dataset not found: {dataset}", file=sys.stderr)
        return 2

    print(f"Enriching traffic in: {dataset}")
    payload = enrich_dataset(dataset)
    dataset.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    tc = payload.get("source", {}).get("traffic_counts", {})
    print(
        "Done. "
        f"Observed matched edges: {tc.get('edges_matched_observed')}/{tc.get('edges_total')} "
        f"(records fetched: {tc.get('records_fetched')}, deduped: {tc.get('records_deduped')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
