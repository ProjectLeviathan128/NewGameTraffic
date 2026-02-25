"""
Stage 6: Validation pass

Compares modeled VMT and transit ridership against known city statistics.
Warns (but does not fail) if error exceeds thresholds.
"""

from __future__ import annotations

import logging

from gridlock.models.city_package import ValidationStats
from gridlock.models.graph import RoadGraph
from gridlock.models.transit import TransitNetwork

log = logging.getLogger(__name__)

VMT_WARN_PCT = 20.0
TRANSIT_WARN_PCT = 25.0

OPERATING_HOURS = 16
VEHICLE_CAPACITY = 60       # passengers/bus
AVG_LOAD_FACTOR = 0.35


def run_validation(
    road_graph: RoadGraph,
    transit_network: TransitNetwork | None,
    target_vmt_daily: float,
    target_transit_ridership_daily: float,
) -> ValidationStats:
    """
    Compute modeled metrics and compare against targets.

    VMT: sum over edges of (volume_veh_hr × 16 hr × length_km), halved
         to correct for directed graph double-counting.
    Ridership: headway-based estimate per route.

    Returns ValidationStats with pass/warn flag.
    """
    log.info("Stage 6: Running validation")

    modeled_vmt = _modeled_vmt(road_graph)
    modeled_ridership = _modeled_ridership(transit_network)

    vmt_err = _pct_error(modeled_vmt, target_vmt_daily)
    transit_err = _pct_error(modeled_ridership, target_transit_ridership_daily)
    passed = vmt_err <= VMT_WARN_PCT and transit_err <= TRANSIT_WARN_PCT

    stats = ValidationStats(
        modeled_vmt_daily=modeled_vmt,
        target_vmt_daily=target_vmt_daily,
        modeled_transit_ridership=modeled_ridership,
        target_transit_ridership=target_transit_ridership_daily,
        vmt_error_pct=vmt_err,
        transit_error_pct=transit_err,
        passed=passed,
    )
    _log_report(stats)
    return stats


def _modeled_vmt(road_graph: RoadGraph) -> float:
    total = 0.0
    for edge in road_graph.edges.values():
        total += edge.volume_veh_hr * OPERATING_HOURS * (edge.length_m / 1000.0)
    return total / 2.0   # directed graph counts each undirected edge twice


def _modeled_ridership(transit_network: TransitNetwork | None) -> float:
    if not transit_network:
        return 0.0
    total = 0.0
    for route in transit_network.routes.values():
        trips_per_hr = 60.0 / max(1.0, route.headway_minutes)
        total += trips_per_hr * OPERATING_HOURS * VEHICLE_CAPACITY * AVG_LOAD_FACTOR
    return total


def _pct_error(modeled: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return abs(modeled - target) / target * 100.0


def _log_report(stats: ValidationStats) -> None:
    status = "PASSED" if stats.passed else "WARNING"
    log.info(f"  Validation {status}")
    log.info(
        f"  VMT:     modeled={stats.modeled_vmt_daily:>12,.0f}  "
        f"target={stats.target_vmt_daily:>12,.0f}  "
        f"error={stats.vmt_error_pct:.1f}%"
    )
    log.info(
        f"  Transit: modeled={stats.modeled_transit_ridership:>12,.0f}  "
        f"target={stats.target_transit_ridership:>12,.0f}  "
        f"error={stats.transit_error_pct:.1f}%"
    )
    if not stats.passed:
        log.warning(
            "  Validation thresholds exceeded. Check synthetic V/C defaults "
            "or GTFS headway computation."
        )
