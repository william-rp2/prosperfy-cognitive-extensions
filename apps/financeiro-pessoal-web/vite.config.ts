import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const financeToken = env.FINANCE_API_TOKEN

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/api/finance': {
          target: 'http://127.0.0.1:8787',
          changeOrigin: true,
          configure: proxy => {
            proxy.on('proxyReq', proxyReq => {
              if (financeToken) {
                proxyReq.setHeader('Authorization', `Bearer ${financeToken}`)
              }
            })
          },
        },
        '/api': {
          target: 'http://127.0.0.1:8787',
          changeOrigin: true,
        },
      },
    },
  }
})
