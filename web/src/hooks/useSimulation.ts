"use client";

import { useEffect, useRef, useState } from "react";
import { SimSnapshot } from "@/types/simulation";
import { createWebSocket } from "@/lib/api";
import { buildDemoSnapshot } from "@/lib/demo";

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

    if (IS_DEMO) {
      // Demo mode: client-side simulation tick, no backend required
      setConnected(true);
      setSnapshot(buildDemoSnapshot(hourRef.current));
      tickRef.current = setInterval(() => {
        hourRef.current = (hourRef.current + 1) % 24;
        setSnapshot(buildDemoSnapshot(hourRef.current));
      }, 2000);
      return () => {
        if (tickRef.current) clearInterval(tickRef.current);
      };
    }

    // Live mode: connect to Python FastAPI server
    fetch(`${API_BASE}/cities/${city}/load`, { method: "POST" })
      .then((r) => {
        if (!r.ok) return r.text().then((t) => { throw new Error(t); });
        return r.json();
      })
      .then(() => {
        const ws = createWebSocket((snap) => {
          setSnapshot(snap);
          setConnected(true);
        });
        ws.onopen = () => {
          ws.send(JSON.stringify({ city }));
          setConnected(true);
          setError(null);
        };
        ws.onerror = () => setError("WebSocket connection failed");
        ws.onclose = () => setConnected(false);
        wsRef.current = ws;
      })
      .catch((e) => setError(e.message));

    return () => {
      wsRef.current?.close();
    };
  }, [city]);

  return { snapshot, connected, error };
}
