/** @type {import('next').NextConfig} */
const nextConfig = process.env.BUILD_STATIC === '1'
  ? {
      // Packaged mode: static export served by Flask on :5000 (single
      // process). lib/api.ts uses relative '/api' so calls are same-origin.
      output: 'export',
      images: { unoptimized: true },
    }
  : {
      // Dev mode: proxy /api to the backend
      async rewrites() {
        return [
          { source: '/api/:path*', destination: 'http://localhost:5000/api/:path*' },
        ]
      },
    }

module.exports = nextConfig
