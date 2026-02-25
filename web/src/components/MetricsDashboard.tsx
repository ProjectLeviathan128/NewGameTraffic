"use client";

import {
  ActiveEventState,
  CampaignStageState,
  CityMetrics,
  TrafficModelState,
} from "@/types/simulation";
import { fmt, formatHour } from "@/lib/colors";

interface Props {
  metrics: CityMetrics | null;
  tickHour: number;
  cityName: string;
  trafficModel: TrafficModelState | null;
  campaign: CampaignStageState | null;
  activeEvent: ActiveEventState | null;
}

type MetricRow = {
  key: keyof CityMetrics;
  label: string;
  unit: string;
  target: number | null;
  lower: boolean;
};

const METRIC_ROWS: MetricRow[] = [
  { key: "avg_commute_min", label: "Avg Commute", unit: "min", target: 27, lower: true },
  { key: "vmt_daily", label: "Daily VMT", unit: "km", target: null, lower: true },
  { key: "transit_ridership", label: "Transit Rides", unit: "/day", target: null, lower: false },
  { key: "equity_score", label: "Equity Index", unit: "", target: 1, lower: false },
  { key: "co2_g_per_commuter_km", label: "CO₂ Intensity", unit: "g/km", target: 150, lower: true },
];

export default function MetricsDashboard({
  metrics,
  tickHour,
  cityName,
  trafficModel,
  campaign,
  activeEvent,
}: Props) {
  if (!metrics) {
    return (
      <div className="metrics-panel loading">
        <h2>{cityName}</h2>
        <p>Loading simulation…</p>
      </div>
    );
  }

  return (
    <div className="metrics-panel">
      <h2>{cityName}</h2>
      <div className="time-display">{formatHour(tickHour)}</div>
      <div className="pc-meter">
        <span>Political Capital</span>
        <span className="pc-value">{metrics.political_capital}</span>
      </div>

      {campaign && (
        <div className="campaign-box">
          <p className="campaign-name">{campaign.stage_name}</p>
          <p className="campaign-progress">
            Progress {campaign.progress_points}
            {campaign.next_stage_points !== null ? ` / ${campaign.next_stage_points}` : ""}
          </p>
          <p className="campaign-assets">
            Unlocked: {fmt(campaign.unlocked_edges, 0)} roads · {fmt(campaign.unlocked_buildings, 0)} buildings
          </p>
        </div>
      )}

      {trafficModel && (
        <div className="agent-box">
          <p className="agent-title">Representative Traffic Model</p>
          <p>{fmt(trafficModel.represented_travelers, 0)} travelers represented</p>
          <p>{fmt(trafficModel.active_vehicle_agents, 0)} active vehicle agents</p>
          <p>{fmt(trafficModel.representative_groups, 0)} groups · ~{trafficModel.avg_group_size} each</p>
        </div>
      )}

      {activeEvent && (
        <div className="event-box">
          <p className="event-title">{activeEvent.title}</p>
          <p className="event-desc">{activeEvent.description}</p>
          <p className="event-meta">
            {activeEvent.affected_edges} impacted roads · {Math.round((activeEvent.demand_multiplier - 1) * 100)}% demand surge
          </p>
          <p className="event-meta">
            Reward: +{activeEvent.reward_pc} PC {activeEvent.reward_claimed ? "(claimed)" : "(available)"}
          </p>
        </div>
      )}

      <hr />
      <table className="metrics-table">
        <tbody>
          {METRIC_ROWS.map(({ key, label, unit, target, lower }) => {
            const val = metrics[key] ?? 0;
            const good = target
              ? (lower ? val <= target * 1.05 : val >= target * 0.95)
              : null;
            return (
              <tr key={key}>
                <td className="metric-label">{label}</td>
                <td className={`metric-value ${good === true ? "good" : good === false ? "bad" : ""}`}>
                  {key === "equity_score"
                    ? val.toFixed(2)
                    : fmt(val, key === "avg_commute_min" ? 1 : 0)}
                  {unit && <span className="unit"> {unit}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
