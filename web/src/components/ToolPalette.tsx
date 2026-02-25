"use client";

import { InterventionTool } from "@/types/simulation";

interface Props {
  activeTool: InterventionTool;
  onSelectTool: (tool: InterventionTool) => void;
  selectedEdgeId: number | null;
  city: string;
  onIntervention: (result: { success: boolean; message: string; pc_cost: number }) => void;
}

const TOOLS: { id: InterventionTool; label: string; description: string; pcCost: string }[] = [
  { id: "bus_lane",           label: "Bus Lane",          description: "Convert one GP lane to bus-only",    pcCost: "15 PC" },
  { id: "frequency_boost",   label: "Boost Frequency",   description: "Reduce headway on a transit route",  pcCost: "8 PC" },
  { id: "congestion_pricing",label: "Congestion Pricing", description: "Charge vehicles to enter zone",      pcCost: "40 PC" },
  { id: "remove_parking",    label: "Remove Parking",    description: "Convert parking lane to travel",     pcCost: "12 PC" },
  { id: "road_diet",         label: "Road Diet",         description: "4→3 lanes with bike lanes",          pcCost: "10 PC" },
  { id: "speed_limit",       label: "Speed Limit",       description: "Reduce speed limit on segment",      pcCost: "6 PC" },
];

export default function ToolPalette({ activeTool, onSelectTool, selectedEdgeId, city, onIntervention }: Props) {
  return (
    <div className="tool-palette">
      <h3>Interventions</h3>
      {TOOLS.map((tool) => (
        <button
          key={tool.id}
          className={`tool-btn ${activeTool === tool.id ? "active" : ""}`}
          onClick={() => onSelectTool(activeTool === tool.id ? null : tool.id)}
          title={tool.description}
        >
          <span className="tool-label">{tool.label}</span>
          <span className="tool-cost">{tool.pcCost}</span>
        </button>
      ))}
      {selectedEdgeId !== null && activeTool && (
        <div className="apply-section">
          <p className="apply-hint">
            Selected edge: #{selectedEdgeId}
          </p>
          <ApplyButton
            tool={activeTool}
            edgeId={selectedEdgeId}
            city={city}
            onResult={onIntervention}
          />
        </div>
      )}
    </div>
  );
}

function ApplyButton({ tool, edgeId, city, onResult }: {
  tool: InterventionTool;
  edgeId: number;
  city: string;
  onResult: (r: { success: boolean; message: string; pc_cost: number }) => void;
}) {
  const apply = async () => {
    const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    let url = "";
    let body: Record<string, unknown> = {};

    if (tool === "bus_lane") {
      url = `${API}/cities/${city}/interventions/bus_lane`;
      body = { edge_id: edgeId };
    } else if (tool === "remove_parking" || tool === "road_diet" || tool === "speed_limit") {
      // Placeholder — these interventions TBD in Phase 1
      onResult({ success: false, message: "Intervention not yet implemented", pc_cost: 0 });
      return;
    } else {
      onResult({ success: false, message: "Select a specific tool", pc_cost: 0 });
      return;
    }

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    onResult(data);
  };

  return (
    <button className="apply-btn" onClick={apply}>
      Apply to Edge #{edgeId}
    </button>
  );
}
