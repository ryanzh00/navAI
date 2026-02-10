import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { defineConfig } from 'vite'

export default defineConfig({
  root: 'src',
  plugins: [react()],
  build: {
    emptyOutDir: true,
    outDir: '../dist',
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'src/popup/popup.html'),
        background: resolve(__dirname, 'src/background/index.ts'),
        content: resolve(__dirname, 'src/content/index.ts')
      },
      output: {
        entryFileNames: (chunkInfo) => {
          if (chunkInfo.name === 'index') return 'popup/[name].js';
          return '[name].js';
        },
        assetFileNames: '[name].[ext]',
        chunkFileNames: '[name].js',
        // Use ES modules - Chrome supports ES modules in service workers (Manifest V3)
        format: 'es'
      }
    },
    // Disable code splitting to bundle everything into single files
    cssCodeSplit: false
  }
})