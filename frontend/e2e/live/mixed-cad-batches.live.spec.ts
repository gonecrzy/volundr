import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { liveEnabled, waitForWorkflowOutcome } from "./liveEnvironment";

type ProjectSpec = {
  name: string;
  prompt: string;
  fallbackAnswer: string;
  answers: Array<{ terms: string[]; answer: string }>;
};

const PROJECTS: ProjectSpec[] = [
  {
    name: "five-tray-wall-carrier",
    prompt: "Create a wall-mounted carrier that holds up to five 3600-size tackle trays. Each tray is 276 mm wide, 184 mm deep, and 44 mm thick. The trays should slide in from the front and stack vertically. Add a top carrying handle, a removable front retention bar, skeletonized side walls to reduce material, and four wall-mounting holes for #10 screws.",
    fallbackAnswer: "Millimeters; vertical wall mounting; front loading; up to five trays; ordinary FDM; use reasonable tray clearance; integral printed handle; removable front retention bar; #10 screws; one connected printable carrier unless the retention bar must be separate.",
    answers: [
      { terms: ["unit", "measure"], answer: "Millimeters." },
      { terms: ["capacity", "tray", "number", "many"], answer: "Up to five trays; fewer may be present." },
      { terms: ["mount", "orient"], answer: "Vertical wall mounting." },
      { terms: ["load", "slide", "direction"], answer: "Load trays from the front." },
      { terms: ["handle"], answer: "Use an integral printed handle." },
      { terms: ["retain", "bar"], answer: "Use a removable front retention bar." },
      { terms: ["screw", "fastener"], answer: "Use #10 wall-mounting screws." },
      { terms: ["clearance"], answer: "Use a reasonable tray-clearance proposal." },
    ],
  },
  {
    name: "two-tray-portable-holder",
    prompt: "Create a compact portable holder for two 3600-size tackle trays measuring 276 mm wide, 184 mm deep, and 44 mm thick. The trays load vertically from the top. Add a carrying handle on the right side, drainage openings in the bottom, two slots for a removable retention strap, and mostly open side walls to reduce material.",
    fallbackAnswer: "Millimeters; exactly two trays; freestanding; top loading; use reasonable clearance; integral right-side handle; external removable strap; bottom supports trays around drainage openings; ordinary FDM.",
    answers: [
      { terms: ["unit", "measure"], answer: "Millimeters." },
      { terms: ["capacity", "tray", "number", "many"], answer: "Exactly two trays." },
      { terms: ["load", "orient", "top"], answer: "Load vertically from the top." },
      { terms: ["handle"], answer: "Use an integral handle on the right side." },
      { terms: ["strap", "retain"], answer: "The retention strap is external and removable." },
      { terms: ["drain", "bottom", "support"], answer: "Use drainage openings while preserving bottom support." },
      { terms: ["clearance"], answer: "Use a reasonable tray-clearance proposal." },
    ],
  },
  {
    name: "desktop-organizer",
    prompt: "Create a one-piece desktop organizer that is 220 mm wide, 140 mm deep, and 65 mm tall. Use a 4 mm base and 3 mm walls. Across the rear, add a 180 mm wide, 18 mm deep slot for a phone or small tablet. In the front-left, add a 75 mm by 75 mm pen compartment. Divide the remaining front area into two unequal accessory compartments, with the center compartment 55 mm wide. Add a 12 mm wide cable notch in the rear wall and use 8 mm outside corner radii.",
    fallbackAnswer: "Millimeters; one connected open-top printable part; external overall dimensions; center the rear slot and cable notch; use 3 mm dividers; calculate the remaining front-right width; notch passes through the rear wall only; ordinary FDM.",
    answers: [
      { terms: ["unit", "measure"], answer: "Millimeters." },
      { terms: ["open", "top"], answer: "One connected printable part with an open top." },
      { terms: ["dimension", "overall", "external"], answer: "The overall dimensions are external." },
      { terms: ["slot", "phone", "tablet"], answer: "Center the rear slot." },
      { terms: ["compartment", "remaining", "width"], answer: "Calculate the remaining front-right width; use a 55 mm center compartment and 3 mm dividers." },
      { terms: ["notch", "cable"], answer: "Center the 12 mm cable notch in the rear wall; it passes through the wall, not the base." },
    ],
  },
  {
    name: "fixed-monitor-wall-mount",
    prompt: "Create a two-piece fixed wall mount for a monitor weighing up to 5 kg and using a VESA 100 mm by 100 mm mounting pattern. Use one wall plate and one monitor plate. The monitor plate should slide downward onto the wall plate and be secured with two M4 locking screws inserted from below. Use four 6 mm wall fastener holes in a 120 mm by 80 mm rectangular pattern. Keep the rear of the monitor plate approximately 35 mm from the wall. Do not add tilt or swivel.",
    fallbackAnswer: "Millimeters; fixed two-piece mount; maximum monitor mass 5 kg; VESA 100 by 100 mm with M4 fasteners; two M4 locking screws from below; four 6 mm wall holes in a 120 by 80 mm pattern; approximately 35 mm wall offset; no tilt or swivel; physical engineering review required before load-bearing use.",
    answers: [
      { terms: ["unit", "measure"], answer: "Millimeters." },
      { terms: ["weight", "mass", "load", "monitor"], answer: "The maximum monitor mass is 5 kg; physical engineering review is required before load-bearing use." },
      { terms: ["vesa", "pattern"], answer: "Use a 100 by 100 mm VESA pattern with M4 fasteners." },
      { terms: ["lock", "screw", "fastener"], answer: "Use two M4 locking screws inserted from below." },
      { terms: ["output", "piece", "component"], answer: "Use two printable outputs: one wall plate and one monitor plate." },
      { terms: ["offset", "wall", "distance"], answer: "Keep the rear of the monitor plate approximately 35 mm from the wall." },
      { terms: ["tilt", "swivel"], answer: "No tilt and no swivel." },
    ],
  },
  {
    name: "screw-lid-container",
    prompt: "Create a cylindrical storage container with a screw-on lid. The container must have a 90 mm internal diameter and 120 mm usable internal height. Use 3 mm walls and a 4 mm base. The lid should overlap the container by 18 mm. Use a coarse single-start printable thread with a 4 mm pitch, approximately 1.5 mm thread depth, and 0.4 mm radial clearance. Add vertical grip ribs around the outside of the lid and a 4 mm rounded edge around the outside bottom of the container.",
    fallbackAnswer: "Millimeters; two printable outputs body and lid; 90 mm internal diameter; 120 mm usable internal height; 3 mm walls; 4 mm base; 18 mm lid overlap; single-start 4 mm pitch thread with about 1.5 mm depth and 0.4 mm radial clearance; fully removable lid; no watertight guarantee.",
    answers: [
      { terms: ["unit", "measure"], answer: "Millimeters." },
      { terms: ["output", "piece", "component"], answer: "Use two printable outputs: body and lid." },
      { terms: ["diameter"], answer: "The internal diameter is 90 mm." },
      { terms: ["height"], answer: "The usable internal height is 120 mm." },
      { terms: ["overlap"], answer: "The lid overlap is 18 mm." },
      { terms: ["thread", "pitch", "clearance"], answer: "Use a coarse single-start thread, 4 mm pitch, about 1.5 mm depth, and 0.4 mm radial clearance." },
      { terms: ["watertight", "seal"], answer: "Do not assume a watertight guarantee." },
    ],
  },
];

const liveDataDir = process.env.VOLUNDR_LIVE_DATA_DIR ?? "/tmp/volundr-live-e2e-unconfigured";

async function ensureDir(directory: string) {
  await fs.mkdir(directory, { recursive: true });
}

function sessionRoot(batchId: string) {
  return path.join(liveDataDir, "data", "debug-sessions", batchId);
}

async function screenshot(page: Page, batchId: string, filename: string) {
  const directory = path.join(sessionRoot(batchId), "screenshots");
  await ensureDir(directory);
  await page.screenshot({ path: path.join(directory, filename), fullPage: true });
}

function answerForQuestion(spec: ProjectSpec, question: string) {
  const normalized = question.toLowerCase();
  return spec.answers.find((entry) => entry.terms.some((term) => normalized.includes(term)))?.answer ?? spec.fallbackAnswer;
}

async function startBatch(page: Page, label: string, notes: string, baselineBatchId?: string, screenshotTag = label) {
  await page.getByRole("button", { name: "Debug batch", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Start live debug batch", exact: true })).toBeVisible();
  await page.getByLabel("Batch name").fill(label);
  await page.getByLabel("Target projects").fill("5");
  await page.getByLabel("Batch notes").fill(notes);
  if (baselineBatchId) {
    await page.getByLabel("Baseline batch").selectOption(baselineBatchId);
  }
  const pendingScreenshot = path.join(liveDataDir, "data", "debug-sessions", "pending", `${label}-start.png`);
  await ensureDir(path.dirname(pendingScreenshot));
  await page.screenshot({ path: pendingScreenshot, fullPage: true });
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/debug-batches") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Start batch", exact: true }).click();
  const response = await responsePromise;
  expect(response.ok(), "debug batch start").toBeTruthy();
  const batch = await response.json() as { id: string; label: string };
  const destination = path.join(sessionRoot(batch.id), "screenshots", `${screenshotTag}-batch-start.png`);
  await ensureDir(path.dirname(destination));
  await fs.rename(pendingScreenshot, destination);
  await expect(page.getByText(new RegExp(`Debug batch: ${label}`))).toBeVisible();
  await screenshot(page, batch.id, `${screenshotTag}-batch-empty.png`);
  const close = page.locator(".debug-batch-drawer").getByRole("button", { name: "Close", exact: true });
  if (await close.isVisible()) {
    await close.click();
  }
  return batch.id;
}

async function openNextProject(page: Page, first: boolean) {
  if (first) {
    await page.goto("/");
    return null;
  }
  await page.goto("/");
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const draftResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/projects/draft") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "New project", exact: true }).click();
  const response = await draftResponsePromise;
  return await response.json() as { id: string };
}

async function answerClarifications(page: Page, projectId: string, spec: ProjectSpec, batchId: string, screenshotTag: string, projectNumber: number) {
  for (let round = 0; round < 2; round += 1) {
    await expect.poll(async () => {
      const requirements = page.locator('[aria-label="Design requirements"]');
      if (await requirements.count() && await requirements.isVisible()) return "requirements";
      if (await page.getByRole("heading", { name: /New version|Current working version|Creating new version/ }).count()) return "outcome";
      if (await page.getByText(/failed|could not|unable|blocked|rejected/i).count()) return "outcome";
      return "waiting";
    }, { timeout: 240_000, intervals: [1_000, 2_000, 4_000] }).not.toBe("waiting");

    const requirements = page.locator('[aria-label="Design requirements"]');
    if (await requirements.getByText("A few details are still needed", { exact: true }).count()) {
      await screenshot(page, batchId, `${screenshotTag}-project-${String(projectNumber).padStart(2, "0")}-clarification.png`);
      const inputs = requirements.locator("input");
      for (let index = 0; index < await inputs.count(); index += 1) {
        const question = await inputs.nth(index).evaluate((input) => input.parentElement?.innerText ?? "");
        await inputs.nth(index).fill(answerForQuestion(spec, question));
      }
      await requirements.getByRole("button", { name: "Continue", exact: true }).click();
      await page.waitForTimeout(750);
      await screenshot(page, batchId, `${screenshotTag}-project-${String(projectNumber).padStart(2, "0")}-answer-${round + 1}.png`);
      await waitForProjectRunSettled(page, projectId);
      await page.reload();
      continue;
    }

    const answerButton = page.getByRole("button", { name: "Answer", exact: true });
    if (await answerButton.count() && await answerButton.isEnabled()) {
      const question = await requirements.innerText().catch(() => "clarification needed");
      await screenshot(page, batchId, `${screenshotTag}-project-${String(projectNumber).padStart(2, "0")}-clarification.png`);
      await page.getByLabel("AI chat message").fill(answerForQuestion(spec, question));
      await answerButton.click();
      await page.waitForTimeout(750);
      await screenshot(page, batchId, `${screenshotTag}-project-${String(projectNumber).padStart(2, "0")}-answer-${round + 1}.png`);
      await waitForProjectRunSettled(page, projectId);
      await page.reload();
      continue;
    }
    break;
  }
}

async function waitForProjectRunSettled(page: Page, projectId: string) {
  await expect.poll(async () => {
    const response = await page.request.get(`/api/projects/${projectId}/workflow-runs`);
    if (!response.ok()) return "waiting";
    const runs = await response.json() as Array<{ status: string }>;
    if (runs.length === 0 || runs.some((run) => ["running", "pending"].includes(run.status))) return "running";
    return "settled";
  }, { timeout: 300_000, intervals: [1_000, 2_000, 5_000] }).toBe("settled");
}

async function runProject(page: Page, batchId: string, screenshotTag: string, spec: ProjectSpec, projectNumber: number, first: boolean) {
  const createdProject = await openNextProject(page, first);
  const draftResponsePromise = first
    ? page.waitForResponse(
        (response) => response.url().endsWith("/api/projects/draft") && response.request().method() === "POST",
      )
    : null;
  await page.getByLabel("AI chat message").fill(spec.prompt);
  await screenshot(page, batchId, `${screenshotTag}-project-${String(projectNumber).padStart(2, "0")}-initial.png`);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const draft = createdProject ?? await (await draftResponsePromise!).json() as { id: string };

  await waitForProjectRunSettled(page, draft.id);
  await page.reload();
  await answerClarifications(page, draft.id, spec, batchId, screenshotTag, projectNumber);
  const outcome = await waitForWorkflowOutcome(page);
  const accept = page.getByRole("button", { name: "Accept new version", exact: true });
  if (outcome === "candidate" && await accept.count() && await accept.isEnabled()) {
    await accept.click();
    await expect(page.getByRole("heading", { name: /Current working version|Current design/ }).first()).toBeVisible({ timeout: 60_000 });
  }
  await screenshot(page, batchId, `${screenshotTag}-project-${String(projectNumber).padStart(2, "0")}-final.png`);

  if (outcome === "candidate" && projectNumber === 1) {
    const exportButton = page.getByRole("button", { name: "Export", exact: true }).first();
    if (await exportButton.count() && await exportButton.isEnabled()) {
      await exportButton.click();
      await expect(page.getByRole("dialog", { name: "Export" })).toBeVisible();
      await screenshot(page, batchId, `${screenshotTag}-project-01-export.png`);
      await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Close", exact: true }).click();
    }
  }
  return { projectId: draft.id, outcome };
}

async function finishBatch(page: Page, batchId: string, label: string) {
  await page.getByRole("button", { name: "View batch", exact: true }).click();
  await expect(page.locator(".debug-batch-drawer")).toBeVisible();
  await screenshot(page, batchId, `${label}-batch-drawer-complete.png`);
  await page.locator(".debug-batch-drawer").getByRole("button", { name: "Finish batch", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Finish debug batch?", exact: true })).toBeVisible();
  await screenshot(page, batchId, `${label}-finish-confirmation.png`);
  await page.getByRole("button", { name: "Finish batch", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Debug batch complete", exact: true })).toBeVisible({ timeout: 240_000 });
  await screenshot(page, batchId, `${label}-batch-summary.png`);
  const report = await page.request.get(`/api/debug-batches/${batchId}/report`).then(async (response) => {
    expect(response.ok(), "debug batch report").toBeTruthy();
    return response.json();
  });
  return report;
}

test.describe.serial("mixed CAD live debug batches", () => {
  test.skip(!liveEnabled, "Opt-in live suite; set VOLUNDR_RUN_LIVE_E2E=true.");

  test("runs the unchanged five-project pair and freezes evidence", async ({ page }) => {
    test.setTimeout(1_800_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");

    const batchOne = await startBatch(page, "mixed-cad-live-01", "First unchanged live run of five varied functional CAD projects.", undefined, "mixed-01");
    const batchOneProjects = [];
    for (let index = 0; index < PROJECTS.length; index += 1) {
      batchOneProjects.push(await runProject(page, batchOne, "mixed-01", PROJECTS[index], index + 1, index === 0));
    }
    const batchOneReport = await finishBatch(page, batchOne, "mixed-01");

    await page.goto("/");
    const batchTwo = await startBatch(
      page,
      "mixed-cad-live-02",
      "Second unchanged live run of the same five prompts to measure provider and runtime variability.",
      batchOne,
      "mixed-02",
    );
    const batchTwoProjects = [];
    for (let index = 0; index < PROJECTS.length; index += 1) {
      batchTwoProjects.push(await runProject(page, batchTwo, "mixed-02", PROJECTS[index], index + 1, index === 0));
    }
    const batchTwoReport = await finishBatch(page, batchTwo, "mixed-02");
    const comparisonResponse = await page.request.get(`/api/debug-batches/${batchTwo}/comparison`);
    expect(comparisonResponse.ok(), "controlled comparison endpoint").toBeTruthy();
    const comparison = await comparisonResponse.json();
    await screenshot(page, batchTwo, "mixed-batch-comparison.png");

    await fs.writeFile(
      path.join(sessionRoot(batchOne), "live-batch-manifest.json"),
      JSON.stringify({ batch_id: batchOne, projects: batchOneProjects, report: batchOneReport }, null, 2),
      "utf-8",
    );
    await fs.writeFile(
      path.join(sessionRoot(batchTwo), "live-batch-manifest.json"),
      JSON.stringify({ batch_id: batchTwo, projects: batchTwoProjects, report: batchTwoReport, comparison }, null, 2),
      "utf-8",
    );
    expect(comparison.status).toBe("controlled");
    expect(comparison.identity_match).toBe(true);
  });
});
