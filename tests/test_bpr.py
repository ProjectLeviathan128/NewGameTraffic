"""Unit tests for BPR traffic flow model."""

import numpy as np
import pytest

from gridlock.bpr import (
    BPR_ALPHA,
    BPR_BETA,
    bpr_travel_time,
    bpr_travel_time_vectorized,
    congestion_ratio,
    induced_demand_factor,
    level_of_service,
    los_color,
)
from gridlock.models.graph import (
    CAPACITY_PER_LANE,
    FREEFLOW_SPEED_KPH,
    compute_edge_capacity,
    compute_free_flow_time,
)


class TestBprTravelTime:
    def test_free_flow_at_zero_volume(self):
        assert bpr_travel_time(100.0, 0.0, 1000.0) == pytest.approx(100.0)

    def test_at_full_capacity(self):
        # V/C = 1.0 → t = t0 * (1 + 0.15 * 1) = t0 * 1.15
        assert bpr_travel_time(100.0, 1000.0, 1000.0) == pytest.approx(115.0)

    def test_overcapacity_doubles(self):
        # V/C = 2.0 → t = t0 * (1 + 0.15 * 16) = t0 * 3.4
        assert bpr_travel_time(100.0, 2000.0, 1000.0) == pytest.approx(340.0)

    def test_negative_volume_clamped_to_free_flow(self):
        assert bpr_travel_time(100.0, -500.0, 1000.0) == pytest.approx(100.0)

    def test_custom_alpha_beta(self):
        # alpha=0, beta=anything → always returns t0
        assert bpr_travel_time(50.0, 900.0, 1000.0, alpha=0.0, beta=4.0) == pytest.approx(50.0)

    def test_raises_on_zero_t0(self):
        with pytest.raises(ValueError, match="t0 must be positive"):
            bpr_travel_time(0.0, 500.0, 1000.0)

    def test_raises_on_negative_t0(self):
        with pytest.raises(ValueError):
            bpr_travel_time(-10.0, 500.0, 1000.0)

    def test_raises_on_zero_capacity(self):
        with pytest.raises(ValueError, match="capacity must be positive"):
            bpr_travel_time(100.0, 500.0, 0.0)

    def test_result_always_gte_t0(self):
        for vol in [0, 100, 500, 1000, 2000]:
            t = bpr_travel_time(60.0, float(vol), 1000.0)
            assert t >= 60.0

    def test_monotonically_increasing_with_volume(self):
        times = [bpr_travel_time(60.0, float(v), 1000.0) for v in range(0, 2001, 100)]
        assert times == sorted(times)


class TestVectorizedBpr:
    def test_matches_scalar(self):
        t0 = np.array([100.0, 60.0, 30.0])
        vol = np.array([500.0, 1200.0, 0.0])
        cap = np.array([1000.0, 1000.0, 800.0])
        result = bpr_travel_time_vectorized(t0, vol, cap)
        for i in range(3):
            expected = bpr_travel_time(t0[i], vol[i], cap[i])
            assert result[i] == pytest.approx(expected)

    def test_zero_volume_returns_t0(self):
        t0 = np.array([100.0, 200.0])
        vol = np.zeros(2)
        cap = np.array([1000.0, 500.0])
        result = bpr_travel_time_vectorized(t0, vol, cap)
        np.testing.assert_allclose(result, t0)


class TestLevelOfService:
    @pytest.mark.parametrize("vc,expected", [
        (0.10, "A"), (0.20, "A"),
        (0.21, "B"), (0.44, "B"),
        (0.45, "C"), (0.64, "C"),
        (0.65, "D"), (0.85, "D"),
        (0.86, "E"), (1.00, "E"),
        (1.01, "F"), (2.00, "F"),
    ])
    def test_thresholds(self, vc, expected):
        assert level_of_service(vc) == expected


class TestLosColor:
    def test_returns_hex_string(self):
        for vc in [0.1, 0.3, 0.6, 0.9, 1.5]:
            color = los_color(vc)
            assert color.startswith("#")
            assert len(color) == 7

    def test_gridlock_is_darkest(self):
        gridlock_color = los_color(1.5)
        free_flow_color = los_color(0.1)
        assert gridlock_color != free_flow_color


class TestCongestionRatio:
    def test_basic(self):
        assert congestion_ratio(500.0, 1000.0) == pytest.approx(0.5)

    def test_negative_volume_clamped(self):
        assert congestion_ratio(-100.0, 1000.0) == pytest.approx(0.0)

    def test_zero_capacity_clamped(self):
        # Should not raise, capacity clamped to 1
        r = congestion_ratio(500.0, 0.0)
        assert r == pytest.approx(500.0)


class TestEdgeCapacity:
    def test_primary_two_lanes(self):
        assert compute_edge_capacity("primary", 2) == CAPACITY_PER_LANE["primary"] * 2

    def test_motorway_four_lanes(self):
        assert compute_edge_capacity("motorway", 4) == CAPACITY_PER_LANE["motorway"] * 4

    def test_unknown_type_defaults(self):
        cap = compute_edge_capacity("unknown", 1)
        assert cap == 700   # default per-lane capacity

    def test_minimum_one_lane(self):
        assert compute_edge_capacity("residential", 0) == CAPACITY_PER_LANE["residential"]


class TestFreeFlowTime:
    def test_basic_calculation(self):
        # 100m at 36 km/h = 10 m/s → 10 seconds
        t = compute_free_flow_time(100.0, "residential", speed_kph=36.0)
        assert t == pytest.approx(10.0)

    def test_uses_lookup_when_speed_not_given(self):
        t = compute_free_flow_time(100.0, "motorway")
        expected = 100.0 / (FREEFLOW_SPEED_KPH["motorway"] / 3.6)
        assert t == pytest.approx(expected)

    def test_zero_length_returns_zero(self):
        assert compute_free_flow_time(0.0, "primary", speed_kph=60.0) == 0.0


class TestInducedDemand:
    def test_zero_days_returns_one(self):
        assert induced_demand_factor(25.0, 0) == pytest.approx(1.0)

    def test_zero_capacity_increase_returns_one(self):
        assert induced_demand_factor(0.0, 10) == pytest.approx(1.0)

    def test_factor_grows_over_time(self):
        f5 = induced_demand_factor(25.0, 5)
        f12 = induced_demand_factor(25.0, 12)
        assert f12 > f5 > 1.0

    def test_saturates_near_elasticity_bound(self):
        # At saturation: (1 + 0.25)^0.75 ≈ 1.185
        f = induced_demand_factor(25.0, 100, saturation_days=12)
        expected_max = (1.25) ** 0.75
        assert f == pytest.approx(expected_max, rel=0.05)
