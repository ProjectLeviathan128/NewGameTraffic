# Gridlock — Post-MVP Roadmap

Phase 0 delivered the core pipeline (OSM → GTFS → BPR → .gdlk) and a working
web simulation loop. This document tracks what comes next, organized by phase
and priority. Each item includes the concrete library or approach to use, based
on research validation.

---

## Phase 1 — Fidelity (Weeks 7–14)

Goal: Replace Phase 0 approximations with production-grade models.
Portland should be playable and produce results a traffic engineer would believe.

### 1.1 User-Equilibrium Traffic Assignment (AequilibraE)

**Replaces**: all-or-nothing assignment in `pipeline/congestion.py`

AequilibraE v1.5.0 implements biconjugate Frank-Wolfe (BFW), the fastest
converging link-based UE algorithm in practice. Confirmed at Portland scale:
157 TAZs, 8,245 nodes, 31,939 links.

**Integration approach** — AequilibraE does NOT accept a NetworkX graph directly.
Use their native OSM importer:

```python
from aequilibrae import Project
project = Project()
project.new("data/processed/portland_aeq")
project.network.create_from_osm(
    west=-122.836, east=-122.472, south=45.432, north=45.653
)
project.close()
```

Then run Frank-Wolfe assignment from the computed OD matrix.
After convergence, back-map link volumes onto our `RoadEdge.volume_veh_hr`.

**File**: create `gridlock/pipeline/assignment.py`

---

### 1.2 Multi-Modal Travel Time Matrix (r5py)

**Replaces**: gravity-model OD estimation in `pipeline/od_matrix.py`

r5py wraps Conveyal's R5 engine for all-to-all multimodal routing
(car + transit + walk). Requires OSM .pbf + GTFS zip.

```python
import r5py
transport_network = r5py.TransportNetwork(
    "data/raw/osm/portland.osm.pbf",
    ["data/raw/gtfs/portland_gtfs.zip"],
)
travel_times = r5py.TravelTimeMatrixComputer(
    transport_network,
    origins=origins_gdf,
    destinations=destinations_gdf,
    departure=datetime(2024, 10, 1, 8, 0),
    transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK],
).compute_travel_times()
```

Note: AGPL-3.0 license — r5py is a pipeline-only tool (not shipped in the game
binary), so AGPL is acceptable.

**File**: replace `gridlock/pipeline/od_matrix.py`

---

### 1.3 UXsim + r5py Coupled Simulation (Server Tick)

**Replaces**: BPR-only hourly tick in `server/simulation_runner.py`

UXsim is a pure-Python mesoscopic simulator (Kinematic Wave / Newell's X-model).
Confirmed performance: ~60,000 vehicles on a 10×10 km grid in 30 seconds.
**Critical gotcha**: UXsim has NO native GTFS support. Transit ridership must
come from r5py travel time matrices, not UXsim.

Coupling strategy:
- UXsim handles road vehicle simulation (cars)
- r5py handles transit accessibility and ridership estimation
- Server tick fuses both into SimSnapshot

```python
# In simulation_runner.py
import uxsim
sim = uxsim.World(...)
# Load road network from RoadGraph
# Feed OD demand from r5py travel_time matrix
sim.exec_simulation()
```

**File**: `gridlock/server/simulation_runner.py` — add UXsim loader

---

### 1.4 Real OSM Edge Geometry in the Frontend

**Replaces**: straight-line edges in `web/src/components/CityMap.tsx`

The Python server already stores edge polyline geometry in osmnx. Export it
in the .gdlk file as a GeoJSON section, then serve it via a new endpoint:
`GET /cities/{city}/geometry` → returns edge GeoJSON.

**Frontend optimization** (from deck.gl performance research):
- Use **MapLibre native LineLayer** for the static road network (much faster
  than deck.gl PathLayer for 100K+ edges at 60fps)
- Keep deck.gl **PathLayer** only for the dynamic congestion overlay (updates
  at 1 Hz with fresh V/C ratios)
- Use binary GeoJSON format (`geojsonToBinary()`) for deck.gl layers

```typescript
// MapLibre for static road geometry (fast, no re-render on data update)
map.addLayer({ id: "roads", type: "line", source: "osm-roads" });

// deck.gl overlay for live congestion coloring (updates 1x/sec)
new PathLayer({ data: liveEdges, getColor: vcToColor });
```

**Files**: `web/src/components/CityMap.tsx`, `gridlock/server/app.py`

---

### 1.5 .gdlk Edge Geometry Section

**Adds**: compressed polyline geometry to the .gdlk binary

Add `SEC_GEOMETRY = 0x0A` to `gdlk_format.py`:
- Stores per-edge coordinate arrays as packed float32 pairs
- zlib-compress this section (geometry dominates file size)

---

### 1.6 More Cities

Each city needs a `cities/<slug>.yaml` config.
Priority order based on transit system size and data availability:

| City       | GTFS Source       | OSM Quality | Priority |
|------------|-------------------|-------------|----------|
| Seattle    | King County Metro | Excellent   | High     |
| Denver     | RTD               | Excellent   | High     |
| Minneapolis| Metro Transit     | Good        | Medium   |
| Houston    | METRO             | Good        | Medium   |
| Austin     | Capital Metro     | Good        | Medium   |

All have open GTFS feeds. Add `gridlock build seattle` as next target after Portland.

---

### 1.7 Scenario System (Undo / Compare)

**Replaces**: single mutable game state in `SimulationRunner`

Add a scenario stack:
```python
class SimulationRunner:
    def push_scenario(self, name: str): ...   # snapshot current state
    def pop_scenario(self): ...               # revert to last snapshot
    def compare_scenarios(self, a, b): ...   # diff two SimSnapshots
```

REST API: `POST /cities/{city}/scenarios/push`, `POST /pop`, `GET /compare`

Frontend: Add "Undo" button (pops scenario), "Compare" mode (side-by-side metrics diff).

---

## Phase 2 — Game Loop (Months 4–6)

### 2.1 Event System

Political and operational events fire on a schedule:
- Sporting events → spike traffic on specific corridors
- City council vote → PC swing ±20
- Severe weather → reduce road capacities 20%
- New employment center opens → OD matrix shift

```python
@dataclass
class GameEvent:
    event_id: str
    title: str
    description: str
    trigger_hour: int
    effects: list[dict]  # e.g. [{"type": "capacity_mult", "edge_ids": [...], "value": 0.8}]
```

Events are city-specific JSON files in `cities/portland_events.json`.

### 2.2 Budget System

Replace the simple PC meter with a full budget:
- Operating budget ($/year) — paid for by ridership fare revenue + city tax
- Capital budget ($/year) — one-time infrastructure spending
- Debt financing — borrow against future revenue (high PC cost)
- Federal grants — unlock with certain equity score thresholds

### 2.3 Transit Schedule Editor

Let players design routes and stops, not just tweak headways:
- Draw new route on the map (click-to-add stops)
- The pipeline computes the new GTFS stop sequence + travel times
- r5py recalculates downstream travel time matrix

### 2.4 Campaign Mode

- 5 cities, each with a transit crisis to solve (Portland: I-5 bridge; Seattle: SR-99; etc.)
- Each city has a target CommutScore (avg_commute_min + equity_score × weight)
- Victory condition: reach CommutScore within N in-game days and budget

---

## Phase 3 — Polish & Launch (Months 7–12)

### 3.1 Steam / itch.io Release
- Switch GitHub Pages demo to full Electron wrapper (desktop app)
- OR keep web-only and launch on itch.io (no Steam cut)
- Consider Tauri (Rust-based Electron alternative) for smaller bundle

### 3.2 Multiplayer / Co-op
- Two mayors, same city, competing budgets
- Cooperative: one manages roads, one manages transit

### 3.3 Accessibility & Mobile
- Touch controls for tablet (deck.gl supports touch)
- High-contrast mode for colorblind users (replace LOS color palette)
- Screen reader labels on metrics dashboard

### 3.4 Mod Support
- `cities/<slug>.yaml` + custom events JSON is already the mod format
- Expose a Python SDK: `from gridlock.sdk import CityBuilder`
- Workshop-style upload via GitHub Releases or itch.io

---

## Technical Debt / Cleanup (Ongoing)

| Item | Priority | Notes |
|------|----------|-------|
| AequilibraE OSM import replaces osmnx | High | Better perf + UE assignment |
| Actual TMC spatial join for NPMRDS | Medium | Name-based matching is Phase 0 |
| `.gdlk` flat binary edge geometry | Medium | Currently no geometry section |
| Pytest integration tests (requires OSM download) | Medium | Mark as `@pytest.mark.integration` |
| Type stubs for deck.gl 9 (incomplete upstream) | Low | Cast to `any` workaround for now |
| `gridlock/cli/__init__.py` is empty (dead) | Low | Remove or consolidate with `gridlock/cli.py` |

---

## Immediate Next Issues to File

1. **`#1` AequilibraE integration** — `gridlock/pipeline/assignment.py`
2. **`#2` Edge geometry in .gdlk** — `SEC_GEOMETRY = 0x0A`
3. **`#3` MapLibre road geometry layer** — replace deck.gl PathLayer for static roads
4. **`#4` UXsim server tick** — replace BPR-only hourly mult
5. **`#5` r5py OD matrix** — replace gravity model
6. **`#6` Seattle city config** — second city
7. **`#7` Scenario push/pop/compare** — undo system
8. **`#8` Event system** — `GameEvent` dataclass + Portland event pack
