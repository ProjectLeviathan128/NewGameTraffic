/**
 * Traffic overlay color utilities.
 * Colors match GDD spec: green → yellow → orange → red → dark red.
 */

/** Convert V/C ratio to RGBA array for deck.gl layers [r, g, b, a] */
export function vcToColor(vc: number): [number, number, number, number] {
  if (vc <= 0.25) return [76, 175, 80, 220];    // #4CAF50 green
  if (vc <= 0.50) return [255, 193, 7, 220];    // #FFC107 yellow
  if (vc <= 0.75) return [255, 152, 0, 220];    // #FF9800 orange
  if (vc <= 1.00) return [244, 67, 54, 220];    // #F44336 red
  return [183, 28, 28, 255];                    // #B71C1C dark red / gridlock
}

/** Convert equity score (0–1) to blue shading [r, g, b, a] */
export function equityToColor(score: number): [number, number, number, number] {
  const alpha = Math.round(score * 180 + 40);
  return [33, 150, 243, alpha];   // Blue, opacity scales with equity need
}

/** LOS label to human-readable description */
export const LOS_LABELS: Record<string, string> = {
  A: "Free flow",
  B: "Reasonable",
  C: "Stable",
  D: "Approaching unstable",
  E: "Near capacity",
  F: "Breakdown / gridlock",
};

/** Format an in-game hour (0–23) to "8:00 AM" style */
export function formatHour(hour: number): string {
  const h = hour % 12 || 12;
  const ampm = hour < 12 ? "AM" : "PM";
  return `${h}:00 ${ampm}`;
}

/** Format large numbers with commas */
export function fmt(n: number, decimals = 0): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
