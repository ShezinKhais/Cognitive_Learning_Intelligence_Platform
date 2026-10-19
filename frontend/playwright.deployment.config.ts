import { defineConfig } from '@playwright/test'
import process from 'node:process'

// Opt-in only. Never start a server or silently target a developer's database.
const baseURL = process.env.CLIP_DEPLOYMENT_TEST_URL
if (!baseURL) throw new Error('Set CLIP_DEPLOYMENT_TEST_URL to an isolated development/demo deployment.')

export default defineConfig({
  testDir: './deployment-tests',
  outputDir: './deployment-test-results',
  workers: 1,
  timeout: 30_000,
  use: { baseURL, reducedMotion: 'reduce', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
