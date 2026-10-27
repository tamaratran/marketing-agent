import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Served at tamarajtran.com/marketing-agent through a rewrite on the personal site.
  basePath: "/marketing-agent",
  async redirects() {
    return [
      { source: "/", destination: "/marketing-agent", basePath: false, permanent: false },
      { source: "/:path((?!marketing-agent(?:/|$)).*)", destination: "/marketing-agent/:path", basePath: false, permanent: false },
      // Folded into the three tabs.
      { source: "/how", destination: "/", permanent: false },
      { source: "/overview", destination: "/", permanent: false },
      { source: "/scripts", destination: "/learnings", permanent: false },
      { source: "/runs", destination: "/learnings", permanent: false },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
