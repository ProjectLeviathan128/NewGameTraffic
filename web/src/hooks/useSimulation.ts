"use client";

import { useEffect, useRef, useState } from "react";
import { SimSnapshot } from "@/types/simulation";
import { createWebSocket } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function useSimulation(city: string) {
  const [snapshot, setSnapshot] = useState<SimSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!city) return;

    // Load city on server first
    fetch(`${API_BASE}/cities/${city}/load`, { method: "POST" })
      .then((r) => {
        if (!r.ok) return r.text().then((t) => { throw new Error(t); });
        return r.json();
      })
      .then(() => {
        // Open WebSocket after city is loaded
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
