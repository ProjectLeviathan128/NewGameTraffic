"use client";

import { useMemo, useRef, useState } from "react";
import Map from "react-map-gl/maplibre";
import DeckGL from "@deck.gl/react";
import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { StyleSpecification } from "maplibre-gl";
import { BuildingState, EdgeState, OverlayMode, RouteState } from "@/types/simulation";
import { RoadEditPreview } from "@/lib/demo";
import { vcToColor } from "@/lib/colors";

interface EdgeGeoFeature {
  path: [number, number][];
  midpoint: [number, number];
  edge_id: number;
  tier: 0 | 1 | 2;
  vc: number;
  has_bus_lane: boolean;
  lanes: number;
  highway_type: string;
}

interface BuildingFeature {
  id: number;
  center: [number, number];
  height_m: number;
  radius_m: number;
  tier: 0 | 1 | 2;
}

interface NodeHandleFeature {
  kind: "road_handle";
  edge_id: number;
  endpoint: "start" | "end";
  position: [number, number];
}

interface Bounds {
  west: number;
  east: number;
  south: number;
  north: number;
}

interface Props {
  edges: EdgeState[];
  routes: RouteState[];
  buildings: BuildingState[];
  overlayMode: OverlayMode;
  onEdgeClick?: (edgeId: number) => void;
  selectedEdgeId?: number | null;
  roadEditEnabled?: boolean;
  roadEditPreview?: RoadEditPreview | null;
  conflictBuildingIds?: number[];
  onRoadNodePreview?: (edgeId: number, endpoint: "start" | "end", coordinate: [number, number]) => void;
  onRoadNodeCommit?: (edgeId: number, endpoint: "start" | "end", coordinate: [number, number]) => void;
  initialViewState?: {
    longitude: number;
    latitude: number;
    zoom: number;
    pitch: number;
    bearing: number;
  };
  bounds?: Bounds | null;
}

const PORTLAND_VIEW = {
  longitude: -122.676,
  latitude: 45.523,
  zoom: 12,
  pitch: 45,
  bearing: 0,
};

const LOCAL_STYLE: StyleSpecification = {
  version: 8,
  name: "gridlock-local-style",
  sources: {},
  layers: [
    {
      id: "bg",
      type: "background",
      paint: {
        "background-color": "#081523",
      },
    },
  ],
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

function roadBaseColor(highway: string, tier: 0 | 1 | 2): [number, number, number, number] {
  if (highway.startsWith("motorway") || highway.startsWith("trunk")) return [86, 111, 134, 255];
  if (tier === 1) return [72, 93, 114, 248];
  return [56, 74, 92, 235];
}

export default function CityMap({
  edges,
  routes,
  buildings,
  overlayMode,
  onEdgeClick,
  selectedEdgeId = null,
  roadEditEnabled = false,
  roadEditPreview = null,
  conflictBuildingIds = [],
  onRoadNodePreview,
  onRoadNodeCommit,
  initialViewState = PORTLAND_VIEW,
  bounds = null,
}: Props) {
  const [zoomBucket, setZoomBucket] = useState<ZoomBucket>(() => zoomBucketFor(initialViewState.zoom));
  const zoomBucketRef = useRef<ZoomBucket>(zoomBucket);
  const [dragHandle, setDragHandle] = useState<NodeHandleFeature | null>(null);

  const enablePicking = Boolean(onEdgeClick || roadEditEnabled);
  const minZoom = Math.max(9, initialViewState.zoom - 1.9);
  const maxBounds = bounds ? [[bounds.west, bounds.south], [bounds.east, bounds.north]] as [[number, number], [number, number]] : undefined;
  const conflictSet = useMemo(() => new Set(conflictBuildingIds), [conflictBuildingIds]);

  // Keep `routes` referenced for future route rendering hooks without tripping unused-param rules.
  void routes;

  // Build edge features from geometry. Use road-edit preview path when present.
  const edgeFeatures: EdgeGeoFeature[] = useMemo(
    () =>
      edges
        .map((e) => {
          const basePath = e.path && e.path.length >= 2 ? e.path : null;
          if (!basePath) return null;
          const path = roadEditPreview && roadEditPreview.edge_id === e.edge_id ? roadEditPreview.path : basePath;
          const midpoint = path[Math.floor(path.length / 2)] ?? e.midpoint ?? path[0];
          return {
            path,
            midpoint,
            edge_id: e.edge_id,
            tier: edgeTier(e.highway_type),
            vc: e.congestion_ratio,
            has_bus_lane: e.has_bus_lane,
            lanes: Math.max(1, e.lanes ?? 1),
            highway_type: e.highway_type ?? "residential",
          };
        })
        .filter((d): d is EdgeGeoFeature => d !== null),
    [edges, roadEditPreview],
  );

  const selectedEdgeFeature = useMemo(
    () => edgeFeatures.find((e) => e.edge_id === selectedEdgeId) ?? null,
    [edgeFeatures, selectedEdgeId],
  );

  const roadNodeHandles = useMemo<NodeHandleFeature[]>(() => {
    if (!roadEditEnabled || !selectedEdgeFeature) return [];
    const path = selectedEdgeFeature.path;
    if (path.length < 2) return [];
    return [
      {
        kind: "road_handle",
        edge_id: selectedEdgeFeature.edge_id,
        endpoint: "start",
        position: path[0],
      },
      {
        kind: "road_handle",
        edge_id: selectedEdgeFeature.edge_id,
        endpoint: "end",
        position: path[path.length - 1],
      },
    ];
  }, [roadEditEnabled, selectedEdgeFeature]);

  const buildingFeatures: BuildingFeature[] = useMemo(
    () =>
      buildings
        .map((b) => {
          const center = b.center;
          if (!center || center.length < 2) return null;
          return {
            id: b.id,
            center,
            height_m: Math.max(4, Math.min(90, b.height_m)),
            radius_m: Math.max(3, Math.min(42, b.radius_m)),
            tier: b.tier,
          };
        })
        .filter((b): b is BuildingFeature => b !== null),
    [buildings],
  );

  const visibleEdges: EdgeGeoFeature[] = useMemo(() => {
    if (zoomBucket === "near") return edgeFeatures;
    if (zoomBucket === "mid") {
      return edgeFeatures.filter((e) => e.tier <= 1 || (e.tier === 2 && e.edge_id % 6 === 0));
    }
    return edgeFeatures.filter((e) => e.tier === 0 || (e.tier === 1 && e.edge_id % 4 === 0));
  }, [edgeFeatures, zoomBucket]);

  const visibleBuildings: BuildingFeature[] = useMemo(() => {
    if (!buildingFeatures.length) return [];
    if (zoomBucket === "near") {
      return buildingFeatures.filter(
        (b) => b.tier === 0 || (b.tier === 1 && b.id % 2 === 0) || (b.tier === 2 && b.id % 4 === 0),
      );
    }
    if (zoomBucket === "mid") {
      return buildingFeatures.filter((b) => b.tier === 0 || (b.tier === 1 && b.id % 4 === 0));
    }
    return [];
  }, [buildingFeatures, zoomBucket]);

  const handleViewStateChange = (params: unknown) => {
    const zoom = Number((params as { viewState?: { zoom?: number } })?.viewState?.zoom);
    if (!Number.isFinite(zoom)) return;
    const next = zoomBucketFor(zoom);
    if (next !== zoomBucketRef.current) {
      zoomBucketRef.current = next;
      setZoomBucket(next);
    }
  };

  const handleDeckClick = (info: { object?: EdgeGeoFeature | NodeHandleFeature; coordinate?: number[] }) => {
    if ((info.object as NodeHandleFeature | undefined)?.kind === "road_handle") {
      return;
    }

    if (!onEdgeClick) return;

    const asEdge = info.object as EdgeGeoFeature | undefined;
    if (asEdge && typeof asEdge.edge_id === "number") {
      onEdgeClick(asEdge.edge_id);
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

    if (nearestId !== null && best < 1.6e-6) {
      onEdgeClick(nearestId);
    }
  };

  const onDragStart = (info: { object?: NodeHandleFeature }) => {
    if (!roadEditEnabled) return;
    const obj = info.object;
    if (!obj || obj.kind !== "road_handle") return;
    setDragHandle(obj);
  };

  const onDrag = (info: { coordinate?: number[] }) => {
    if (!dragHandle || !onRoadNodePreview) return;
    if (!info.coordinate || info.coordinate.length < 2) return;
    onRoadNodePreview(dragHandle.edge_id, dragHandle.endpoint, [info.coordinate[0], info.coordinate[1]]);
  };

  const onDragEnd = (info: { coordinate?: number[] }) => {
    if (!dragHandle) return;
    if (info.coordinate && info.coordinate.length >= 2 && onRoadNodeCommit) {
      onRoadNodeCommit(dragHandle.edge_id, dragHandle.endpoint, [info.coordinate[0], info.coordinate[1]]);
    }
    setDragHandle(null);
  };

  const roadBaseLayer = useMemo(
    () =>
      new PathLayer({
        id: "road-base",
        data: visibleEdges,
        getPath: (d: EdgeGeoFeature) => d.path,
        getColor: (d: EdgeGeoFeature) => {
          if (overlayMode === "congestion") return vcToColor(d.vc);
          return roadBaseColor(d.highway_type, d.tier);
        },
        getWidth: (d: EdgeGeoFeature) => {
          if (d.tier === 0) return Math.max(6, d.lanes * 2.3);
          if (d.tier === 1) return Math.max(4, d.lanes * 1.8);
          return Math.max(2.2, d.lanes * 1.3);
        },
        widthUnits: "pixels",
        pickable: enablePicking,
      }),
    [visibleEdges, enablePicking, overlayMode],
  );

  const laneMarkingLayer = useMemo(() => {
    if (zoomBucket !== "near" || visibleEdges.length > 5_000) return null;
    return new PathLayer({
        id: "road-markings",
        data: visibleEdges,
        getPath: (d: EdgeGeoFeature) => d.path,
        getColor: () => [240, 247, 255, 75],
        getWidth: (d: EdgeGeoFeature) => (d.tier === 0 ? 1.6 : 1.0),
        widthUnits: "pixels",
        pickable: false,
    });
  }, [visibleEdges, zoomBucket]);

  const selectedEdgeLayer = useMemo(() => {
    if (!selectedEdgeFeature) return null;
    return new PathLayer({
      id: "selected-road",
      data: [selectedEdgeFeature],
      getPath: (d: EdgeGeoFeature) => d.path,
      getColor: () => [64, 196, 255, 240],
      getWidth: () => 7,
      widthUnits: "pixels",
      pickable: false,
    });
  }, [selectedEdgeFeature]);

  const handleLayer = useMemo(() => {
    if (!roadEditEnabled || !roadNodeHandles.length) return null;
    return new ScatterplotLayer({
      id: "road-node-handles",
      data: roadNodeHandles,
      getPosition: (d: NodeHandleFeature) => d.position,
      getFillColor: () => [255, 96, 96, 230],
      getLineColor: () => [255, 205, 205, 255],
      lineWidthUnits: "pixels",
      lineWidthMinPixels: 1,
      getRadius: () => 9,
      radiusUnits: "pixels",
      stroked: true,
      filled: true,
      pickable: true,
      autoHighlight: true,
    });
  }, [roadEditEnabled, roadNodeHandles]);

  const buildingLayer = useMemo(() => {
    if (!visibleBuildings.length || zoomBucket === "far") return null;
    return new ScatterplotLayer({
      id: "building-footprints",
      data: visibleBuildings,
      getPosition: (d: BuildingFeature) => d.center,
      radiusUnits: "meters",
      getRadius: (d: BuildingFeature) => Math.max(4, Math.min(16, d.radius_m * 0.7)),
      getFillColor: (d: BuildingFeature) => {
        if (conflictSet.has(d.id)) return [255, 144, 64, 230];
        if (d.tier === 0) return [140, 152, 160, 128];
        if (d.tier === 1) return [122, 138, 146, 106];
        return [104, 120, 128, 84];
      },
      opacity: 0.62,
      pickable: false,
    });
  }, [visibleBuildings, zoomBucket, conflictSet]);

  const useDevicePixels = typeof window === "undefined" ? 1 : Math.min(1.25, window.devicePixelRatio || 1);

  const layers = useMemo(
    () => [buildingLayer, roadBaseLayer, laneMarkingLayer, selectedEdgeLayer, handleLayer].filter(Boolean),
    [buildingLayer, roadBaseLayer, laneMarkingLayer, selectedEdgeLayer, handleLayer],
  );

  return (
    <DeckGL
      initialViewState={initialViewState}
      useDevicePixels={useDevicePixels}
      onViewStateChange={handleViewStateChange}
      onClick={handleDeckClick}
      onDragStart={onDragStart as (info: unknown) => void}
      onDrag={onDrag as (info: unknown) => void}
      onDragEnd={onDragEnd as (info: unknown) => void}
      controller={{
        dragPan: !dragHandle,
        dragRotate: true,
        scrollZoom: true,
        touchZoom: true,
      }}
      layers={layers}
      style={{ position: "absolute", inset: "0" }}
    >
      <Map
        mapStyle={LOCAL_STYLE}
        style={{ width: "100%", height: "100%" }}
        reuseMaps
        maxBounds={maxBounds}
        minZoom={minZoom}
      />
    </DeckGL>
  );
}
