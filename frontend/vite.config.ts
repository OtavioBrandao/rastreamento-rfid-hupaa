import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// O projeto não instala @types/node; basta tipar a leitura do ambiente aqui.
declare const process: { env: Record<string, string | undefined> }

// scripts/dev.py repassa --api-port por aqui; sem a variável, mantém a porta padrão.
const api = process.env.RFID_API_URL ?? 'http://127.0.0.1:8010'

// changeOrigin false: a API compara o Origin do navegador com o Host recebido
// (proteção contra CSRF); o atalho em string do Vite reescreveria o Host.
const proxied = { target: api, changeOrigin: false }

export default defineConfig({
  plugins: [react()],
  server: { proxy: {
    '/api': proxied,
    '/tipos-equipamento': proxied,
    '/localizacoes': proxied,
    '/portais': proxied,
    '/leitores': proxied,
    '/equipamentos': proxied,
    // Sessão e administração usam a mesma origem e o cookie HttpOnly.
    '/auth': proxied,
    '/usuarios': proxied,
    '/auditorias': proxied,
  } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
