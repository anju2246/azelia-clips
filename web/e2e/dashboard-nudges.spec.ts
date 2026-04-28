/**
 * Dashboard nudge matrix — 2×2 of (telemetry on/off) × (YouTube connected/not).
 *
 * Both nudges live in DashboardController.tsx and gate themselves on the
 * server's status endpoints. We mock those endpoints to put the dashboard in
 * each cell of the matrix and assert which nudges surface. This is the
 * regression net for "user declined everything → silent dashboard" — the bug
 * we just fixed by adding TelemetryNudge.
 */
import { test, expect, type Page } from '@playwright/test';

const NUDGE_KEYS = [
    'azelia_yt_nudge_dismissed',
    'azelia_telemetry_nudge_dismissed',
];

/**
 * Mock both status endpoints. Done inside `page.route` so the server can be
 * down — these tests run hermetically against the static dashboard.
 */
async function mockStatuses(page: Page, opts: { telemetryEnabled: boolean; youtubeConnected: boolean }) {
    await page.route('**/api/telemetry/status', route =>
        route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ telemetry_enabled: opts.telemetryEnabled, supabase_connected: true }),
        })
    );
    await page.route('**/api/analytics/youtube/status', route =>
        route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ connected: opts.youtubeConnected }),
        })
    );
}

async function loadDashboardClean(page: Page) {
    // Land on dashboard, then wipe any previous dismiss flags so each case
    // re-renders both nudges from scratch.
    await page.goto('/dashboard');
    await page.evaluate((keys) => keys.forEach(k => localStorage.removeItem(k)), NUDGE_KEYS);
    await page.reload();
    await page.waitForLoadState('networkidle');
}

test.describe('Dashboard nudges — telemetry × YouTube matrix', () => {
    test('(1) telemetry ON + YT connected → no nudge surfaces', async ({ page }) => {
        await mockStatuses(page, { telemetryEnabled: true, youtubeConnected: true });
        await loadDashboardClean(page);
        await expect(page.getByText(/Activate Collective Intelligence/i)).not.toBeVisible({ timeout: 3000 });
        await expect(page.getByText(/Connect YouTube to unlock Intelligence/i)).not.toBeVisible({ timeout: 3000 });
    });

    test('(2) telemetry ON + YT disconnected → only YouTube nudge surfaces', async ({ page }) => {
        await mockStatuses(page, { telemetryEnabled: true, youtubeConnected: false });
        await loadDashboardClean(page);
        await expect(page.getByText(/Connect YouTube to unlock Intelligence/i)).toBeVisible({ timeout: 5000 });
        await expect(page.getByText(/Activate Collective Intelligence/i)).not.toBeVisible({ timeout: 1500 });
    });

    test('(3) telemetry OFF + YT connected → only telemetry nudge surfaces', async ({ page }) => {
        await mockStatuses(page, { telemetryEnabled: false, youtubeConnected: true });
        await loadDashboardClean(page);
        await expect(page.getByText(/Activate Collective Intelligence/i)).toBeVisible({ timeout: 5000 });
        await expect(page.getByText(/Connect YouTube to unlock Intelligence/i)).not.toBeVisible({ timeout: 1500 });
    });

    test('(4) telemetry OFF + YT disconnected → both nudges surface (worst-case UX)', async ({ page }) => {
        await mockStatuses(page, { telemetryEnabled: false, youtubeConnected: false });
        await loadDashboardClean(page);
        await expect(page.getByText(/Connect YouTube to unlock Intelligence/i)).toBeVisible({ timeout: 5000 });
        await expect(page.getByText(/Activate Collective Intelligence/i)).toBeVisible({ timeout: 5000 });
    });

    test('telemetry nudge — dismiss persists across reloads', async ({ page }) => {
        await mockStatuses(page, { telemetryEnabled: false, youtubeConnected: true });
        await loadDashboardClean(page);

        const nudge = page.getByText(/Activate Collective Intelligence/i);
        await expect(nudge).toBeVisible({ timeout: 5000 });

        // The dismiss button is the X icon button inside the nudge container.
        // Locate by aria-label="Dismiss" scoped to the nudge.
        const dismissBtn = page.getByRole('button', { name: /^dismiss$/i }).last();
        await dismissBtn.click();
        await expect(nudge).not.toBeVisible({ timeout: 2000 });

        // Reload — should stay dismissed (localStorage flag).
        await page.reload();
        await page.waitForLoadState('networkidle');
        await expect(nudge).not.toBeVisible({ timeout: 3000 });
    });

    test('telemetry nudge — Activate CTA links to settings#privacy', async ({ page }) => {
        await mockStatuses(page, { telemetryEnabled: false, youtubeConnected: true });
        await loadDashboardClean(page);

        const cta = page.getByRole('link', { name: /^activate/i });
        await expect(cta).toBeVisible({ timeout: 5000 });
        await expect(cta).toHaveAttribute('href', '/dashboard/settings#privacy');
    });
});
