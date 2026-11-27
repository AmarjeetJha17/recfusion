import { resolve } from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  turbopack: {
    root: resolve(process.cwd(), "../.."),
  },
};

export default nextConfig;
