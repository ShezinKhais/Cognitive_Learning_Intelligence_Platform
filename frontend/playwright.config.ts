import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e', timeout: 90_000, fullyParallel: false,
  workers: 1, retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4174', trace: 'retain-on-failure',
    launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'] },
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'chrome', use: { browserName: 'chromium', channel: 'chrome' } },
    { name: 'edge', use: { browserName: 'chromium', channel: 'msedge' } },
  ],
  webServer: {
    command: 'npm run build:e2e && npx vite preview --config vite.e2e.config.ts',
    url: 'http://127.0.0.1:4174/e2e/harness/index.html', timeout: 180_000,
  },
})
