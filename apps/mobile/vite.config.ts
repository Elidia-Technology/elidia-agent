import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    // Tauri's Android dev flow serves the UI to the device over the network,
    // so binding to localhost only would make it unreachable from the phone.
    host: '0.0.0.0',
    port: 1420,
    strictPort: true,
  },
  build: { target: 'es2021', sourcemap: false },
})
