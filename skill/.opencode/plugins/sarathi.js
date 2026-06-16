/**
 * Sarathi plugin for OpenCode.
 *
 * Detects Sarathi-ready workspaces and injects the Sarathi bootstrap context
 * into the first user message. It also exposes this skill directory to
 * OpenCode's skill discovery.
 */

import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const sarathiSkillDir = path.resolve(__dirname, '../..');
const skillPath = path.join(sarathiSkillDir, 'SKILL.md');
const bootstrapCache = new Map();

const normalizePath = (value) => {
  if (!value || typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (trimmed === '~') return os.homedir();
  if (trimmed.startsWith('~/')) return path.join(os.homedir(), trimmed.slice(2));
  return path.resolve(trimmed);
};

const isSarathiWorkspace = (dir) => {
  return (
    fs.existsSync(path.join(dir, 'policy-pack')) ||
    fs.existsSync(path.join(dir, '.sarathi')) ||
    fs.existsSync(path.join(dir, 'SARATHI.md'))
  );
};

const findSarathiWorkspace = (directory) => {
  let current = normalizePath(process.env.SARATHI_PROJECT_DIR) ||
    normalizePath(process.env.CLAUDE_PROJECT_DIR) ||
    normalizePath(directory) ||
    process.cwd();

  while (current && current !== path.dirname(current)) {
    if (isSarathiWorkspace(current)) return current;
    current = path.dirname(current);
  }
  return null;
};

const getBootstrapContent = (workspaceRoot) => {
  if (bootstrapCache.has(workspaceRoot)) return bootstrapCache.get(workspaceRoot);
  if (!fs.existsSync(skillPath)) {
    bootstrapCache.set(workspaceRoot, null);
    return null;
  }

  const skillContent = fs.readFileSync(skillPath, 'utf8');
  const bootstrap = `<SARATHI_SESSION_START>
Sarathi workspace detected at: ${workspaceRoot}

You are starting inside a Sarathi-ready workspace. Use Sarathi's policy-backed lifecycle when the work benefits from structured route, brainstorm, plan, build, verify, review, task tracking, and learn phases.

Use the workspace policy pack as the source of truth when it exists:
- ${path.join(workspaceRoot, 'policy-pack')}

Do not mutate files or start services only because this plugin fired. Treat this as operating context for the session.

Below is the full content of your 'sarathi' skill:

${skillContent}
</SARATHI_SESSION_START>`;

  bootstrapCache.set(workspaceRoot, bootstrap);
  return bootstrap;
};

export const SarathiPlugin = async ({ directory }) => {
  const workspaceRoot = findSarathiWorkspace(directory);

  return {
    config: async (config) => {
      config.skills = config.skills || {};
      config.skills.paths = config.skills.paths || [];
      if (!config.skills.paths.includes(sarathiSkillDir)) {
        config.skills.paths.push(sarathiSkillDir);
      }
    },

    'experimental.chat.messages.transform': async (_input, output) => {
      if (!workspaceRoot || !output.messages.length) return;
      const bootstrap = getBootstrapContent(workspaceRoot);
      if (!bootstrap) return;

      const firstUser = output.messages.find((message) => message.info.role === 'user');
      if (!firstUser || !firstUser.parts.length) return;
      if (firstUser.parts.some((part) => part.type === 'text' && part.text.includes('SARATHI_SESSION_START'))) {
        return;
      }

      const ref = firstUser.parts[0];
      firstUser.parts.unshift({ ...ref, type: 'text', text: bootstrap });
    },
  };
};
