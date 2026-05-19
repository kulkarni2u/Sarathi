import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";

const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const repoRoot = process.env.SARATHI_REPO_ROOT ?? "/Users/sweethome/Work/Skills/Sarathi";
const pythonExecutable = process.env.SARATHI_PYTHON ?? process.env.PYTHON ?? "python3.11";

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
const isolatedWorkspaceRoot = useIsolatedDb
  ? fs.mkdtempSync(path.join(os.tmpdir(), "sarathi-qa-workspace-"))
  : null;

if (useIsolatedDb) {
  apiServer = spawn(
    pythonExecutable,
    ["-m", "src.service", "--db", apiEnv.SARATHI_DB_PATH, "--token", "dev", "--port", "8766"],
    { cwd: repoRoot, env: apiEnv, stdio: ["ignore", "pipe", "pipe"] }
  );
  apiServer.stderr.on("data", (chunk) => { apiStderrChunks.push(chunk); });
}

function uniqueLabel(prefix) {
  return `${prefix} ${new Date().toISOString().replace(/[:.]/g, "-")}`;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function authHeaders() {
  if (!useIsolatedDb) {
    return {};
  }
  return { authorization: "Bearer dev" };
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

async function goToPrimaryRoute(page, routeName) {
  const nav = page.getByRole("navigation", { name: /primary/i });
  await nav.getByRole("button", { name: new RegExp(routeName, "i") }).click();
}

async function goToKnowledgeSection(page, sectionName) {
  await goToPrimaryRoute(page, "knowledge center");
  await page.getByRole("heading", { name: /knowledge center/i }).first().waitFor();
  await page.getByRole("button", { name: new RegExp(`^${sectionName}$`, "i") }).click();
}

async function waitForApiHealth(timeoutMs = 10000) {
  if (!useIsolatedDb) {
    return;
  }
  const deadline = Date.now() + timeoutMs;
  let lastError = "unknown";
  while (Date.now() < deadline) {
    try {
      const response = await fetch("http://127.0.0.1:8766/api/health", {
        headers: { authorization: "Bearer dev" },
      });
      if (response.ok) {
        return;
      }
      lastError = `status ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const stderr = Buffer.concat(apiStderrChunks).toString("utf8").trim();
  throw new Error(`Timed out waiting for Sarathi API health (${lastError}).${stderr ? ` stderr: ${stderr}` : ""}`);
}

async function apiJson(pathname, options = {}) {
  const response = await fetch(`http://127.0.0.1:8766${pathname}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
  });
  const envelope = await response.json();
  if (!response.ok) {
    throw new Error(`API ${options.method ?? "GET"} ${pathname} failed with ${response.status}: ${JSON.stringify(envelope)}`);
  }
  if (!envelope.ok) {
    throw new Error(`API ${options.method ?? "GET"} ${pathname} returned error envelope: ${JSON.stringify(envelope)}`);
  }
  return envelope.data;
}

async function maybeReadResponse(responsePromise) {
  if (!responsePromise) {
    return null;
  }
  try {
    return await responsePromise;
  } catch {
    return null;
  }
}

async function resolveWorkspaceAndProject(workspaceName, projectName) {
  const workspacesPayload = await apiJson("/api/workspaces");
  const workspaces = workspacesPayload.workspaces ?? [];
  const workspace = workspaces.find((candidate) => candidate.name === workspaceName) ?? workspaces.at(-1);
  assert(workspace, `Could not resolve workspace ${workspaceName}.`);
  const projectsPayload = await apiJson(`/api/workspaces/${encodeURIComponent(workspace.id)}/projects`);
  const projects = projectsPayload.projects ?? [];
  const project = projects.find((candidate) => candidate.name === projectName) ?? projects.at(-1);
  assert(project, `Could not resolve project ${projectName}.`);
  return { workspace, project };
}

function seedKnowledgeLoopFixtures(workspaceRoot) {
  fs.mkdirSync(path.join(workspaceRoot, "policy-pack", ".sarathi-proposals"), { recursive: true });
  fs.mkdirSync(path.join(workspaceRoot, "wiki", "guides"), { recursive: true });
  fs.writeFileSync(path.join(workspaceRoot, "SARATHI.md"), "# Sarathi\n", "utf8");
  fs.writeFileSync(path.join(workspaceRoot, "coding-standards.md"), "# Coding standards\n", "utf8");
  fs.writeFileSync(path.join(workspaceRoot, "guidelines.md"), "# Guidelines\n", "utf8");
  fs.writeFileSync(
    path.join(workspaceRoot, "learnings.md"),
    [
      "## Accepted: Govern release handoffs with compact context",
      "",
      "- Task: learning-task-1",
      "- Summary: Release handoff guidance should stay compact and evidence-backed.",
      "- Tags: workflow, dogfood",
      "- Evidence: retained signal (learning-task-1:repeated_failures:Build)",
      "",
    ].join("\n"),
    "utf8",
  );
  fs.writeFileSync(path.join(workspaceRoot, "wiki", "README.md"), "# Wiki Home\n", "utf8");
  fs.writeFileSync(path.join(workspaceRoot, "wiki", "guides", "setup.md"), "# Setup Guide\n", "utf8");
  fs.writeFileSync(
    path.join(workspaceRoot, "policy-pack", "skills.md"),
    "# Policy Pack: Skill Routing\n\n## Skill Families\n",
    "utf8",
  );
  fs.writeFileSync(
    path.join(workspaceRoot, "policy-pack", "commands.md"),
    ["# Commands", "", "```yaml", "test:", "  command: pytest", "```", ""].join("\n"),
    "utf8",
  );
  fs.writeFileSync(path.join(workspaceRoot, "policy-pack", "model-routing.md"), "# Model routing\n", "utf8");
  fs.writeFileSync(path.join(workspaceRoot, "policy-pack", "escalation.md"), "# Escalation\n", "utf8");
  fs.writeFileSync(
    path.join(workspaceRoot, "policy-pack", ".sarathi-proposals", "reviewed-learning-proposal.json"),
    JSON.stringify(
      {
        id: "reviewed-learning-proposal",
        status: "accepted",
        policy_file: "commands.md",
        title: "Add Build failure recovery guidance",
        source: "repeated_failures",
        proposal_kind: "policy_note",
        impacted_assets: ["policy-pack/commands.md"],
        risk_level: "low",
        confidence: 0.67,
        suggested_change: "Add a root-cause and retry checklist before repeating the same implementation lane.",
        evidence_refs: ["learning-task-1:repeated_failures:Build"],
        routing_hint: {},
        reason: null,
        reviewed_at: new Date().toISOString(),
      },
      null,
      2,
    ),
    "utf8",
  );
}

async function seedReviewedTaskWithHandoff({ workspaceId, projectId, title }) {
  const prompt = `${title} prompt`;
  const draftPayload = await apiJson(`/api/workspaces/${encodeURIComponent(workspaceId)}/task-drafts`, {
    method: "POST",
    body: JSON.stringify({
      prompt,
      title,
      context: { projectId },
    }),
  });
  const task = draftPayload.task;
  await apiJson(`/api/tasks/${encodeURIComponent(task.id)}/approve`, {
    method: "POST",
    body: JSON.stringify({ name: "PRD/AC", status: "approved" }),
  });
  await apiJson(`/api/tasks/${encodeURIComponent(task.id)}/graph-draft`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  await apiJson(`/api/tasks/${encodeURIComponent(task.id)}/approve`, {
    method: "POST",
    body: JSON.stringify({ name: "Task graph", status: "approved" }),
  });
  await apiJson(`/api/tasks/${encodeURIComponent(task.id)}/schedule`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  const studioPayload = await apiJson(`/api/tasks/${encodeURIComponent(task.id)}/studio`);
  const runningNode = studioPayload.graph?.nodes?.[0];
  assert(runningNode?.id, `Expected a scheduled graph node for reviewed task ${title}.`);
  await apiJson(`/api/subtasks/${encodeURIComponent(runningNode.id)}/dispatch`, {
    method: "POST",
    body: JSON.stringify({ provider: "local" }),
  });
  await apiJson(`/api/tasks/${encodeURIComponent(task.id)}/reviews/run`, {
    method: "POST",
    body: JSON.stringify({ review_type: "functional" }),
  });
  await apiJson(`/api/tasks/${encodeURIComponent(task.id)}/handoff`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  return task;
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
  await waitForApiHealth();

  await page.addInitScript((runtimeConfig) => {
    window.__SARATHI_RUNTIME_CONFIG__ = runtimeConfig;
    localStorage.removeItem("sarathi.desktop.workspace.selection.v1");
    sessionStorage.clear();
  }, useIsolatedDb ? { baseUrl: "http://127.0.0.1:8766", token: "dev" } : undefined);

  await page.goto(baseURL, { waitUntil: "domcontentloaded" });
  if (useIsolatedDb) {
    await page.evaluate((runtimeConfig) => {
      window.__SARATHI_RUNTIME_CONFIG__ = runtimeConfig;
    }, { baseUrl: "http://127.0.0.1:8766", token: "dev" });
  }
  await page.waitForTimeout(1500);
  await waitForAnyVisible([
    page.getByRole("heading", { name: /^workspaces$/i }),
    page.getByRole("heading", { name: /no workspace yet/i }),
  ]);
  await logHeadings(page, "initial");

  const workspaceName = uniqueLabel("Validation Workspace");
  let createdWorkspaceId = null;
  let createdProjectId = null;
  const createWorkspaceButtons = page.getByRole("button", { name: /^(Create|New) workspace$/i });
  if (await clickFirstVisible(createWorkspaceButtons)) {
    await waitForAnyVisible([
      page.getByPlaceholder(/workspace name/i),
      page.getByPlaceholder(/^name$/i),
    ]);
    const workspaceCreateResponse = useIsolatedDb
      ? page.waitForResponse((response) =>
        response.request().method() === "POST" && /\/api\/workspaces$/.test(response.url()), { timeout: 5000 })
      : null;
    const workspaceRoot = isolatedWorkspaceRoot ?? repoRoot;
    await page.getByPlaceholder(/workspace name/i).fill(workspaceName);
    await page.getByPlaceholder(/root path/i).fill(workspaceRoot);
    await page.getByRole("button", { name: /^create$/i }).click();
    const workspaceCreateResult = await maybeReadResponse(workspaceCreateResponse);
    if (workspaceCreateResult) {
      const payload = await workspaceCreateResult.json();
      createdWorkspaceId = payload.data?.workspace?.id ?? null;
    }
    await page.waitForTimeout(1500);
    await logHeadings(page, "after-workspace-create");
    const workflowTemplatesHeading = page.getByRole("heading", { name: /workflow templates/i });
    if (!(await isVisible(workflowTemplatesHeading))) {
      const workspaceRow = page.getByRole("button", { name: new RegExp(workspaceName, "i") });
      if (await isVisible(workspaceRow)) {
        await workspaceRow.first().click();
      }
    }
    await workflowTemplatesHeading.waitFor();
    await page.getByRole("heading", { name: /saved views/i }).waitFor();
    await page.getByRole("heading", { name: /^learned playbooks$/i }).waitFor();
    await page.getByText(/feature delivery/i).first().waitFor();
    if (isolatedWorkspaceRoot) {
      seedKnowledgeLoopFixtures(isolatedWorkspaceRoot);
    }
    await page.getByRole("button", { name: /provider posture/i }).click();
    await page.getByRole("heading", { name: /^settings$/i }).waitFor();
    await goToPrimaryRoute(page, "workspace");
    await page.getByRole("heading", { name: /workflow templates/i }).waitFor();
    await goToKnowledgeSection(page, "proposals");
    await page.getByRole("heading", { name: /proposal inbox/i }).waitFor();

    if (isolatedWorkspaceRoot) {
      await page.getByText(/reviewed history/i).first().waitFor();
      await page.getByText(/add build failure recovery guidance/i).first().waitFor();
      await page.getByRole("button", { name: /learning link/i }).first().click();
      await page.getByRole("heading", { name: /learnings/i }).waitFor();
      await page.getByText(/govern release handoffs with compact context/i).first().waitFor();
      await goToKnowledgeSection(page, "proposals");
      await page.getByRole("heading", { name: /proposal inbox/i }).waitFor();
    } else {
      const hasProposals = await isVisible(page.getByText(/add build failure recovery guidance/i));
      if (hasProposals) {
        const learningLinkButton = page.getByRole("button", { name: /learning link/i });
        if (await isVisible(learningLinkButton)) {
          await learningLinkButton.click();
          await page.getByRole("heading", { name: /learnings/i }).waitFor();
          await goToKnowledgeSection(page, "proposals");
          await page.getByRole("heading", { name: /proposal inbox/i }).waitFor();
        }
      } else {
        await page.getByText(/no pending proposals/i).first().waitFor();
      }
    }

    await goToKnowledgeSection(page, "learnings");
    await page.getByRole("heading", { name: /learnings/i }).waitFor();
    await waitForAnyVisible([
      page.getByText(/accepted learnings/i),
      page.getByText(/no accepted learnings/i),
      page.getByText(/accepted learning/i),
    ], 5000);

    const openPlaybooksButton = page.getByRole("button", { name: /open playbooks/i });
    if (isolatedWorkspaceRoot) {
      await openPlaybooksButton.first().click();
      await page.getByRole("heading", { name: /workflow templates/i }).waitFor();
      await page.locator(".section-badge").getByText(/handoff readiness/i).waitFor();
      await goToKnowledgeSection(page, "learnings");
      await page.getByRole("heading", { name: /learnings/i }).waitFor();
    } else if (await isVisible(openPlaybooksButton)) {
      await openPlaybooksButton.click();
      await page.getByRole("heading", { name: /workflow templates/i }).waitFor();
      await goToKnowledgeSection(page, "learnings");
      await page.getByRole("heading", { name: /learnings/i }).waitFor();
    }

    const openProposalButton = page.getByRole("button", { name: /open proposal/i });
    if (isolatedWorkspaceRoot) {
      await openProposalButton.first().click();
      await page.getByRole("heading", { name: /proposal inbox/i }).waitFor();
      await page.getByText(/reviewed history/i).first().waitFor();
      await page.locator('[data-proposal-id="reviewed-learning-proposal"]').waitFor();
      await goToKnowledgeSection(page, "learnings");
      await page.getByRole("heading", { name: /learnings/i }).waitFor();
    } else if (await isVisible(openProposalButton)) {
      await openProposalButton.click();
      await page.getByRole("heading", { name: /proposal inbox/i }).waitFor();
      await goToKnowledgeSection(page, "learnings");
      await page.getByRole("heading", { name: /learnings/i }).waitFor();
    }

    await goToPrimaryRoute(page, "workspace");
    await page.getByRole("heading", { name: /workflow templates/i }).waitFor();
    const customViewName = uniqueLabel("Team approvals");
    await page.getByRole("button", { name: /save current view/i }).click();
    await page.getByLabel(/saved view name/i).fill(customViewName);
    await page.getByLabel(/saved view description/i).fill("Reusable approval posture for validation.");
    await page.getByRole("button", { name: /^save view$/i }).click();
    await page.getByText(new RegExp(customViewName, "i")).first().waitFor();
    await page.getByRole("button", { name: /launch template/i }).first().click();
    await page.getByRole("heading", { name: /^brainstorm$/i }).waitFor();
    await page.getByText(/template: feature delivery/i).first().waitFor();
    await page.getByText(/workflow template: feature delivery/i).first().waitFor();
    await page.getByText(/recommended views: approvals-inbox, handoff-readiness/i).first().waitFor();
    await goToPrimaryRoute(page, "workspace");
    await page.getByRole("heading", { name: /workflow templates/i }).waitFor();
  }

  const projectName = uniqueLabel("Validation Project");
  if (await isVisible(page.getByLabel(/project name/i))) {
    const projectCreateResponse = useIsolatedDb
      ? page.waitForResponse((response) =>
        response.request().method() === "POST" && /\/api\/workspaces\/[^/]+\/projects$/.test(response.url()), { timeout: 5000 })
      : null;
    await page.getByLabel(/project name/i).fill(projectName);
    await page.getByLabel(/project description/i).fill("Validation project for task panel flow");
    await page.getByRole("button", { name: /^create project$/i }).click();
    const projectCreateResult = await maybeReadResponse(projectCreateResponse);
    if (projectCreateResult) {
      const payload = await projectCreateResult.json();
      createdProjectId = payload.data?.project?.id ?? null;
    }
  } else {
    const createProjectButtons = page.getByRole("button", { name: /(?:\+ )?create project|create first project/i });
    assert(await clickFirstVisible(createProjectButtons), "Could not find a create-project button.");
    const projectCreateResponse = useIsolatedDb
      ? page.waitForResponse((response) =>
        response.request().method() === "POST" && /\/api\/workspaces\/[^/]+\/projects$/.test(response.url()), { timeout: 5000 })
      : null;
    await page.getByLabel(/project name/i).fill(projectName);
    await page.getByLabel(/project description/i).fill("Validation project for task panel flow");
    await page.getByRole("button", { name: /^create project$/i }).click();
    const projectCreateResult = await maybeReadResponse(projectCreateResponse);
    if (projectCreateResult) {
      const payload = await projectCreateResult.json();
      createdProjectId = payload.data?.project?.id ?? null;
    }
  }

  await page.waitForTimeout(2000);
  await page.getByRole("heading", { name: /^dashboard$/i }).waitFor();
  await logHeadings(page, "after-project");
  assert(await isVisible(page.getByText(new RegExp(projectName, "i"))), "New project title did not appear.");
  await page.getByText(/active saved view:/i).first().waitFor();
  await page.getByText(/approval inbox/i).first().waitFor();

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
  await page.getByRole("heading", { name: /delivery spine/i }).waitFor();
  await page.getByRole("heading", { name: /artifact overview/i }).waitFor();
  await page.getByRole("heading", { name: /task origin/i }).waitFor();
  await page.getByRole("heading", { name: /changed files/i }).waitFor();
  await page.getByRole("heading", { name: /tests run/i }).waitFor();
  await page.getByRole("heading", { name: /known risks/i }).waitFor();
  await page.getByRole("heading", { name: /review findings/i }).waitFor();
  await page.getByRole("heading", { name: /artifact provenance/i }).waitFor();
  await page.getByText(/governance posture/i).first().waitFor();
  await page.getByRole("button", { name: /^history$/i }).click();
  await page.getByText(/governance overrides/i).first().waitFor();

  if (useIsolatedDb) {
    const reviewedTaskTitle = uniqueLabel("Reviewed handoff dossier");
    const { workspace, project } =
      createdWorkspaceId && createdProjectId
        ? { workspace: { id: createdWorkspaceId }, project: { id: createdProjectId } }
        : await resolveWorkspaceAndProject(workspaceName, projectName);
    await seedReviewedTaskWithHandoff({
      workspaceId: workspace.id,
      projectId: project.id,
      title: reviewedTaskTitle,
    });
    await page.getByRole("button", { name: /back to dashboard/i }).click();
    await page.getByRole("heading", { name: /^dashboard$/i }).waitFor();
    await page.getByText(new RegExp(reviewedTaskTitle, "i")).first().waitFor({ timeout: 15000 });
    await page.getByText(new RegExp(reviewedTaskTitle, "i")).first().click();
    await page.getByRole("heading", { name: /^task panel$/i }).waitFor();
    await page.getByText(/final handoff dossier/i).first().waitFor();
    await page.getByText(/^AC Coverage$/i).first().waitFor();
    await page.getByText(/^Completion context$/i).first().waitFor();
    await page.getByText(/Repo action pending/i).first().waitFor();
    await page.getByText(/compiled context pack/i).first().waitFor();
    await page.getByText(/normalized agent output/i).first().waitFor();
  }

  await goToPrimaryRoute(page, "settings");
  await page.getByRole("heading", { name: /^settings$/i }).waitFor();
  await page.getByRole("heading", { name: /^governance$/i }).waitFor();
  await page.getByRole("heading", { name: /^dispatch order$/i }).waitFor();
  await page.getByRole("heading", { name: /^override history$/i }).waitFor();
  await page.getByRole("heading", { name: /^repository safety$/i }).waitFor();
  await page.getByRole("heading", { name: /^approval workflow$/i }).waitFor();

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
