import { defineConfig, devices } from '@playwright/test';

const AUTH_FILE = 'e2e/.auth/user.json';

export default defineConfig({
    testDir: './e2e',
    fullyParallel: false,
    forbidOnly: !!process.env.CI,
    retries: 0,
    workers: 1,
    reporter: 'list',
    use: {
        baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:4321',
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
        video: 'off',
    },
    projects: [
        // 1. Setup: login once and save session
        {
            name: 'setup',
            testMatch: /auth\.setup\.ts/,
        },
        // 2. All tests run with saved auth state
        {
            name: 'chromium',
            use: {
                ...devices['Desktop Chrome'],
                storageState: AUTH_FILE,
            },
            dependencies: ['setup'],
        },
    ],
});
