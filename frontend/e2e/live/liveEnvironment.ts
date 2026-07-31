import { expect, type Page, type TestInfo } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import zlib from "node:zlib";

export const liveEnabled = process.env.VOLUNDR_RUN_LIVE_E2E === "true";

type WorkflowRun = {
  id: string;
  project_id: string;
  workflow_type: string;
  parent_workflow_run_id: string | null;
  root_workflow_run_id: string | null;
  correlation_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
};

type GenerationAttempt = {
  attempt_id: string;
  provider: string;
  model: string | null;
  status: string;
  duration_ms: number | null;
  estimated_prompt_tokens: number | null;
  estimated_output_tokens: number | null;
};

type BrowserQuality = {
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
  httpErrors: string[];
};

export function installBrowserQualityChecks(page: Page): {
  assertClean: () => Promise<void>;
  snapshot: () => BrowserQuality;
} {
  const quality: BrowserQuality = {
    consoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    httpErrors: [],
  };
  const allowedOptional404 = [
    "/geometric-analysis",
    "/component-revision-summary",
    "/compliance-result",
    "/success-results",
  ];

  page.on("console", (message) => {
    if (message.type() === "error") {
      if (message.text().includes("Failed to load resource") && /409|502/.test(message.text())) {
        return;
      }
      quality.consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => quality.pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    if (request.url().includes("/debug-bundle.zip")) {
      return;
    }
    quality.failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText ?? "failed"}`);
  });
  page.on("response", (response) => {
    if (response.status() < 400) {
      return;
    }
    const url = new URL(response.url());
    if (response.status() === 404 && allowedOptional404.some((part) => url.pathname.endsWith(part))) {
      return;
    }
    if ([409, 502].includes(response.status()) && /requirements|design-plans|generate/.test(url.pathname)) {
      return;
    }
    quality.httpErrors.push(`${response.status()} ${response.request().method()} ${response.url()}`);
  });

  return {
    snapshot: () => ({
      consoleErrors: [...quality.consoleErrors],
      pageErrors: [...quality.pageErrors],
      failedRequests: [...quality.failedRequests],
      httpErrors: [...quality.httpErrors],
    }),
    assertClean: async () => {
      expect(quality.consoleErrors, "browser console errors").toEqual([]);
      expect(quality.pageErrors, "unhandled browser exceptions").toEqual([]);
      expect(quality.failedRequests, "failed browser requests").toEqual([]);
      expect(quality.httpErrors, "unexplained HTTP errors").toEqual([]);
    },
  };
}

export async function waitForWorkflowOutcome(page: Page): Promise<"candidate" | "failure"> {
  await expect.poll(
    async () => {
      if (await page.getByRole("heading", { name: "New version", exact: true }).count()) {
        return "candidate";
      }
      if (await page.getByText(/failed|could not|unable to|request failed|did not implement|mismatch|rejected/i).count()) {
        return "failure";
      }
      return "waiting";
    },
    { timeout: 220_000, intervals: [500, 1_000, 2_000] },
  ).not.toBe("waiting");

  return (await page.getByRole("heading", { name: "New version", exact: true }).count())
    ? "candidate"
    : "failure";
}

export async function answerRequirementClarificationIfShown(
  page: Page,
): Promise<{ count: number; ready: boolean }> {
  const requirements = page.locator('[aria-label="Design requirements"]');
  const isReady = async () => Boolean(
    (await requirements.getByText("Your requirements", { exact: true }).count()) ||
      (await requirements.getByRole("button", { name: "Review proposed design", exact: true }).count()) ||
      (await page.getByText("Requirements are ready", { exact: true }).count()),
  );
  if (await requirements.getByText("A few details are still needed", { exact: true }).count()) {
    const inputs = requirements.locator("input");
    const count = await inputs.count();
    for (let index = 0; index < count; index += 1) {
      if (!(await inputs.nth(index).inputValue())) {
        await inputs.nth(index).fill("20 mm");
      }
    }
    await requirements.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(requirements.getByText("Your requirements", { exact: true })).toBeVisible();
    return { count, ready: true };
  }

  let count = 0;
  for (let index = 0; index < 5; index += 1) {
    if (await isReady()) {
      return count;
    }
    const answerButton = page.getByRole("button", { name: "Answer", exact: true });
    if (!(await answerButton.count())) {
      break;
    }
    await page.getByLabel("AI chat message").fill(
      "Use 20 mm height, a simple snap-fit removable top, and no external mounting tabs. The supplied PCB width and depth must remain unchanged.",
    );
    await expect(answerButton).toBeEnabled({ timeout: 120_000 });
    await answerButton.click();
    count += 1;
    await expect.poll(
      async () => {
        if (await isReady()) {
          return "ready";
        }
        const nextAnswer = page.getByRole("button", { name: "Answer", exact: true });
        return (await nextAnswer.count()) && (await nextAnswer.isEnabled()) ? "next" : "waiting";
      },
      { timeout: 180_000, intervals: [500, 1_000, 2_000] },
    ).not.toBe("waiting");
  }
  return {
    count,
    ready: await isReady(),
  };
}

export async function advanceToGeneration(page: Page): Promise<void> {
  const requirements = page.locator('[aria-label="Design requirements"]');
  await requirements.getByRole("button", { name: "Review proposed design", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Proposed design", exact: true })).toBeVisible();

  const planClarification = page.getByRole("button", { name: "Answer", exact: true });
  if (await planClarification.count()) {
    await page.getByLabel("AI chat message").fill("20 mm height and ordinary print clearance are acceptable.");
    await planClarification.click();
    await expect(page.getByRole("heading", { name: "Proposed design", exact: true })).toBeVisible();
  }

  await page.getByRole("button", { name: "Generate design", exact: true }).first().click();
}

export async function collectLiveEvidence(
  page: Page,
  projectId: string,
  scenario: string,
  finalState: string,
  testInfo: TestInfo,
  quality: BrowserQuality,
): Promise<void> {
  await page.waitForTimeout(1_500);
  const runsResponse = await page.request.get(`/api/projects/${projectId}/workflow-runs`);
  expect(runsResponse.ok(), "workflow run listing").toBeTruthy();
  const runs = (await runsResponse.json()) as WorkflowRun[];
  expect(runs.length, "workflow run exists").toBeGreaterThan(0);

  const attemptsResponse = await page.request.get(`/api/projects/${projectId}/generation-attempts`);
  expect(attemptsResponse.ok(), "generation-attempt evidence").toBeTruthy();
  const attempts = (await attemptsResponse.json()) as GenerationAttempt[];
  expect(attempts.length, "live provider call evidence").toBeGreaterThan(0);
  expect(attempts.some((attempt) => attempt.provider === "gemini_api"), "Gemini provider evidence").toBeTruthy();
  expect(attempts.some((attempt) => (attempt.duration_ms ?? 0) > 0), "provider latency evidence").toBeTruthy();

  const eventsByRun = await Promise.all(
    runs.map(async (run) => {
      const response = await page.request.get(`/api/workflow-runs/${run.id}/events`);
      expect(response.ok(), `events for workflow ${run.id}`).toBeTruthy();
      return { run, events: (await response.json()) as Array<{ event_type: string; sequence_number: number }> };
    }),
  );
  for (const entry of eventsByRun) {
    const sequence = entry.events.map((event) => event.sequence_number);
    expect(sequence, `deterministic event order for ${entry.run.id}`).toEqual([...sequence].sort((a, b) => a - b));
    expect(new Set(sequence).size, `unique event sequence for ${entry.run.id}`).toBe(sequence.length);
  }

  const revisionsResponse = await page.request.get(`/api/projects/${projectId}/revisions`);
  expect(revisionsResponse.ok()).toBeTruthy();
  const revisions = (await revisionsResponse.json()) as Array<Record<string, unknown>>;
  const candidate = revisions.find((revision) => revision.is_accepted !== true) ?? revisions.at(-1) ?? null;
  const outputs = candidate
    ? await page.request.get(`/api/revisions/${String(candidate.id)}/outputs`).then(async (response) => {
        if (!response.ok()) {
          return [];
        }
        return response.json();
      })
    : [];

  const latestRun = runs.at(-1) ?? runs[0];
  const details = page.locator("details.technical-details");
  await details.scrollIntoViewIfNeeded();
  if (!(await details.getByRole("link", { name: "Download diagnostic bundle", exact: true }).count())) {
    await details.locator("summary").click();
  }
  const bundleLink = details.getByRole("link", { name: "Download diagnostic bundle", exact: true });
  await expect(bundleLink, "diagnostic bundle action").toBeVisible();
  const bundleDownloadPromise = page.waitForEvent("download");
  await bundleLink.click();
  const bundleDownload = await bundleDownloadPromise;
  const bundlePath = await bundleDownload.path();
  expect(bundlePath, "diagnostic bundle path").toBeTruthy();
  const bundle = await readZip(bundlePath!);
  const names = [...bundle.keys()];
  for (const required of [
    "run-summary.json",
    "diagnosis.json",
    "event-log.ndjson",
    "frontend-events.ndjson",
    "stage-trace.json",
    "artifacts.json",
    "redaction-report.json",
  ]) {
    expect(names.some((name) => name.endsWith(`/${required}`)), `bundle contains ${required}`).toBeTruthy();
  }
  expect(new Set(names).size, "bundle has no duplicate entries").toBe(names.length);
  const runSummary = textEntry(bundle, "run-summary.json");
  const redactionReport = textEntry(bundle, "redaction-report.json");
  expect(runSummary).toContain("application_commit");
  expect(runSummary).toContain("prompt_versions");
  expect(redactionReport).toContain('"redaction_status": "confirmed"');
  expect(textEntry(bundle, "frontend-events.ndjson")).toMatch(/request_started|request_submitted|generation_started/);

  const evidence = {
    scenario,
    project_id: projectId,
    workflow_runs: runs,
    backend_event_types: eventsByRun.flatMap((entry) => entry.events.map((event) => event.event_type)),
    provider_attempts: attempts.map((attempt) => ({
      provider: attempt.provider,
      model: attempt.model,
      status: attempt.status,
      duration_ms: attempt.duration_ms,
      estimated_prompt_tokens: attempt.estimated_prompt_tokens,
      estimated_output_tokens: attempt.estimated_output_tokens,
    })),
    candidate_state: candidate?.review_state ?? null,
    topology: outputs,
    final_user_visible_state: finalState,
    diagnostic_bundle_run_id: latestRun.id,
    diagnostic_bundle_entries: names,
    browser_quality: quality,
  };
  await testInfo.attach(`${scenario}-live-evidence.json`, {
    body: JSON.stringify(evidence, null, 2),
    contentType: "application/json",
  });
}

function textEntry(entries: Map<string, Buffer>, suffix: string): string {
  const entry = [...entries.entries()].find(([name]) => name.endsWith(`/${suffix}`));
  expect(entry, `bundle text ${suffix}`).toBeTruthy();
  return entry![1].toString("utf8");
}

async function readZip(filePath: string): Promise<Map<string, Buffer>> {
  const data = await fs.readFile(filePath);
  const end = data.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  if (end < 0) {
    throw new Error("Downloaded diagnostic bundle is not a ZIP archive");
  }
  const entryCount = data.readUInt16LE(end + 10);
  const directoryOffset = data.readUInt32LE(end + 16);
  const entries = new Map<string, Buffer>();
  let cursor = directoryOffset;
  for (let index = 0; index < entryCount; index += 1) {
    if (data.readUInt32LE(cursor) !== 0x02014b50) {
      throw new Error("Invalid diagnostic bundle central directory");
    }
    const compression = data.readUInt16LE(cursor + 10);
    const compressedSize = data.readUInt32LE(cursor + 20);
    const nameLength = data.readUInt16LE(cursor + 28);
    const extraLength = data.readUInt16LE(cursor + 30);
    const commentLength = data.readUInt16LE(cursor + 32);
    const localOffset = data.readUInt32LE(cursor + 42);
    const name = data.subarray(cursor + 46, cursor + 46 + nameLength).toString("utf8");
    const localNameLength = data.readUInt16LE(localOffset + 26);
    const localExtraLength = data.readUInt16LE(localOffset + 28);
    const contentStart = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = data.subarray(contentStart, contentStart + compressedSize);
    const content = compression === 0 ? compressed : zlib.inflateRawSync(compressed);
    entries.set(name, content);
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}
