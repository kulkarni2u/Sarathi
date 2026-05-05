export type Tone = "healthy" | "active" | "warning" | "blocked" | "draft" | "complete";

export type WorkspaceRepo = {
  id: string;
  name: string;
  path: string;
  branch: string;
  gitState: "clean" | "dirty";
  permission: "read" | "write";
  initializationStatus?: string;
};

export type WorkspaceDoc = {
  name: string;
  state: string;
  note: string;
};

export type Workspace = {
  id: string;
  name: string;
  description: string;
  status: "live" | "warning" | "blocked";
  policyPack: string;
  sqlite: string;
  repos: WorkspaceRepo[];
  docs: WorkspaceDoc[];
};

export type Provider = {
  id: string;
  name: string;
  type: string;
  health: string;
  auth: string;
  path: string;
  capabilities: string[];
};

export type Role = {
  name: string;
  function: string;
  state: "active" | "idle" | "queued" | "waiting" | "live";
  provider: Provider["name"];
};

export type Task = {
  id: string;
  title: string;
  status: "draft" | "in_progress" | "waiting_human" | "complete";
  phase: string;
  progress: number;
  reviewState: string;
  repoState: string;
  summary: string;
};

export type Subtask = {
  id: string;
  title: string;
  state: "complete" | "in_progress" | "queued" | "blocked" | "waiting_human";
  role: string;
  provider: Provider["name"];
  blockedBy: string[];
  evidenceCount: number;
  review: string;
  ac: string[];
  goal: string;
  context: string;
  files: string[];
  nextAction: string;
  x: number;
  y: number;
};

export type ApprovalGate = {
  id: string;
  name: string;
  status: "approved" | "pending" | "blocked" | "waiting_human";
  help: string;
  auditEventId: string;
  linkedObjects: string[];
};

export type EvidenceArtifact = {
  id: string;
  title: string;
  type: string;
  state: string;
  source: string;
  linkedAc: string;
  linkedUnit: string;
  linkedGate: string;
  linkedEvent: string;
};

export type ReviewRun = {
  id: string;
  type: string;
  verdict: "approved" | "rejected" | "pending";
  reviewer: string;
  loop: string;
  severity: string;
  finding: string;
  linkedUnit: string;
  linkedEvidence: string[];
  linkedGate: string;
  linkedEvent: string;
};

export type SarathiEvent = {
  id: string;
  time: string;
  source: string;
  event: string;
  object: string;
  severity: string;
};

export type Message = {
  from: string;
  target: string;
  tag: string;
  text: string;
  impact: string;
};

export const workspace: Workspace = {
  id: "SARATHI-APP",
  name: "Sarathi App",
  description: "Dogfood workspace proving Sarathi can build Sarathi.",
  status: "live",
  policyPack: "./policy-pack",
  sqlite: ".sarathi/sarathi.db",
  repos: [
    {
      id: "repo-1",
      name: "Sarathi",
      path: "/Users/sweethome/Work/Skills/Sarathi",
      branch: "main",
      gitState: "dirty",
      permission: "write",
    },
    {
      id: "repo-2",
      name: "Sarathi Desktop",
      path: "/Users/sweethome/Work/Skills/Sarathi/desktop",
      branch: "ui-foundation",
      gitState: "clean",
      permission: "write",
    },
  ],
  docs: [
    { name: "SARATHI.md", state: "generated", note: "AI-readable workspace guide." },
    { name: "policy-pack/", state: "valid", note: "Commands, review, routing, escalation." },
    { name: "coding-standards.md", state: "draft", note: "UI and service standards under review." },
    { name: "learnings.md", state: "active", note: "Updated after accepted dogfood learnings." },
  ],
};

export const providers: Provider[] = [
  {
    id: "codex",
    name: "Codex",
    type: "CLI",
    health: "online",
    auth: "connected",
    path: "/usr/local/bin/codex",
    capabilities: ["planning", "coding", "review", "shell", "git", "repo-aware"],
  },
  {
    id: "claude",
    name: "Claude",
    type: "CLI",
    health: "offline",
    auth: "connected",
    path: "/usr/local/bin/claude",
    capabilities: ["research", "review", "multimodal"],
  },
  {
    id: "copilot",
    name: "Copilot",
    type: "Agent",
    health: "degraded",
    auth: "missing",
    path: "GitHub app configuration",
    capabilities: ["coding", "review", "git"],
  },
  {
    id: "local",
    name: "Local deterministic",
    type: "Fallback",
    health: "online",
    auth: "not required",
    path: "sarathi-local",
    capabilities: ["planning", "diagramming", "validation"],
  },
  {
    id: "opencode",
    name: "OpenCode",
    type: "CLI",
    health: "configured_by_user",
    auth: "workspace_setting",
    path: "opencode",
    capabilities: ["coding", "planning", "review"],
  },
];

export const roles: Role[] = [
  { name: "Sarathi", function: "Orchestrator", state: "active", provider: "Codex" },
  { name: "Disha", function: "Planner", state: "idle", provider: "Codex" },
  { name: "Vichara", function: "Researcher", state: "queued", provider: "Claude" },
  { name: "Prajna", function: "Reasoner", state: "active", provider: "Codex" },
  { name: "Marga", function: "Router", state: "idle", provider: "Local deterministic" },
  { name: "Sutra", function: "Message bus", state: "live", provider: "Local deterministic" },
  { name: "Pravaha", function: "Executor", state: "active", provider: "Codex" },
  { name: "Nirnaya", function: "Reviewer", state: "waiting", provider: "Claude" },
  { name: "Samanvaya", function: "Coordinator", state: "idle", provider: "Codex" },
  { name: "Sahayaka", function: "Support", state: "idle", provider: "Copilot" },
];

export const tasks: Task[] = [
  {
    id: "SA-001",
    title: "Sarathi UI foundation",
    status: "in_progress",
    phase: "Build",
    progress: 42,
    reviewState: "not reviewed",
    repoState: "dirty worktree warning",
    summary: "Create the first real desktop UI shell from the v2 prototype and dogfood artifacts.",
  },
  {
    id: "SA-000",
    title: "Sarathi app technical design",
    status: "complete",
    phase: "Handoff",
    progress: 100,
    reviewState: "approved",
    repoState: "no mutation",
    summary: "Senior staff technical design for local service, desktop UI, SQLite, SSE, and dogfood flow.",
  },
];

export const subtasks: Subtask[] = [
  {
    id: "ST-01",
    title: "Desktop package scaffold",
    state: "complete",
    role: "Pravaha",
    provider: "Codex",
    blockedBy: [],
    evidenceCount: 2,
    review: "pending",
    ac: ["AC-01"],
    goal: "Create desktop package, scripts, entrypoint, and Vite config.",
    context: "Keep this isolated from the Python runtime.",
    files: ["desktop/package.json", "desktop/src/main.tsx"],
    nextAction: "Build shell components.",
    x: 70,
    y: 70,
  },
  {
    id: "ST-02",
    title: "Workspace-first shell",
    state: "in_progress",
    role: "Pravaha",
    provider: "Codex",
    blockedBy: ["ST-01"],
    evidenceCount: 1,
    review: "not started",
    ac: ["AC-02", "AC-03"],
    goal: "Render transparent nav, command bar, status strip, and workspace overview.",
    context: "No task exists outside a workspace.",
    files: ["desktop/src/App.tsx", "desktop/src/styles.css"],
    nextAction: "Finish Task Studio.",
    x: 330,
    y: 70,
  },
  {
    id: "ST-03",
    title: "Task Studio truth surface",
    state: "queued",
    role: "Pravaha",
    provider: "Codex",
    blockedBy: ["ST-02"],
    evidenceCount: 0,
    review: "not started",
    ac: ["AC-04", "AC-05"],
    goal: "Show graph/list, packet, approval gates, messages, evidence, review, history, and handoff.",
    context: "This is the most important product surface.",
    files: ["desktop/src/App.tsx"],
    nextAction: "Wait for shell.",
    x: 210,
    y: 245,
  },
  {
    id: "ST-04",
    title: "Dogfood evidence",
    state: "waiting_human",
    role: "Samanvaya",
    provider: "Codex",
    blockedBy: ["ST-03"],
    evidenceCount: 0,
    review: "not started",
    ac: ["AC-06"],
    goal: "Make the UI prove Sarathi is being built through Sarathi artifacts.",
    context: "Release dossier must be visible later.",
    files: ["docs/superpowers/plans/2026-04-27-sarathi-ui-foundation.md"],
    nextAction: "Attach verification.",
    x: 330,
    y: 420,
  },
];

export const approvalGates: ApprovalGate[] = [
  {
    id: "GATE-01",
    name: "PRD/AC approval",
    status: "approved",
    help: "This UI slice follows the approved PRD and technical design.",
    auditEventId: "EVT-01",
    linkedObjects: ["SA-001", "AC-01", "AC-02"],
  },
  {
    id: "GATE-02",
    name: "Task graph approval",
    status: "approved",
    help: "Multiple subtasks require an approved graph before dispatch.",
    auditEventId: "EVT-02",
    linkedObjects: ["ST-01", "ST-02", "ST-03", "ST-04"],
  },
  {
    id: "GATE-03",
    name: "Repository action",
    status: "waiting_human",
    help: "Commit or PR is blocked until explicit approval.",
    auditEventId: "EVT-05",
    linkedObjects: ["Sarathi", "desktop"],
  },
];

export const evidence: EvidenceArtifact[] = [
  {
    id: "EV-01",
    title: "Technical design created",
    type: "doc",
    state: "accepted",
    source: "Sarathi",
    linkedAc: "AC-01",
    linkedUnit: "ST-01",
    linkedGate: "GATE-01",
    linkedEvent: "EVT-01",
  },
  {
    id: "EV-02",
    title: "UI foundation plan created",
    type: "plan",
    state: "accepted",
    source: "Disha",
    linkedAc: "AC-02",
    linkedUnit: "ST-01",
    linkedGate: "GATE-02",
    linkedEvent: "EVT-02",
  },
];

export const reviews: ReviewRun[] = [
  {
    id: "RV-01",
    type: "code",
    verdict: "pending",
    reviewer: "Nirnaya",
    loop: "0/5",
    severity: "normal",
    finding: "Review after the UI shell builds successfully.",
    linkedUnit: "ST-02",
    linkedEvidence: ["EV-01", "EV-02"],
    linkedGate: "GATE-03",
    linkedEvent: "EVT-04",
  },
];

export const events: SarathiEvent[] = [
  { id: "EVT-01", time: "09:10", source: "Sarathi", event: "Technical design accepted as build input", object: "SA-000", severity: "info" },
  { id: "EVT-02", time: "09:18", source: "Disha", event: "UI foundation implementation plan created", object: "SA-001", severity: "info" },
  { id: "EVT-03", time: "09:24", source: "Pravaha", event: "Desktop package scaffold started", object: "ST-01", severity: "active" },
  { id: "EVT-04", time: "09:31", source: "Sutra", event: "SSE placeholder state rendered in UI", object: "desktop", severity: "warning" },
  { id: "EVT-05", time: "09:35", source: "Samanvaya", event: "Repository action gate remains waiting human", object: "GATE-03", severity: "decision" },
];

export const messages: Message[] = [
  {
    from: "User",
    target: "Sarathi",
    tag: "SA-001",
    text: "Start the work, use Sarathi to develop Sarathi UI.",
    impact: "created dogfood task",
  },
  {
    from: "Sarathi",
    target: "Current task agents",
    tag: "Plan",
    text: "We will build the UI shell first, keep Python as orchestration authority, and record this as dogfood evidence.",
    impact: "approved route",
  },
  {
    from: "Pravaha",
    target: "Samanvaya",
    tag: "Build",
    text: "Desktop package scaffold is isolated under desktop/ and ready for the shell.",
    impact: "state changed",
  },
];

// ── Metrics (Dashboard-View mockup) ───────────────────────────────────────────

export type MetricCard = {
  label: string;
  value: string | number;
  delta?: string;
  deltaPositive?: boolean;
  unit?: string;
};

export const metrics: MetricCard[] = [
  { label: "Total Runs", value: "12,847", delta: "+12%", deltaPositive: true },
  { label: "Success Rate", value: "98.2%", delta: "+0.4%", deltaPositive: true },
  { label: "Active Workflows", value: "23", delta: "+3", deltaPositive: true },
  { label: "AI Tokens", value: "842K", delta: "-2%", deltaPositive: false },
];

// ── Policy-pack Templates ─────────────────────────────────────────────────────

export type TemplateCard = {
  id: string;
  name: string;
  category: string;
  complexity: "low" | "medium" | "high";
  phases: number;
  description: string;
  icon: string;
};

export const templates: TemplateCard[] = [
  {
    id: "tmpl-full",
    name: "Full Lifecycle (High)",
    category: "Lifecycle",
    complexity: "high",
    phases: 12,
    description: "All 12 phases: Route → Brainstorm → PlanningAdvisor → Plan → Build → Verify → Review → TaskTracking → RiskCheck → Elegance → PhaseLog → Learn",
    icon: "⚙",
  },
  {
    id: "tmpl-accel",
    name: "Accelerated (Medium)",
    category: "Lifecycle",
    complexity: "medium",
    phases: 11,
    description: "Skips PlanningAdvisor. Best for well-scoped features and multi-file changes.",
    icon: "▶",
  },
  {
    id: "tmpl-minimal",
    name: "Minimal (Low)",
    category: "Lifecycle",
    complexity: "low",
    phases: 11,
    description: "Skips PlanningAdvisor. Best for bug fixes, docs, and single-file changes.",
    icon: "✓",
  },
  {
    id: "tmpl-bugfix",
    name: "Bug Fix",
    category: "Task Type",
    complexity: "low",
    phases: 11,
    description: "Low complexity preset. Focuses Brainstorm on root-cause analysis and Verify on regression coverage.",
    icon: "🐛",
  },
  {
    id: "tmpl-feature",
    name: "Feature Development",
    category: "Task Type",
    complexity: "medium",
    phases: 11,
    description: "Medium complexity preset. Brainstorm explores alternatives; Plan creates a task graph; Build dispatches via Codex/Claude.",
    icon: "✦",
  },
  {
    id: "tmpl-arch",
    name: "Architecture Review",
    category: "Task Type",
    complexity: "high",
    phases: 12,
    description: "High complexity. PlanningAdvisor challenges scope; RiskCheck runs devil's advocate; full evidence gates required.",
    icon: "◈",
  },
  {
    id: "tmpl-refactor",
    name: "Refactor / Cleanup",
    category: "Task Type",
    complexity: "medium",
    phases: 11,
    description: "Medium complexity. Elegance phase drives the polish pass; Review checks for regressions.",
    icon: "↻",
  },
  {
    id: "tmpl-security",
    name: "Security-Sensitive Change",
    category: "Policy",
    complexity: "high",
    phases: 12,
    description: "High complexity. Escalation policy enforces capable-model routing; RiskCheck mandates threat model evidence.",
    icon: "⚿",
  },
];

export const templateCategories = ["All", "Lifecycle", "Task Type", "Policy"];

// ── Workflow runs (Sarathi task history) ──────────────────────────────────────

export type WorkflowItem = {
  id: string;
  name: string;
  complexity: "low" | "medium" | "high";
  phase: string;
  successRate: number;
  lastRun: string;
  status: "in_progress" | "complete" | "paused" | "failed";
};

export const workflows: WorkflowItem[] = [
  { id: "wf-p12", name: "Cross hunk clustering and review confidence synthesis", complexity: "high", phase: "Learn", successRate: 100, lastRun: "2 days ago", status: "complete" },
  { id: "wf-p11", name: "Provider-backed diff risk synthesis", complexity: "high", phase: "Learn", successRate: 100, lastRun: "2 days ago", status: "complete" },
  { id: "wf-p10", name: "Provider-backed spec drift enforcement", complexity: "high", phase: "Learn", successRate: 100, lastRun: "2 days ago", status: "complete" },
  { id: "wf-p9",  name: "Provider diff + spec evidence depth", complexity: "high", phase: "Learn", successRate: 100, lastRun: "2 days ago", status: "complete" },
  { id: "wf-p8",  name: "Provider review trace depth", complexity: "high", phase: "Learn", successRate: 100, lastRun: "2 days ago", status: "complete" },
  { id: "wf-v105", name: "Desktop packaging + startup foundation", complexity: "medium", phase: "Learn", successRate: 100, lastRun: "2 days ago", status: "complete" },
  { id: "wf-v104", name: "100% zoom UX density pass", complexity: "medium", phase: "Learn", successRate: 100, lastRun: "2 days ago", status: "complete" },
  { id: "wf-m6",  name: "Sarathi Desktop Dogfood MVP", complexity: "high", phase: "Learn", successRate: 100, lastRun: "2 days ago", status: "complete" },
  { id: "wf-fix", name: "Fix UI: Agents/Templates/Workflows tabs", complexity: "medium", phase: "Build", successRate: 0, lastRun: "Now", status: "in_progress" },
];
