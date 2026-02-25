/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export for GitHub Pages
  output: "export",
  // Adjust basePath if deploying to a sub-path (e.g. /<repo-name>/)
  // basePath: process.env.NEXT_PUBLIC_BASE_PATH ?? "",
  trailingSlash: true,
  // deck.gl requires transpilation
  transpilePackages: ["deck.gl", "@deck.gl/core", "@deck.gl/layers", "@deck.gl/react"],
  // Disable image optimization (not available in static export)
  images: { unoptimized: true },
};

module.exports = nextConfig;
