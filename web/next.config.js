/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // deck.gl requires transpilation
  transpilePackages: ["deck.gl", "@deck.gl/core", "@deck.gl/layers", "@deck.gl/react"],
};

module.exports = nextConfig;
