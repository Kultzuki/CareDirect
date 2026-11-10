import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  /* config options here */
  // A second lockfile in the user's home directory must not widen filesystem watching.
  turbopack: { root: path.resolve(__dirname) },
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    // Uploads are Server Actions. The API accepts 20 MiB; the extra room covers multipart
    // boundaries and field metadata (the default limit is 1 MB).
    serverActions: { bodySizeLimit: "21mb" },
  },
  logging: {
    // Upload links carry their token in the URL path. Keep those requests out of dev logs.
    incomingRequests: { ignore: [/^\/upload\//, /^\/provider\/respond\//, /^\/family\/join\//] },
  },
};

export default nextConfig;
