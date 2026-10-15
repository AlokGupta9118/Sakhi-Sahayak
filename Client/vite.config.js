import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Removed VitePWA locally to prevent chrome-error iframe conflicts during development
export default defineConfig({
  plugins: [react()]
})
