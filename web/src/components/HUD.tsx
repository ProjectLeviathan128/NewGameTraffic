"use client";

import { CityMetrics } from "@/types/simulation";
import { formatHour } from "@/lib/colors";

interface Props {
  cityName: string;
  tickHour: number;
  metrics: CityMetrics | null;
  connected: boolean;
}

export default function HUD({ cityName, tickHour, metrics, connected }: Props) {
  return (
    <div className="hud-topbar">
      <div className="hud-city">{cityName}</div>
      <div className="hud-time">{formatHour(tickHour)}</div>
      <div className="hud-pc">
        PC: <strong>{metrics?.political_capital ?? "—"}</strong>
      </div>
      <div className={`hud-status ${connected ? "connected" : "disconnected"}`}>
        {connected ? "● LIVE" : "○ Connecting…"}
      </div>
    </div>
  );
}
