"use client";

import { useMemo, useRef, useState } from "react";
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
  tier: 0 | 1 | 2;
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

type ZoomBucket = "far" | "mid" | "near";

function zoomBucketFor(z: number): ZoomBucket {
  if (z < 11.8) return "far";
  if (z < 13.0) return "mid";
  return "near";
}

function edgeTier(highway: string | undefined): 0 | 1 | 2 {
  if (!highway) return 2;
  if (highway.startsWith("motorway") || highway.startsWith("trunk")) return 0;
  if (highway.startsWith("primary") || highway.startsWith("secondary") || highway.startsWith("tertiary")) return 1;
  return 2;
}

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
  const [zoomBucket, setZoomBucket] = useState<ZoomBucket>(() => zoomBucketFor(initialViewState.zoom));
  const zoomBucketRef = useRef<ZoomBucket>(zoomBucket);
  const enablePicking = Boolean(onEdgeClick);

  // Build edge features from real geometry when available.
  const edgeFeatures: EdgeGeoFeature[] = useMemo(
    () =>
      edges
        .map((e) => {
          const path = e.path && e.path.length >= 2 ? e.path : null;
          if (!path) return null;
          const midpoint = e.midpoint ?? path[Math.floor(path.length / 2)];
          return {
            path,
            midpoint,
            edge_id: e.edge_id,
            tier: edgeTier(e.highway_type),
            vc: e.congestion_ratio,
            has_bus_lane: e.has_bus_lane,
          };
        })
        .filter((d): d is EdgeGeoFeature => d !== null),
    [edges]
  );

  const visibleEdges: EdgeGeoFeature[] = useMemo(() => {
    if (zoomBucket === "near") return edgeFeatures;
    if (zoomBucket === "mid") {
      return edgeFeatures.filter((e) => e.tier <= 1);
    }
    // Zoomed out: keep freeways + a deterministic sample of arterials.
    return edgeFeatures.filter((e) => e.tier === 0 || (e.tier === 1 && e.edge_id % 2 === 0));
  }, [edgeFeatures, zoomBucket]);

  const heatmapData = useMemo(() => {
    if (overlayMode !== "congestion") return [];
    const hot = visibleEdges.filter((e) => e.vc > 0.6);
    if (zoomBucket === "near") return hot;
    if (zoomBucket === "mid") return hot.filter((e) => e.edge_id % 3 === 0);
    return hot.filter((e) => e.edge_id % 6 === 0);
  }, [visibleEdges, overlayMode, zoomBucket]);

  const handleViewStateChange = (params: unknown) => {
    const zoom = Number((params as { viewState?: { zoom?: number } })?.viewState?.zoom);
    if (!Number.isFinite(zoom)) return;
    const next = zoomBucketFor(zoom);
    if (next !== zoomBucketRef.current) {
      zoomBucketRef.current = next;
      setZoomBucket(next);
    }
  };

  const handleDeckClick = (info: { object?: EdgeGeoFeature; coordinate?: number[] }) => {
    if (!onEdgeClick || !enablePicking) return;
    if (info.object) {
      onEdgeClick(info.object.edge_id);
      return;
    }
    if (!info.coordinate || info.coordinate.length < 2 || !visibleEdges.length) return;

    const lon = info.coordinate[0];
    const lat = info.coordinate[1];
    let nearestId: number | null = null;
    let best = Number.POSITIVE_INFINITY;
    for (const edge of visibleEdges) {
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

  const pathLayer = useMemo(
    () =>
      new PathLayer({
        id: "road-network",
        data: visibleEdges,
        getPath: (d: EdgeGeoFeature) => d.path,
        getColor: (d: EdgeGeoFeature) => vcToColor(d.vc),
        getWidth: (d: EdgeGeoFeature) => (d.has_bus_lane ? 5 : 2),
        widthUnits: "pixels",
        pickable: enablePicking,
      }),
    [visibleEdges, enablePicking]
  );

  const heatmapLayer = useMemo(() => {
    if (overlayMode !== "congestion" || !heatmapData.length || zoomBucket === "far") return null;
    return new HeatmapLayer({
      id: "traffic-heatmap",
      data: heatmapData,
      getPosition: (d: EdgeGeoFeature) => d.midpoint,
      getWeight: (d: EdgeGeoFeature) => d.vc,
      radiusPixels: 32,
      intensity: 0.8,
      threshold: 0.08,
      colorRange: [
        [76, 175, 80, 100],
        [255, 235, 59, 150],
        [255, 152, 0, 200],
        [244, 67, 54, 220],
        [183, 28, 28, 255],
      ],
    });
  }, [overlayMode, heatmapData, zoomBucket]);

  const layers = useMemo(() => [pathLayer, heatmapLayer].filter(Boolean), [pathLayer, heatmapLayer]);

  return (
    <DeckGL
      initialViewState={initialViewState}
      onViewStateChange={handleViewStateChange}
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
