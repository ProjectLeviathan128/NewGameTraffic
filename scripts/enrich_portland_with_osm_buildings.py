#!/usr/bin/env python3
"""
Enrich bundled Portland static dataset with simplified OSM building meshes.

Reads:
  web/public/data/portland_real_osm.json

Fetches:
  OpenStreetMap building footprints via Overpass (sampled per tile)

Writes:
  web/public/data/portland_real_osm.json (in-place)

Why this exists:
  - Add lightweight static building meshes (for better city feel).
  - Add per-edge land-acquisition/demolition surcharge estimates so "build road"
    actions can cost more when they run through built-up areas.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
import zlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "web" / "public" / "data" / "portland_real_osm.json"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

TILE_COLS = 9
TILE_ROWS = 7
PER_TILE_LIMIT = 360
TILE_DELAY_SEC = 0.06

GRID_STEP_DEG = 0.0014
CORRIDOR_RADIUS_M = 45.0
MAX_EDGE_HITS = 24


def to_num(value: Any, fallback: float) -> float:
    try:
        if value is None:
            return fallback
        n = float(value)
        if math.isfinite(n):
            return n
    except Exception:
        pass
    return fallback


def parse_height_m(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    text = text.replace("meters", "m").replace("meter", "m")
    # Formats like "12.5", "12 m", "40ft", "40'"
    num = ""
    for ch in text:
        if ch.isdigit() or ch in ".-":
            num += ch
        elif num:
            break
    if not num:
        return None
    value = to_num(num, float("nan"))
    if not math.isfinite(value):
        return None
    if "ft" in text or "'" in text:
        value *= 0.3048
    return max(3.0, min(120.0, value))


def normalize_kind(raw: Any) -> str:
    text = str(raw or "yes").strip().lower()
    if not text:
        return "yes"
    if text in {"house", "detached", "residential", "semidetached_house", "terrace"}:
        return "residential"
    if text in {"apartments", "dormitory"}:
        return "apartments"
    if text in {"retail", "supermarket", "mall", "kiosk"}:
        return "retail"
    if text in {"commercial", "office", "bank"}:
        return "commercial"
    if text in {"industrial", "warehouse", "hangar"}:
        return "industrial"
    if text in {"school", "college", "university", "kindergarten"}:
        return "education"
    if text in {"hospital", "clinic"}:
        return "healthcare"
    if text in {"government", "public", "civic", "courthouse"}:
        return "civic"
    return text


def kind_defaults(kind: str) -> tuple[float, float]:
    """
    Returns (footprint_m2, height_m) defaults.
    """
    if kind == "residential":
        return 120.0, 8.5
    if kind == "apartments":
        return 320.0, 14.0
    if kind in {"retail", "commercial"}:
        return 420.0, 13.0
    if kind == "industrial":
        return 780.0, 12.0
    if kind == "education":
        return 620.0, 14.0
    if kind == "healthcare":
        return 800.0, 18.0
    if kind == "civic":
        return 560.0, 15.0
    return 190.0, 9.5


def building_tier(kind: str, height_m: float, footprint_m2: float) -> int:
    if kind in {"commercial", "industrial", "healthcare", "education", "civic"}:
        return 0
    if height_m >= 16.0 or footprint_m2 >= 500.0:
        return 1
    return 2


def stable_hash(text: str) -> int:
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


def _overpass_json(endpoint: str, query: str, timeout_sec: float = 120.0) -> dict[str, Any]:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "User-Agent": "gridlock-osm-buildings/1.0",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))


def query_tile(
    endpoint: str,
    south: float,
    west: float,
    north: float,
    east: float,
) -> list[dict[str, Any]]:
    query = (
        f"[out:json][timeout:90];"
        f"("
        f'way["building"]({south:.6f},{west:.6f},{north:.6f},{east:.6f});'
        f'relation["building"]({south:.6f},{west:.6f},{north:.6f},{east:.6f});'
        f");"
        f"out ids center tags qt {PER_TILE_LIMIT};"
    )
    payload = _overpass_json(endpoint, query, timeout_sec=140.0)
    elements = payload.get("elements", [])
    if isinstance(elements, list):
        return elements
    return []


def fetch_sampled_building_elements(bbox: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    south = float(bbox["south"])
    west = float(bbox["west"])
    north = float(bbox["north"])
    east = float(bbox["east"])

    # Attempt endpoints in order.
    last_error: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            all_elements: dict[str, dict[str, Any]] = {}
            for row in range(TILE_ROWS):
                y0 = south + (north - south) * (row / TILE_ROWS)
                y1 = south + (north - south) * ((row + 1) / TILE_ROWS)
                for col in range(TILE_COLS):
                    x0 = west + (east - west) * (col / TILE_COLS)
                    x1 = west + (east - west) * ((col + 1) / TILE_COLS)
                    tile_elements = query_tile(endpoint, y0, x0, y1, x1)
                    for el in tile_elements:
                        et = str(el.get("type") or "")
                        eid = el.get("id")
                        center = el.get("center")
                        if et not in {"way", "relation"} or eid is None or not isinstance(center, dict):
                            continue
                        lon = center.get("lon")
                        lat = center.get("lat")
                        if lon is None or lat is None:
                            continue
                        key = f"{et}:{eid}"
                        all_elements[key] = el
                    time.sleep(TILE_DELAY_SEC)
            return list(all_elements.values()), endpoint
        except Exception as err:
            last_error = err
    if last_error is not None:
        raise RuntimeError(f"Failed to fetch buildings from Overpass: {last_error}") from last_error
    raise RuntimeError("Failed to fetch buildings from Overpass")


def osm_id_to_number(osm_type: str, osm_id: int) -> int:
    # Avoid id collision between way/relation.
    if osm_type == "relation":
        return 9_000_000_000 + osm_id
    return osm_id


def build_buildings(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for el in elements:
        center = el.get("center") or {}
        tags = el.get("tags") or {}
        lon = to_num(center.get("lon"), float("nan"))
        lat = to_num(center.get("lat"), float("nan"))
        if not (math.isfinite(lon) and math.isfinite(lat)):
            continue

        osm_type = str(el.get("type") or "way")
        osm_id = int(to_num(el.get("id"), -1))
        if osm_id < 0:
            continue

        kind = normalize_kind(tags.get("building"))
        default_area, default_h = kind_defaults(kind)

        levels = int(round(to_num(tags.get("building:levels"), 0)))
        levels = max(0, min(40, levels))
        height = parse_height_m(tags.get("height"))
        if height is None:
            if levels > 0:
                height = max(4.0, min(120.0, levels * 3.2 + 2.4))
            else:
                height = default_h

        area = to_num(tags.get("building:area"), float("nan"))
        if not math.isfinite(area) or area <= 0:
            area = default_area * (1.0 + min(8, levels) * 0.05)
        area = max(40.0, min(3000.0, area))
        radius_m = max(4.0, min(28.0, math.sqrt(area / math.pi)))

        tier = building_tier(kind, height, area)
        sid = f"{osm_type}:{osm_id}"
        rows.append(
            {
                "id": osm_id_to_number(osm_type, osm_id),
                "sid": sid,
                "center": [round(lon, 6), round(lat, 6)],
                "height_m": round(height, 1),
                "radius_m": round(radius_m, 1),
                "tier": tier,
                "kind": kind,
            }
        )

    # Deterministic downsampling to keep rendering budget stable.
    major = [r for r in rows if r["tier"] == 0]
    medium = [r for r in rows if r["tier"] == 1]
    small = [r for r in rows if r["tier"] == 2]

    target_total = 26_000
    keep_small_ratio = 1.00
    keep_medium_ratio = 1.00

    def keep_ratio(items: list[dict[str, Any]], ratio: float) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        threshold = int(max(1, min(1000, round(ratio * 1000))))
        for r in items:
            if stable_hash(r["sid"]) % 1000 < threshold:
                out.append(r)
        return out

    kept = major + keep_ratio(medium, keep_medium_ratio) + keep_ratio(small, keep_small_ratio)
    if len(kept) > target_total:
        kept.sort(key=lambda r: (r["tier"], stable_hash(r["sid"])))
        kept = kept[:target_total]

    for r in kept:
        # Remove debug-only fields before writing.
        r.pop("sid", None)
        r.pop("kind", None)

    return kept


def cell_for(lon: float, lat: float) -> tuple[int, int]:
    return (int(math.floor(lon / GRID_STEP_DEG)), int(math.floor(lat / GRID_STEP_DEG)))


def build_spatial_index(buildings: list[dict[str, Any]]) -> dict[tuple[int, int], list[int]]:
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, b in enumerate(buildings):
        c = b.get("center")
        if not isinstance(c, list) or len(c) < 2:
            continue
        lon = float(c[0])
        lat = float(c[1])
        grid[cell_for(lon, lat)].append(i)
    return grid


def sample_path_points(path: list[list[float]]) -> list[tuple[float, float]]:
    if not path:
        return []
    n = len(path)
    if n <= 10:
        return [(float(p[0]), float(p[1])) for p in path if isinstance(p, list) and len(p) >= 2]
    stride = max(1, n // 12)
    points: list[tuple[float, float]] = []
    for i in range(0, n, stride):
        p = path[i]
        if isinstance(p, list) and len(p) >= 2:
            points.append((float(p[0]), float(p[1])))
    last = path[-1]
    if isinstance(last, list) and len(last) >= 2:
        lp = (float(last[0]), float(last[1]))
        if not points or points[-1] != lp:
            points.append(lp)
    return points


def annotate_edges_with_building_costs(
    edges: list[dict[str, Any]],
    buildings: list[dict[str, Any]],
) -> dict[str, float]:
    grid = build_spatial_index(buildings)
    corridor_deg = CORRIDOR_RADIUS_M / 111_000.0
    hit_samples: list[int] = []

    for edge in edges:
        path = edge.get("path")
        if not isinstance(path, list) or len(path) < 2:
            edge["building_hits"] = 0
            edge["land_acquisition_pc"] = 0
            continue

        seen: set[int] = set()
        for lon, lat in sample_path_points(path):
            cx, cy = cell_for(lon, lat)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for bi in grid.get((cx + dx, cy + dy), []):
                        if bi in seen:
                            continue
                        b = buildings[bi]
                        center = b.get("center")
                        if not isinstance(center, list) or len(center) < 2:
                            continue
                        bx = float(center[0])
                        by = float(center[1])
                        radius_deg = (float(b.get("radius_m", 8.0)) / 111_000.0) * 0.35
                        max_deg = corridor_deg + radius_deg
                        d2 = (bx - lon) ** 2 + (by - lat) ** 2
                        if d2 <= max_deg * max_deg:
                            seen.add(bi)
                            if len(seen) >= MAX_EDGE_HITS:
                                break
                    if len(seen) >= MAX_EDGE_HITS:
                        break
                if len(seen) >= MAX_EDGE_HITS:
                    break
            if len(seen) >= MAX_EDGE_HITS:
                break

        hits = min(MAX_EDGE_HITS, len(seen))
        lanes = max(1, int(to_num(edge.get("lanes"), 1)))
        land_pc = int(round(min(40.0, hits * 1.7 + max(0, lanes - 1) * 0.8)))

        edge["building_hits"] = hits
        edge["land_acquisition_pc"] = land_pc
        hit_samples.append(hits)

    return {
        "mean_edge_hits": round(statistics.mean(hit_samples), 2) if hit_samples else 0.0,
        "p95_edge_hits": round(float(statistics.quantiles(hit_samples, n=20)[18]), 2)
        if len(hit_samples) >= 20
        else 0.0,
        "max_edge_hits": max(hit_samples) if hit_samples else 0,
    }


def enrich_dataset(dataset_path: Path) -> dict[str, Any]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    edges = payload.get("edges")
    if not isinstance(edges, list) or not edges:
        raise RuntimeError(f"Dataset has no edges: {dataset_path}")

    source = payload.get("source") or {}
    bbox = source.get("bbox")
    if not isinstance(bbox, dict):
        raise RuntimeError("Dataset source.bbox missing; cannot query OSM buildings")

    raw_elements, endpoint_used = fetch_sampled_building_elements(bbox)
    buildings = build_buildings(raw_elements)
    stats = annotate_edges_with_building_costs(edges, buildings)

    payload["buildings"] = buildings
    source = payload.setdefault("source", {})
    source["buildings"] = {
        "provider": "OpenStreetMap via Overpass",
        "endpoint": endpoint_used,
        "query_mode": "tiled_center_sample",
        "tile_rows": TILE_ROWS,
        "tile_cols": TILE_COLS,
        "per_tile_limit": PER_TILE_LIMIT,
        "records_fetched_raw": len(raw_elements),
        "records_kept": len(buildings),
        "corridor_radius_m": CORRIDOR_RADIUS_M,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        **stats,
    }
    return payload


def main() -> int:
    dataset = DEFAULT_DATASET
    if len(sys.argv) > 1:
        dataset = Path(sys.argv[1]).expanduser().resolve()

    if not dataset.exists():
        print(f"Dataset not found: {dataset}", file=sys.stderr)
        return 2

    print(f"Enriching buildings in: {dataset}")
    payload = enrich_dataset(dataset)
    dataset.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    meta = payload.get("source", {}).get("buildings", {})
    print(
        "Done. "
        f"Buildings kept: {meta.get('records_kept')} "
        f"(raw fetched: {meta.get('records_fetched_raw')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
