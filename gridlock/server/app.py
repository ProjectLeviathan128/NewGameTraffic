"""
Gridlock Simulation Server

FastAPI app exposing:
  GET  /cities                        — list available cities
  POST /cities/{city}/load            — load a .gdlk city package
  GET  /cities/{city}/state           — current simulation snapshot
  POST /cities/{city}/time            — set in-game hour
  POST /cities/{city}/interventions/bus_lane
  POST /cities/{city}/interventions/frequency_boost
  POST /cities/{city}/interventions/congestion_pricing
  WS   /ws                            — real-time SimSnapshot stream (~1/sec)

Start with: uvicorn gridlock.server.app:app --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger(__name__)

app = FastAPI(
    title="Gridlock Simulation API",
    description="Real-world city transit simulation engine",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Lock down in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory state ────────────────────────────────────────────────────────
_city_packages: dict[str, Any] = {}       # city_slug → CityPackage
_sim_runners: dict[str, Any] = {}         # city_slug → SimulationRunner
_ws_clients: list[WebSocket] = []


# ── Models ─────────────────────────────────────────────────────────────────

class EdgeState(BaseModel):
    edge_id: int
    congestion_ratio: float
    travel_time_sec: float
    volume_veh_hr: float
    los: str
    has_bus_lane: bool
    color: str


class RouteState(BaseModel):
    route_id: str
    headway_minutes: float
    ridership_estimate: float


class CityMetrics(BaseModel):
    avg_commute_min: float
    vmt_daily: float
    transit_ridership: float
    equity_score: float
    co2_g_per_commuter_km: float
    political_capital: int


class SimSnapshot(BaseModel):
    city_slug: str
    tick_hour: int               # 0–23
    edges: list[EdgeState]
    routes: list[RouteState]
    metrics: CityMetrics


class LoadCityRequest(BaseModel):
    gdlk_path: str | None = None


class SetTimeRequest(BaseModel):
    hour: int                    # 0–23


class BusLaneRequest(BaseModel):
    edge_id: int


class FrequencyBoostRequest(BaseModel):
    route_id: str
    new_headway_min: float


class CongestionPricingRequest(BaseModel):
    node_ids: list[int]
    toll_usd: float = 5.0


class InterventionResponse(BaseModel):
    success: bool
    pc_cost: int
    message: str


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"service": "Gridlock Simulation API", "version": "0.1.0"}


@app.get("/cities")
async def list_cities():
    data_dir = Path(os.getenv("GRIDLOCK_DATA_DIR", "data")) / "output"
    cities = [p.stem for p in data_dir.glob("*.gdlk")] if data_dir.exists() else []
    return {"cities": cities}


@app.post("/cities/{city}/load")
async def load_city(city: str, req: LoadCityRequest | None = None):
    """Load a .gdlk package into memory and initialize the simulation runner."""
    from gridlock.gdlk_format import GdlkReader
    from gridlock.server.simulation_runner import SimulationRunner

    data_dir = Path(os.getenv("GRIDLOCK_DATA_DIR", "data")) / "output"
    gdlk_path = (req.gdlk_path if req and req.gdlk_path else None) or str(data_dir / f"{city}.gdlk")

    if not os.path.exists(gdlk_path):
        raise HTTPException(404, f"City package not found: {gdlk_path}")

    try:
        runner = SimulationRunner(gdlk_path)
        _sim_runners[city] = runner
        info = GdlkReader().read_header(gdlk_path)
        return {
            "loaded": city,
            "metadata": info["metadata"],
            "message": f"Simulation ready. Use ws://.../ws to subscribe.",
        }
    except Exception as e:
        log.exception(f"Failed to load {gdlk_path}")
        raise HTTPException(500, str(e))


@app.get("/cities/{city}/state", response_model=SimSnapshot)
async def get_state(city: str):
    runner = _get_runner(city)
    return runner.snapshot()


@app.post("/cities/{city}/time")
async def set_time(city: str, req: SetTimeRequest):
    runner = _get_runner(city)
    if not 0 <= req.hour <= 23:
        raise HTTPException(400, "hour must be 0–23")
    runner.set_hour(req.hour)
    return {"tick_hour": req.hour}


# ── Interventions ──────────────────────────────────────────────────────────

@app.post("/cities/{city}/interventions/bus_lane", response_model=InterventionResponse)
async def intervention_bus_lane(city: str, req: BusLaneRequest):
    from gridlock.simulation.interventions import convert_to_bus_lane
    runner = _get_runner(city)
    try:
        graph, net, pc = convert_to_bus_lane(runner.road_graph, req.edge_id, runner.transit_network)
        runner.road_graph = graph
        runner.transit_network = net
        runner.political_capital -= pc
        await _broadcast_snapshot(city, runner)
        return InterventionResponse(success=True, pc_cost=pc,
                                    message=f"Bus lane added to edge {req.edge_id}")
    except (KeyError, ValueError) as e:
        return InterventionResponse(success=False, pc_cost=0, message=str(e))


@app.post("/cities/{city}/interventions/frequency_boost", response_model=InterventionResponse)
async def intervention_frequency_boost(city: str, req: FrequencyBoostRequest):
    from gridlock.simulation.interventions import boost_frequency
    runner = _get_runner(city)
    try:
        net, pc = boost_frequency(runner.transit_network, req.route_id, req.new_headway_min)
        runner.transit_network = net
        runner.political_capital -= pc
        await _broadcast_snapshot(city, runner)
        return InterventionResponse(success=True, pc_cost=pc,
                                    message=f"Route {req.route_id!r} headway → {req.new_headway_min} min")
    except (KeyError, ValueError) as e:
        return InterventionResponse(success=False, pc_cost=0, message=str(e))


@app.post("/cities/{city}/interventions/congestion_pricing", response_model=InterventionResponse)
async def intervention_congestion_pricing(city: str, req: CongestionPricingRequest):
    from gridlock.simulation.interventions import apply_congestion_pricing
    runner = _get_runner(city)
    try:
        graph, pc = apply_congestion_pricing(runner.road_graph, req.node_ids, req.toll_usd)
        runner.road_graph = graph
        runner.political_capital -= pc
        await _broadcast_snapshot(city, runner)
        return InterventionResponse(success=True, pc_cost=pc,
                                    message=f"Congestion pricing zone active (${req.toll_usd:.2f})")
    except Exception as e:
        return InterventionResponse(success=False, pc_cost=0, message=str(e))


# ── WebSocket ──────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Real-time simulation feed. Sends SimSnapshot JSON every second.
    Accepts JSON messages to set target city: {"city": "portland"}
    """
    await ws.accept()
    _ws_clients.append(ws)
    city = os.getenv("GRIDLOCK_CITY", "")

    try:
        async def tick_loop():
            while True:
                if city in _sim_runners:
                    runner = _sim_runners[city]
                    snap = runner.snapshot()
                    await ws.send_text(snap.model_dump_json())
                await asyncio.sleep(1.0)

        tick_task = asyncio.create_task(tick_loop())
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
                if "city" in data:
                    city = data["city"]
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.remove(ws)
        tick_task.cancel()


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_runner(city: str):
    if city not in _sim_runners:
        raise HTTPException(
            404,
            f"City {city!r} not loaded. POST /cities/{city}/load first."
        )
    return _sim_runners[city]


async def _broadcast_snapshot(city: str, runner: Any) -> None:
    if not _ws_clients:
        return
    snap = runner.snapshot()
    payload = snap.model_dump_json()
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)
