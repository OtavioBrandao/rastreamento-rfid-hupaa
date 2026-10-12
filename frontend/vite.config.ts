import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// O projeto não instala @types/node; basta tipar a leitura do ambiente aqui.
declare const process: { env: Record<string, string | undefined> }

// scripts/dev.py repassa --api-port por aqui; sem a variável, mantém a porta padrão.
const api = process.env.RFID_API_URL ?? 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [react()],
  server: { proxy: {
    '/api': api,
    '/tipos-equipamento': api,
    '/localizacoes': api,
    '/portais': api,
    '/equipamentos': api,
  } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
