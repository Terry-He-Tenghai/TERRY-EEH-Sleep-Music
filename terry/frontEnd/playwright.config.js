import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './browser-tests', timeout: 45000, workers: 1,
  use: { baseURL: 'http://127.0.0.1:5178', headless: true, launchOptions: { args: ['--mute-audio'] } },
  webServer: { command: 'pnpm dev --host 127.0.0.1 --port 5178 --strictPort', url: 'http://127.0.0.1:5178', reuseExistingServer: false },
})
