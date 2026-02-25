"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useSimulation } from "@/hooks/useSimulation";
import MetricsDashboard from "@/components/MetricsDashboard";
import HUD from "@/components/HUD";
import ToolPalette from "@/components/ToolPalette";
import { OverlayMode, InterventionTool } from "@/types/simulation";

// CityMap uses WebGL — must be client-only, no SSR
const CityMap = dynamic(() => import("@/components/CityMap"), { ssr: false });

const DEFAULT_CITY = process.env.NEXT_PUBLIC_DEFAULT_CITY ?? "portland";

export default function GridlockApp() {
  const { snapshot, connected, error } = useSimulation(DEFAULT_CITY);
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

  return (
    <main className="gridlock-main">
      {/* Top HUD bar */}
      <HUD
        cityName="Portland, OR"
        tickHour={snapshot?.tick_hour ?? 8}
        metrics={snapshot?.metrics ?? null}
        connected={connected}
      />

      {/* 3D city map — full screen */}
      <div className="map-container">
        {error ? (
          <div className="error-overlay">
            <h2>Connection Error</h2>
            <p>{error}</p>
            <p>Make sure the Gridlock server is running:</p>
            <code>gridlock serve {DEFAULT_CITY}</code>
          </div>
        ) : (
          <CityMap
            edges={snapshot?.edges ?? []}
            routes={snapshot?.routes ?? []}
            overlayMode={overlayMode}
            onEdgeClick={setSelectedEdgeId}
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
          city={DEFAULT_CITY}
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
