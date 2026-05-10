import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";

const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const repoRoot = process.env.SARATHI_REPO_ROOT ?? "/Users/sweethome/Work/Skills/Sarathi";

const cleanupDbPath = process.env.CLEANUP_DB_PATH;
const useIsolatedDb = cleanupDbPath === "true" || cleanupDbPath === "1";
const apiEnv = { ...process.env };

if (useIsolatedDb) {
  const tmpDir = os.tmpdir();
  const dbFile = path.join(tmpDir, `sarathi-qa-${Date.now()}.db`);
  apiEnv.SARATHI_DB_PATH = dbFile;
  apiEnv.SARATHI_API_TOKEN = "dev";
  apiEnv.SARATHI_API_PORT = "8766";
}

let apiServer = null;
let apiStderrChunks = [];

if (useIsolatedDb) {
  apiServer = spawn(
    process.execPath,
    ["-m", "src.service", "--db", apiEnv.SARATHI_DB_PATH, "--token", "dev", "--port", "8766"],
    { cwd: repoRoot, env: apiEnv, stdio: ["ignore", "pipe", "pipe"] }
  );
  apiServer.stderr.on("data", (chunk) => { apiStderrChunks.push(chunk); });
  await new Promise((resolve) => setTimeout(resolve, 2000));
}

function uniqueLabel(prefix) {
  return `${prefix} ${new Date().toISOString().replace(/[:.]/g, "-")}`;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function findPlaywrightRoot() {
  const roots = [
    path.join(os.homedir(), ".npm/_npx"),
    path.join(os.homedir(), ".cache/_npx"),
  ];
  let latestCandidate = null;
  let latestMtime = 0;

  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    for (const entry of fs.readdirSync(root)) {
      const nodeModules = path.join(root, entry, "node_modules");
      const playwrightModule = path.join(nodeModules, "playwright");
      if (!fs.existsSync(playwrightModule)) continue;
      const stat = fs.statSync(nodeModules);
      if (stat.mtimeMs > latestMtime) {
        latestMtime = stat.mtimeMs;
        latestCandidate = nodeModules;
      }
    }
  }

  if (!latestCandidate) {
    throw new Error("Could not find a Playwright installation in the npx cache.");
  }
  return latestCandidate;
}

async function isVisible(locator) {
  try {
    return await locator.first().isVisible();
  } catch {
    return false;
  }
}

async function clickFirstVisible(locator) {
  const count = await locator.count();
  for (let index = 0; index < count; index += 1) {
    const candidate = locator.nth(index);
    if (await candidate.isVisible()) {
      await candidate.click();
      return true;
    }
  }
  return false;
}

async function waitForAnyVisible(locators, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const locator of locators) {
      if (await isVisible(locator)) {
        return locator;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Timed out waiting for a visible target.");
}

async function logHeadings(page, label) {
  const headings = await page.locator("h1, h2, h3").allTextContents();
  console.log(`${label}: ${headings.join(" | ")}`);
}

const playwrightRoot = findPlaywrightRoot();
const require = createRequire(import.meta.url);
const { chromium } = require(path.join(playwrightRoot, "playwright"));

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });

try {
  await page.addInitScript(() => {
    localStorage.removeItem("sarathi.desktop.workspace.selection.v1");
    sessionStorage.clear();
  });

  await page.goto(baseURL, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  await waitForAnyVisible([
    page.getByRole("heading", { name: /^workspace$/i }),
    page.getByRole("heading", { name: /^dashboard$/i }),
    page.getByRole("heading", { name: /your workspaces/i }),
    page.getByRole("heading", { name: /projects/i }),
  ]);
  await logHeadings(page, "initial");

  const createWorkspaceButtons = page.getByRole("button", { name: /^Create workspace$/i });
  if (await clickFirstVisible(createWorkspaceButtons)) {
    await page.getByPlaceholder(/^name$/i).fill(uniqueLabel("Validation Workspace"));
    await page.getByPlaceholder(/path/i).fill(repoRoot);
    await page.getByRole("button", { name: /^create$/i }).click();
    await page.waitForTimeout(1500);
    await logHeadings(page, "after-workspace-create");
  }

  const projectName = uniqueLabel("Validation Project");
  if (await isVisible(page.getByLabel(/project name/i))) {
    await page.getByLabel(/project name/i).fill(projectName);
    await page.getByLabel(/project description/i).fill("Validation project for task panel flow");
    await page.getByRole("button", { name: /^create project$/i }).click();
  } else {
    const createProjectButtons = page.getByRole("button", { name: /(?:\+ )?create project|create first project/i });
    assert(await clickFirstVisible(createProjectButtons), "Could not find a create-project button.");
    await page.getByLabel(/project name/i).fill(projectName);
    await page.getByLabel(/project description/i).fill("Validation project for task panel flow");
    await page.getByRole("button", { name: /^create project$/i }).click();
  }

  await page.waitForTimeout(2000);
  await page.getByRole("heading", { name: /^dashboard$/i }).waitFor();
  await logHeadings(page, "after-project");
  assert(await isVisible(page.getByText(new RegExp(projectName, "i"))), "New project title did not appear.");

  const prompt = uniqueLabel("Validate task panel flow");
  await page.getByRole("button", { name: /^\+ New task$/i }).click();
  await page.getByPlaceholder(/describe the task or feature/i).fill(prompt);
  await page.locator("form").getByRole("button", { name: /^create$/i }).click();
  await page.waitForTimeout(5000);
  await logHeadings(page, "after-task-create");

  await page.getByText(new RegExp(prompt, "i")).first().waitFor();
  await page.getByRole("heading", { name: /dependency graph/i }).waitFor();
  await page.getByRole("heading", { name: /^task panel$/i }).waitFor();
  await waitForAnyVisible([
    page.getByText(/Approval requested for PRD\/AC/i),
    page.getByText(/PRD\/AC gate pending/i),
    page.getByRole("heading", { name: /^task panel$/i }),
  ]);

  console.log("validate-task-panel: workspace -> project -> task studio flow passed");
} catch (error) {
  await page.screenshot({ path: "/private/tmp/validate-task-panel-failure.png", fullPage: true });
  throw error;
} finally {
  await browser.close();
  if (apiServer) {
    apiServer.kill("SIGTERM");
    apiServer = null;
  }
}
