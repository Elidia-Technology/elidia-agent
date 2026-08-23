import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  test: {
    // Collect ONLY first-party renderer tests. Two directories otherwise leak in:
    //  - `release/`: electron-builder output whose packaged bundles vendor
    //    node-pty's own *.test.js files (they fail with "describe is not
    //    defined" / missing `ps-list`). Vitest's default exclude list has no
    //    entry for it.
    //  - `electron/*.test.cjs`: those use the `node:test` runner, not vitest,
    //    so vitest reports "No test suite found".
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['**/node_modules/**', '**/dist/**', 'release/**'],
    // Renderer tests render React components, which need a DOM. Without this
    // vitest defaults to the `node` environment and every component test dies
    // on `ReferenceError: document is not defined` — 18 of 42 files and 76
    // tests were failing that way, so the suite ran green-ish in CI while
    // giving no signal at all on component behaviour.
    environment: 'jsdom'
  },
  build: {
    // Keep desktop packaging stable: Shiki ships many dynamic chunks by
    // default, and electron-builder can OOM scanning thousands of files.
    rolldownOptions: {
      output: {
        codeSplitting: false
      }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@elidia/shared': path.resolve(__dirname, '../shared/src'),
      react: path.resolve(__dirname, '../../node_modules/react'),
      'react-dom': path.resolve(__dirname, '../../node_modules/react-dom'),
      'react/jsx-dev-runtime': path.resolve(__dirname, '../../node_modules/react/jsx-dev-runtime.js'),
      'react/jsx-runtime': path.resolve(__dirname, '../../node_modules/react/jsx-runtime.js')
    },
    dedupe: ['react', 'react-dom']
  },
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true
  },
  preview: {
    host: '127.0.0.1',
    port: 4174
  }
})
