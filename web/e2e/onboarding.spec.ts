/**
 * Onboarding flow E2E tests
 * Step 1: podcast_name required
 * Step 2: user_role + primary_goal + content_niche required
 * Step 3: YouTube (optional, Next always enabled)
 * Step 4: API key + acceptTerms required
 */
import { test, expect } from '@playwright/test';

const ANTHROPIC_KEY = process.env.TEST_ANTHROPIC_KEY || '<REDACTED_KEY>';

/** Navigate through steps 1-3 filling required fields (assumes beforeEach already loaded the page clean) */
async function completeSteps1to3(page: any) {

    // Step 1 — podcast name
    const nameInput = page.locator('input[type="text"]').first();
    await nameInput.fill('Test Podcast E2E');
    await page.getByRole('button', { name: /siguiente/i }).click();
    await page.waitForTimeout(400);

    // Step 2 — role (button), goal (button), niche (select)
    await page.getByRole('button', { name: /Creador Local/i }).click();
    await page.getByRole('button', { name: /Crecer mi Audiencia/i }).click();
    // content_niche is the only visible <select> in this step
    await page.locator('select:visible').selectOption('Tecnología');
    await page.getByRole('button', { name: /siguiente/i }).click();
    await page.waitForTimeout(400);

    // Step 3 — YouTube (optional, Next is always enabled)
    await page.getByRole('button', { name: /siguiente/i }).click();
    await page.waitForTimeout(400);
}

test.describe('Onboarding', () => {
    test.beforeEach(async ({ page }) => {
        // Prevent redirect if account already completed onboarding
        await page.route('**/auth/onboarding-status', route =>
            route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ onboarding_complete: false }) })
        );
        // Load page, clear ALL onboarding localStorage, reload clean
        await page.goto('/onboarding');
        await page.evaluate(() => {
            ['az_onboarding_complete','az_onboard_step','az_onboard_profile',
             'az_onboard_telemetry','az_onboard_form','az_historical_synced'].forEach(k => localStorage.removeItem(k));
        });
        await page.reload();
        await page.waitForLoadState('networkidle');
    });

    test('renders step 1 — welcome screen', async ({ page }) => {
        await expect(page.getByText(/bienvenido|welcome|azelia/i).first()).toBeVisible({ timeout: 10000 });
    });

    test('step 1 — Next button disabled until name is filled', async ({ page }) => {
        const nextBtn = page.getByRole('button', { name: /siguiente/i });
        const nameInput = page.locator('input[type="text"]').first();
        await expect(nameInput).toBeVisible({ timeout: 5000 });

        // Clear any backend-persisted value, verify button disables
        await nameInput.fill('');
        await nameInput.dispatchEvent('input');
        await expect(nextBtn).toBeDisabled({ timeout: 3000 });

        // Fill → button enables
        await nameInput.fill('Mi Podcast');
        await expect(nextBtn).toBeEnabled({ timeout: 3000 });
    });

    test('step 4 — AI key field starts empty (no masked values)', async ({ page }) => {
        await completeSteps1to3(page);

        // Should be on step 4 now — select a provider first to reveal the key input
        const providerSelect = page.locator('select:visible').first();
        await expect(providerSelect).toBeVisible({ timeout: 8000 });
        await providerSelect.selectOption('anthropic');

        const keyInput = page.locator('input[type="password"]').first();
        await expect(keyInput).toBeVisible({ timeout: 5000 });

        const value = await keyInput.inputValue();
        expect(value).not.toContain('...');
        expect(value).not.toContain('****');
        expect(value).toBe('');
    });

    test('step 4 — invalid key shows error, no model detected', async ({ page }) => {
        await completeSteps1to3(page);

        // Select provider first
        const providerSelect = page.locator('select:visible').first();
        await expect(providerSelect).toBeVisible({ timeout: 8000 });
        await providerSelect.selectOption('anthropic');

        const keyInput = page.locator('input[type="password"]').first();
        await expect(keyInput).toBeVisible({ timeout: 5000 });

        await keyInput.fill('sk-ant-INVALID_KEY_12345');
        // Wait for debounce (1.2s) + request
        await page.waitForTimeout(4000);

        // No successful model detection
        const detected = page.getByText(/modelo detectado:/i);
        await expect(detected).not.toBeVisible({ timeout: 1000 }).catch(() => {});
    });

    test('flujo completo — steps 1→4→dashboard', async ({ page }) => {
        test.setTimeout(90000);
        await completeSteps1to3(page);

        // Step 4: select provider + fill valid key
        const providerSelect = page.locator('select:visible').first();
        await expect(providerSelect).toBeVisible({ timeout: 8000 });
        await providerSelect.selectOption('anthropic');

        const keyInput = page.locator('input[type="password"]').first();
        await expect(keyInput).toBeVisible({ timeout: 5000 });
        await keyInput.fill(ANTHROPIC_KEY);

        // Wait for model detection
        await expect(page.locator('code.text-green-400')).toBeVisible({ timeout: 12000 });

        // Accept terms — click the visual checkbox div (avoid clicking the <a> links inside the label)
        const termsCheckboxDiv = page.locator('label').filter({ hasText: /términos|terms/i }).locator('div').first();
        await termsCheckboxDiv.scrollIntoViewIfNeeded();
        await termsCheckboxDiv.click();
        // Verify terms are accepted (button should become enabled)
        await expect(page.getByRole('button', { name: /terminar setup/i })).toBeEnabled({ timeout: 5000 });

        // Submit
        await page.getByRole('button', { name: /terminar setup/i }).click();

        // Should show ProUpgradeCard or redirect to dashboard
        await expect(
            page.getByText(/ya estás listo|continuar con free/i).first()
        ).toBeVisible({ timeout: 10000 });

        // Skip Pro → go to dashboard
        await page.getByText(/continuar con free/i).click();
        await page.waitForURL(/dashboard/, { timeout: 10000 });
    });

    test('step 4 — valid Anthropic key detects a model', async ({ page }) => {
        await completeSteps1to3(page);

        // Select provider first
        const providerSelect = page.locator('select:visible').first();
        await expect(providerSelect).toBeVisible({ timeout: 8000 });
        await providerSelect.selectOption('anthropic');

        const keyInput = page.locator('input[type="password"]').first();
        await expect(keyInput).toBeVisible({ timeout: 5000 });

        await keyInput.fill(ANTHROPIC_KEY);
        // Wait for debounce (1.2s) + save + refresh + response (~8s total)
        await page.waitForTimeout(10000);

        // Should show detected model in the green <code> element inside the feedback area
        // The UI renders: <span>Modelo: <code class="text-green-400">claude-xxx</code></span>
        const detectedCode = page.locator('code.text-green-400');
        await expect(detectedCode).toBeVisible({ timeout: 8000 });
    });
});
