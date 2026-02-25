const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function loadCity(city: string): Promise<void> {
  const res = await fetch(`${API_BASE}/cities/${city}/load`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to load city: ${await res.text()}`);
}

export async function setSimTime(city: string, hour: number): Promise<void> {
  const res = await fetch(`${API_BASE}/cities/${city}/time`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hour }),
  });
  if (!res.ok) throw new Error(`Failed to set time: ${await res.text()}`);
}

export async function applyBusLane(city: string, edgeId: number) {
  const res = await fetch(`${API_BASE}/cities/${city}/interventions/bus_lane`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edge_id: edgeId }),
  });
  return res.json();
}

export async function applyFrequencyBoost(
  city: string,
  routeId: string,
  newHeadwayMin: number
) {
  const res = await fetch(`${API_BASE}/cities/${city}/interventions/frequency_boost`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ route_id: routeId, new_headway_min: newHeadwayMin }),
  });
  return res.json();
}

export async function applyCongestionPricing(
  city: string,
  nodeIds: number[],
  tollUsd: number
) {
  const res = await fetch(`${API_BASE}/cities/${city}/interventions/congestion_pricing`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_ids: nodeIds, toll_usd: tollUsd }),
  });
  return res.json();
}

export function createWebSocket(onMessage: (snap: import("@/types/simulation").SimSnapshot) => void) {
  const ws_url = (API_BASE.replace(/^http/, "ws")) + "/ws";
  const ws = new WebSocket(ws_url);
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data));
    } catch (err) {
      console.error("WS parse error", err);
    }
  };
  return ws;
}
