Original prompt: i want portland to load immediatly when the app gets opened i want this mvp to be amazing

## 2026-02-25
- Started investigation of startup city load path in web app.
- Confirmed `web/src/app/page.tsx` and `web/src/hooks/useSimulation.ts` currently use a default city fallback of `portland`.
- Enforced startup city as `portland` in `web/src/app/page.tsx` (removed env override).
- Updated `web/src/hooks/useSimulation.ts` to fetch `/cities/{city}/state` immediately after `/load`, so the UI renders city state without waiting for WebSocket tick cadence.
- `npm run build` in `web/` passes with no TypeScript/build errors.
- `npm run lint` in `web/` is currently blocked by Next.js interactive ESLint setup prompt (no existing ESLint config in repo).
- Ran Playwright client (`web_game_playwright_client.js`) against `next dev` on port 4173 with demo mode enabled; screenshot confirms Portland HUD is visible immediately on load.
- Playwright run captured existing runtime issue: `TypeError: Cannot read properties of undefined (reading 'maxTextureDimension2D')` from map rendering (WebGL/deck.gl context), plus a missing `/assets/svg/favicon.svg` 404.
- Audited live GitHub Pages deployment via `https://projectleviathan128.github.io/NewGameTraffic/` and confirmed it was running in synthetic demo mode (banner + blank/placeholder map behavior before fixes).
- Added bundled real data for static mode at `web/public/data/portland_real_osm.json` generated from OpenStreetMap (Overpass) + TriMet GTFS route metadata (current GTFS endpoint: `https://developer.trimet.org/schedule/gtfs.zip`).
- Updated demo/static simulation loader to asynchronously load bundled real city data before ticking (`ensureDemoCityLoaded` in `web/src/lib/demo.ts` and `web/src/hooks/useSimulation.ts`).
- Updated map rendering to consume per-edge geometry (`path` + `midpoint`) instead of placeholder `[0,0]` lines (`web/src/components/CityMap.tsx`, `web/src/types/simulation.ts`).
- Updated GitHub Pages banner/workflow text to reflect static bundled real data mode.
- Updated `cities/portland.yaml` GTFS URL to current working TriMet endpoint.
- Verified `npm run build` succeeds after all changes.
- Local browser artifacts now show real Portland road geometry rendered on startup in static mode (`output/web-game-real/shot-0.png`, `output/web-game-real-headed/shot-0.png`).
- Residual issue still present in automated Playwright runs: deck.gl/luma page error `maxTextureDimension2D` in this automation environment, plus a `/favicon.ico` 404 in local dev if icon file is missing at root.
