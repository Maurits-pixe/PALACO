import { readFileSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => {
  if (command === 'build') return { plugins: [react()] }
  const https = {
    key: readFileSync(new URL('./certs/localhost-key.pem', import.meta.url)),
    cert: readFileSync(new URL('./certs/localhost.pem', import.meta.url)),
  }
  const nonce = randomBytes(18).toString('base64')
  const local = {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    cors: false,
    https,
    allowedHosts: ['localhost', '127.0.0.1'],
    headers: {
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
      'Content-Security-Policy': `default-src 'self'; script-src 'self' 'nonce-${nonce}'; style-src 'self' 'nonce-${nonce}'; connect-src 'self' wss://localhost:5174 wss://127.0.0.1:5174; img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self' https://localhost:5173 https://127.0.0.1:5173`,
    },
    proxy: {
      '/api': { target: 'http://127.0.0.1:3006', changeOrigin: false },
      '/health': { target: 'http://127.0.0.1:3006', changeOrigin: false },
      '/.well-known/palaco-app.json': { target: 'http://127.0.0.1:3006', changeOrigin: false },
    },
  }
  return { plugins: [react()], html: { cspNonce: nonce }, server: local, preview: local }
})
