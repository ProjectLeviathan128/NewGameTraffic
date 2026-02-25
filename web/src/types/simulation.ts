export interface EdgeState {
  edge_id: number;
  congestion_ratio: number;   // V/C ratio
  travel_time_sec: number;
  volume_veh_hr: number;
  los: "A" | "B" | "C" | "D" | "E" | "F";
  has_bus_lane: boolean;
  lanes?: number;
  color: string;              // Hex color from server
  // Optional geometry fields for static/demo-mode rendering on GitHub Pages.
  path?: [number, number][];
  midpoint?: [number, number];
  highway_type?: string;
  // Optional static calibration provenance fields.
  traffic_source?: "pbot_observed" | "pbot_inferred" | string;
  pbot_sample_count?: number;
  // Optional static land-use conflict fields for build-road costing.
  building_hits?: number;
  land_acquisition_pc?: number;
  // Editable road meta.
  edit_level?: number;
}

export interface RouteState {
  route_id: string;
  headway_minutes: number;
  ridership_estimate: number;
}

export interface CityMetrics {
  avg_commute_min: number;
  vmt_daily: number;
  transit_ridership: number;
  equity_score: number;
  co2_g_per_commuter_km: number;
  political_capital: number;
}

export interface BuildingState {
  id: number;
  center: [number, number];
  height_m: number;
  radius_m: number;
  tier: 0 | 1 | 2;
}

export interface SimSnapshot {
  city_slug: string;
  tick_hour: number;          // 0–23
  edges: EdgeState[];
  routes: RouteState[];
  buildings?: BuildingState[];
  metrics: CityMetrics;
  traffic_model?: TrafficModelState;
  campaign?: CampaignStageState;
  active_event?: ActiveEventState | null;
}

export interface TrafficModelState {
  mode: "mesoscopic_representative_groups";
  represented_travelers: number;
  active_vehicle_agents: number;
  representative_groups: number;
  avg_group_size: number;
}

export interface CampaignStageState {
  stage_index: number;
  stage_name: string;
  unlocked_edges: number;
  unlocked_buildings: number;
  next_stage_name: string | null;
  progress_points: number;
  next_stage_points: number | null;
  expansion_ready: boolean;
}

export interface ActiveEventState {
  event_id: string;
  title: string;
  description: string;
  affected_edges: number;
  demand_multiplier: number;
  reward_pc: number;
  reward_claimed: boolean;
}

export type OverlayMode =
  | "congestion"      // default — V/C ratio heat
  | "equity"          // census tract equity scores
  | "transit"         // transit coverage radius
  | "emissions"       // CO2 intensity
  | "accessibility";  // pedestrian access index

export type InterventionTool =
  | "road_edit"
  | "capacity_upgrade"
  | "demolish_road"
  | null;
