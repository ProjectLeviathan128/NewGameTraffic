"use client";

import { useEffect, useRef, useState } from "react";
import { SimSnapshot } from "@/types/simulation";
import { createWebSocket } from "@/lib/api";
import { buildDemoSnapshot, ensureDemoCityLoaded } from "@/lib/demo";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const IS_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export function useSimulation(city: string) {
  const [snapshot, setSnapshot] = useState<SimSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hourRef = useRef(8);

  useEffect(() => {
    if (!city) return;
    let disposed = false;

    wsRef.current?.close();
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
    setConnected(false);
    setError(null);

    if (IS_DEMO) {
      // Demo mode: load bundled static city data, then run client-side ticks.
      const startDemo = async () => {
        try {
          await ensureDemoCityLoaded();
          if (disposed) return;

          setConnected(true);
          setSnapshot(buildDemoSnapshot(hourRef.current));
          tickRef.current = setInterval(() => {
            hourRef.current = (hourRef.current + 1) % 24;
            setSnapshot(buildDemoSnapshot(hourRef.current));
          }, 2000);
        } catch (e) {
          if (!disposed) {
            setError(e instanceof Error ? e.message : "Failed to initialize demo city");
          }
        }
      };

      void startDemo();
      return () => {
        disposed = true;
        if (tickRef.current) {
          clearInterval(tickRef.current);
          tickRef.current = null;
        }
      };
    }

    const loadAndConnect = async () => {
      try {
        const loadRes = await fetch(`${API_BASE}/cities/${city}/load`, { method: "POST" });
        if (!loadRes.ok) {
          throw new Error(await loadRes.text());
        }

        // Pull one immediate snapshot so the city is visible before the first WS tick.
        const stateRes = await fetch(`${API_BASE}/cities/${city}/state`);
        if (!stateRes.ok) {
          throw new Error(await stateRes.text());
        }

        const initialSnapshot = (await stateRes.json()) as SimSnapshot;
        if (disposed) return;
        setSnapshot(initialSnapshot);
        setConnected(true);

        const ws = createWebSocket((snap) => {
          if (disposed) return;
          setSnapshot(snap);
          setConnected(true);
        });
        ws.onopen = () => {
          ws.send(JSON.stringify({ city }));
          if (!disposed) setError(null);
        };
        ws.onerror = () => {
          if (!disposed) setError("WebSocket connection failed");
        };
        ws.onclose = () => {
          if (!disposed) setConnected(false);
        };
        wsRef.current = ws;
      } catch (e) {
        if (!disposed) {
          setError(e instanceof Error ? e.message : "Failed to load city");
        }
      }
    };

    void loadAndConnect();

    return () => {
      disposed = true;
      wsRef.current?.close();
    };
  }, [city]);

  return { snapshot, connected, error };
}
