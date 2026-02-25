"""
Pipeline orchestrator: runs all 7 stages in sequence with checkpointing.

Intermediate results are pickled to data/processed/ so that earlier stages
can be skipped when re-running after a failure or when iterating on later stages.
Use --no-resume to force a clean run.
"""

from __future__ import annotations

import logging
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path

from gridlock.gdlk_format import GdlkWriter
from gridlock.models.city_package import CityPackage
from gridlock.pipeline.congestion import calibrate_congestion, generate_synthetic_od_matrix
from gridlock.pipeline.demographics import apply_demographic_weights
from gridlock.pipeline.gtfs import build_transit_network
from gridlock.pipeline.land_use import build_demand_zones
from gridlock.pipeline.osm import build_road_graph
from gridlock.pipeline.validation import run_validation

log = logging.getLogger(__name__)


def run_pipeline(
    city_slug: str,
    city_name: str,
    bbox: tuple[float, float, float, float],
    crs_epsg: int,
    gtfs_path: str | None,
    census_path: str | None,
    land_use_path: str | None,
    npmrds_path: str | None,
    output_dir: str,
    processed_dir: str,
    validation_config: dict,
    resume: bool = True,
    skip_stages: list[int] | None = None,
) -> str:
    """
    Run the 7-stage Gridlock data pipeline and write a .gdlk file.

    Args:
        city_slug: Short identifier (e.g. 'portland').
        city_name: Display name (e.g. 'Portland, OR').
        bbox: (south, west, north, east) in WGS84 degrees.
        crs_epsg: Local projected CRS EPSG code.
        gtfs_path: Path to GTFS .zip (or None to skip Stage 2).
        census_path: Path to census shapefile/GeoJSON (or None to skip Stage 4).
        land_use_path: Path to land use file (or None to skip Stage 5).
        npmrds_path: Path to NPMRDS CSV (or None to use synthetic OD).
        output_dir: Directory for the output .gdlk file.
        processed_dir: Directory for stage checkpoint pickles.
        validation_config: Dict with 'target_vmt_daily' and 'target_transit_ridership_daily'.
        resume: If True, load stage checkpoints when available.
        skip_stages: List of stage numbers to skip (e.g. [2, 4]).

    Returns:
        Absolute path to the written .gdlk file.
    """
    skip = set(skip_stages or [])
    checkpoints = _load_checkpoints(processed_dir, city_slug) if resume else {}
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)

    pkg = CityPackage(
        city_name=city_name,
        city_slug=city_slug,
        created_at=datetime.now(timezone.utc).isoformat(),
        crs_epsg=crs_epsg,
        bbox=bbox,
    )

    # ── Stage 1: Road Graph ────────────────────────────────────────────────
    if 1 not in skip:
        if "s1" in checkpoints:
            log.info("Stage 1: Loaded from checkpoint")
            pkg.road_graph = checkpoints["s1"]
        else:
            pkg.road_graph = build_road_graph(bbox=bbox, crs_epsg=crs_epsg)
            _save(processed_dir, city_slug, "s1", pkg.road_graph)
    else:
        log.info("Stage 1: Skipped")

    # ── Stage 2: Transit Network ───────────────────────────────────────────
    if 2 not in skip and gtfs_path:
        if "s2" in checkpoints:
            log.info("Stage 2: Loaded from checkpoint")
            pkg.transit_network = checkpoints["s2"]
        else:
            pkg.transit_network = build_transit_network(
                gtfs_path=gtfs_path,
                road_graph=pkg.road_graph,
                crs_epsg=crs_epsg,
            )
            _save(processed_dir, city_slug, "s2", pkg.transit_network)
    else:
        log.info("Stage 2: Skipped (no GTFS)" if gtfs_path is None else "Stage 2: Skipped")

    # ── Stage 3: Congestion Calibration ───────────────────────────────────
    if 3 not in skip:
        if "s3" in checkpoints:
            log.info("Stage 3: Loaded from checkpoint")
            pkg.road_graph = checkpoints["s3"]
        else:
            od_matrix = None
            if pkg.demand_zones:
                od_matrix = generate_synthetic_od_matrix(pkg.road_graph, pkg.demand_zones)
            pkg.road_graph = calibrate_congestion(
                road_graph=pkg.road_graph,
                npmrds_path=npmrds_path,
                od_matrix=od_matrix,
            )
            _save(processed_dir, city_slug, "s3", pkg.road_graph)
    else:
        log.info("Stage 3: Skipped")

    # ── Stage 4: Demographics ──────────────────────────────────────────────
    if 4 not in skip and census_path:
        if "s4" in checkpoints:
            log.info("Stage 4: Loaded from checkpoint")
            pkg.road_graph, pkg.census_tracts = checkpoints["s4"]
        else:
            pkg.road_graph, pkg.census_tracts = apply_demographic_weights(
                road_graph=pkg.road_graph,
                census_path=census_path,
                crs_epsg=crs_epsg,
            )
            _save(processed_dir, city_slug, "s4", (pkg.road_graph, pkg.census_tracts))
    else:
        log.info("Stage 4: Skipped (no census data)" if census_path is None else "Stage 4: Skipped")

    # ── Stage 5: Land Use / Demand Zones ──────────────────────────────────
    if 5 not in skip and land_use_path:
        if "s5" in checkpoints:
            log.info("Stage 5: Loaded from checkpoint")
            pkg.demand_zones = checkpoints["s5"]
        else:
            pkg.demand_zones = build_demand_zones(
                land_use_path=land_use_path,
                road_graph=pkg.road_graph,
                crs_epsg=crs_epsg,
            )
            _save(processed_dir, city_slug, "s5", pkg.demand_zones)
    else:
        log.info("Stage 5: Skipped (no land use data)" if land_use_path is None else "Stage 5: Skipped")

    # ── Stage 6: Validation ────────────────────────────────────────────────
    if 6 not in skip:
        pkg.validation = run_validation(
            road_graph=pkg.road_graph,
            transit_network=pkg.transit_network,
            target_vmt_daily=validation_config.get("target_vmt_daily", 0.0),
            target_transit_ridership_daily=validation_config.get("target_transit_ridership_daily", 0.0),
        )
    else:
        log.info("Stage 6: Skipped")

    # ── Stage 7: Export ────────────────────────────────────────────────────
    output_path = str(Path(output_dir) / f"{city_slug}.gdlk")
    writer = GdlkWriter()
    writer.write(pkg, output_path)
    size_kb = os.path.getsize(output_path) / 1024
    log.info(f"Stage 7: Written {output_path} ({size_kb:.1f} KB)")
    return output_path


def _ckpt_path(processed_dir: str, city_slug: str, key: str) -> str:
    return str(Path(processed_dir) / f"{city_slug}_{key}.pkl")


def _save(processed_dir: str, city_slug: str, key: str, obj: object) -> None:
    path = _ckpt_path(processed_dir, city_slug, key)
    with open(path, "wb") as f:
        pickle.dump(obj, f, protocol=5)
    log.debug(f"  Checkpoint saved: {path}")


def _load_checkpoints(processed_dir: str, city_slug: str) -> dict:
    ckpts: dict = {}
    for key in ["s1", "s2", "s3", "s4", "s5"]:
        path = _ckpt_path(processed_dir, city_slug, key)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    ckpts[key] = pickle.load(f)
                log.debug(f"  Found checkpoint: {key}")
            except Exception as e:
                log.warning(f"  Could not load checkpoint {key}: {e}")
    return ckpts
