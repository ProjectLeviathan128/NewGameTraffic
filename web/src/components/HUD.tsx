"use client";

import { CityMetrics } from "@/types/simulation";
import { formatHour } from "@/lib/colors";

interface Props {
  cityName: string;
  stageName: string;
  tickHour: number;
  metrics: CityMetrics | null;
  connected: boolean;
  sandboxMode: boolean;
}

export default function HUD({ cityName, stageName, tickHour, metrics, connected, sandboxMode }: Props) {
  return (
    <div className="hud-topbar">
      <div className="hud-city">{cityName}</div>
      <div className="hud-stage">{stageName}</div>
      <div className="hud-time">{formatHour(tickHour)}</div>
      <div className="hud-pc">
        PC: <strong>{metrics?.political_capital ?? "—"}</strong>
      </div>
      <div className={`hud-sandbox ${sandboxMode ? "on" : "off"}`}>
        {sandboxMode ? "SANDBOX" : "CHALLENGE"}
      </div>
      <div className={`hud-status ${connected ? "connected" : "disconnected"}`}>
        {connected ? "● LIVE" : "○ Connecting…"}
      </div>
    </div>
  );
}
