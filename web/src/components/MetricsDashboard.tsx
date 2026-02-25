"use client";

import { CityMetrics } from "@/types/simulation";
import { fmt, formatHour } from "@/lib/colors";

interface Props {
  metrics: CityMetrics | null;
  tickHour: number;
  cityName: string;
}

type MetricRow = {
  key: keyof CityMetrics;
  label: string;
  unit: string;
  target: number | null;
  lower: boolean;
};

const METRIC_ROWS: MetricRow[] = [
  { key: "avg_commute_min",      label: "Avg Commute",    unit: "min",    target: 27,  lower: true },
  { key: "vmt_daily",            label: "Daily VMT",      unit: "km",     target: null, lower: true },
  { key: "transit_ridership",    label: "Transit Rides",  unit: "/day",   target: null, lower: false },
  { key: "equity_score",         label: "Equity Index",   unit: "",       target: 1,   lower: false },
  { key: "co2_g_per_commuter_km",label: "CO₂ Intensity",  unit: "g/km",   target: 150, lower: true },
];

export default function MetricsDashboard({ metrics, tickHour, cityName }: Props) {
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
