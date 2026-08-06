import assert from "node:assert/strict";
import { chmod, cp, mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import test from "node:test";

const scriptsDirectory = dirname(fileURLToPath(import.meta.url));
const liveScript = join(scriptsDirectory, "run-live-e2e.sh");

async function makeFixture({ withRootEnv = true } = {}) {
  const root = await mkdtemp(join(tmpdir(), "volundr-live-e2e-test-"));
  const frontendScripts = join(root, "frontend", "scripts");
  const workerBin = join(root, "backend", ".venv", "bin");
  const stubs = join(root, "stubs");
  const tempDirectory = join(root, "tmp");
  const record = join(root, "record");
  const ready = join(root, "ready");

  await mkdir(frontendScripts, { recursive: true });
  await mkdir(workerBin, { recursive: true });
  await mkdir(stubs, { recursive: true });
  await mkdir(tempDirectory, { recursive: true });
  await cp(liveScript, join(frontendScripts, "run-live-e2e.sh"));
  if (withRootEnv) {
    await writeFile(
      join(root, ".env"),
      "GEMINI_API_KEY_2=root-secondary-test-value\nGEMINI_API_KEY=root-primary-test-value\n",
      { mode: 0o600 },
    );
  }

  await writeFile(
    join(workerBin, "python"),
    `#!/usr/bin/env bash
set -euo pipefail
record=\"$LIVE_TEST_RECORD\"
if [[ -n \"\${GEMINI_API_KEY_2:-}\" ]]; then echo worker_secondary_nonempty=true >>\"$record\"; else echo worker_secondary_nonempty=false >>\"$record\"; fi
if [[ -n \"\${GEMINI_API_KEY:-}\" ]]; then echo worker_primary_nonempty=true >>\"$record\"; else echo worker_primary_nonempty=false >>\"$record\"; fi
while :; do sleep 1; done
`,
  );
  await writeFile(
    join(stubs, "npx"),
    `#!/usr/bin/env bash
set -euo pipefail
record=\"$LIVE_TEST_RECORD\"
printf 'env_file=%s\\n' \"$VOLUNDR_LIVE_ENV_FILE\" >>\"$record\"
if [[ -n \"\${GEMINI_API_KEY_2:-}\" ]]; then echo browser_secondary_nonempty=true >>\"$record\"; else echo browser_secondary_nonempty=false >>\"$record\"; fi
if [[ -n \"\${GEMINI_API_KEY:-}\" ]]; then echo browser_primary_nonempty=true >>\"$record\"; else echo browser_primary_nonempty=false >>\"$record\"; fi
if [[ \"\${LIVE_TEST_MODE:-}\" == inspect-root-env ]]; then
  . \"$VOLUNDR_LIVE_ENV_FILE\"
  if [[ \"\${GEMINI_API_KEY_2:-}\" == root-secondary-test-value && \"\${GEMINI_API_KEY:-}\" == root-primary-test-value ]]; then
    echo root_env_authoritative=true >>\"$record\"
  else
    echo root_env_authoritative=false >>\"$record\"
  fi
fi
if [[ \"\${LIVE_TEST_MODE:-}\" == signal ]]; then
  touch \"$LIVE_TEST_READY\"
  while :; do sleep 1; done
fi
if [[ \"\${LIVE_TEST_MODE:-}\" == failure ]]; then exit 23; fi
if [[ \"\${LIVE_TEST_MODE:-}\" == early-exit ]]; then exit 24; fi
exit 0
`,
  );
  await chmod(join(workerBin, "python"), 0o755);
  await chmod(join(stubs, "npx"), 0o755);

  return { root, record, ready, stubs, tempDirectory };
}

function spawnWrapper(fixture, mode, { processCredentials = false } = {}) {
  const environment = { ...process.env };
  for (const name of ["GEMINI_API_KEY_2", "GEMINI_API_KEY", "VOLUNDR_GEMINI_API_KEY_2", "VOLUNDR_GEMINI_API_KEY"]) {
    delete environment[name];
  }
  Object.assign(environment, {
    LIVE_TEST_MODE: mode,
    LIVE_TEST_READY: fixture.ready,
    LIVE_TEST_RECORD: fixture.record,
    PATH: `${fixture.stubs}:${environment.PATH ?? ""}`,
    TMPDIR: fixture.tempDirectory,
    VOLUNDR_KEEP_LIVE_DATA: "true",
    VOLUNDR_RUN_LIVE_E2E: "true",
  });
  if (processCredentials) {
    environment.GEMINI_API_KEY_2 = "process-secondary-test-value";
    environment.GEMINI_API_KEY = "process-primary-test-value";
  }

  return spawn("bash", [join(fixture.root, "frontend", "scripts", "run-live-e2e.sh")], {
    cwd: tmpdir(),
    env: environment,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

async function collectProcess(process) {
  let output = "";
  process.stdout.on("data", (chunk) => { output += chunk; });
  process.stderr.on("data", (chunk) => { output += chunk; });
  const result = await new Promise((resolve, reject) => {
    process.once("error", reject);
    process.once("close", (code, signal) => resolve({ code, signal, output }));
  });
  return result;
}

async function waitForFile(path) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      await readFile(path);
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }
  throw new Error(`Timed out waiting for ${path}`);
}

async function assertCleanup(fixture, result, expectedCode) {
  assert.equal(result.code, expectedCode, result.output);
  assert.doesNotMatch(result.output, /root-(secondary|primary)-test-value/);

  const record = await readFile(fixture.record, "utf8");
  const environmentFile = record.match(/^env_file=(.+)$/m)?.[1];
  assert.ok(environmentFile, record);
  await assert.rejects(readFile(environmentFile), { code: "ENOENT" });
  assert.match(record, /browser_secondary_nonempty=false/);
  assert.match(record, /browser_primary_nonempty=false/);
  assert.match(record, /worker_secondary_nonempty=false/);
  assert.match(record, /worker_primary_nonempty=false/);

  const preservedData = result.output.match(/Live E2E data preserved at (.+)$/m)?.[1]?.trim();
  assert.ok(preservedData, result.output);
  const files = [];
  async function collectFiles(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) await collectFiles(path);
      else files.push(path);
    }
  }
  await collectFiles(preservedData);
  for (const path of files) {
    const contents = await readFile(path, "utf8");
    assert.doesNotMatch(contents, /root-(secondary|primary)-test-value/);
  }
  await rm(preservedData, { recursive: true, force: true });
}

for (const [mode, expectedCode, description] of [
  ["success", 0, "success"],
  ["failure", 23, "failure"],
  ["early-exit", 24, "early browser exit"],
]) {
  test(`removes the backend environment after ${description}`, async () => {
    const fixture = await makeFixture();
    try {
      const result = await collectProcess(spawnWrapper(fixture, mode));
      await assertCleanup(fixture, result, expectedCode);
    } finally {
      await rm(fixture.root, { recursive: true, force: true });
    }
  });
}

test("removes the backend environment after signal interruption", async () => {
  const fixture = await makeFixture();
  try {
    const process = spawnWrapper(fixture, "signal");
    await waitForFile(fixture.ready);
    process.kill("SIGTERM");
    const result = await collectProcess(process);
    await assertCleanup(fixture, result, 130);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("removes the credential staging file on early credential validation exit", async () => {
  const fixture = await makeFixture({ withRootEnv: false });
  try {
    const result = await collectProcess(spawnWrapper(fixture, "missing-credentials"));
    assert.equal(result.code, 2, result.output);
    assert.doesNotMatch(result.output, /root-(secondary|primary)-test-value/);
    assert.deepEqual(await readdir(fixture.tempDirectory), []);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test("uses the repository root env values over process credential values", async () => {
  const fixture = await makeFixture();
  try {
    const result = await collectProcess(spawnWrapper(fixture, "inspect-root-env", { processCredentials: true }));
    await assertCleanup(fixture, result, 0);
    const record = await readFile(fixture.record, "utf8");
    assert.match(record, /root_env_authoritative=true/);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});
