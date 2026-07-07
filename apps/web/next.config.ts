import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 백엔드(FastAPI)에 CORS 미들웨어가 없어 브라우저 직접 호출이 막힌다.
  // NEXT_PUBLIC_AXKG_API_BASE_URL=/backend 로 두면 same-origin으로 받아
  // 여기서 API로 프록시한다 (dev/로컬 검증용).
  async rewrites() {
    const target = process.env.AXKG_API_PROXY_TARGET ?? "http://localhost:8000";
    return [
      {
        source: "/backend/:path*",
        destination: `${target}/:path*`,
      },
    ];
  },
};

export default nextConfig;
