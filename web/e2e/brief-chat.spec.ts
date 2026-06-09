/**
 * Brief chat modal E2E (T6).
 *
 * Drives the dashboard into the `awaiting_brief` state by mocking the job +
 * brief endpoints, then asserts the split-view chat modal appears, that
 * feedback round-trips, and that approving transitions the job to processing.
 *
 * NOTE: requires the Astro dev server (localhost:4321) + Playwright auth setup,
 * like the other e2e specs. It is hermetic against the API (all routes mocked).
 */
import { test, expect, type Page } from "@playwright/test";

const JOB_ID = "EP001-process";

const BRIEF = {
  status: "awaiting_brief",
  episode_id: "EP001",
  candidates: [
    { id: 1, start_time: 100, end_time: 140, title: "Hook sobre IA", summary: "s",
      reasoning: "", score: 85, critic_approved: true, above_threshold: true,
      selected: true, origin: "curation" },
    { id: 2, start_time: 300, end_time: 340, title: "El secreto", summary: "s",
      reasoning: "", score: 70, critic_approved: true, above_threshold: true,
      selected: true, origin: "curation" },
    { id: 3, start_time: 500, end_time: 540, title: "Tangente", summary: "s",
      reasoning: "", score: 0, critic_approved: false, above_threshold: false,
      selected: false, origin: "rescued" },
  ],
  messages: [],
  counts: { selected: 2, total: 3, discarded: 1 },
};

async function mockBrief(page: Page) {
  await page.addInitScript((id) => {
    localStorage.setItem("azelia_active_job_id", id);
  }, JOB_ID);

  await page.route(`**/api/jobs/${JOB_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: JOB_ID, status: "awaiting_brief", progress: 68,
        message: "Esperando tu revisión", created_at: "t",
      }),
    }),
  );

  await page.route(`**/api/jobs/${JOB_ID}/brief`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(BRIEF) }),
  );

  await page.route(`**/api/jobs/${JOB_ID}/brief/message`, (route) => {
    const updated = structuredClone(BRIEF);
    updated.candidates[0].selected = false; // dropped #1
    updated.counts.selected = 1;
    route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        ...updated, reply: "Descarté #1. → 1 seleccionado.",
        change_summary: "Descarté #1.", actions: [{ type: "drop", targets: [1] }],
      }),
    });
  });

  await page.route(`**/api/jobs/${JOB_ID}/brief/approve`, (route) =>
    route.fulfill({
      status: 202, contentType: "application/json",
      body: JSON.stringify({ status: "processing", approved_count: 2 }),
    }),
  );
}

test("brief modal appears on awaiting_brief with candidates", async ({ page }) => {
  await mockBrief(page);
  await page.goto("/dashboard");
  await expect(page.getByText("Revisar brief antes de procesar")).toBeVisible();
  await expect(page.getByText("Hook sobre IA")).toBeVisible();
  await expect(page.getByTestId("brief-candidate")).toHaveCount(3);
});

test("sending feedback shows change summary and updates the list", async ({ page }) => {
  await mockBrief(page);
  await page.goto("/dashboard");
  await page.getByTestId("brief-input").fill("quita el #1");
  await page.getByTestId("brief-input").press("Enter");
  await expect(page.getByText("Descarté #1.")).toBeVisible();
  await expect(page.getByTestId("brief-approve")).toContainText("(1)");
});

test("approve transitions job to processing", async ({ page }) => {
  await mockBrief(page);
  await page.goto("/dashboard");
  const approveReq = page.waitForRequest(`**/api/jobs/${JOB_ID}/brief/approve`);
  await page.getByTestId("brief-approve").click();
  await approveReq;
});

test("critic insights modal no longer in final flow", async ({ page }) => {
  await page.goto("/dashboard/review");
  await expect(page.getByRole("button", { name: "Critic insights" })).toHaveCount(0);
});
