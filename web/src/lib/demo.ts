/**
 * Demo/static mode for GitHub Pages.
 *
 * This module now models a constrained campaign loop:
 * - mesoscopic representative traffic groups (not one-agent-per-person)
 * - district-by-district map unlocks
 * - road node dragging with real-time land + demolition pricing
 * - surge-event pressure with performance rewards
 */

import {
  ActiveEventState,
  CampaignStageState,
  CityMetrics,
  EdgeState,
  RouteState,
  SimSnapshot,
  TrafficModelState,
} from "@/types/simulation";

const DEMO_CITY = "portland";
const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
const REAL_DATA_PATH = "/data/portland_real_osm.json";
const REAL_DATA_URLS = Array.from(
  new Set(
    [
      `${BASE_PATH}${REAL_DATA_PATH}`,
      REAL_DATA_PATH,
      "data/portland_real_osm.json",
    ].filter((url) => url.length > 0),
  ),
);

// BPR constants
const ALPHA = 0.15;
const BETA = 4;

// Rush-hour multipliers
const RUSH: Record<number, number> = {
  0: 0.20, 1: 0.15, 2: 0.15, 3: 0.15, 4: 0.20, 5: 0.40,
  6: 0.60, 7: 0.85, 8: 1.00, 9: 0.90, 10: 0.70, 11: 0.65,
  12: 0.70, 13: 0.65, 14: 0.70, 15: 0.80, 16: 0.95, 17: 1.00,
  18: 0.90, 19: 0.75, 20: 0.60, 21: 0.50, 22: 0.40, 23: 0.30,
};

interface BBox {
  west: number;
  east: number;
  south: number;
  north: number;
}

export interface DemoBounds {
  west: number;
  east: number;
  south: number;
  north: number;
}

interface StageDefinition {
  name: string;
  bbox: BBox | null;
  unlock_points: number;
  view: {
    longitude: number;
    latitude: number;
    zoom: number;
    pitch: number;
    bearing: number;
  };
}

const STAGES: StageDefinition[] = [
  {
    name: "Pilot District",
    bbox: { west: -122.695, east: -122.63, south: 45.495, north: 45.54 },
    unlock_points: 0,
    view: { longitude: -122.666, latitude: 45.519, zoom: 12.9, pitch: 42, bearing: -8 },
  },
  {
    name: "City Core",
    bbox: { west: -122.74, east: -122.57, south: 45.465, north: 45.575 },
    unlock_points: 3,
    view: { longitude: -122.65, latitude: 45.521, zoom: 11.9, pitch: 43, bearing: -10 },
  },
  {
    name: "Metro Network",
    bbox: null,
    unlock_points: 8,
    view: { longitude: -122.676, latitude: 45.523, zoom: 11.0, pitch: 45, bearing: -8 },
  },
];

interface SurgeEventDefinition {
  id: string;
  title: string;
  description: string;
  center: [number, number];
  radius_m: number;
  start_hour: number;
  end_hour: number;
  demand_multiplier: number;
  reward_pc: number;
  target_vc: number;
  min_stage: number;
}

const SURGE_EVENTS: SurgeEventDefinition[] = [
  {
    id: "riverfront_show",
    title: "Riverfront Show Let-Out",
    description: "A large venue empties quickly. Keep nearby corridors moving to avoid public backlash.",
    center: [-122.671, 45.531],
    radius_m: 900,
    start_hour: 17,
    end_hour: 20,
    demand_multiplier: 1.42,
    reward_pc: 6,
    target_vc: 0.95,
    min_stage: 0,
  },
];

export interface DemoEdge {
  edge_id: number;
  path: [number, number][];
  midpoint: [number, number];
  highway_type: string;
  lanes: number;
  t0_sec: number;
  capacity: number;
  base_volume: number; // volume at rush_mult=1.0
  has_bus_lane: boolean;
  equity_weight: number;
  building_hits: number;
  land_acquisition_pc: number;
  base_land_acquisition_pc: number;
  build_road_level: number;
}

export interface DemoRoute {
  route_id: string;
  short_name: string;
  headway_minutes: number;
  stop_count: number;
}

export interface DemoBuilding {
  id: number;
  center: [number, number];
  height_m: number;
  radius_m: number;
  tier: 0 | 1 | 2;
}

interface DemoCity {
  edges: DemoEdge[];
  routes: DemoRoute[];
  buildings: DemoBuilding[];
  pc: number;
  stage_index: number;
  progress_points: number;
  total_edits: number;
  reward_keys: Set<string>;
  event_edge_ids: Record<string, Set<number>>;
}

export interface RoadEditPreview {
  edge_id: number;
  endpoint: "start" | "end";
  path: [number, number][];
  building_ids: number[];
  building_hits: number;
  land_acquisition_pc: number;
  demolition_pc: number;
  edit_pc_cost: number;
  move_distance_m: number;
}

// Singleton city instance — loaded once, mutated by interventions
let _city: DemoCity | null = null;
let _loadPromise: Promise<void> | null = null;
let _pc = 100;
let _sandboxMode = false;

function toNum(value: unknown, fallback: number): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function sanitizePath(raw: unknown): [number, number][] | null {
  if (!Array.isArray(raw) || raw.length < 2) return null;
  const out: [number, number][] = [];
  for (const p of raw) {
    if (!Array.isArray(p) || p.length < 2) continue;
    const lon = toNum(p[0], NaN);
    const lat = toNum(p[1], NaN);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    out.push([lon, lat]);
  }
  if (out.length < 2) return null;
  return out;
}

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

function midPoint(path: [number, number][]): [number, number] {
  return path[Math.floor(path.length / 2)];
}

function inBBox(point: [number, number], bbox: BBox | null): boolean {
  if (!bbox) return true;
  return (
    point[0] >= bbox.west &&
    point[0] <= bbox.east &&
    point[1] >= bbox.south &&
    point[1] <= bbox.north
  );
}

function getStageIndex(city: DemoCity): number {
  return clamp(city.stage_index, 0, STAGES.length - 1);
}

function getStage(city: DemoCity): StageDefinition {
  return STAGES[getStageIndex(city)];
}

function isEdgeUnlocked(city: DemoCity, edge: DemoEdge): boolean {
  return inBBox(edge.midpoint, getStage(city).bbox);
}

function isBuildingUnlocked(city: DemoCity, b: DemoBuilding): boolean {
  return inBBox(b.center, getStage(city).bbox);
}

function toMeters(point: [number, number], latRefDeg: number): [number, number] {
  const latScale = 110_540;
  const lonScale = 111_320 * Math.cos((latRefDeg * Math.PI) / 180);
  return [point[0] * lonScale, point[1] * latScale];
}

function pointToSegmentDistanceMeters(point: [number, number], a: [number, number], b: [number, number]): number {
  const latRef = (point[1] + a[1] + b[1]) / 3;
  const [px, py] = toMeters(point, latRef);
  const [ax, ay] = toMeters(a, latRef);
  const [bx, by] = toMeters(b, latRef);

  const abx = bx - ax;
  const aby = by - ay;
  const apx = px - ax;
  const apy = py - ay;
  const ab2 = abx * abx + aby * aby;

  if (ab2 <= 1e-9) {
    const dx = px - ax;
    const dy = py - ay;
    return Math.sqrt(dx * dx + dy * dy);
  }

  const t = clamp((apx * abx + apy * aby) / ab2, 0, 1);
  const cx = ax + abx * t;
  const cy = ay + aby * t;
  const dx = px - cx;
  const dy = py - cy;
  return Math.sqrt(dx * dx + dy * dy);
}

function pointDistanceMeters(a: [number, number], b: [number, number]): number {
  const latRef = (a[1] + b[1]) / 2;
  const [ax, ay] = toMeters(a, latRef);
  const [bx, by] = toMeters(b, latRef);
  const dx = bx - ax;
  const dy = by - ay;
  return Math.sqrt(dx * dx + dy * dy);
}

function pathLengthMeters(path: [number, number][]): number {
  let total = 0;
  for (let i = 0; i < path.length - 1; i += 1) {
    total += pointDistanceMeters(path[i], path[i + 1]);
  }
  return total;
}

function clonePath(path: [number, number][]): [number, number][] {
  return path.map(([lon, lat]) => [lon, lat]);
}

function withMovedEndpoint(path: [number, number][], endpoint: "start" | "end", coordinate: [number, number]): [number, number][] {
  const out = clonePath(path);
  if (endpoint === "start") {
    out[0] = [coordinate[0], coordinate[1]];
  } else {
    out[out.length - 1] = [coordinate[0], coordinate[1]];
  }
  return out;
}

function expandBBoxOfSegment(a: [number, number], b: [number, number], padMeters: number): BBox {
  const latRef = (a[1] + b[1]) / 2;
  const latPad = padMeters / 110_540;
  const lonPad = padMeters / (111_320 * Math.max(0.3, Math.cos((latRef * Math.PI) / 180)));
  return {
    west: Math.min(a[0], b[0]) - lonPad,
    east: Math.max(a[0], b[0]) + lonPad,
    south: Math.min(a[1], b[1]) - latPad,
    north: Math.max(a[1], b[1]) + latPad,
  };
}

function buildEventEdgeLookup(edges: DemoEdge[]): Record<string, Set<number>> {
  const out: Record<string, Set<number>> = {};
  for (const event of SURGE_EVENTS) {
    const ids = new Set<number>();
    for (const edge of edges) {
      const d = pointToSegmentDistanceMeters(event.center, edge.midpoint, edge.midpoint);
      if (d <= event.radius_m) {
        ids.add(edge.edge_id);
      }
    }
    out[event.id] = ids;
  }
  return out;
}

function normalizeCity(city: DemoCity): DemoCity {
  city.stage_index = clamp(city.stage_index, 0, STAGES.length - 1);
  city.progress_points = Math.max(0, Math.trunc(city.progress_points));
  city.total_edits = Math.max(0, Math.trunc(city.total_edits));
  city.reward_keys = city.reward_keys ?? new Set<string>();
  city.event_edge_ids = city.event_edge_ids ?? buildEventEdgeLookup(city.edges);
  return city;
}

function maybeUnlockStage(city: DemoCity): string | null {
  let unlockedMessage: string | null = null;
  while (city.stage_index < STAGES.length - 1) {
    const next = STAGES[city.stage_index + 1];
    if (city.progress_points < next.unlock_points) break;
    city.stage_index += 1;
    unlockedMessage = `Unlocked ${STAGES[city.stage_index].name}`;
  }
  return unlockedMessage;
}

function awardProgress(city: DemoCity, points: number): string | null {
  city.progress_points = Math.max(0, city.progress_points + points);
  return maybeUnlockStage(city);
}

async function loadRealDemoCity(): Promise<DemoCity> {
  let payload: {
    edges?: unknown[];
    routes?: unknown[];
    buildings?: unknown[];
    political_capital?: number;
  } | null = null;
  let lastErr: unknown = null;

  for (const url of REAL_DATA_URLS) {
    try {
      const res = await fetch(url, { cache: "force-cache" });
      if (!res.ok) {
        lastErr = new Error(`status ${res.status} at ${url}`);
        continue;
      }
      payload = (await res.json()) as {
        edges?: unknown[];
        routes?: unknown[];
        buildings?: unknown[];
        political_capital?: number;
      };
      break;
    } catch (err) {
      lastErr = err;
    }
  }

  if (!payload) {
    throw new Error(`Failed to load static Portland data from ${REAL_DATA_URLS.join(", ")} (${String(lastErr)})`);
  }

  const edgesRaw = Array.isArray(payload.edges) ? payload.edges : [];
  const edges: DemoEdge[] = [];

  for (const raw of edgesRaw) {
    const edge = raw as Record<string, unknown>;
    const path = sanitizePath(edge.path);
    if (!path) continue;

    const midpointRaw = sanitizePath([edge.midpoint, edge.midpoint]);
    const midpoint = midpointRaw ? midpointRaw[0] : midPoint(path);

    const landPc = Math.max(0, Math.trunc(toNum(edge.land_acquisition_pc, 0)));

    edges.push({
      edge_id: Math.trunc(toNum(edge.edge_id, edges.length + 1)),
      path,
      midpoint,
      highway_type: String(edge.highway_type ?? "unclassified"),
      lanes: Math.max(1, Math.trunc(toNum(edge.lanes, 1))),
      t0_sec: Math.max(1, toNum(edge.t0_sec, 30)),
      capacity: Math.max(120, Math.trunc(toNum(edge.capacity, 800))),
      base_volume: Math.max(0, toNum(edge.base_volume, 320)),
      has_bus_lane: false,
      equity_weight: Math.max(0, Math.min(1, toNum(edge.equity_weight, 0.6))),
      building_hits: Math.max(0, Math.trunc(toNum(edge.building_hits, 0))),
      land_acquisition_pc: landPc,
      base_land_acquisition_pc: landPc,
      build_road_level: 0,
    });
  }

  if (!edges.length) {
    throw new Error("Static Portland dataset has no usable edges");
  }

  const routesRaw = Array.isArray(payload.routes) ? payload.routes : [];
  const routes: DemoRoute[] = routesRaw
    .map((raw, idx) => {
      const r = raw as Record<string, unknown>;
      return {
        route_id: String(r.route_id ?? `route-${idx + 1}`),
        short_name: String(r.short_name ?? r.route_id ?? `Route ${idx + 1}`),
        headway_minutes: Math.max(4, Math.min(45, toNum(r.headway_minutes, 18))),
        stop_count: Math.max(0, Math.trunc(toNum(r.stop_count, 0))),
      };
    })
    .slice(0, 120);

  const buildingsRaw = Array.isArray(payload.buildings) ? payload.buildings : [];
  const buildings: DemoBuilding[] = buildingsRaw
    .map((raw, idx) => {
      const b = raw as Record<string, unknown>;
      const center = sanitizePath([b.center, b.center]);
      if (!center) return null;
      return {
        id: Math.trunc(toNum(b.id, idx + 1)),
        center: center[0],
        height_m: Math.max(4, Math.min(80, toNum(b.height_m, 10))),
        radius_m: Math.max(3, Math.min(40, toNum(b.radius_m, 8))),
        tier: Math.max(0, Math.min(2, Math.trunc(toNum(b.tier, 2)))) as 0 | 1 | 2,
      };
    })
    .filter((b): b is DemoBuilding => b !== null);

  const city: DemoCity = {
    edges,
    routes,
    buildings,
    pc: Math.max(0, Math.trunc(toNum(payload.political_capital, 100))),
    stage_index: 0,
    progress_points: 0,
    total_edits: 0,
    reward_keys: new Set<string>(),
    event_edge_ids: buildEventEdgeLookup(edges),
  };

  return normalizeCity(city);
}

// ── Synthetic fallback city (used only if static dataset load fails) ──────

const FALLBACK_BBOX = { south: 45.500, west: -122.700, north: 45.550, east: -122.620 };
const GRID_COLS = 12;
const GRID_ROWS = 8;

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function buildSyntheticFallbackCity(): DemoCity {
  const edges: DemoEdge[] = [];
  let eid = 1;

  const lon = (col: number) => lerp(FALLBACK_BBOX.west, FALLBACK_BBOX.east, col / GRID_COLS);
  const lat = (row: number) => lerp(FALLBACK_BBOX.south, FALLBACK_BBOX.north, row / GRID_ROWS);

  // Horizontal edges
  for (let row = 0; row <= GRID_ROWS; row += 1) {
    for (let col = 0; col < GRID_COLS; col += 1) {
      const isArterial = row % 3 === 0;
      const isHighway = row === 0 || row === GRID_ROWS;
      const hw = isHighway ? "motorway" : isArterial ? "primary" : "residential";
      const lanes = isHighway ? 4 : isArterial ? 2 : 1;
      const cap = isHighway ? 9200 : isArterial ? 3200 : 600;
      const baseVcRatio = isHighway ? 0.75 : isArterial ? 0.65 : 0.25;
      const lengthM = 150;
      const speedKph = isHighway ? 105 : isArterial ? 60 : 40;

      const x1 = lon(col);
      const y1 = lat(row);
      const x2 = lon(col + 1);
      const y2 = lat(row);

      edges.push({
        edge_id: eid,
        path: [[x1, y1], [x2, y2]],
        midpoint: [(x1 + x2) / 2, (y1 + y2) / 2],
        highway_type: hw,
        lanes,
        t0_sec: lengthM / (speedKph / 3.6),
        capacity: cap,
        base_volume: cap * baseVcRatio,
        has_bus_lane: false,
        equity_weight: 0.45 + ((eid * 37) % 50) / 100,
        building_hits: 0,
        land_acquisition_pc: 0,
        base_land_acquisition_pc: 0,
        build_road_level: 0,
      });
      eid += 1;
    }
  }

  // Vertical edges
  for (let col = 0; col <= GRID_COLS; col += 1) {
    for (let row = 0; row < GRID_ROWS; row += 1) {
      const isArterial = col % 4 === 0;
      const hw = isArterial ? "secondary" : "residential";
      const lanes = isArterial ? 2 : 1;
      const cap = isArterial ? 2400 : 600;
      const baseVcRatio = isArterial ? 0.55 : 0.20;
      const lengthM = 120;
      const speedKph = isArterial ? 50 : 40;

      const x1 = lon(col);
      const y1 = lat(row);
      const x2 = lon(col);
      const y2 = lat(row + 1);

      edges.push({
        edge_id: eid,
        path: [[x1, y1], [x2, y2]],
        midpoint: [(x1 + x2) / 2, (y1 + y2) / 2],
        highway_type: hw,
        lanes,
        t0_sec: lengthM / (speedKph / 3.6),
        capacity: cap,
        base_volume: cap * baseVcRatio,
        has_bus_lane: false,
        equity_weight: 0.45 + ((eid * 53) % 50) / 100,
        building_hits: 0,
        land_acquisition_pc: 0,
        base_land_acquisition_pc: 0,
        build_road_level: 0,
      });
      eid += 1;
    }
  }

  const routes: DemoRoute[] = [
    { route_id: "14", short_name: "14 - Hawthorne", headway_minutes: 12, stop_count: 22 },
    { route_id: "4", short_name: "4 - Division", headway_minutes: 10, stop_count: 28 },
    { route_id: "71", short_name: "71 - 60th/122nd", headway_minutes: 15, stop_count: 18 },
    { route_id: "MAX", short_name: "MAX Blue Line", headway_minutes: 8, stop_count: 30 },
  ];

  const buildings: DemoBuilding[] = edges
    .filter((e) => e.highway_type === "residential" || e.highway_type === "secondary")
    .filter((_, idx) => idx % 3 === 0)
    .slice(0, 900)
    .map((e) => ({
      id: e.edge_id,
      center: e.midpoint,
      height_m: 8 + (e.edge_id % 6),
      radius_m: 6 + (e.edge_id % 4),
      tier: e.highway_type === "secondary" ? 1 : 2,
    }));

  const city: DemoCity = {
    edges,
    routes,
    buildings,
    pc: 100,
    stage_index: 0,
    progress_points: 0,
    total_edits: 0,
    reward_keys: new Set<string>(),
    event_edge_ids: buildEventEdgeLookup(edges),
  };

  return normalizeCity(city);
}

export async function ensureDemoCityLoaded(): Promise<void> {
  if (_city) return;
  if (_loadPromise) return _loadPromise;

  _loadPromise = loadRealDemoCity()
    .then((city) => {
      _city = city;
      _pc = city.pc;
    })
    .catch((err) => {
      console.error("Falling back to synthetic demo city:", err);
      _city = buildSyntheticFallbackCity();
      _pc = _city.pc;
    })
    .finally(() => {
      _loadPromise = null;
    });

  return _loadPromise;
}

export function getDemoCity(): DemoCity {
  if (!_city) {
    _city = buildSyntheticFallbackCity();
    _pc = _city.pc;
  }
  return _city;
}

export function resetDemoCity() {
  _city = null;
  _pc = 100;
  _sandboxMode = false;
}

export function getDemoCurrentViewState() {
  const city = getDemoCity();
  return STAGES[getStageIndex(city)].view;
}

export function getDemoViewStateForStage(stageIndex: number) {
  return STAGES[clamp(stageIndex, 0, STAGES.length - 1)].view;
}

export function getDemoBoundsForStage(stageIndex: number): DemoBounds | null {
  const stage = STAGES[clamp(stageIndex, 0, STAGES.length - 1)];
  return stage.bbox ? { ...stage.bbox } : null;
}

export function setDemoSandboxMode(enabled: boolean) {
  _sandboxMode = Boolean(enabled);
}

export function isDemoSandboxMode() {
  return _sandboxMode;
}

function buildRoadEditPreview(city: DemoCity, edge: DemoEdge, endpoint: "start" | "end", coordinate: [number, number]): RoadEditPreview {
  const proposedPath = withMovedEndpoint(edge.path, endpoint, coordinate);
  const oldEndpoint = endpoint === "start" ? edge.path[0] : edge.path[edge.path.length - 1];
  const moveDistanceM = pointToSegmentDistanceMeters(oldEndpoint, oldEndpoint, coordinate);

  const changedSegment = endpoint === "start"
    ? [proposedPath[0], proposedPath[1]] as [[number, number], [number, number]]
    : [proposedPath[proposedPath.length - 2], proposedPath[proposedPath.length - 1]] as [[number, number], [number, number]];

  const corridorRadiusM = 24;
  const candidateBBox = expandBBoxOfSegment(changedSegment[0], changedSegment[1], corridorRadiusM + 35);

  const buildingIds: number[] = [];
  for (const building of city.buildings) {
    if (!isBuildingUnlocked(city, building)) continue;
    if (!inBBox(building.center, candidateBBox)) continue;
    const d = pointToSegmentDistanceMeters(building.center, changedSegment[0], changedSegment[1]);
    if (d <= corridorRadiusM + building.radius_m * 0.35) {
      buildingIds.push(building.id);
    }
  }

  const demolitionPc = buildingIds.length * 2;
  const rightOfWayPc = Math.max(0, Math.round(moveDistanceM / 40));
  const geometricComplexityPc = Math.max(0, Math.round(Math.max(0, moveDistanceM - 12) / 55));
  const landAcqPc = Math.max(
    edge.base_land_acquisition_pc,
    Math.round(edge.base_land_acquisition_pc + rightOfWayPc + geometricComplexityPc),
  );

  const editBasePc = 3;
  const totalPc = editBasePc + landAcqPc + demolitionPc;

  return {
    edge_id: edge.edge_id,
    endpoint,
    path: proposedPath,
    building_ids: buildingIds,
    building_hits: buildingIds.length,
    land_acquisition_pc: landAcqPc,
    demolition_pc: demolitionPc,
    edit_pc_cost: totalPc,
    move_distance_m: Math.round(moveDistanceM * 10) / 10,
  };
}

export function demoPreviewRoadNodeMove(edgeId: number, endpoint: "start" | "end", coordinate: [number, number]): RoadEditPreview | null {
  const city = getDemoCity();
  const edge = city.edges.find((e) => e.edge_id === edgeId);
  if (!edge || !isEdgeUnlocked(city, edge)) return null;
  return buildRoadEditPreview(city, edge, endpoint, coordinate);
}

export function demoCommitRoadNodeMove(edgeId: number, endpoint: "start" | "end", coordinate: [number, number]) {
  const city = getDemoCity();
  const edge = city.edges.find((e) => e.edge_id === edgeId);
  if (!edge) {
    return { success: false, message: `Edge ${edgeId} not found`, pc_cost: 0, preview: null as RoadEditPreview | null };
  }
  if (!isEdgeUnlocked(city, edge)) {
    return { success: false, message: "Edge is outside unlocked district", pc_cost: 0, preview: null as RoadEditPreview | null };
  }

  const preview = buildRoadEditPreview(city, edge, endpoint, coordinate);
  if (!_sandboxMode && _pc < preview.edit_pc_cost) {
    return {
      success: false,
      message: `Need ${preview.edit_pc_cost} PC for this road move, have ${_pc}`,
      pc_cost: 0,
      preview,
    };
  }

  const oldLen = pathLengthMeters(edge.path);
  edge.path = preview.path;
  edge.midpoint = midPoint(preview.path);
  edge.building_hits = preview.building_hits;
  edge.land_acquisition_pc = preview.land_acquisition_pc;

  const newLen = pathLengthMeters(edge.path);
  const lengthRatio = clamp(newLen / Math.max(1, oldLen), 0.75, 1.35);
  edge.t0_sec = Math.max(1, Math.round(edge.t0_sec * lengthRatio * 100) / 100);

  if (!_sandboxMode) {
    _pc = Math.max(0, _pc - preview.edit_pc_cost);
  }
  city.total_edits += 1;
  const unlockMessage = awardProgress(city, 1);

  const msgParts = [
    `Road node moved on edge ${edgeId}`,
    `${preview.building_hits} building conflicts`,
    `${preview.land_acquisition_pc} PC right-of-way`,
  ];
  if (unlockMessage) msgParts.push(unlockMessage);

  return {
    success: true,
    message: msgParts.join(" | "),
    pc_cost: preview.edit_pc_cost,
    preview,
    unlocked_stage: unlockMessage,
  };
}

// ── Apply interventions (client-side) ─────────────────────────────────────

export function demoApplyBusLane(edgeId: number): { success: boolean; message: string; pc_cost: number } {
  const city = getDemoCity();
  const edge = city.edges.find((e) => e.edge_id === edgeId);
  if (!edge) return { success: false, message: `Edge ${edgeId} not found`, pc_cost: 0 };
  if (!isEdgeUnlocked(city, edge)) return { success: false, message: "Edge is outside unlocked district", pc_cost: 0 };
  if (edge.has_bus_lane) return { success: false, message: "Already has bus lane", pc_cost: 0 };
  if (edge.lanes <= 1) return { success: false, message: "Only 1 lane — cannot convert", pc_cost: 0 };

  edge.lanes -= 1;
  edge.capacity = Math.max(120, Math.round(edge.capacity * edge.lanes / (edge.lanes + 1)));
  edge.has_bus_lane = true;
  if (!_sandboxMode) {
    _pc = Math.max(0, _pc - 15);
  }
  return { success: true, message: `Bus lane added to edge ${edgeId}`, pc_cost: _sandboxMode ? 0 : 15 };
}

export function demoApplyCapacityUpgrade(edgeId: number): { success: boolean; message: string; pc_cost: number } {
  const city = getDemoCity();
  const edge = city.edges.find((e) => e.edge_id === edgeId);
  if (!edge) return { success: false, message: `Edge ${edgeId} not found`, pc_cost: 0 };
  if (!isEdgeUnlocked(city, edge)) return { success: false, message: "Edge is outside unlocked district", pc_cost: 0 };
  if ((edge.build_road_level ?? 0) >= 2) {
    return { success: false, message: "Corridor already maxed for this MVP", pc_cost: 0 };
  }

  const basePc = 14;
  const rightOfWayPc = Math.max(0, Math.trunc(toNum(edge.land_acquisition_pc, 0)));
  const demolitionPc = Math.max(0, Math.trunc(toNum(edge.building_hits, 0))) * 2;
  const totalPc = basePc + rightOfWayPc + demolitionPc;
  if (!_sandboxMode && _pc < totalPc) {
    return {
      success: false,
      message: `Need ${totalPc} PC (${basePc} base + ${rightOfWayPc} land + ${demolitionPc} demolition), have ${_pc}`,
      pc_cost: 0,
    };
  }

  edge.capacity = Math.max(edge.capacity + 240, Math.round(edge.capacity * 1.33));
  edge.t0_sec = Math.max(1, Math.round(edge.t0_sec * 0.91 * 100) / 100);
  edge.base_volume = Math.round(edge.base_volume * 1.07 * 100) / 100;
  edge.build_road_level = (edge.build_road_level ?? 0) + 1;

  if (!_sandboxMode) {
    _pc = Math.max(0, _pc - totalPc);
  }
  city.total_edits += 1;
  const unlockMessage = awardProgress(city, 1);

  const detail = `${rightOfWayPc} land + ${demolitionPc} demolition`;
  return {
    success: true,
    message: unlockMessage
      ? `Capacity upgraded on edge ${edgeId} (${detail}) | ${unlockMessage}`
      : `Capacity upgraded on edge ${edgeId} (${detail})`,
    pc_cost: _sandboxMode ? 0 : totalPc,
  };
}

// Backwards-compatible alias with previous UI naming.
export const demoBuildRoad = demoApplyCapacityUpgrade;

function isSmallRoad(highwayType: string): boolean {
  return (
    highwayType.startsWith("residential") ||
    highwayType.startsWith("unclassified") ||
    highwayType.startsWith("tertiary") ||
    highwayType.startsWith("service")
  );
}

export function demoDemolishRoad(edgeId: number): { success: boolean; message: string; pc_cost: number } {
  const city = getDemoCity();
  const idx = city.edges.findIndex((e) => e.edge_id === edgeId);
  if (idx < 0) return { success: false, message: `Edge ${edgeId} not found`, pc_cost: 0 };

  const edge = city.edges[idx];
  if (!isEdgeUnlocked(city, edge)) return { success: false, message: "Edge is outside unlocked district", pc_cost: 0 };
  if (!_sandboxMode && !isSmallRoad(edge.highway_type)) {
    return { success: false, message: "Challenge mode only allows demolition of smaller local roads", pc_cost: 0 };
  }

  const demolitionBasePc = 6 + Math.max(0, Math.trunc(edge.building_hits * 1.5));
  if (!_sandboxMode && _pc < demolitionBasePc) {
    return { success: false, message: `Need ${demolitionBasePc} PC, have ${_pc}`, pc_cost: 0 };
  }

  city.edges.splice(idx, 1);
  city.event_edge_ids = buildEventEdgeLookup(city.edges);
  city.total_edits += 1;
  const unlockMessage = awardProgress(city, 1);
  if (!_sandboxMode) {
    _pc = Math.max(0, _pc - demolitionBasePc);
  }

  return {
    success: true,
    message: unlockMessage ? `Road ${edgeId} demolished | ${unlockMessage}` : `Road ${edgeId} demolished`,
    pc_cost: _sandboxMode ? 0 : demolitionBasePc,
  };
}

export function demoBoostFrequency(routeId: string, newHeadway: number): { success: boolean; message: string; pc_cost: number } {
  const city = getDemoCity();
  const route = city.routes.find((r) => r.route_id === routeId);
  if (!route) return { success: false, message: `Route ${routeId} not found`, pc_cost: 0 };
  if (newHeadway >= route.headway_minutes) return { success: false, message: "New headway must be lower", pc_cost: 0 };

  route.headway_minutes = newHeadway;
  _pc = Math.max(0, _pc - 8);
  return { success: true, message: `Route ${routeId} headway → ${newHeadway} min`, pc_cost: 8 };
}

export function demoApplyCongestionPricing(edgeIds: number[], tollUsd: number): { success: boolean; message: string; pc_cost: number } {
  const city = getDemoCity();
  const elasticity = 0.3;
  const fraction = Math.min(1.0, tollUsd / 20.0);
  const reduction = elasticity * fraction;
  let count = 0;

  for (const edge of city.edges) {
    if (edgeIds.includes(edge.edge_id) && isEdgeUnlocked(city, edge)) {
      edge.base_volume *= (1 - reduction);
      count += 1;
    }
  }

  if (!_sandboxMode) {
    _pc = Math.max(0, _pc - 40);
  }
  return { success: true, message: `Pricing zone active on ${count} edges ($${tollUsd})`, pc_cost: _sandboxMode ? 0 : 40 };
}

// ── Snapshot generation ────────────────────────────────────────────────────

function bprTime(t0: number, vol: number, cap: number): number {
  const vc = Math.max(0, vol) / Math.max(1, cap);
  return t0 * (1 + ALPHA * Math.pow(vc, BETA));
}

function vcToHexColor(vc: number): string {
  if (vc <= 0.25) return "#4CAF50";
  if (vc <= 0.50) return "#FFC107";
  if (vc <= 0.75) return "#FF9800";
  if (vc <= 1.00) return "#F44336";
  return "#B71C1C";
}

function vcToLos(vc: number): "A" | "B" | "C" | "D" | "E" | "F" {
  if (vc <= 0.20) return "A";
  if (vc <= 0.44) return "B";
  if (vc <= 0.64) return "C";
  if (vc <= 0.85) return "D";
  if (vc <= 1.00) return "E";
  return "F";
}

function activeEventForHour(hour: number, stageIndex: number): SurgeEventDefinition | null {
  for (const event of SURGE_EVENTS) {
    if (stageIndex < event.min_stage) continue;
    if (hour >= event.start_hour && hour <= event.end_hour) return event;
  }
  return null;
}

function getUnlockedEdgeList(city: DemoCity): DemoEdge[] {
  return city.edges.filter((e) => isEdgeUnlocked(city, e));
}

function getUnlockedBuildingList(city: DemoCity): DemoBuilding[] {
  return city.buildings.filter((b) => isBuildingUnlocked(city, b));
}

function buildTrafficModelState(totalVehiclesPerHour: number): TrafficModelState {
  const representedTravelers = Math.max(1_200, Math.round(totalVehiclesPerHour * 1.26));
  const activeVehicleAgents = Math.max(400, Math.round(representedTravelers * 0.24));
  const representativeGroups = Math.max(80, Math.round(activeVehicleAgents / 22));
  const avgGroupSize = Math.max(1, Math.round((representedTravelers / representativeGroups) * 10) / 10);

  return {
    mode: "mesoscopic_representative_groups",
    represented_travelers: representedTravelers,
    active_vehicle_agents: activeVehicleAgents,
    representative_groups: representativeGroups,
    avg_group_size: avgGroupSize,
  };
}

function buildCampaignState(city: DemoCity, unlockedEdges: number, unlockedBuildings: number): CampaignStageState {
  const stageIndex = getStageIndex(city);
  const stage = STAGES[stageIndex];
  const next = STAGES[stageIndex + 1] ?? null;

  return {
    stage_index: stageIndex,
    stage_name: stage.name,
    unlocked_edges: unlockedEdges,
    unlocked_buildings: unlockedBuildings,
    next_stage_name: next?.name ?? null,
    progress_points: city.progress_points,
    next_stage_points: next?.unlock_points ?? null,
    expansion_ready: Boolean(next && city.progress_points >= next.unlock_points),
  };
}

export function buildDemoSnapshot(hour: number): SimSnapshot {
  const city = normalizeCity(getDemoCity());
  const rushMult = RUSH[hour] ?? 0.5;

  const unlockedEdges = getUnlockedEdgeList(city);
  const unlockedBuildings = getUnlockedBuildingList(city);

  const activeEventDef = activeEventForHour(hour, city.stage_index);
  const eventEdgeIds = activeEventDef ? (city.event_edge_ids[activeEventDef.id] ?? new Set<number>()) : new Set<number>();

  let totalCommute = 0;
  let totalVmt = 0;
  let totalVehicles = 0;
  let affectedVcSum = 0;
  let affectedCount = 0;

  const edges: EdgeState[] = unlockedEdges.map((e) => {
    const eventMult = activeEventDef && eventEdgeIds.has(e.edge_id) ? activeEventDef.demand_multiplier : 1;
    const vol = e.base_volume * rushMult * eventMult;
    const vc = vol / Math.max(1, e.capacity);
    const tt = bprTime(e.t0_sec, vol, e.capacity);

    totalCommute += tt;
    totalVehicles += vol;
    totalVmt += vol * 16 * 0.15;

    if (activeEventDef && eventEdgeIds.has(e.edge_id)) {
      affectedVcSum += vc;
      affectedCount += 1;
    }

    return {
      edge_id: e.edge_id,
      congestion_ratio: Math.round(vc * 1000) / 1000,
      travel_time_sec: Math.round(tt * 10) / 10,
      volume_veh_hr: Math.round(vol * 10) / 10,
      los: vcToLos(vc),
      has_bus_lane: e.has_bus_lane,
      lanes: e.lanes,
      color: vcToHexColor(vc),
      path: e.path,
      midpoint: e.midpoint,
      highway_type: e.highway_type,
      building_hits: e.building_hits,
      land_acquisition_pc: e.land_acquisition_pc,
      edit_level: e.build_road_level,
    };
  });

  const VEHICLE_CAP = 60;
  const LOAD = 0.35;
  let totalRidership = 0;
  const routes: RouteState[] = city.routes.map((r) => {
    const tripsPerHr = 60 / Math.max(1, r.headway_minutes);
    const ridership = tripsPerHr * 16 * VEHICLE_CAP * LOAD * rushMult;
    totalRidership += ridership;
    return {
      route_id: r.route_id,
      headway_minutes: r.headway_minutes,
      ridership_estimate: Math.round(ridership),
    };
  });

  let rewardClaimed = false;
  if (activeEventDef && affectedCount > 0) {
    const avgAffectedVc = affectedVcSum / Math.max(1, affectedCount);
    const rewardKey = `${activeEventDef.id}:${hour}`;
    const alreadyClaimed = city.reward_keys.has(rewardKey);
    if (!alreadyClaimed && avgAffectedVc <= activeEventDef.target_vc) {
      city.reward_keys.add(rewardKey);
      _pc += activeEventDef.reward_pc;
      rewardClaimed = true;
    } else {
      rewardClaimed = alreadyClaimed;
    }
  }

  const avgCommute = totalCommute / Math.max(1, edges.length) / 60;
  const equityAvg = unlockedEdges.reduce((s, e) => s + e.equity_weight, 0) / Math.max(1, unlockedEdges.length);

  const metrics: CityMetrics = {
    avg_commute_min: Math.round(avgCommute * 10) / 10,
    vmt_daily: Math.round(totalVmt),
    transit_ridership: Math.round(totalRidership),
    equity_score: Math.round(equityAvg * 1000) / 1000,
    co2_g_per_commuter_km: Math.round(180 * (1 - equityAvg * 0.3)),
    political_capital: _pc,
  };

  const activeEvent: ActiveEventState | null = activeEventDef
    ? {
      event_id: activeEventDef.id,
      title: activeEventDef.title,
      description: activeEventDef.description,
      affected_edges: affectedCount,
      demand_multiplier: activeEventDef.demand_multiplier,
      reward_pc: activeEventDef.reward_pc,
      reward_claimed: rewardClaimed,
    }
    : null;

  return {
    city_slug: DEMO_CITY,
    tick_hour: hour,
    edges,
    routes,
    buildings: unlockedBuildings,
    metrics,
    traffic_model: buildTrafficModelState(totalVehicles),
    campaign: buildCampaignState(city, unlockedEdges.length, unlockedBuildings.length),
    active_event: activeEvent,
  };
}
