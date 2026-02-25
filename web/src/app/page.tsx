"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useSimulation } from "@/hooks/useSimulation";
import MetricsDashboard from "@/components/MetricsDashboard";
import HUD from "@/components/HUD";
import ToolPalette from "@/components/ToolPalette";
import { OverlayMode, InterventionTool } from "@/types/simulation";
import {
  demoApplyBusLane,
  demoBoostFrequency,
  demoApplyCongestionPricing,
} from "@/lib/demo";

// CityMap uses WebGL — must be client-only, no SSR
const CityMap = dynamic(() => import("@/components/CityMap"), { ssr: false });

const STARTUP_CITY = "portland";
const IS_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export default function GridlockApp() {
  const { snapshot, connected, error } = useSimulation(STARTUP_CITY);
  const [overlayMode, setOverlayMode] = useState<OverlayMode>("congestion");
  const [activeTool, setActiveTool] = useState<InterventionTool>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<number | null>(null);
  const [notification, setNotification] = useState<string | null>(null);

  const handleIntervention = (result: { success: boolean; message: string; pc_cost: number }) => {
    setNotification(
      result.success
        ? `✓ ${result.message} (−${result.pc_cost} PC)`
        : `✗ ${result.message}`
    );
    setTimeout(() => setNotification(null), 4000);
  };

  // In demo mode, intercept interventions and apply them client-side
  const handleDemoIntervention = (tool: InterventionTool, edgeId: number | null) => {
    if (!IS_DEMO || edgeId === null) return;
    let result: { success: boolean; message: string; pc_cost: number };
    if (tool === "bus_lane") {
      result = demoApplyBusLane(edgeId);
    } else if (tool === "congestion_pricing") {
      result = demoApplyCongestionPricing([edgeId], 5.0);
    } else {
      result = { success: false, message: "Use the full server for this intervention", pc_cost: 0 };
    }
    handleIntervention(result);
  };

  return (
    <main className="gridlock-main">
      {/* Demo mode banner */}
      {IS_DEMO && (
        <div className="demo-banner">
          Static mode — real Portland OSM + TriMet snapshot bundled for GitHub Pages.
        </div>
      )}

      {/* Top HUD bar */}
      <HUD
        cityName="Portland, OR"
        tickHour={snapshot?.tick_hour ?? 8}
        metrics={snapshot?.metrics ?? null}
        connected={connected}
      />

      {/* 3D city map — full screen */}
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
            edges={snapshot?.edges ?? []}
            routes={snapshot?.routes ?? []}
            overlayMode={overlayMode}
            onEdgeClick={IS_DEMO
              ? (id) => { setSelectedEdgeId(id); handleDemoIntervention(activeTool, id); }
              : setSelectedEdgeId
            }
          />
        )}
      </div>

      {/* Left panel — metrics */}
      <div className="left-panel">
        <MetricsDashboard
          metrics={snapshot?.metrics ?? null}
          tickHour={snapshot?.tick_hour ?? 8}
          cityName="Portland"
        />
        <div className="overlay-selector">
          <p>Overlay</p>
          {(["congestion", "transit", "equity", "emissions"] as OverlayMode[]).map((m) => (
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

      {/* Right panel — tools */}
      <div className="right-panel">
        <ToolPalette
          activeTool={activeTool}
          onSelectTool={setActiveTool}
          selectedEdgeId={selectedEdgeId}
          city={STARTUP_CITY}
          onIntervention={handleIntervention}
        />
      </div>

      {/* Notification toast */}
      {notification && (
        <div className={`notification ${notification.startsWith("✓") ? "success" : "error"}`}>
          {notification}
        </div>
      )}
    </main>
  );
}
