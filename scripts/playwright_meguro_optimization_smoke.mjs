import { createRequire } from "node:module";

const requireFromFrontend = createRequire("C:/master-course/frontend/package.json");
const { chromium } = requireFromFrontend("playwright");

const FRONTEND_ORIGIN = process.env.FRONTEND_ORIGIN || "http://127.0.0.1:5173";
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN || "http://127.0.0.1:8000";

function parseScenarioIdFromUrl(url) {
  const match = url.match(/\/scenarios\/([^/]+)\//);
  return match ? match[1] : null;
}

function parseTripCount(text) {
  const match = text.match(/tripCount\s*([\d,]+)/i);
  if (!match) {
    return 0;
  }
  return Number.parseInt(match[1].replace(/,/g, ""), 10) || 0;
}

async function waitForJobCompletion(request, jobId, timeoutMs = 300000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const response = await request.get(`${BACKEND_ORIGIN}/api/jobs/${jobId}`);
    if (!response.ok()) {
      throw new Error(`Failed to fetch job ${jobId}: ${response.status()}`);
    }
    const payload = await response.json();
    const status = String(payload.status || "");
    if (status === "completed" || status === "failed") {
      return payload;
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(`Timed out waiting for job completion: ${jobId}`);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    page.on("pageerror", (error) => {
      console.error("[pageerror]", error);
    });
    page.on("console", (message) => {
      const type = message.type();
      if (type === "error") {
        console.error("[console.error]", message.text());
      }
    });

    await page.goto(`${FRONTEND_ORIGIN}/scenarios`, { waitUntil: "domcontentloaded" });

    const createButton = page.locator("section button", { hasText: "Create" }).first();
    await createButton.waitFor({ state: "visible", timeout: 30000 });
    await createButton.click();

    await page.waitForURL(/\/scenarios\/[^/]+\/planning/, { timeout: 60000 });
    const scenarioId = parseScenarioIdFromUrl(page.url());
    if (!scenarioId) {
      throw new Error(`Failed to parse scenario id from URL: ${page.url()}`);
    }

    await page.goto(`${FRONTEND_ORIGIN}/scenarios/${scenarioId}/simulation-builder`, {
      waitUntil: "domcontentloaded",
    });
    await page.getByText("Step 1 Target Selection").waitFor({ timeout: 30000 });

    const depotMeguroButton = page
      .locator("button")
      .filter({ hasText: /目黒|meguro/i })
      .first();
    await depotMeguroButton.waitFor({ state: "visible", timeout: 30000 });
    await depotMeguroButton.click();

    const clearButton = page.getByRole("button", { name: /Clear/i }).first();
    await clearButton.waitFor({ state: "visible", timeout: 30000 });
    await clearButton.click();

    await page.locator('label:has-text("tripCount")').first().waitFor({ timeout: 30000 });
    const routeCards = page.locator('label:has-text("tripCount")');
    const routeCount = await routeCards.count();
    if (routeCount < 3) {
      throw new Error(`Expected at least 3 route cards, got ${routeCount}`);
    }

    const rankedRoutes = [];
    for (let index = 0; index < routeCount; index += 1) {
      const card = routeCards.nth(index);
      const text = await card.innerText();
      const lines = text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      rankedRoutes.push({
        index,
        name: lines[0] || `route-${index + 1}`,
        tripCount: parseTripCount(text),
      });
    }
    rankedRoutes.sort((left, right) => right.tripCount - left.tripCount);
    const top3 = rankedRoutes.slice(0, 3);

    for (const item of top3) {
      const checkbox = routeCards.nth(item.index).locator('input[type="checkbox"]');
      await checkbox.check({ force: true });
    }

    const prepareResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/scenarios/")
        && response.url().includes("/simulation/prepare")
        && response.request().method() === "POST",
      { timeout: 120000 },
    );
    const prepareButton = page.getByRole("button", { name: /入力データ作成|Preparing/i });
    await prepareButton.click();
    const prepareResponse = await prepareResponsePromise;
    if (!prepareResponse.ok()) {
      throw new Error(`Prepare request failed with status ${prepareResponse.status()}`);
    }
    const prepareResult = await prepareResponse.json();
    if (!prepareResult.ready) {
      throw new Error(`Prepared input is not ready: ${JSON.stringify(prepareResult)}`);
    }

    try {
      await page.goto(`${FRONTEND_ORIGIN}/scenarios/${scenarioId}/optimization`, {
        waitUntil: "domcontentloaded",
      });
      await page.waitForLoadState("networkidle", { timeout: 60000 });
    } catch (error) {
      console.error("[warn] optimization page load was unstable:", error);
    }

    const runResponse = await page.request.post(
      `${BACKEND_ORIGIN}/api/scenarios/${scenarioId}/run-optimization`,
      {
        data: {
          mode: "mode_milp_only",
          time_limit_seconds: 120,
          mip_gap: 0.01,
          random_seed: 42,
          rebuild_dispatch: true,
          use_existing_duties: false,
          alns_iterations: 200,
        },
      },
    );
    if (!runResponse.ok()) {
      throw new Error(`Run optimization request failed with status ${runResponse.status()}`);
    }
    const runJob = await runResponse.json();
    const jobId = runJob.job_id;
    if (!jobId) {
      throw new Error(`Run optimization response missing job_id: ${JSON.stringify(runJob)}`);
    }

    const completedJob = await waitForJobCompletion(page.request, jobId);
    const optimizationResponse = await page.request.get(
      `${BACKEND_ORIGIN}/api/scenarios/${scenarioId}/optimization`,
    );
    if (!optimizationResponse.ok()) {
      throw new Error(`Failed to fetch optimization result: ${optimizationResponse.status()}`);
    }
    const optimizationResult = await optimizationResponse.json();

    const summary = {
      scenarioId,
      selectedDepot: "meguro",
      selectedTop3Routes: top3,
      preparedInputId: prepareResult.preparedInputId,
      prepareTripCount: prepareResult.tripCount,
      optimizationJobId: jobId,
      optimizationJobStatus: completedJob.status,
      solverStatus: optimizationResult.solver_status,
      objectiveMode: optimizationResult.objective_mode,
      objectiveValue: optimizationResult.objective_value,
      servedTrips: optimizationResult.summary?.trip_count_served,
      unservedTrips: optimizationResult.summary?.trip_count_unserved,
      totalCost: optimizationResult.cost_breakdown?.total_cost,
    };

    console.log(JSON.stringify(summary, null, 2));
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
