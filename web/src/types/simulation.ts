export interface EdgeState {
  edge_id: number;
  congestion_ratio: number;   // V/C ratio
  travel_time_sec: number;
  volume_veh_hr: number;
  los: "A" | "B" | "C" | "D" | "E" | "F";
  has_bus_lane: boolean;
  color: string;              // Hex color from server
  // Optional geometry fields for static/demo-mode rendering on GitHub Pages.
  path?: [number, number][];
  midpoint?: [number, number];
  highway_type?: string;
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

export interface SimSnapshot {
  city_slug: string;
  tick_hour: number;          // 0–23
  edges: EdgeState[];
  routes: RouteState[];
  metrics: CityMetrics;
}

export type OverlayMode =
  | "congestion"      // default — V/C ratio heat
  | "equity"          // census tract equity scores
  | "transit"         // transit coverage radius
  | "emissions"       // CO2 intensity
  | "accessibility";  // pedestrian access index

export type InterventionTool =
  | "bus_lane"
  | "frequency_boost"
  | "congestion_pricing"
  | "remove_parking"
  | "road_diet"
  | "speed_limit"
  | null;
