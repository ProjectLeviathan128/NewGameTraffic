/** @type {import('next').NextConfig} */
const rawBasePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const basePath = rawBasePath === "/" ? "" : rawBasePath.replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  // Static export for GitHub Pages
  output: "export",
  // Set by the GitHub Actions Pages workflow; empty for root domains/custom domains.
  basePath,
  assetPrefix: basePath ? `${basePath}/` : undefined,
  trailingSlash: true,
  // deck.gl requires transpilation
  transpilePackages: [
    "deck.gl",
    "@deck.gl/core",
    "@deck.gl/layers",
    "@deck.gl/aggregation-layers",
    "@deck.gl/react",
  ],
  // Disable image optimization (not available in static export)
  images: { unoptimized: true },
};

module.exports = nextConfig;
