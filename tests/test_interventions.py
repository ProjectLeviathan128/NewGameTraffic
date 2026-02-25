"""Unit tests for the intervention system."""

import pytest

from gridlock.simulation.interventions import (
    apply_congestion_pricing,
    apply_road_diet,
    apply_speed_limit_reduction,
    boost_frequency,
    convert_to_bus_lane,
    get_intervention_cost,
    remove_parking,
)


class TestConvertToBusLane:
    def test_reduces_lanes_by_one(self, tiny_graph, tiny_transit):
        original_lanes = tiny_graph.edges[0].lanes  # primary = 2 lanes
        graph, _, _ = convert_to_bus_lane(tiny_graph, 0, tiny_transit)
        assert graph.edges[0].lanes == original_lanes - 1

    def test_marks_bus_lane(self, tiny_graph, tiny_transit):
        graph, _, _ = convert_to_bus_lane(tiny_graph, 0, tiny_transit)
        assert graph.edges[0].has_bus_lane is True

    def test_returns_pc_cost(self, tiny_graph, tiny_transit):
        _, _, pc = convert_to_bus_lane(tiny_graph, 0, tiny_transit)
        assert pc > 0

    def test_does_not_mutate_original(self, tiny_graph, tiny_transit):
        original_lanes = tiny_graph.edges[0].lanes
        convert_to_bus_lane(tiny_graph, 0, tiny_transit)
        assert tiny_graph.edges[0].lanes == original_lanes   # untouched

    def test_raises_if_single_lane(self, tiny_graph, tiny_transit):
        # Edge 1 is residential with 1 lane
        with pytest.raises(ValueError, match="only 1 lane"):
            convert_to_bus_lane(tiny_graph, 1, tiny_transit)

    def test_raises_if_already_bus_lane(self, tiny_graph, tiny_transit):
        graph, net, _ = convert_to_bus_lane(tiny_graph, 0, tiny_transit)
        with pytest.raises(ValueError, match="already has a bus lane"):
            convert_to_bus_lane(graph, 0, net)

    def test_raises_if_edge_not_found(self, tiny_graph, tiny_transit):
        with pytest.raises(KeyError):
            convert_to_bus_lane(tiny_graph, 9999, tiny_transit)

    def test_capacity_decreases(self, tiny_graph, tiny_transit):
        original_cap = tiny_graph.edges[0].capacity_veh_hr
        graph, _, _ = convert_to_bus_lane(tiny_graph, 0, tiny_transit)
        assert graph.edges[0].capacity_veh_hr < original_cap


class TestBoostFrequency:
    def test_reduces_headway(self, tiny_transit):
        original_hw = tiny_transit.routes["R1"].headway_minutes
        net, _ = boost_frequency(tiny_transit, "R1", original_hw - 4)
        assert net.routes["R1"].headway_minutes == original_hw - 4

    def test_returns_pc_cost(self, tiny_transit):
        _, pc = boost_frequency(tiny_transit, "R1", 8.0)
        assert pc > 0

    def test_does_not_mutate_original(self, tiny_transit):
        original_hw = tiny_transit.routes["R1"].headway_minutes
        boost_frequency(tiny_transit, "R1", 8.0)
        assert tiny_transit.routes["R1"].headway_minutes == original_hw

    def test_raises_if_not_lower(self, tiny_transit):
        hw = tiny_transit.routes["R1"].headway_minutes
        with pytest.raises(ValueError, match="must be less than current"):
            boost_frequency(tiny_transit, "R1", hw + 1)

    def test_raises_if_route_not_found(self, tiny_transit):
        with pytest.raises(KeyError):
            boost_frequency(tiny_transit, "NONEXISTENT", 5.0)


class TestCongestionPricing:
    def test_reduces_volume(self, tiny_graph):
        original_vol = tiny_graph.edges[0].volume_veh_hr
        # Nodes 1 and 2 form edge 0
        graph, _ = apply_congestion_pricing(tiny_graph, [1, 2], toll_usd=5.0)
        assert graph.edges[0].volume_veh_hr < original_vol

    def test_unaffected_edges_unchanged(self, tiny_graph):
        original_vol = tiny_graph.edges[3].volume_veh_hr
        # Pricing only on nodes 1,2 — edge 3 (4→1) should be affected only if both endpoints in zone
        # Nodes 4 and 1: 4 is NOT in zone [1, 2], so edge 3 is unaffected
        graph, _ = apply_congestion_pricing(tiny_graph, [1, 2], toll_usd=5.0)
        assert graph.edges[3].volume_veh_hr == pytest.approx(original_vol)

    def test_returns_pc_cost(self, tiny_graph):
        _, pc = apply_congestion_pricing(tiny_graph, [1, 2], toll_usd=5.0)
        assert pc > 0

    def test_higher_toll_reduces_more(self, tiny_graph):
        graph_low, _ = apply_congestion_pricing(tiny_graph, [1, 2], toll_usd=2.0)
        graph_high, _ = apply_congestion_pricing(tiny_graph, [1, 2], toll_usd=15.0)
        assert graph_high.edges[0].volume_veh_hr < graph_low.edges[0].volume_veh_hr


class TestRemoveParking:
    def test_increases_capacity(self, tiny_graph):
        original_cap = tiny_graph.edges[1].capacity_veh_hr   # residential
        graph, _ = remove_parking(tiny_graph, 1)
        assert graph.edges[1].capacity_veh_hr > original_cap

    def test_returns_pc_cost(self, tiny_graph):
        _, pc = remove_parking(tiny_graph, 1)
        assert pc > 0


class TestRoadDiet:
    def test_reduces_to_three_lanes(self, tiny_graph):
        # Edge 0 has 2 lanes — too few for road diet
        with pytest.raises(ValueError, match="requires >= 4 lanes"):
            apply_road_diet(tiny_graph, 0)

    def test_four_lane_road(self, tiny_graph):
        # Manually set edge to 4 lanes for this test
        import dataclasses
        from gridlock.models.graph import RoadEdge
        edge4 = dataclasses.replace(tiny_graph.edges[0], lanes=4,
                                     capacity_veh_hr=6400)
        edges = dict(tiny_graph.edges)
        edges[0] = edge4
        from gridlock.models.graph import RoadGraph
        graph4 = RoadGraph(nodes=tiny_graph.nodes, edges=edges,
                           nx_graph=tiny_graph.nx_graph, crs_epsg=tiny_graph.crs_epsg)
        result, pc = apply_road_diet(graph4, 0)
        assert result.edges[0].lanes == 3
        assert pc > 0


class TestSpeedLimitReduction:
    def test_reduces_speed(self, tiny_graph):
        original_speed = tiny_graph.edges[0].speed_kph
        graph, _ = apply_speed_limit_reduction(tiny_graph, 0, original_speed - 10)
        assert graph.edges[0].speed_kph == pytest.approx(original_speed - 10)

    def test_raises_if_higher(self, tiny_graph):
        spd = tiny_graph.edges[0].speed_kph
        with pytest.raises(ValueError, match="must be less than current speed"):
            apply_speed_limit_reduction(tiny_graph, 0, spd + 10)


class TestPcCosts:
    def test_all_interventions_have_cost(self):
        for name in ["bus_lane", "frequency_boost", "congestion_pricing",
                     "remove_parking", "brt_conversion", "light_rail", "road_diet"]:
            assert get_intervention_cost(name) > 0

    def test_congestion_pricing_highest_cost(self):
        assert get_intervention_cost("congestion_pricing") > get_intervention_cost("bus_lane")
        assert get_intervention_cost("congestion_pricing") > get_intervention_cost("frequency_boost")
