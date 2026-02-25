"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useSimulation } from "@/hooks/useSimulation";
import MetricsDashboard from "@/components/MetricsDashboard";
import HUD from "@/components/HUD";
import ToolPalette from "@/components/ToolPalette";
import { InterventionTool, OverlayMode } from "@/types/simulation";
import {
  RoadEditPreview,
  demoApplyCapacityUpgrade,
  demoCommitRoadNodeMove,
  demoDemolishRoad,
  demoPreviewRoadNodeMove,
  getDemoBoundsForStage,
  getDemoViewStateForStage,
  setDemoSandboxMode,
} from "@/lib/demo";

// CityMap uses WebGL — must be client-only, no SSR
const CityMap = dynamic(() => import("@/components/CityMap"), { ssr: false });

const STARTUP_CITY = "portland";
// GitHub Pages build is fully static/demo; keep this deterministic client/server.
const IS_DEMO = true;

export default function GridlockApp() {
  const { snapshot, connected, error, refreshDemoSnapshot, advanceDemoTime } = useSimulation(STARTUP_CITY);
  const [overlayMode, setOverlayMode] = useState<OverlayMode>("congestion");
  const [activeTool, setActiveTool] = useState<InterventionTool>("road_edit");
  const [selectedEdgeId, setSelectedEdgeId] = useState<number | null>(null);
  const [notification, setNotification] = useState<string | null>(null);
  const [sandboxMode, setSandboxMode] = useState(false);
  const [roadEditPreview, setRoadEditPreview] = useState<RoadEditPreview | null>(null);

  const selectedEdge = useMemo(
    () => (selectedEdgeId === null ? null : (snapshot?.edges ?? []).find((e) => e.edge_id === selectedEdgeId) ?? null),
    [selectedEdgeId, snapshot?.edges],
  );

  const stageIndex = snapshot?.campaign?.stage_index ?? 0;
  const stageView = useMemo(() => getDemoViewStateForStage(stageIndex), [stageIndex]);
  const stageBounds = useMemo(() => getDemoBoundsForStage(stageIndex), [stageIndex]);

  useEffect(() => {
    if (activeTool !== "road_edit") {
      setRoadEditPreview(null);
    }
    if (activeTool === null) {
      setSelectedEdgeId(null);
    }
  }, [activeTool]);

  useEffect(() => {
    if (!IS_DEMO) return;
    setDemoSandboxMode(sandboxMode);
    refreshDemoSnapshot();
    if (sandboxMode) {
      setNotification("✓ Sandbox mode on (unlimited budget + unrestricted demolition)");
      setTimeout(() => setNotification(null), 2600);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sandboxMode]);

  useEffect(() => {
    // Stage unlock should clear stale drag previews and force a fresh edge selection pass.
    setRoadEditPreview(null);
  }, [stageIndex]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.render_game_to_text = () => {
      const payload = {
        coordinate_system: "lon/lat WGS84, +lon east, +lat north",
        hour: snapshot?.tick_hour ?? 0,
        stage: snapshot?.campaign?.stage_name ?? "Unknown",
        stage_index: snapshot?.campaign?.stage_index ?? 0,
        progress_points: snapshot?.campaign?.progress_points ?? 0,
        next_stage_points: snapshot?.campaign?.next_stage_points ?? null,
        tool: activeTool,
        sandbox_mode: sandboxMode,
        selected_edge_id: selectedEdgeId,
        road_edit_preview: roadEditPreview
          ? {
            edge_id: roadEditPreview.edge_id,
            endpoint: roadEditPreview.endpoint,
            building_hits: roadEditPreview.building_hits,
            edit_pc_cost: roadEditPreview.edit_pc_cost,
          }
          : null,
        metrics: snapshot?.metrics ?? null,
        traffic_model: snapshot?.traffic_model ?? null,
        active_event: snapshot?.active_event ?? null,
      };
      return JSON.stringify(payload, null, 2);
    };

    window.advanceTime = async (ms: number) => {
      advanceDemoTime(ms);
    };

    return () => {
      delete window.render_game_to_text;
      delete window.advanceTime;
    };
  }, [snapshot, activeTool, selectedEdgeId, roadEditPreview, sandboxMode, advanceDemoTime]);

  const handleIntervention = (result: { success: boolean; message: string; pc_cost: number }) => {
    setNotification(
      result.success
        ? `✓ ${result.message}${result.pc_cost > 0 ? ` (−${result.pc_cost} PC)` : ""}`
        : `✗ ${result.message}`,
    );
    setTimeout(() => setNotification(null), 4200);
  };

  const handleApplyCapacityUpgrade = () => {
    if (!selectedEdgeId || !IS_DEMO) return;
    const result = demoApplyCapacityUpgrade(selectedEdgeId);
    handleIntervention(result);
    refreshDemoSnapshot();
  };

  const handleDemolishRoad = () => {
    if (!selectedEdgeId || !IS_DEMO) return;
    const result = demoDemolishRoad(selectedEdgeId);
    if (result.success) {
      setSelectedEdgeId(null);
      setRoadEditPreview(null);
    }
    handleIntervention(result);
    refreshDemoSnapshot();
  };

  const handleRoadEditPreview = (
    edgeId: number,
    endpoint: "start" | "end",
    coordinate: [number, number],
  ) => {
    if (!IS_DEMO || activeTool !== "road_edit") return;
    setSelectedEdgeId(edgeId);
    const preview = demoPreviewRoadNodeMove(edgeId, endpoint, coordinate);
    setRoadEditPreview(preview);
  };

  const handleRoadEditCommit = (
    edgeId: number,
    endpoint: "start" | "end",
    coordinate: [number, number],
  ) => {
    if (!IS_DEMO || activeTool !== "road_edit") return;
    const result = demoCommitRoadNodeMove(edgeId, endpoint, coordinate);
    if (result.preview) {
      setRoadEditPreview(result.preview);
    }
    handleIntervention(result);
    refreshDemoSnapshot();
    if (result.success) {
      setRoadEditPreview(null);
    }
  };

  return (
    <main className="gridlock-main">
      {IS_DEMO && (
        <div className="demo-banner">
          Static mode — real Portland OSM + PBOT traffic counts + OSM building meshes with demolition-aware road costs.
        </div>
      )}

      <HUD
        cityName="Portland Campaign"
        stageName={snapshot?.campaign?.stage_name ?? "Pilot District"}
        tickHour={snapshot?.tick_hour ?? 8}
        metrics={snapshot?.metrics ?? null}
        connected={connected}
        sandboxMode={sandboxMode}
      />

      <div className={`map-container${IS_DEMO ? " has-demo-banner" : ""}`}>
        {error ? (
          <div className="error-overlay">
            <h2>Connection Error</h2>
            <p>{error}</p>
            <p>Make sure the Gridlock server is running:</p>
            <code>gridlock serve {STARTUP_CITY}</code>
          </div>
        ) : (
          <CityMap
            key={`stage-${stageIndex}`}
            edges={snapshot?.edges ?? []}
            routes={snapshot?.routes ?? []}
            buildings={snapshot?.buildings ?? []}
            overlayMode={overlayMode}
            selectedEdgeId={selectedEdgeId}
            roadEditEnabled={activeTool === "road_edit"}
            roadEditPreview={roadEditPreview}
            conflictBuildingIds={roadEditPreview?.building_ids ?? []}
            onEdgeClick={activeTool === null ? undefined : setSelectedEdgeId}
            onRoadNodePreview={handleRoadEditPreview}
            onRoadNodeCommit={handleRoadEditCommit}
            initialViewState={stageView}
            bounds={stageBounds}
          />
        )}
      </div>

      <div className="left-panel">
        <MetricsDashboard
          metrics={snapshot?.metrics ?? null}
          tickHour={snapshot?.tick_hour ?? 8}
          cityName="Portland"
          trafficModel={snapshot?.traffic_model ?? null}
          campaign={snapshot?.campaign ?? null}
          activeEvent={snapshot?.active_event ?? null}
        />
        <div className="overlay-selector">
          <p>Overlay</p>
          {(["congestion"] as OverlayMode[]).map((m) => (
            <button
              key={m}
              className={overlayMode === m ? "active" : ""}
              onClick={() => setOverlayMode(m)}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div className="right-panel">
        <ToolPalette
          activeTool={activeTool}
          onSelectTool={setActiveTool}
          selectedEdgeId={selectedEdgeId}
          selectedEdge={selectedEdge}
          sandboxMode={sandboxMode}
          onToggleSandbox={setSandboxMode}
          roadEditPreview={roadEditPreview}
          onApplyCapacityUpgrade={handleApplyCapacityUpgrade}
          onDemolishRoad={handleDemolishRoad}
        />
      </div>

      {notification && (
        <div className={`notification ${notification.startsWith("✓") ? "success" : "error"}`}>
          {notification}
        </div>
      )}
    </main>
  );
}
