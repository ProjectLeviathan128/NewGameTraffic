"use client";

import { useMemo, useState } from "react";
import Map from "react-map-gl/maplibre";
import DeckGL from "@deck.gl/react";
import { PathLayer } from "@deck.gl/layers";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { EdgeState, RouteState, OverlayMode } from "@/types/simulation";
import { vcToColor } from "@/lib/colors";

interface EdgeGeoFeature {
  path: [number, number][];
  midpoint: [number, number];
  edge_id: number;
  vc: number;
  has_bus_lane: boolean;
}

interface Props {
  edges: EdgeState[];
  routes: RouteState[];
  overlayMode: OverlayMode;
  onEdgeClick?: (edgeId: number) => void;
  initialViewState?: {
    longitude: number;
    latitude: number;
    zoom: number;
    pitch: number;
    bearing: number;
  };
}

const PORTLAND_VIEW = {
  longitude: -122.676,
  latitude: 45.523,
  zoom: 12,
  pitch: 45,
  bearing: 0,
};

/**
 * CityMap renders the road network and traffic overlay using deck.gl + MapLibre.
 *
 * Edge geometry is approximated as straight lines between node positions.
 * In Phase 1, this is replaced with actual OSM geometry loaded from the API.
 */
export default function CityMap({
  edges,
  routes,
  overlayMode,
  onEdgeClick,
  initialViewState = PORTLAND_VIEW,
}: Props) {
  const [viewState, setViewState] = useState(initialViewState);

  // Build edge features from real geometry when available.
  const edgeFeatures: EdgeGeoFeature[] = useMemo(() => edges
    .map((e) => {
      const path = e.path && e.path.length >= 2 ? e.path : null;
      if (!path) return null;
      const midpoint = e.midpoint ?? path[Math.floor(path.length / 2)];
      return {
        path,
        midpoint,
        edge_id: e.edge_id,
        vc: e.congestion_ratio,
        has_bus_lane: e.has_bus_lane,
      };
    })
    .filter((d): d is EdgeGeoFeature => d !== null), [edges]);

  const handleDeckClick = (info: { object?: EdgeGeoFeature; coordinate?: number[] }) => {
    if (!onEdgeClick) return;
    if (info.object) {
      onEdgeClick(info.object.edge_id);
      return;
    }
    if (!info.coordinate || info.coordinate.length < 2 || !edgeFeatures.length) return;

    const lon = info.coordinate[0];
    const lat = info.coordinate[1];
    let nearestId: number | null = null;
    let best = Number.POSITIVE_INFINITY;
    for (const edge of edgeFeatures) {
      const dx = edge.midpoint[0] - lon;
      const dy = edge.midpoint[1] - lat;
      const dist2 = dx * dx + dy * dy;
      if (dist2 < best) {
        best = dist2;
        nearestId = edge.edge_id;
      }
    }

    // Roughly ~120m at Portland lat, enough for practical click tolerance.
    if (nearestId !== null && best < 1.6e-6) {
      onEdgeClick(nearestId);
    }
  };

  // Traffic path layer — color-coded by LOS
  const pathLayer = new PathLayer({
    id: "road-network",
    data: edgeFeatures,
    getPath: (d: EdgeGeoFeature) => d.path,
    getColor: (d: EdgeGeoFeature) => vcToColor(d.vc),
    getWidth: (d: EdgeGeoFeature) => (d.has_bus_lane ? 6 : 3),
    widthUnits: "pixels",
    pickable: true,
  });

  // Heatmap layer for high-congestion zones
  const heatmapLayer = overlayMode === "congestion"
    ? new HeatmapLayer({
        id: "traffic-heatmap",
        data: edgeFeatures.filter((e) => e.vc > 0.6),
        getPosition: (d: EdgeGeoFeature) => d.midpoint,
        getWeight: (d: EdgeGeoFeature) => d.vc,
        radiusPixels: 40,
        intensity: 1,
        threshold: 0.05,
        colorRange: [
          [76, 175, 80, 100],
          [255, 235, 59, 150],
          [255, 152, 0, 200],
          [244, 67, 54, 220],
          [183, 28, 28, 255],
        ],
      })
    : null;

  const layers = [pathLayer, heatmapLayer].filter(Boolean);

  return (
    <DeckGL
      viewState={viewState}
      onViewStateChange={({ viewState: vs }) => setViewState(vs as typeof viewState)}
      onClick={handleDeckClick}
      controller={true}
      layers={layers}
      style={{ position: "absolute", inset: "0" }}
    >
      <Map
        mapStyle="https://demotiles.maplibre.org/style.json"
        style={{ width: "100%", height: "100%" }}
        reuseMaps
      />
    </DeckGL>
  );
}
