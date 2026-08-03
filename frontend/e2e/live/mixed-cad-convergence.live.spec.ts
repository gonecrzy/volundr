import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const liveDataDir = process.env.VOLUNDR_LIVE_DATA_DIR ?? "/tmp/volundr-live-e2e-unconfigured";

const PROJECTS = [
  {
    name: "five-tray-wall-carrier",
    prompt: "Create a wall-mounted carrier that holds up to five 3600-size tackle trays. Each tray is 276 mm wide, 184 mm deep, and 44 mm thick. The trays should slide in from the front and stack vertically. Add a top carrying handle, a removable front retention bar, skeletonized side walls to reduce material, and four wall-mounting holes for #10 screws.",
    answers: [
      ["unit", "Millimeters."], ["capacity", "Up to five trays; fewer may be present."], ["mount", "Vertical wall mounting."],
      ["load", "Load trays from the front."], ["handle", "Use an integral printed handle."], ["retain", "Use a removable front retention bar."],
      ["screw", "Use #10 wall-mounting screws."], ["clearance", "Use a reasonable tray-clearance proposal."],
    ],
    fallback: "Millimeters; vertical wall mounting; front loading; up to five trays; ordinary FDM; use reasonable tray clearance; integral printed handle; removable front retention bar; #10 screws; one connected printable carrier unless the retention bar must be separate.",
  },
  {
    name: "two-tray-portable-holder",
    prompt: "Create a compact portable holder for two 3600-size tackle trays measuring 276 mm wide, 184 mm deep, and 44 mm thick. The trays load vertically from the top. Add a carrying handle on the right side, drainage openings in the bottom, two slots for a removable retention strap, and mostly open side walls to reduce material.",
    answers: [
      ["unit", "Millimeters."], ["capacity", "Exactly two trays."], ["load", "Load vertically from the top."], ["handle", "Use an integral handle on the right side."],
      ["strap", "The retention strap is external and removable."], ["drain", "Use drainage openings while preserving bottom support."], ["clearance", "Use a reasonable tray-clearance proposal."],
    ],
    fallback: "Millimeters; exactly two trays; freestanding; top loading; use reasonable clearance; integral right-side handle; external removable strap; bottom supports trays around drainage openings; ordinary FDM.",
  },
  {
    name: "desktop-organizer",
    prompt: "Create a one-piece desktop organizer that is 220 mm wide, 140 mm deep, and 65 mm tall. Use a 4 mm base and 3 mm walls. Across the rear, add a 180 mm wide, 18 mm deep slot for a phone or small tablet. In the front-left, add a 75 mm by 75 mm pen compartment. Divide the remaining front area into two unequal accessory compartments, with the center compartment 55 mm wide. Add a 12 mm wide cable notch in the rear wall and use 8 mm outside corner radii.",
    answers: [
      ["unit", "Millimeters."], ["open", "One connected printable part with an open top."], ["dimension", "The overall dimensions are external."],
      ["slot", "Center the rear slot."], ["compartment", "Calculate the remaining front-right width; use a 55 mm center compartment and 3 mm dividers."],
      ["notch", "Center the 12 mm cable notch in the rear wall; it passes through the wall, not the base."],
    ],
    fallback: "Millimeters; one connected open-top printable part; external overall dimensions; center the rear slot and cable notch; use 3 mm dividers; calculate the remaining front-right width; notch passes through the rear wall only; ordinary FDM.",
  },
  {
    name: "fixed-monitor-wall-mount",
    prompt: "Create a two-piece fixed wall mount for a monitor weighing up to 5 kg and using a VESA 100 mm by 100 mm mounting pattern. Use one wall plate and one monitor plate. The monitor plate should slide downward onto the wall plate and be secured with two M4 locking screws inserted from below. Use four 6 mm wall fastener holes in a 120 mm by 80 mm rectangular pattern. Keep the rear of the monitor plate approximately 35 mm from the wall. Do not add tilt or swivel.",
    answers: [
      ["unit", "Millimeters."], ["weight", "The maximum monitor mass is 5 kg; physical engineering review is required before load-bearing use."],
      ["vesa", "Use a 100 by 100 mm VESA pattern with M4 fasteners."], ["lock", "Use two M4 locking screws inserted from below."],
      ["output", "Use two printable outputs: one wall plate and one monitor plate."], ["offset", "Keep the rear of the monitor plate approximately 35 mm from the wall."], ["tilt", "No tilt and no swivel."],
    ],
    fallback: "Millimeters; fixed two-piece mount; maximum monitor mass 5 kg; VESA 100 by 100 mm with M4 fasteners; two M4 locking screws from below; four 6 mm wall holes in a 120 by 80 mm pattern; approximately 35 mm wall offset; no tilt or swivel; physical engineering review required before load-bearing use.",
  },
  {
    name: "screw-lid-container",
    prompt: "Create a cylindrical storage container with a screw-on lid. The container must have a 90 mm internal diameter and 120 mm usable internal height. Use 3 mm walls and a 4 mm base. The lid should overlap the container by 18 mm. Use a coarse single-start printable thread with a 4 mm pitch, approximately 1.5 mm thread depth, and 0.4 mm radial clearance. Add vertical grip ribs around the outside of the lid and a 4 mm rounded edge around the outside bottom of the container.",
    answers: [
      ["unit", "Millimeters."], ["output", "Use two printable outputs: body and lid."], ["diameter", "The internal diameter is 90 mm."], ["height", "The usable internal height is 120 mm."],
      ["overlap", "The lid overlap is 18 mm."], ["thread", "Use a coarse single-start thread, 4 mm pitch, about 1.5 mm depth, and 0.4 mm radial clearance."], ["watertight", "Do not assume a watertight guarantee."],
    ],
    fallback: "Millimeters; two printable outputs body and lid; 90 mm internal diameter; 120 mm usable internal height; 3 mm walls; 4 mm base; 18 mm lid overlap; single-start 4 mm pitch thread with about 1.5 mm depth and 0.4 mm radial clearance; fully removable lid; no watertight guarantee.",
  },
] as const;

function sessionRoot(batchId: string) {
  return path.join(liveDataDir, "data", "debug-sessions", batchId);
}

async function saveScreenshot(page: Page, batchId: string, filename: string) {
  const directory = path.join(sessionRoot(batchId), "screenshots");
  await fs.mkdir(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, filename), fullPage: true });
}

async function startBatch(page: Page, label: string, notes: string, baselineBatchId?: string) {
  await page.getByRole("button", { name: "Debug batch", exact: true }).click();
  await page.getByRole("heading", { name: "Start live debug batch", exact: true }).waitFor();
  await page.getByLabel("Batch name").fill(label);
  await page.getByLabel("Target projects").fill("5");
  await page.getByLabel("Batch notes").fill(notes);
  if (baselineBatchId) await page.getByLabel("Baseline batch").selectOption(baselineBatchId);
  const responsePromise = page.waitForResponse((response) => response.url().endsWith("/api/debug-batches") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Start batch", exact: true }).click();
  const batch = await (await responsePromise).json() as { id: string };
  await expect(page.getByText(new RegExp(`Debug batch: ${label}`))).toBeVisible();
  await saveScreenshot(page, batch.id, `${label}-batch-start.png`);
  return batch.id;
}

async function waitSettled(page: Page, projectId: string) {
  await expect.poll(async () => {
    const response = await page.request.get(`/api/projects/${projectId}/workflow-runs`);
    if (!response.ok()) return "waiting";
    const runs = await response.json() as Array<{ status: string }>;
    return runs.length > 0 && runs.some((run) => ["running", "pending"].includes(run.status)) ? "running" : "settled";
  }, { timeout: 300_000, intervals: [1_000, 2_000, 5_000] }).toBe("settled");
}

function answerFor(project: typeof PROJECTS[number], question: string) {
  const normalized = question.toLowerCase();
  return project.answers.find(([term]) => normalized.includes(term))?.[1] ?? project.fallback;
}

async function answerClarifications(page: Page, project: typeof PROJECTS[number]) {
  for (let round = 0; round < 2; round += 1) {
    const requirements = page.locator('[aria-label="Design requirements"]');
    if (await requirements.count() && await requirements.isVisible()) {
      const waiting = requirements.getByText("A few details are still needed", { exact: true });
      if (await waiting.count()) {
        const inputs = requirements.locator("input");
        for (let index = 0; index < await inputs.count(); index += 1) {
          const question = await inputs.nth(index).evaluate((input) => input.parentElement?.innerText ?? "");
          await inputs.nth(index).fill(answerFor(project, question));
        }
        await requirements.getByRole("button", { name: "Continue", exact: true }).click();
        continue;
      }
    }
    const answer = page.getByRole("button", { name: "Answer", exact: true });
    if (await answer.count() && await answer.isEnabled()) {
      await page.getByLabel("AI chat message").fill(answerFor(project, await requirements.innerText().catch(() => "clarification")));
      await answer.click();
      continue;
    }
    break;
  }
}

async function runProject(page: Page, batchId: string, project: typeof PROJECTS[number], position: number) {
  const created = await (await page.request.post("/api/projects/draft")).json() as { id: string };
  await page.goto(`/projects/${created.id}`);
  await page.getByLabel("AI chat message").fill(project.prompt);
  await saveScreenshot(page, batchId, `mixed-project-${String(position).padStart(2, "0")}-initial.png`);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await waitSettled(page, created.id);
  await page.reload();
  await saveScreenshot(page, batchId, `mixed-project-${String(position).padStart(2, "0")}-clarification.png`);
  await answerClarifications(page, project);
  await waitSettled(page, created.id);
  await page.reload();
  await saveScreenshot(page, batchId, `mixed-project-${String(position).padStart(2, "0")}-final.png`);
  return {
    project_id: created.id,
    attempts: await page.request.get(`/api/projects/${created.id}/generation-attempts`).then((response) => response.json()),
  };
}

async function finishBatch(page: Page, batchId: string, label: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "View batch", exact: true }).click();
  await saveScreenshot(page, batchId, `${label}-batch-drawer-complete.png`);
  await page.locator(".debug-batch-drawer").getByRole("button", { name: "Finish batch", exact: true }).click();
  await saveScreenshot(page, batchId, `${label}-finish-confirmation.png`);
  await page.getByRole("button", { name: "Finish batch", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Debug batch complete", exact: true })).toBeVisible({ timeout: 240_000 });
  await saveScreenshot(page, batchId, `${label}-batch-summary.png`);
  const report = await page.request.get(`/api/debug-batches/${batchId}/report`).then((response) => response.json());
  await page.goto("/");
  return report;
}

test.skip(process.env.VOLUNDR_RUN_CONVERGENCE_E2E !== "true", "Opt-in controlled convergence pair.");
test("runs two unchanged mixed-CAD convergence batches and freezes a controlled comparison", async ({ page }) => {
  test.setTimeout(1_800_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const batchOne = await startBatch(page, "mixed-cad-convergence-01", "First unchanged live convergence run of five mixed-CAD prompts.");
  const batchOneProjects = [];
  for (let index = 0; index < PROJECTS.length; index += 1) batchOneProjects.push(await runProject(page, batchOne, PROJECTS[index], index + 1));
  const batchOneReport = await finishBatch(page, batchOne, "mixed-cad-convergence-01");

  const batchTwo = await startBatch(page, "mixed-cad-convergence-02", "Second unchanged live convergence run of the same five prompts.", batchOne);
  const batchTwoProjects = [];
  for (let index = 0; index < PROJECTS.length; index += 1) batchTwoProjects.push(await runProject(page, batchTwo, PROJECTS[index], index + 1));
  const batchTwoReport = await finishBatch(page, batchTwo, "mixed-cad-convergence-02");
  const comparison = await page.request.get(`/api/debug-batches/${batchTwo}/comparison`).then((response) => response.json());
  await saveScreenshot(page, batchTwo, "mixed-cad-convergence-comparison.png");
  await fs.writeFile(path.join(sessionRoot(batchOne), "live-batch-manifest.json"), JSON.stringify({ batch_id: batchOne, projects: batchOneProjects, report: batchOneReport }, null, 2), "utf-8");
  await fs.writeFile(path.join(sessionRoot(batchTwo), "live-batch-manifest.json"), JSON.stringify({ batch_id: batchTwo, projects: batchTwoProjects, report: batchTwoReport, comparison }, null, 2), "utf-8");
  expect(comparison.status).toBe("controlled");
  expect(comparison.identity_match).toBe(true);
});
