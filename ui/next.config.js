/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle so the Docker runner stage can ship
  // just .next/standalone + static assets.
  output: "standalone",
};

module.exports = nextConfig;
