import { defineConfig } from '@playwright/test'

/**
 * The chain runs against a real environment (staging). One worker, one test at a time: the
 * Windows VM needs the cluster's whole quota, and the chain creates and removes real apps.
 */
export default defineConfig({
  testDir: './tests',
  timeout: 20 * 60 * 1000, // a Windows VM boots for minutes
  expect: { timeout: 20_000 },
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'https://appstore-staging.t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ignoreHTTPSErrors: false,
  },
})
