"""
Bureau of Public Roads (BPR) link performance function.

    t = t0 * (1 + alpha * (V/C)^beta)

Standard parameters: alpha=0.15, beta=4 (HCM-validated).

This module is intentionally pure — no I/O, no side effects.
All functions are stateless and fully unit-testable.
"""

from __future__ import annotations
import numpy as np

BPR_ALPHA: float = 0.15
BPR_BETA: float = 4.0

# Synthetic V/C ratios by highway type for baseline calibration
SYNTHETIC_VC_BASELINE: dict[str, float] = {
    "motorway":       0.75,
    "motorway_link":  0.65,
    "trunk":          0.70,
    "trunk_link":     0.60,
    "primary":        0.65,
    "primary_link":   0.55,
    "secondary":      0.55,
    "secondary_link": 0.45,
    "tertiary":       0.45,
    "tertiary_link":  0.35,
    "residential":    0.25,
    "living_street":  0.10,
    "unclassified":   0.40,
    "service":        0.20,
}

# Duranton & Turner (2011) empirical induced demand elasticity
INDUCED_DEMAND_ELASTICITY: float = 0.75


def bpr_travel_time(
    t0: float,
    volume: float,
    capacity: float,
    alpha: float = BPR_ALPHA,
    beta: float = BPR_BETA,
) -> float:
    """
    BPR link performance function for a single road segment.

    Args:
        t0: Free-flow travel time (seconds, or any consistent unit).
        volume: Traffic volume (vehicles/hour).
        capacity: Link capacity (vehicles/hour).
        alpha: BPR alpha parameter (default 0.15).
        beta: BPR beta exponent (default 4.0).

    Returns:
        Congested travel time in the same unit as t0.

    Raises:
        ValueError: If t0 or capacity are non-positive.
    """
    if t0 <= 0:
        raise ValueError(f"t0 must be positive, got {t0}")
    if capacity <= 0:
        raise ValueError(f"capacity must be positive, got {capacity}")
    vc = max(0.0, volume) / capacity
    return t0 * (1.0 + alpha * (vc ** beta))


def bpr_travel_time_vectorized(
    t0: np.ndarray,
    volume: np.ndarray,
    capacity: np.ndarray,
    alpha: float = BPR_ALPHA,
    beta: float = BPR_BETA,
) -> np.ndarray:
    """
    Vectorized BPR across all edges.

    All arrays must be same shape. Division by zero is handled by clamping
    capacity to a minimum of 1.
    """
    vc = np.maximum(0.0, volume) / np.maximum(1.0, capacity)
    return t0 * (1.0 + alpha * (vc ** beta))


def congestion_ratio(volume: float, capacity: float) -> float:
    """V/C ratio, clamped to [0, ∞)."""
    return max(0.0, volume) / max(1.0, capacity)


def level_of_service(vc_ratio: float) -> str:
    """
    HCM 6th Edition Level of Service from V/C ratio.
    Returns 'A' (free flow) through 'F' (breakdown/gridlock).
    """
    if vc_ratio <= 0.20:
        return "A"
    elif vc_ratio <= 0.44:
        return "B"
    elif vc_ratio <= 0.64:
        return "C"
    elif vc_ratio <= 0.85:
        return "D"
    elif vc_ratio <= 1.00:
        return "E"
    return "F"


def los_color(vc_ratio: float) -> str:
    """
    HUD color for traffic overlay (matches GDD spec).
    Returns hex color string.
    """
    if vc_ratio <= 0.25:
        return "#4CAF50"   # Green — free-flowing
    elif vc_ratio <= 0.50:
        return "#FFC107"   # Yellow — mild congestion
    elif vc_ratio <= 0.75:
        return "#FF9800"   # Orange — moderate
    elif vc_ratio <= 1.00:
        return "#F44336"   # Red — severe
    return "#B71C1C"       # Dark red — gridlock


def induced_demand_factor(
    capacity_increase_pct: float,
    days_elapsed: int,
    elasticity: float = INDUCED_DEMAND_ELASTICITY,
    saturation_days: int = 12,
) -> float:
    """
    Compute induced demand multiplier from a road capacity expansion.

    Based on Duranton & Turner (2011): every 10% increase in lane-miles
    produces roughly 7.5% increase in VMT over ~10-15 years.
    This is compressed to a game-day timescale.

    Args:
        capacity_increase_pct: Percent increase in capacity (e.g. 25.0 for +25%).
        days_elapsed: In-game days since the expansion was completed.
        elasticity: Demand elasticity with respect to capacity (default 0.75).
        saturation_days: Days until full induced demand materializes (default 12).

    Returns:
        Demand multiplier (>= 1.0). At day 0 returns 1.0; at saturation_days
        returns (1 + capacity_increase_pct/100)^elasticity.
    """
    if days_elapsed <= 0 or capacity_increase_pct <= 0:
        return 1.0
    max_factor = (1.0 + capacity_increase_pct / 100.0) ** elasticity
    progress = min(1.0, days_elapsed / saturation_days)
    # Log curve: rapid initial uptake, plateaus near saturation
    curved_progress = np.log1p(progress * (np.e - 1)) / 1.0
    return 1.0 + (max_factor - 1.0) * curved_progress
