/** @type {import('next').NextConfig} */
const apiInternalBaseUrl = (
  process.env.API_INTERNAL_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // Keep browser sessions same-origin. The API destination is server-only and
  // is resolved on the Compose network (or localhost during local development).
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiInternalBaseUrl}/api/:path*`
      },
      {
        source: "/auth/:path*",
        destination: `${apiInternalBaseUrl}/auth/:path*`
      },
      {
        source: "/health",
        destination: `${apiInternalBaseUrl}/health`
      }
    ];
  }
};

export default nextConfig;
