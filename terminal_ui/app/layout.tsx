import type { Metadata } from 'next'
import '@/styles/globals.css'
import TopBar from '@/components/TopBar'
import Toasts from '@/components/Toasts'
import MeshBackground from '@/components/MeshBackground'

export const metadata: Metadata = {
  title: 'TERMINAL//IN',
  description: 'Indian Markets Quantitative Trading Terminal',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: '#0A0B0D' }}>
        <MeshBackground />
        {/* everything above the mesh */}
        <div style={{ position: 'relative', zIndex: 1, display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
          <TopBar />
          <main style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            {children}
          </main>
        </div>
        <Toasts />
      </body>
    </html>
  )
}
