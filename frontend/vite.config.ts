import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  base: '/react-shell/',
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8999',
      '/login': 'http://127.0.0.1:8999',
      '/logout': 'http://127.0.0.1:8999',
      '/static': 'http://127.0.0.1:8999',
    },
  },
  build: {
    manifest: 'manifest.json',
    outDir: path.resolve(__dirname, '../app_cybersparker/static/react-shell'),
    emptyOutDir: true,
    minify: 'terser',
    terserOptions: {
      compress: { drop_console: false, drop_debugger: true },
    },
    rollupOptions: {
      input: path.resolve(__dirname, 'index.html'),
      output: {
        entryFileNames: 'assets/react-shell.js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name?.endsWith('.css')) {
            return 'assets/react-shell.css'
          }
          return 'assets/[name]-[hash][extname]'
        },
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-antd': ['antd', '@ant-design/icons'],
        },
      },
    },
  },
})
