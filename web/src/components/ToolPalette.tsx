"use client";

import { RoadEditPreview } from "@/lib/demo";
import { EdgeState, InterventionTool } from "@/types/simulation";

interface Props {
  activeTool: InterventionTool;
  onSelectTool: (tool: InterventionTool) => void;
  selectedEdgeId: number | null;
  selectedEdge: EdgeState | null;
  sandboxMode: boolean;
  onToggleSandbox: (enabled: boolean) => void;
  roadEditPreview: RoadEditPreview | null;
  onApplyCapacityUpgrade: () => void;
  onDemolishRoad: () => void;
}

const TOOLS: { id: InterventionTool; label: string; description: string }[] = [
  {
    id: "road_edit",
    label: "Road Edit",
    description: "Drag road end nodes. Cost updates in real time from land + demolition impacts.",
  },
  {
    id: "capacity_upgrade",
    label: "Capacity Upgrade",
    description: "One-click corridor expansion. Strong but expensive.",
  },
  {
    id: "demolish_road",
    label: "Demolish Road",
    description: "Challenge mode: local roads only. Sandbox mode: unrestricted.",
  },
];

export default function ToolPalette({
  activeTool,
  onSelectTool,
  selectedEdgeId,
  selectedEdge,
  sandboxMode,
  onToggleSandbox,
  roadEditPreview,
  onApplyCapacityUpgrade,
  onDemolishRoad,
}: Props) {
  const upgradeProjectedCost = selectedEdge
    ? 14 + Math.max(0, selectedEdge.land_acquisition_pc ?? 0) + Math.max(0, selectedEdge.building_hits ?? 0) * 2
    : null;

  const canApplyAction = selectedEdgeId !== null && activeTool !== "road_edit";

  return (
    <div className="tool-palette">
      <h3>Road Authority Tools</h3>

      <label className="sandbox-toggle">
        <input
          type="checkbox"
          checked={sandboxMode}
          onChange={(e) => onToggleSandbox(e.target.checked)}
        />
        <span>Sandbox Mode (Unlimited Budget)</span>
      </label>

      {TOOLS.map((tool) => (
        <button
          key={tool.id}
          className={`tool-btn ${activeTool === tool.id ? "active" : ""}`}
          onClick={() => onSelectTool(activeTool === tool.id ? null : tool.id)}
          title={tool.description}
        >
          <span className="tool-label">{tool.label}</span>
        </button>
      ))}

      {selectedEdgeId !== null && (
        <div className="apply-section">
          <p className="apply-hint">Selected road: #{selectedEdgeId}</p>
          {selectedEdge?.highway_type && (
            <p className="apply-hint">Type: {selectedEdge.highway_type}</p>
          )}
        </div>
      )}

      {activeTool === "road_edit" && (
        <div className="apply-section">
          <p className="apply-hint">Road Edit Mode</p>
          <p className="apply-hint">Click a road, then drag red node handles directly on the map.</p>
          {roadEditPreview && (
            <>
              <p className="apply-hint">Projected edit cost: {roadEditPreview.edit_pc_cost} PC</p>
              <p className="apply-hint">
                {roadEditPreview.land_acquisition_pc} land + {roadEditPreview.demolition_pc} demolition from {roadEditPreview.building_hits} building conflicts
              </p>
            </>
          )}
        </div>
      )}

      {activeTool === "capacity_upgrade" && (
        <div className="apply-section">
          <p className="apply-hint">
            {upgradeProjectedCost !== null
              ? `Projected upgrade cost: ${upgradeProjectedCost} PC`
              : "Select a road segment to apply upgrade"}
          </p>
          <button
            className="apply-btn"
            onClick={onApplyCapacityUpgrade}
            disabled={!canApplyAction}
          >
            Apply Capacity Upgrade
          </button>
        </div>
      )}

      {activeTool === "demolish_road" && (
        <div className="apply-section">
          <p className="apply-hint">
            {sandboxMode
              ? "Sandbox: any selected road can be demolished."
              : "Challenge: demolition is restricted to smaller local roads."}
          </p>
          <button
            className="apply-btn danger"
            onClick={onDemolishRoad}
            disabled={!canApplyAction}
          >
            Demolish Selected Road
          </button>
        </div>
      )}
    </div>
  );
}
