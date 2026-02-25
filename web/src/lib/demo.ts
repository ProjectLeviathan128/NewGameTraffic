/**
 * Demo/static mode for GitHub Pages.
 *
 * Priority order:
 * 1) Load bundled real Portland OSM + TriMet snapshot from /public/data.
 * 2) If unavailable, fall back to a synthetic local grid so the app still runs.
 */

import { CityMetrics, EdgeState, RouteState, SimSnapshot } from "@/types/simulation";

const DEMO_CITY = "portland";
const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
const REAL_DATA_URL = `${BASE_PATH}/data/portland_real_osm.json`;

// BPR constants
const ALPHA = 0.15;
const BETA = 4;

// Rush-hour multipliers (matches Python server profile)
const RUSH: Record<number, number> = {
  0: 0.20, 1: 0.15, 2: 0.15, 3: 0.15, 4: 0.20, 5: 0.40,
  6: 0.60, 7: 0.85, 8: 1.00, 9: 0.90, 10: 0.70, 11: 0.65,
  12: 0.70, 13: 0.65, 14: 0.70, 15: 0.80, 16: 0.95, 17: 1.00,
  18: 0.90, 19: 0.75, 20: 0.60, 21: 0.50, 22: 0.40, 23: 0.30,
};

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
}

export interface DemoRoute {
  route_id: string;
  short_name: string;
  headway_minutes: number;
  stop_count: number;
}

interface DemoCity {
  edges: DemoEdge[];
  routes: DemoRoute[];
  pc: number;
}

// Singleton city instance — loaded once, mutated by interventions
let _city: DemoCity | null = null;
let _loadPromise: Promise<void> | null = null;
let _pc = 100;

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

function midPoint(path: [number, number][]): [number, number] {
  return path[Math.floor(path.length / 2)];
}

async function loadRealDemoCity(): Promise<DemoCity> {
  const res = await fetch(REAL_DATA_URL, { cache: "force-cache" });
  if (!res.ok) {
    throw new Error(`Failed to load static Portland data (${res.status})`);
  }

  const payload = (await res.json()) as {
    edges?: unknown[];
    routes?: unknown[];
    political_capital?: number;
  };

  const edgesRaw = Array.isArray(payload.edges) ? payload.edges : [];
  const edges: DemoEdge[] = [];

  for (const raw of edgesRaw) {
    const edge = raw as Record<string, unknown>;
    const path = sanitizePath(edge.path);
    if (!path) continue;

    const midpointRaw = sanitizePath([edge.midpoint, edge.midpoint]);
    const midpoint = midpointRaw ? midpointRaw[0] : midPoint(path);

    edges.push({
      edge_id: Math.trunc(toNum(edge.edge_id, edges.length + 1)),
      path,
      midpoint,
      highway_type: String(edge.highway_type ?? "unclassified"),
      lanes: Math.max(1, Math.trunc(toNum(edge.lanes, 1))),
      t0_sec: Math.max(1, toNum(edge.t0_sec, 30)),
      capacity: Math.max(120, Math.trunc(toNum(edge.capacity, 800))),
      base_volume: Math.max(0, toNum(edge.base_volume, 320)),
      has_bus_lane: Boolean(edge.has_bus_lane),
      equity_weight: Math.max(0, Math.min(1, toNum(edge.equity_weight, 0.6))),
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

  return {
    edges,
    routes,
    pc: Math.max(0, Math.trunc(toNum(payload.political_capital, 100))),
  };
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
  for (let row = 0; row <= GRID_ROWS; row++) {
    for (let col = 0; col < GRID_COLS; col++) {
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
        t0_sec: (lengthM / (speedKph / 3.6)),
        capacity: cap,
        base_volume: cap * baseVcRatio,
        has_bus_lane: false,
        equity_weight: 0.45 + ((eid * 37) % 50) / 100,
      });
      eid += 1;
    }
  }

  // Vertical edges
  for (let col = 0; col <= GRID_COLS; col++) {
    for (let row = 0; row < GRID_ROWS; row++) {
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
        t0_sec: (lengthM / (speedKph / 3.6)),
        capacity: cap,
        base_volume: cap * baseVcRatio,
        has_bus_lane: false,
        equity_weight: 0.45 + ((eid * 53) % 50) / 100,
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

  return { edges, routes, pc: 100 };
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
}

// ── Apply interventions (client-side) ─────────────────────────────────────

export function demoApplyBusLane(edgeId: number): { success: boolean; message: string; pc_cost: number } {
  const city = getDemoCity();
  const edge = city.edges.find((e) => e.edge_id === edgeId);
  if (!edge) return { success: false, message: `Edge ${edgeId} not found`, pc_cost: 0 };
  if (edge.has_bus_lane) return { success: false, message: "Already has bus lane", pc_cost: 0 };
  if (edge.lanes <= 1) return { success: false, message: "Only 1 lane — cannot convert", pc_cost: 0 };

  edge.lanes -= 1;
  edge.capacity = Math.max(120, Math.round(edge.capacity * edge.lanes / (edge.lanes + 1)));
  edge.has_bus_lane = true;
  _pc = Math.max(0, _pc - 15);
  return { success: true, message: `Bus lane added to edge ${edgeId}`, pc_cost: 15 };
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
    if (edgeIds.includes(edge.edge_id)) {
      edge.base_volume *= (1 - reduction);
      count += 1;
    }
  }

  _pc = Math.max(0, _pc - 40);
  return { success: true, message: `Pricing zone active on ${count} edges ($${tollUsd})`, pc_cost: 40 };
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

export function buildDemoSnapshot(hour: number): SimSnapshot {
  const city = getDemoCity();
  const mult = RUSH[hour] ?? 0.5;

  let totalCommute = 0;
  let totalVmt = 0;

  const edges: EdgeState[] = city.edges.map((e) => {
    const vol = e.base_volume * mult;
    const vc = vol / Math.max(1, e.capacity);
    const tt = bprTime(e.t0_sec, vol, e.capacity);
    totalCommute += tt;
    totalVmt += vol * 16 * 0.15; // rough km proxy

    return {
      edge_id: e.edge_id,
      congestion_ratio: Math.round(vc * 1000) / 1000,
      travel_time_sec: Math.round(tt * 10) / 10,
      volume_veh_hr: Math.round(vol * 10) / 10,
      los: vcToLos(vc),
      has_bus_lane: e.has_bus_lane,
      color: vcToHexColor(vc),
      path: e.path,
      midpoint: e.midpoint,
      highway_type: e.highway_type,
    };
  });

  const VEHICLE_CAP = 60;
  const LOAD = 0.35;
  let totalRidership = 0;
  const routes: RouteState[] = city.routes.map((r) => {
    const tripsPerHr = 60 / Math.max(1, r.headway_minutes);
    const ridership = tripsPerHr * 16 * VEHICLE_CAP * LOAD * mult;
    totalRidership += ridership;
    return {
      route_id: r.route_id,
      headway_minutes: r.headway_minutes,
      ridership_estimate: Math.round(ridership),
    };
  });

  const avgCommute = totalCommute / Math.max(1, edges.length) / 60;
  const equityAvg = city.edges.reduce((s, e) => s + e.equity_weight, 0) / Math.max(1, city.edges.length);

  const metrics: CityMetrics = {
    avg_commute_min: Math.round(avgCommute * 10) / 10,
    vmt_daily: Math.round(totalVmt),
    transit_ridership: Math.round(totalRidership),
    equity_score: Math.round(equityAvg * 1000) / 1000,
    co2_g_per_commuter_km: Math.round(180 * (1 - equityAvg * 0.3)),
    political_capital: _pc,
  };

  return {
    city_slug: DEMO_CITY,
    tick_hour: hour,
    edges,
    routes,
    metrics,
  };
}
