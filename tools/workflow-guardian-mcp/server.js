/**
 * Workflow Guardian MCP Server + HTTP Dashboard
 *
 * MCP stdio server (JSON-RPC): lets Claude query/update workflow state
 * HTTP server (port 3848): serves dashboard UI for the user
 *
 * Zero npm dependencies. Node.js 18+.
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const { exec } = require("child_process");

// ─── Crash protection & logging ─────────────────────────────────────────────

const CLAUDE_DIR = path.join(require("os").homedir(), ".claude");
const WORKFLOW_DIR = path.join(CLAUDE_DIR, "workflow");
const CRASH_LOG = path.join(WORKFLOW_DIR, "guardian-crash.log");

let _crashLogging = false;
function crashLog(label, err) {
  if (_crashLogging) return;          // re-entry guard: prevent EPIPE cascade
  _crashLogging = true;
  const ts = new Date().toISOString();
  const msg = `[${ts}] ${label}: ${err?.stack || err}\n`;
  try { fs.appendFileSync(CRASH_LOG, msg); } catch {}
  try { process.stderr.write(`[workflow-guardian] ${label}: ${err?.message || err}\n`); } catch {}
  _crashLogging = false;
}

process.on("uncaughtException", (err) => {
  crashLog("UncaughtException", err);
});
process.on("unhandledRejection", (reason) => {
  crashLog("UnhandledRejection", reason);
});
process.on("SIGTERM", () => {
  crashLog("SIGTERM", "Process received SIGTERM");
});
process.on("SIGINT", () => {
  crashLog("SIGINT", "Process received SIGINT");
});
const MEMORY_DIR = path.join(CLAUDE_DIR, "memory");
const TOOLS_DIR = path.join(CLAUDE_DIR, "tools");
const CONFIG_PATH = path.join(WORKFLOW_DIR, "config.json");
const REGISTRY_PATH = path.join(MEMORY_DIR, "project-registry.json");
const VERSION_PATH = path.join(CLAUDE_DIR, "version.json");
const DASHBOARD_PORT = loadConfig().dashboard_port || 3848;

function loadVersions() {
  try { return JSON.parse(fs.readFileSync(VERSION_PATH, "utf-8")); }
  catch { return { guardian: "0.0.0", atom_memory: "?" }; }
}
const VERSIONS = loadVersions();

function loadRegistry() {
  try {
    return JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf-8"));
  } catch {
    return { projects: {} };
  }
}

/** Returns [{slug, memDir}] for all registered projects that have .claude/memory/ */
function getRegistryMemDirs() {
  const reg = loadRegistry();
  const results = [];
  for (const [slug, info] of Object.entries(reg.projects || {})) {
    if (!info.root) continue;
    const newMem = path.join(info.root, ".claude", "memory");
    if (fs.existsSync(newMem)) {
      results.push({ slug, memDir: newMem });
    }
  }
  return results;
}

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"));
  } catch {
    return {};
  }
}

// ─── State File I/O ─────────────────────────────────────────────────────────

function listStatePaths() {
  try {
    return fs
      .readdirSync(WORKFLOW_DIR)
      .filter((f) => f.startsWith("state-") && f.endsWith(".json"))
      .map((f) => path.join(WORKFLOW_DIR, f));
  } catch {
    return [];
  }
}

function resolveSessionId(prefix) {
  // Support prefix matching: "3c7a47d0" → full UUID
  // Direct hit: exact filename exists → fast path
  const directPath = path.join(WORKFLOW_DIR, `state-${prefix}.json`);
  try { if (fs.existsSync(directPath)) return prefix; } catch {}

  // Prefix search: enumerate state files
  const ids = listStatePaths().map((p) =>
    path.basename(p).replace("state-", "").replace(".json", "")
  );
  const matches = ids.filter((id) => id.startsWith(prefix));
  if (matches.length === 1) return matches[0];
  if (matches.length === 0) return null;
  // Ambiguous: return null (caller handles error)
  return null;
}

function readState(sessionId) {
  const p = path.join(WORKFLOW_DIR, `state-${sessionId}.json`);
  try {
    return JSON.parse(fs.readFileSync(p, "utf-8"));
  } catch {
    return null;
  }
}

function writeState(sessionId, state) {
  state.last_updated = new Date().toISOString();
  const p = path.join(WORKFLOW_DIR, `state-${sessionId}.json`);
  const tmp = p + ".tmp";
  try {
    fs.mkdirSync(WORKFLOW_DIR, { recursive: true });
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2), "utf-8");
    fs.renameSync(tmp, p);
  } catch {
    try { fs.unlinkSync(tmp); } catch {}
  }
}

function deleteState(sessionId) {
  const p = path.join(WORKFLOW_DIR, `state-${sessionId}.json`);
  try {
    fs.unlinkSync(p);
    return true;
  } catch {
    return false;
  }
}

function deriveSessionName(cwd) {
  if (!cwd) return "unknown";
  // Normalize path separators and extract last meaningful directory
  const parts = cwd.replace(/\\/g, "/").replace(/\/+$/, "").split("/").filter(Boolean);
  return parts[parts.length - 1] || "unknown";
}

function listAllSessions() {
  const cfg = loadConfig().cleanup || {};
  const DONE_TTL_MS    = cfg.ended_ttl_ms          || 60 * 1000;          // 1 min
  const ORPHAN_DONE_MS = cfg.orphan_done_ttl_ms     || 30 * 60 * 1000;    // 30 min
  const ORPHAN_WORK_MS = cfg.orphan_working_ttl_ms  || 24 * 60 * 60 * 1000; // 24 hr

  return listStatePaths().map((p) => {
    try {
      const state = JSON.parse(fs.readFileSync(p, "utf-8"));
      const sid = state.session?.id || path.basename(p).replace("state-", "").replace(".json", "");
      const now = Date.now();

      // ── Auto-cleanup (3-tier) ─────────────────────────────────────
      const safeTs = (v) => { const t = new Date(v).getTime(); return isNaN(t) ? 0 : t; };

      // Tier 1: ended_at is set → clean after 1 min
      if (state.ended_at) {
        const endedAge = now - safeTs(state.ended_at);
        if (endedAge > DONE_TTL_MS) {
          process.stderr.write(`[guardian] cleanup: ended session ${sid.slice(0,8)} (${Math.round(endedAge/60000)}min)\n`);
          try { fs.unlinkSync(p); } catch {}
          return null;
        }
      }

      // Tier 2: phase=done but no ended_at (orphan) → clean after 30 min
      if (!state.ended_at && state.phase === "done") {
        const lu = safeTs(state.last_updated);
        if (lu && (now - lu) > ORPHAN_DONE_MS) {
          process.stderr.write(`[guardian] cleanup: orphan-done ${sid.slice(0,8)} (${Math.round((now-lu)/60000)}min idle)\n`);
          try { fs.unlinkSync(p); } catch {}
          return null;
        }
      }

      // Tier 3: not done, no ended_at, no activity for 24h → dead session
      if (!state.ended_at && state.phase !== "done") {
        const ref = safeTs(state.last_updated) || safeTs(state.session?.started_at);
        if (ref && (now - ref) > ORPHAN_WORK_MS) {
          process.stderr.write(`[guardian] cleanup: stale-working ${sid.slice(0,8)} (${Math.round((now-ref)/3600000)}h idle)\n`);
          try { fs.unlinkSync(p); } catch {}
          return null;
        }
      }

      // ── Build session info ────────────────────────────────────────
      const startedAt = state.session?.started_at || "";
      const ageMs = startedAt ? now - new Date(startedAt).getTime() : 0;
      return {
        session_id: sid,
        name: deriveSessionName(state.session?.cwd),
        phase: state.phase || "unknown",
        project: state.session?.cwd || "",
        started_at: startedAt,
        modified_files_count: (state.modified_files || []).length,
        knowledge_queue_count: (state.knowledge_queue || []).length,
        sync_pending: state.sync_pending || false,
        age_minutes: Math.round(ageMs / 60000),
        ended: !!state.ended_at,
        muted: !!state.muted,
        merged_into: state.merged_into || null,
        skip_vector_init: !!state._skip_vector_init,
      };
    } catch {
      return null;
    }
  }).filter(Boolean);
}

// ─── MCP Protocol ───────────────────────────────────────────────────────────

let buffer = "";

process.stdin.setEncoding("utf-8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  processBuffer();
});

function processBuffer() {
  // Newline-delimited JSON (Claude Code 2.x transport format)
  let line;
  while ((line = extractLine()) !== null) {
    if (!line.trim()) continue;
    try {
      const parsed = JSON.parse(line);
      handleMessage(parsed);
    } catch (err) {
      crashLog("PARSE_ERROR", err);
      sendError(null, -32700, "Parse error");
    }
  }
}

function extractLine() {
  // Try newline-delimited first (what Claude Code actually sends)
  const nlIdx = buffer.indexOf("\n");
  if (nlIdx !== -1) {
    const line = buffer.slice(0, nlIdx);
    buffer = buffer.slice(nlIdx + 1);
    return line;
  }
  return null;
}

function sendResponse(id, result) {
  const msg = JSON.stringify({ jsonrpc: "2.0", id, result });
  process.stdout.write(msg + "\n");
}

function sendError(id, code, message) {
  const msg = JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } });
  process.stdout.write(msg + "\n");
}

// ─── MCP Message Handler ────────────────────────────────────────────────────

function handleMessage(msg) {
  const { id, method, params } = msg;

  switch (method) {
    case "initialize":
      sendResponse(id, {
        protocolVersion: "2025-11-25",
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "workflow-guardian", version: VERSIONS.guardian },
      });
      break;

    case "notifications/initialized":
      break;

    case "tools/list":
      sendResponse(id, { tools: TOOL_DEFINITIONS });
      break;

    case "tools/call":
      handleToolCall(id, params?.name, params?.arguments || {});
      break;

    default:
      if (id !== undefined) {
        sendError(id, -32601, `Method not found: ${method}`);
      }
  }
}

// ─── Tool Definitions ───────────────────────────────────────────────────────

const TOOL_DEFINITIONS = [
  {
    name: "workflow_status",
    description:
      "Query the current workflow guardian state. " +
      "Shows modified files, knowledge queue, sync status, and phase. " +
      "Omit session_id to list all active sessions.",
    inputSchema: {
      type: "object",
      properties: {
        session_id: {
          type: "string",
          description: "Session ID to query. Omit for all sessions.",
        },
      },
    },
  },
  {
    name: "workflow_signal",
    description:
      "Send a workflow signal to update session state. " +
      "Use sync_started when beginning sync, sync_completed when done, " +
      "reset to clear a stuck state.",
    inputSchema: {
      type: "object",
      properties: {
        session_id: { type: "string", description: "Target session ID" },
        signal: {
          type: "string",
          enum: ["sync_started", "sync_completed", "reset", "mute"],
          description: "Signal to send. Use 'mute' to silence Guardian reminders for this session.",
        },
      },
      required: ["session_id", "signal"],
    },
  },
  {
    name: "memory_queue_add",
    description:
      "Add a knowledge item to the session's pending memory queue. " +
      "Items will be written to atom files during end-of-session sync.",
    inputSchema: {
      type: "object",
      properties: {
        session_id: { type: "string" },
        content: {
          type: "string",
          description: "The knowledge to remember",
        },
        classification: {
          type: "string",
          enum: ["[固]", "[觀]", "[臨]"],
          description: "Memory classification level",
        },
        trigger_context: {
          type: "string",
          description: "What triggered this knowledge discovery",
        },
      },
      required: ["session_id", "content", "classification"],
    },
  },
  {
    name: "memory_queue_flush",
    description:
      "Mark all pending knowledge queue items as flushed (written to atoms). " +
      "Call this after successfully writing atom files.",
    inputSchema: {
      type: "object",
      properties: {
        session_id: { type: "string" },
      },
      required: ["session_id"],
    },
  },
  {
    name: "atom_write",
    description:
      "Write or update an atom file with validated format. " +
      "Ensures correct metadata structure, runs write-gate dedup, " +
      "updates MEMORY.md index, and triggers vector indexing. " +
      "V4: supports shared/role/personal scopes; sensitive audience " +
      "(architecture/decision) on shared auto-routes to _pending_review/.",
    inputSchema: {
      type: "object",
      properties: {
        title: { type: "string", description: "Atom title (becomes # heading and filename slug)" },
        scope: {
          type: "string",
          enum: ["global", "shared", "role", "personal", "project"],
          description: "V4 scope. shared=project-wide, role=role-shared (requires `role`), personal=per-user (requires `user` or defaults to current). global=cross-project. project (legacy)=transparently mapped to shared. Defaults to shared.",
        },
        role: {
          type: "string",
          description: "Role subdir name (e.g. art, programmer, planner). Required when scope=role.",
        },
        user: {
          type: "string",
          description: "Personal subdir owner. Required when scope=personal; falls back to current OS user.",
        },
        audience: {
          type: "array", items: { type: "string" },
          description: "Audience tags (multi-role). On scope=shared, presence of 'architecture' or 'decision' auto-routes atom to _pending_review/ with Pending-review-by: management.",
        },
        pending_review_by: {
          type: "string",
          description: "Optional Pending-review-by metadata (e.g. 'management'). Auto-set for sensitive audience on shared.",
        },
        merge_strategy: {
          type: "string", enum: ["ai-assist", "git-only"],
          description: "Optional Merge-strategy metadata. Default ai-assist (omitted from file).",
        },
        confidence: { type: "string", enum: ["[固]", "[觀]", "[臨]"], description: "Confidence level" },
        triggers: {
          type: "array", items: { type: "string" },
          description: "Trigger keywords for MEMORY.md index",
        },
        knowledge: {
          type: "array", items: { type: "string" },
          description: "Knowledge lines (each prefixed with [固]/[觀]/[臨])",
        },
        actions: {
          type: "array", items: { type: "string" },
          description: "Action guidelines",
        },
        related: {
          type: "array", items: { type: "string" },
          description: "Related atom names (optional)",
        },
        mode: {
          type: "string", enum: ["create", "append", "replace"],
          description: "create=new atom, append=add knowledge lines, replace=overwrite knowledge section",
        },
        project_cwd: {
          type: "string",
          description: "Project root path (required for scope=shared/role/personal)",
        },
        skip_gate: {
          type: "boolean",
          description: "Skip write-gate quality check (for [固] or explicit user request)",
        },
        skip_conflict_check: {
          type: "boolean",
          description: "Skip V4 Phase 5 write-time conflict detection (shared scope only). Use only for controlled migrations / tests.",
        },
      },
      required: ["title", "confidence", "triggers", "knowledge", "mode"],
    },
  },
  {
    name: "atom_promote",
    description:
      "Promote an atom's confidence level. " +
      "Checks dual thresholds: [臨]→[觀] Conf≥4 or RH≥20, [觀]→[固] Conf≥10 or RH≥50. " +
      "Use execute=false for dry-run. " +
      "When promoting to [固], pass merge_to_preferences=true to append knowledge " +
      "into preferences.md and archive the source atom (global scope only).",
    inputSchema: {
      type: "object",
      properties: {
        atom_name: { type: "string", description: "Atom filename without .md extension" },
        scope: { type: "string", enum: ["global", "project"], description: "Scope to search in" },
        project_cwd: { type: "string", description: "Project root (required for project scope)" },
        execute: { type: "boolean", description: "true=execute promotion, false=dry-run check only" },
        merge_to_preferences: {
          type: "boolean",
          description: "On [觀]→[固] promotion, auto-merge knowledge into preferences.md and archive this atom. global scope only. Default false.",
        },
      },
      required: ["atom_name", "scope", "execute"],
    },
  },
  {
    name: "atom_move",
    description:
      "Atomic atom move/reconcile across memory layers. " +
      "subcommand='move' moves atom from --from to --to (both memory-root dirs) and syncs _ATOM_INDEX/MEMORY.md/inbound refs. " +
      "subcommand='reconcile' assumes atom already lives at --at and cleans stale state elsewhere. " +
      "Enforces layering: down-refs (global→project) removed automatically, up-refs (project→global) kept, " +
      "sibling cross-project refs reported as warnings. Use dry_run=true to preview.",
    inputSchema: {
      type: "object",
      properties: {
        subcommand: { type: "string", enum: ["move", "reconcile"], description: "move=full mv + sync; reconcile=sync only (atom already at target)" },
        atom: { type: "string", description: "Atom slug (filename without .md)" },
        from: { type: "string", description: "Source memory root dir (required for move)" },
        to: { type: "string", description: "Target memory root dir (required for move)" },
        at: { type: "string", description: "Current memory root where atom lives (required for reconcile)" },
        dry_run: { type: "boolean", description: "Preview without applying changes" },
      },
      required: ["subcommand", "atom"],
    },
  },
];

// ─── Tool Handlers ──────────────────────────────────────────────────────────

function handleToolCall(id, toolName, args) {
  switch (toolName) {
    case "workflow_status":
      return toolWorkflowStatus(id, args);
    case "workflow_signal":
      return toolWorkflowSignal(id, args);
    case "memory_queue_add":
      return toolMemoryQueueAdd(id, args);
    case "memory_queue_flush":
      return toolMemoryQueueFlush(id, args);
    case "atom_write":
      return toolAtomWrite(id, args).catch(e => sendToolResult(id, `atom_write error: ${e.message}`, true));
    case "atom_promote":
      // S3.2: toolAtomPromote 改 async，需 .catch 包 throw（與 atom_write/atom_move 一致）
      return toolAtomPromote(id, args).catch(e => sendToolResult(id, `atom_promote error: ${e.message}`, true));
    case "atom_move":
      return toolAtomMove(id, args).catch(e => sendToolResult(id, `atom_move error: ${e.message}`, true));
    default:
      sendError(id, -32601, `Unknown tool: ${toolName}`);
  }
}

function toolWorkflowStatus(id, args) {
  if (args.session_id) {
    const resolved = resolveSessionId(args.session_id);
    if (!resolved) {
      return sendToolResult(id, `No state found for session ${args.session_id}`);
    }
    const state = readState(resolved);
    if (!state) {
      return sendToolResult(id, `No state found for session ${args.session_id}`);
    }
    const modFiles = (state.modified_files || [])
      .map((m) => `  - ${m.path} (${m.tool} @ ${m.at})`)
      .join("\n");
    const kqItems = (state.knowledge_queue || [])
      .map((q) => `  - ${q.classification} ${q.content}`)
      .join("\n");
    const text = [
      `## Session ${args.session_id}`,
      `- Phase: ${state.phase}`,
      `- CWD: ${state.session?.cwd || "?"}`,
      `- Started: ${state.session?.started_at || "?"}`,
      `- Sync pending: ${state.sync_pending}`,
      `- Stop blocked: ${state.stop_blocked_count || 0}x`,
      "",
      `### Modified files (${(state.modified_files || []).length})`,
      modFiles || "  (none)",
      "",
      `### Knowledge queue (${(state.knowledge_queue || []).length})`,
      kqItems || "  (none)",
    ].join("\n");
    return sendToolResult(id, text);
  }

  // List all sessions
  const sessions = listAllSessions();
  if (sessions.length === 0) {
    return sendToolResult(id, "No active workflow sessions.");
  }
  const lines = sessions.map(
    (s) =>
      `- **${s.session_id.slice(0, 8)}** | ${s.phase} | files: ${s.modified_files_count} | knowledge: ${s.knowledge_queue_count} | ${s.age_minutes}min${s.ended ? " (ended)" : ""}`
  );
  return sendToolResult(id, "## Active Sessions\n" + lines.join("\n"));
}

function toolWorkflowSignal(id, args) {
  const { session_id, signal } = args;
  const resolved = resolveSessionId(session_id);
  if (!resolved) {
    return sendToolResult(id, `No state found for session ${session_id}`, true);
  }
  const state = readState(resolved);
  if (!state) {
    return sendToolResult(id, `No state found for session ${session_id}`, true);
  }

  switch (signal) {
    case "sync_started":
      state.phase = "syncing";
      break;
    case "sync_completed":
      state.phase = "done";
      state.sync_pending = false;
      state.knowledge_queue = [];
      state.modified_files = [];
      state.ended_at = new Date().toISOString();
      break;
    case "reset":
      state.phase = "working";
      state.sync_pending = false;
      state.stop_blocked_count = 0;
      state.remind_count = 0;
      state.muted = false;
      break;
    case "mute":
      state.muted = true;
      break;
  }

  writeState(resolved, state);
  return sendToolResult(id, `Signal '${signal}' applied. Phase: ${state.phase}`);
}

function toolMemoryQueueAdd(id, args) {
  const { session_id, content, classification, trigger_context } = args;
  const resolved = resolveSessionId(session_id);
  if (!resolved) {
    return sendToolResult(id, `No state found for session ${session_id}`, true);
  }
  const state = readState(resolved);
  if (!state) {
    return sendToolResult(id, `No state found for session ${session_id}`, true);
  }

  state.knowledge_queue = state.knowledge_queue || [];
  state.knowledge_queue.push({
    content,
    classification: classification || "[臨]",
    context: trigger_context || "",
    at: new Date().toISOString(),
  });
  state.sync_pending = true;
  writeState(resolved, state);

  return sendToolResult(
    id,
    `Added to knowledge queue (${state.knowledge_queue.length} items): ${classification} ${content.slice(0, 60)}`
  );
}

function toolMemoryQueueFlush(id, args) {
  const { session_id } = args;
  const resolved = resolveSessionId(session_id);
  if (!resolved) {
    return sendToolResult(id, `No state found for session ${session_id}`, true);
  }
  const state = readState(resolved);
  if (!state) {
    return sendToolResult(id, `No state found for session ${session_id}`, true);
  }

  const count = (state.knowledge_queue || []).length;
  state.knowledge_queue = [];
  writeState(resolved, state);

  return sendToolResult(id, `Flushed ${count} knowledge queue items.`);
}

// ─── Atom Write/Promote Helpers ────────────────────────────────────────────

/** Convert title to a safe filename slug (lowercase, hyphens, no special chars) */
function slugify(title) {
  return title
    .toLowerCase()
    .replace(/[\s_]+/g, "-")
    .replace(/[^a-z0-9\u4e00-\u9fff\u3400-\u4dbf-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    || "untitled";
}

/** Build atom file content from structured parameters.
 *  V4: scopeLabel may be plain "shared"/"global" or composite "role:art"/"personal:alice".
 *  Optional metadata (audience/author/pending_review_by/merge_strategy/created_at)
 *  written only when present, in SPEC §4 order. */
function buildAtomContent({
  title,
  scope,
  confidence,
  triggers,
  knowledge,
  actions,
  related,
  audience,
  author,
  pendingReviewBy,
  mergeStrategy,
  createdAt,
}) {
  const today = new Date().toISOString().slice(0, 10);
  const lines = [`# ${title}`, ""];
  lines.push(`- Scope: ${scope}`);
  if (audience && audience.length > 0) {
    lines.push(`- Audience: ${audience.join(", ")}`);
  }
  if (author) {
    lines.push(`- Author: ${author}`);
  }
  lines.push(`- Confidence: ${confidence}`);
  lines.push(`- Trigger: ${triggers.join(", ")}`);
  lines.push(`- Last-used: ${today}`);
  lines.push("- Confirmations: 0");
  lines.push("- ReadHits: 0");
  if (pendingReviewBy) {
    lines.push(`- Pending-review-by: ${pendingReviewBy}`);
  }
  if (mergeStrategy && mergeStrategy !== "ai-assist") {
    lines.push(`- Merge-strategy: ${mergeStrategy}`);
  }
  lines.push(`- Created-at: ${createdAt || today}`);
  if (related && related.length > 0) {
    lines.push(`- Related: ${related.join(", ")}`);
  }
  lines.push("", "## 知識", "");
  for (const k of knowledge) {
    lines.push(k.startsWith("- ") ? k : `- ${k}`);
  }
  lines.push("", "## 行動", "");
  if (actions && actions.length > 0) {
    for (const a of actions) {
      lines.push(a.startsWith("- ") ? a : `- ${a}`);
    }
  } else {
    lines.push("- （依知識內容判斷）");
  }
  lines.push("");
  return lines.join("\n");
}

/** Validate atom content structure. Returns null if valid, error string if invalid. */
function validateAtomContent(content) {
  if (content.includes("---\n") && content.indexOf("---\n") < 5) {
    return "YAML frontmatter (---) is forbidden in atom files";
  }
  if (!content.match(/^# .+/m)) {
    return "Missing # title heading";
  }
  if (!content.includes("## 知識")) {
    return "Missing ## 知識 section";
  }
  if (!content.includes("## 行動")) {
    return "Missing ## 行動 section";
  }
  const confMatch = content.match(/^- Confidence:\s*(.+)$/m);
  if (!confMatch || !["[固]", "[觀]", "[臨]"].includes(confMatch[1].trim())) {
    return "Missing or invalid Confidence metadata";
  }
  return null;
}

// V4: project root marker walk (mirrors hooks/wg_paths.find_project_root)
function findProjectRoot(cwd) {
  if (!cwd) return null;
  let p = path.resolve(cwd);
  for (let i = 0; i < 4; i++) {
    if (fs.existsSync(path.join(p, ".claude", "memory", "MEMORY.md"))) return p;
    if (fs.existsSync(path.join(p, "_AIDocs"))) return p;
    if (fs.existsSync(path.join(p, ".git")) || fs.existsSync(path.join(p, ".svn"))) return p;
    const parent = path.dirname(p);
    if (parent === p) break;
    p = parent;
  }
  return null;
}

// Mirrors wg_roles.get_current_user (env override + os user).
function getCurrentUser() {
  if (process.env.CLAUDE_USER) return process.env.CLAUDE_USER;
  try { return require("os").userInfo().username; } catch { return "unknown"; }
}

// SPEC 7.4 first-version sensitive audience set.
const SENSITIVE_AUDIENCE = new Set(["architecture", "decision"]);
function isSensitiveAudience(audience) {
  if (!Array.isArray(audience)) return false;
  return audience.some(a => SENSITIVE_AUDIENCE.has(String(a).trim().toLowerCase()));
}

/** Resolve the memory directory for a given scope.
 *  V4: shared / role / personal land in project subdirs;
 *  legacy "project" maps to "shared"; "global" unchanged.
 *  Returns { dir, error } — caller checks error.
 */
function resolveMemDir(scope, projectCwd, opts = {}) {
  scope = scope || "shared";

  // ─── S3.2 P3+P4: cwd-scope mismatch 防護 ────────────────────────────────
  // 防止「在專案 root 下用 scope=global 寫個人/專案知識到全域」與
  // 「在 ~/.claude 下用 scope=shared/role/personal 落到不存在的 V4 子層」。
  // force_global escape hatch 給 migration / 測試使用。
  const normCwd = (s) => {
    if (!s) return "";
    try { return path.resolve(s).toLowerCase(); }
    catch { return String(s).toLowerCase(); }
  };
  const claudeDirNorm = normCwd(CLAUDE_DIR);
  const cwdNorm = normCwd(projectCwd);
  const isUnderClaudeDir = cwdNorm && (
    cwdNorm === claudeDirNorm ||
    cwdNorm.startsWith(claudeDirNorm + path.sep.toLowerCase()) ||
    cwdNorm.startsWith(claudeDirNorm + "/")
  );

  if (scope === "global" && !opts.force_global) {
    // P3: 若 cwd 落在某個專案 root（非 ~/.claude）→ 拒絕（避免污染 global）
    if (cwdNorm && !isUnderClaudeDir) {
      const projRoot = findProjectRoot(projectCwd);
      if (projRoot && normCwd(projRoot) !== claudeDirNorm) {
        return { error:
          `scope=global rejected: cwd=${projectCwd} is inside project root=${projRoot}; ` +
          `use scope=shared/role/personal for project knowledge, or pass force_global=true`,
        };
      }
    }
  }

  if ((scope === "shared" || scope === "role" || scope === "personal") && isUnderClaudeDir) {
    // P4: ~/.claude 本身沒有 V4 sub-scope 結構（已被 P1 防護擋住）
    return { error:
      `scope=${scope} rejected: cwd=${projectCwd} is under ~/.claude itself; ` +
      `use scope=global for cross-project knowledge`,
    };
  }
  // ─── /S3.2 P3+P4 ────────────────────────────────────────────────────────

  if (scope === "global") {
    fs.mkdirSync(MEMORY_DIR, { recursive: true });
    return { dir: MEMORY_DIR, base: MEMORY_DIR };
  }

  // Legacy: scope=project returns root memory dir (no V4 subdir).
  // atom_write should pre-map project→shared via callers; here we keep legacy
  // root-dir behavior for atom_promote / readers that still pass "project".
  if (scope === "project" && projectCwd) {
    const projMem = path.join(projectCwd, ".claude", "memory");
    if (fs.existsSync(projMem)) return { dir: projMem, base: projMem };
    const norm = projectCwd.replace(/\\/g, "/").replace(/\/+$/, "");
    const slug = norm.replace(/[^a-zA-Z0-9]/g, "-").replace(/-+/g, "-");
    const projDir = path.join(CLAUDE_DIR, "projects", slug, "memory");
    if (fs.existsSync(projDir)) return { dir: projDir, base: projDir };
    return { dir: projMem, base: projMem };
  }

  if (scope === "role" && !opts.role) {
    return { error: "scope=role requires 'role' parameter (e.g., 'art', 'programmer')" };
  }
  if (scope !== "shared" && scope !== "role" && scope !== "personal") {
    return { error: `Unknown scope: ${scope}` };
  }

  const root = findProjectRoot(projectCwd || "");
  if (!root) {
    return { error: `No project root found for scope=${scope} (need .git/.svn/_AIDocs/.claude/memory/MEMORY.md marker under ${projectCwd || "(no cwd)"})` };
  }
  // ~/.claude itself is global memory; reject V4 sub-scopes there
  try {
    if (path.resolve(root) === path.resolve(CLAUDE_DIR)) {
      return { error: `cwd is ~/.claude itself; use scope=global for cross-project knowledge` };
    }
  } catch {}

  const base = path.join(root, ".claude", "memory");
  let dir;
  if (scope === "shared") dir = path.join(base, "shared");
  else if (scope === "role") dir = path.join(base, "roles", opts.role);
  else dir = path.join(base, "personal", opts.user);

  fs.mkdirSync(dir, { recursive: true });
  return { dir, base };
}

/** Find atom index path for a given scope (V3.2: prefer _ATOM_INDEX.md) */
function resolveMemoryIndex(memDir) {
  const atomIdx = path.join(memDir, "_ATOM_INDEX.md");
  if (fs.existsSync(atomIdx)) return atomIdx;
  return path.join(memDir, "MEMORY.md");  // fallback
}

/** V4 Phase 5: Run conflict-detector --mode=write-check.
 *  Returns Promise<{verdict, matches, detector_model, skipped, skip_reason, scope}>.
 *  Fail-open: on script error resolves to verdict=ok+skipped=true (do not block writes
 *  when detector infra is down). Longer timeout than write-gate (LLM is slower). */
function execConflictDetector(content, scope, projectCwd) {
  return new Promise((resolve) => {
    const scriptPath = path.join(TOOLS_DIR, "memory-conflict-detector.py");
    if (!fs.existsSync(scriptPath)) {
      return resolve({ verdict: "ok", matches: [], detector_model: "n/a",
                       skipped: true, skip_reason: "detector script missing", scope });
    }
    const args = ["--mode=write-check",
                  "--scope", scope,
                  "--content", content];
    if (projectCwd) {
      args.push("--project-cwd", projectCwd);
    }
    const cp = require("child_process").spawn("python", [scriptPath, ...args], {
      windowsHide: true,
    });
    let out = "", err = "";
    const timer = setTimeout(() => {
      try { cp.kill(); } catch {}
    }, 60000);  // 60s — vector + 3 LLM calls
    cp.stdout.on("data", d => { out += d.toString(); });
    cp.stderr.on("data", d => { err += d.toString(); });
    cp.on("close", () => {
      clearTimeout(timer);
      try {
        const parsed = JSON.parse(out.trim().split("\n").pop());
        resolve(parsed);
      } catch (e) {
        try { process.stderr.write(`[conflict-detector] parse error: ${e.message} stderr=${err.slice(0, 200)}\n`); } catch {}
        resolve({ verdict: "ok", matches: [], detector_model: "n/a",
                  skipped: true, skip_reason: "detector parse/exec error", scope });
      }
    });
    cp.on("error", (e) => {
      clearTimeout(timer);
      try { process.stderr.write(`[conflict-detector] spawn error: ${e.message}\n`); } catch {}
      resolve({ verdict: "ok", matches: [], detector_model: "n/a",
                skipped: true, skip_reason: "detector spawn error", scope });
    });
  });
}

/** V4 Phase 5: TSV append to {baseDir}/_merge_history.log. SPEC §10.
 *  baseDir is {proj}/.claude/memory/ (so log sits alongside shared/ roles/ personal/). */
function appendMergeHistory(baseDir, action, atom, scope, by, detail) {
  try {
    const safe = s => String(s || "-").replace(/[\t\n\r]/g, " ").trim() || "-";
    const line = [new Date().toISOString(), action, atom, scope, by, detail]
      .map(safe).join("\t") + "\n";
    fs.appendFileSync(path.join(baseDir, "_merge_history.log"), line, "utf-8");
  } catch (e) {
    try { process.stderr.write(`[merge_history] ${e.message}\n`); } catch {}
  }
}

/** V4 Phase 5: render CONTRADICT report (non-atom) for _pending_review/{slug}.conflict.md. */
function buildConflictReport({ slug, incomingTitle, incomingContent, matches, detectorModel, author }) {
  const lines = [
    `# Write-time conflict: ${incomingTitle || slug}`,
    "",
    `- Detected-at: ${new Date().toISOString()}`,
    `- Incoming-author: ${author || "-"}`,
    `- Detector: ${detectorModel || "n/a"}`,
    `- Pending-review-by: management`,
    "",
    "## Incoming knowledge",
    "",
    "```",
    (incomingContent || "").slice(0, 4000),
    "```",
    "",
    "## Conflicting existing atoms",
    "",
  ];
  for (const m of matches || []) {
    lines.push(`- **${m.atom_name}** (layer=\`${m.layer}\`, similarity=${(m.similarity || 0).toFixed(3)}, class=${m.classification})`);
    if (m.fact_preview) lines.push(`  preview: ${m.fact_preview.replace(/\n/g, " ")}`);
  }
  lines.push(
    "",
    "## Resolution",
    "",
    "管理職 `/conflict-review`：",
    "1. 編輯既有 atom 或 incoming — 以消解事實衝突",
    "2. 若 incoming 有獨立價值 → approve（搬草稿到 `shared/`）",
    "3. 若 incoming 錯誤 → reject（僅刪本報告，既有 atom 不動）",
    "",
  );
  return lines.join("\n");
}

/** Run write-gate Python script for dedup check. Returns Promise<{action, reason}> */
function execWriteGate(content, classification) {
  return new Promise((resolve) => {
    const scriptPath = path.join(TOOLS_DIR, "memory-write-gate.py");
    if (!fs.existsSync(scriptPath)) {
      return resolve({ action: "add", reason: "write-gate script not found, allowing" });
    }
    // Escape content for CLI: use stdin via echo pipe
    const escaped = JSON.stringify({ content, classification });
    const cmd = `echo ${escaped.replace(/"/g, '\\"')} | python "${scriptPath.replace(/\\/g, "/")}"`;
    exec(cmd, { timeout: 15000 }, (err, stdout) => {
      if (err || !stdout) {
        return resolve({ action: "add", reason: "write-gate unavailable, allowing" });
      }
      try {
        const result = JSON.parse(stdout.trim());
        resolve(result);
      } catch {
        resolve({ action: "add", reason: "write-gate parse error, allowing" });
      }
    });
  });
}

/** Append or update an atom entry in MEMORY.md index table */
async function appendToIndex(memDir, atomName, relPath, triggers) {
  const indexPath = resolveMemoryIndex(memDir);
  const triggerStr = triggers.join(", ");
  const newRow = `| ${atomName} | ${relPath} | ${triggerStr} |`;

  let content = "";
  try {
    content = fs.readFileSync(indexPath, "utf-8");
  } catch {
    // Create new MEMORY.md with table header
    content = [
      "# Atom Index",
      "",
      "> Session 啟動時先讀此索引。比對 Trigger → Read 對應 atom。",
      "| Atom | Path | Trigger |",
      "|------|------|---------|",
      "",
    ].join("\n");
  }

  // Check if atom already exists in the table
  const escapedName = atomName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const existingRe = new RegExp(`^\\|\\s*${escapedName}\\s*\\|.*$`, "m");
  if (existingRe.test(content)) {
    // Update existing row
    content = content.replace(existingRe, newRow);
  } else {
    // Insert before the first empty line after the table header separator
    const sepIdx = content.indexOf("|------|");
    if (sepIdx >= 0) {
      const afterSep = content.indexOf("\n", sepIdx);
      if (afterSep >= 0) {
        // Find the end of the table (first line that doesn't start with |)
        const lines = content.split("\n");
        let insertIdx = -1;
        let foundSep = false;
        for (let i = 0; i < lines.length; i++) {
          if (lines[i].startsWith("|------")) { foundSep = true; continue; }
          if (foundSep && !lines[i].startsWith("|")) {
            insertIdx = i;
            break;
          }
        }
        if (insertIdx >= 0) {
          lines.splice(insertIdx, 0, newRow);
          content = lines.join("\n");
        } else {
          // Table runs to end of file
          content = content.trimEnd() + "\n" + newRow + "\n";
        }
      }
    } else {
      // No table found, append
      content += "\n" + newRow + "\n";
    }
  }

  // S3.2: 走 lib.atom_io.write_index_full funnel（atomic write + audit log）
  // appendToIndex 改 async + caller await，避免 syncMemoryIndex 在 index 寫入
  // 完成前讀到舊版 _ATOM_INDEX 而漏新行。
  const r = await funnelWriteIndexFull(indexPath, content, "mcp");
  if (!r.ok) crashLog("appendToIndex funnel", r.error);
}

/** Trigger vector service re-index (fire and forget) */
function triggerVectorReindex() {
  try {
    const url = "http://127.0.0.1:3849/reindex";
    const req = http.request(url, { method: "POST", timeout: 3000 }, () => {});
    req.on("error", () => {}); // ignore
    req.end();
  } catch {}
}

/** Regenerate MEMORY.md from _ATOM_INDEX (fire and forget).
 *  Only touches global memory — project layers don't have sync-memory-index hookup yet. */
function syncMemoryIndex() {
  try {
    const script = path.join(TOOLS_DIR, "sync-memory-index.py");
    if (!fs.existsSync(script)) return;
    const cp = require("child_process").spawn("python", [script, "--write"], {
      windowsHide: true, detached: true, stdio: "ignore",
    });
    cp.on("error", () => {});
    cp.unref();
  } catch {}
}

/** Parse atom metadata from file content. Returns {confidence, confirmations, ...} */
function parseAtomMeta(content) {
  const meta = {};
  const re = /^- ([\w-]+):\s*(.+)$/gm;
  let m;
  while ((m = re.exec(content)) !== null) {
    const key = m[1].toLowerCase();
    const val = m[2].trim();
    switch (key) {
      case "confidence": meta.confidence = val; break;
      case "confirmations": meta.confirmations = parseInt(val, 10) || 0; break;
      case "readhits": meta.readhits = parseInt(val, 10) || 0; break;
      case "scope": meta.scope = val; break;
      case "trigger": meta.triggers = val; break;
      case "last-used": meta.lastUsed = val; break;
      case "related": meta.related = val; break;
    }
  }
  const titleMatch = content.match(/^# (.+)$/m);
  if (titleMatch) meta.title = titleMatch[1];
  return meta;
}

// ─── S3.2: Atom Funnel Bridge (spawn lib/atom_io_cli) ─────────────────────

/** Spawn `python -m lib.atom_io_cli` to perform atom write through the
 *  centralized funnel (audit log + audit-id + uniform error contract).
 *  Returns Promise<{ok, error, audit_id, path}>.
 *  All atomic writes from MCP go through this so PreToolUse strict gate
 *  (S3.3) can verify every write has an audit log entry.
 */
function spawnAtomCli(action, payload) {
  return new Promise((resolve) => {
    let cp;
    try {
      cp = require("child_process").spawn(
        "python", ["-m", "lib.atom_io_cli"],
        {
          cwd: CLAUDE_DIR,
          windowsHide: true,
          env: { ...process.env, PYTHONIOENCODING: "utf-8" },
        }
      );
    } catch (e) {
      return resolve({ ok: false, error: `spawn failed: ${e.message}` });
    }
    let out = "", err = "";
    cp.stdout.on("data", (d) => { out += d.toString("utf-8"); });
    cp.stderr.on("data", (d) => { err += d.toString("utf-8"); });
    cp.on("close", () => {
      try {
        resolve(JSON.parse(out));
      } catch (e) {
        resolve({ ok: false, error: `cli parse fail: ${e.message} stderr=${err.slice(0, 200)}` });
      }
    });
    cp.on("error", (e) => resolve({ ok: false, error: `spawn error: ${e.message}` }));
    try {
      cp.stdin.write(JSON.stringify({ action, ...payload }));
      cp.stdin.end();
    } catch (e) {
      resolve({ ok: false, error: `stdin write failed: ${e.message}` });
    }
  });
}

/** Atomic write through funnel: routes raw content via lib.atom_io.write_raw. */
function funnelWriteRaw(filePath, content, source, op) {
  return spawnAtomCli("write_raw", {
    file_path: filePath, content, source, op: op || "raw",
  });
}

/** Index full overwrite through funnel. */
function funnelWriteIndexFull(indexPath, content, source) {
  return spawnAtomCli("write_index_full", {
    index_path: indexPath, content, source,
  });
}


// ─── Atom Write Handler ────────────────────────────────────────────────────

async function toolAtomWrite(id, args) {
  let {
    title, scope, confidence, triggers, knowledge, actions, related, mode,
    project_cwd, skip_gate, skip_conflict_check,
    role, user, audience, pending_review_by, merge_strategy,
  } = args;

  // Validate core required fields (scope now optional, defaults to shared)
  if (!title || !confidence || !triggers || !knowledge || !mode) {
    return sendToolResult(id, "Missing required parameters (title, confidence, triggers, knowledge, mode)", true);
  }

  // V4: default scope, transparent legacy mapping
  if (!scope) scope = "shared";
  if (scope === "project") {
    try { process.stderr.write(`[atom_write] scope=project is deprecated; mapped to shared\n`); } catch {}
    scope = "shared";
  }

  // V4 personal default user
  if (scope === "personal" && !user) user = getCurrentUser();

  // Resolve target memory dir (write target + base for index)
  const resolved = resolveMemDir(scope, project_cwd, { role, user });
  if (resolved.error) {
    return sendToolResult(id, `atom_write: ${resolved.error}`, true);
  }
  let memDir = resolved.dir;
  const baseDir = resolved.base;

  // SPEC 7.4: sensitive audience on shared → auto-pending
  let pendingReviewBy = pending_review_by || null;
  if (scope === "shared" && isSensitiveAudience(audience)) {
    memDir = path.join(baseDir, "shared", "_pending_review");
    fs.mkdirSync(memDir, { recursive: true });
    if (!pendingReviewBy) pendingReviewBy = "management";
  }

  // V4 metadata: scope label (composite for role/personal)
  let scopeLabel = scope;
  if (scope === "role") scopeLabel = `role:${role}`;
  else if (scope === "personal") scopeLabel = `personal:${user}`;

  const slug = slugify(title);
  // V4 Phase 5: filePath/relPath may be recomputed after conflict-detector reroute
  let filePath = path.join(memDir, slug + ".md");
  let relFromBase = path.relative(baseDir, filePath).replace(/\\/g, "/");
  let relPath = "memory/" + relFromBase;

  const author = getCurrentUser();
  const today = new Date().toISOString().slice(0, 10);

  // ── Mode: create ──
  if (mode === "create") {
    if (fs.existsSync(filePath)) {
      return sendToolResult(id, `Atom already exists: ${slug}.md — use mode=append or mode=replace`, true);
    }

    // 原子記憶語意契約：新 atom 必須 [臨]
    if (confidence !== "[臨]") {
      return sendToolResult(id,
        `New atom must start at [臨] (confidence=${confidence} rejected).\n` +
        `Reason: [觀]/[固] reflect cross-session stability; first-write cannot assert that.\n` +
        `Knowledge items inside should also use [臨] prefix.\n` +
        `Promotion: Confirmations (cross-session) ≥4→[觀] ≥10→[固]; ReadHits (injection) ≥20/≥50 auxiliary.`,
        true);
    }

    if (!skip_gate) {
      const gateResult = await execWriteGate(knowledge.join("\n"), confidence);
      if (gateResult.action === "skip") {
        return sendToolResult(id, `Write-gate rejected: ${gateResult.reason}`, true);
      }
      if (gateResult.action === "update" && gateResult.dedup_match) {
        return sendToolResult(id,
          `Write-gate: similar to existing atom "${gateResult.dedup_match.atom_name}" ` +
          `(score=${gateResult.dedup_match.score}). Use mode=append on that atom instead.`, true);
      }
    }

    // ─── V4 Phase 5: write-time conflict detection (SPEC §7.1) ───
    // Only shared scope. skip_conflict_check honored for migrations/tests.
    if (scope === "shared" && !skip_conflict_check) {
      const cr = await execConflictDetector(knowledge.join("\n"), "shared", project_cwd);
      if (cr.verdict === "contradict") {
        const pendingDir = path.join(baseDir, "shared", "_pending_review");
        fs.mkdirSync(pendingDir, { recursive: true });
        const reportPath = path.join(pendingDir, slug + ".conflict.md");
        const report = buildConflictReport({
          slug, incomingTitle: title, incomingContent: knowledge.join("\n"),
          matches: cr.matches, detectorModel: cr.detector_model, author,
        });
        fs.writeFileSync(reportPath + ".tmp", report, "utf-8");
        fs.renameSync(reportPath + ".tmp", reportPath);
        appendMergeHistory(baseDir, "pending-create", slug, scopeLabel, author,
          `contradict vs ${(cr.matches[0] || {}).atom_name || "?"} sim=${((cr.matches[0] || {}).similarity || 0).toFixed(3)}`);
        return sendToolResult(id,
          `BLOCKED by conflict detector — CONTRADICT vs "${(cr.matches[0] || {}).atom_name || "?"}".\n` +
          `Report written: ${reportPath}\n` +
          `Atom NOT written to shared/. Awaiting management review (/conflict-review).`,
          false  // not isError — pending is normal flow
        );
      }
      if (cr.verdict === "extend_overlap") {
        // Reroute to _pending_review/ as atom draft (still full atom format)
        memDir = path.join(baseDir, "shared", "_pending_review");
        fs.mkdirSync(memDir, { recursive: true });
        if (!pendingReviewBy) pendingReviewBy = "management";
        filePath = path.join(memDir, slug + ".md");
        relFromBase = path.relative(baseDir, filePath).replace(/\\/g, "/");
        relPath = "memory/" + relFromBase;
        appendMergeHistory(baseDir, "pending-create", slug, scopeLabel, author,
          `extend_overlap vs ${(cr.matches[0] || {}).atom_name || "?"} sim=${((cr.matches[0] || {}).similarity || 0).toFixed(3)}`);
      }
    }

    const content = buildAtomContent({
      title, scope: scopeLabel, confidence, triggers, knowledge, actions, related,
      audience, author, pendingReviewBy, mergeStrategy: merge_strategy, createdAt: today,
    });
    const err = validateAtomContent(content);
    if (err) {
      return sendToolResult(id, `Validation failed: ${err}`, true);
    }

    fs.mkdirSync(memDir, { recursive: true });
    // S3.2: 走 lib.atom_io.write_raw funnel（atomic write + audit log）
    const wr = await funnelWriteRaw(filePath, content, "mcp", "atom_create");
    if (!wr.ok) {
      return sendToolResult(id, `funnel write_raw failed: ${wr.error}`, true);
    }

    await appendToIndex(baseDir, slug, relPath, triggers);
    triggerVectorReindex();
    if (scopeLabel === "global") syncMemoryIndex();

    return sendToolResult(id,
      `Created atom: ${slug}.md (${confidence}, scope=${scopeLabel})\n` +
      `Path: ${filePath}\n` +
      `Author: ${author}\n` +
      (pendingReviewBy ? `Pending-review-by: ${pendingReviewBy} (sensitive audience auto-routed)\n` : "") +
      `Triggers: ${triggers.join(", ")}\n` +
      `MEMORY.md index updated.`
    );
  }

  // ── Mode: append ──
  if (mode === "append") {
    if (!fs.existsSync(filePath)) {
      return sendToolResult(id, `Atom not found: ${slug}.md — use mode=create first`, true);
    }

    let existing = fs.readFileSync(filePath, "utf-8");
    if (existing.charCodeAt(0) === 0xFEFF) existing = existing.slice(1);

    const actionIdx = existing.indexOf("## 行動");
    if (actionIdx < 0) {
      return sendToolResult(id, `Atom ${slug}.md has no ## 行動 section — cannot append`, true);
    }

    const newLines = knowledge.map(k => k.startsWith("- ") ? k : `- ${k}`).join("\n");
    const before = existing.slice(0, actionIdx).trimEnd();
    const after = existing.slice(actionIdx);
    const updated = before + "\n" + newLines + "\n\n" + after;

    // Append only updates Last-used; Author/Created-at preserved (initial writer's identity)
    const finalContent = updated.replace(
      /^- Last-used:\s*.+$/m,
      `- Last-used: ${today}`
    );

    const err = validateAtomContent(finalContent);
    if (err) {
      return sendToolResult(id, `Validation failed after append: ${err}`, true);
    }

    // S3.2: 走 lib.atom_io.write_raw funnel
    const wr = await funnelWriteRaw(filePath, finalContent, "mcp", "atom_append");
    if (!wr.ok) {
      return sendToolResult(id, `funnel write_raw failed: ${wr.error}`, true);
    }

    triggerVectorReindex();

    return sendToolResult(id,
      `Appended ${knowledge.length} knowledge lines to ${slug}.md\n` +
      `Last-used updated.`
    );
  }

  // ── Mode: replace ──
  if (mode === "replace") {
    // Preserve Confirmations + ReadHits + initial Author/Created-at if file exists
    let confirmations = 0;
    let readhits = 0;
    let prevAuthor = author;
    let prevCreatedAt = today;
    if (fs.existsSync(filePath)) {
      try {
        const old = fs.readFileSync(filePath, "utf-8");
        const meta = parseAtomMeta(old);
        confirmations = meta.confirmations || 0;
        readhits = meta.readhits || 0;
        const am = old.match(/^- Author:\s*(.+)$/m);
        if (am) prevAuthor = am[1].trim();
        const cm = old.match(/^- Created-at:\s*(.+)$/m);
        if (cm) prevCreatedAt = cm[1].trim();
      } catch {}
    }

    const content = buildAtomContent({
      title, scope: scopeLabel, confidence, triggers, knowledge, actions, related,
      audience, author: prevAuthor, pendingReviewBy, mergeStrategy: merge_strategy, createdAt: prevCreatedAt,
    });
    const err = validateAtomContent(content);
    if (err) {
      return sendToolResult(id, `Validation failed: ${err}`, true);
    }

    const finalContent = content
      .replace(/^- Confirmations:\s*\d+$/m, `- Confirmations: ${confirmations}`)
      .replace(/^- ReadHits:\s*\d+$/m, `- ReadHits: ${readhits}`);

    fs.mkdirSync(memDir, { recursive: true });
    // S3.2: 走 lib.atom_io.write_raw funnel
    const wr = await funnelWriteRaw(filePath, finalContent, "mcp", "atom_replace");
    if (!wr.ok) {
      return sendToolResult(id, `funnel write_raw failed: ${wr.error}`, true);
    }

    await appendToIndex(baseDir, slug, relPath, triggers);
    triggerVectorReindex();
    if (scopeLabel === "global") syncMemoryIndex();

    return sendToolResult(id,
      `Replaced atom: ${slug}.md (${confidence}, preserved conf=${confirmations} rh=${readhits}, author=${prevAuthor})\n` +
      `MEMORY.md index updated.`
    );
  }

  return sendToolResult(id, `Unknown mode: ${mode}. Use create/append/replace.`, true);
}

// ─── Atom Promote Handler ──────────────────────────────────────────────────

async function toolAtomPromote(id, args) {
  const { atom_name, scope, project_cwd, execute, role, user, merge_to_preferences } = args;

  const resolved = resolveMemDir(scope, project_cwd, { role, user });
  if (resolved.error) {
    return sendToolResult(id, `atom_promote: ${resolved.error}`, true);
  }
  const memDir = resolved.dir;
  const filePath = path.join(memDir, atom_name + ".md");

  if (!fs.existsSync(filePath)) {
    return sendToolResult(id, `Atom not found: ${atom_name}.md in ${scope} scope`, true);
  }

  let content = fs.readFileSync(filePath, "utf-8");
  if (content.charCodeAt(0) === 0xFEFF) content = content.slice(1);

  const meta = parseAtomMeta(content);
  if (!meta.confidence) {
    return sendToolResult(id, `Cannot parse confidence from ${atom_name}.md`, true);
  }

  // Determine promotion path (v3 dual-field)
  // SYNC: memory/decisions.md — promotion thresholds
  const THRESHOLDS = {
    "[臨]": { next: "[觀]", confirmations: 4, readhits: 20 },
    "[觀]": { next: "[固]", confirmations: 10, readhits: 50 },
    "[固]": null, // already max
  };

  const path_info = THRESHOLDS[meta.confidence];
  if (!path_info) {
    return sendToolResult(id,
      `${atom_name} is already at ${meta.confidence} — no promotion available.`
    );
  }

  const { next, confirmations: reqConf, readhits: reqRH } = path_info;
  const confirmations = meta.confirmations || 0;
  const readhits = meta.readhits || 0;

  // Primary gate: Confirmations (cross-session behavior hits)
  let eligible = confirmations >= reqConf;
  let method = "confirmations";

  // Auxiliary gate: ReadHits (injection hits)
  if (!eligible && readhits >= reqRH) {
    eligible = true;
    method = "readhits_auxiliary";
  }

  // 7-day exemption: migration fallback (ReadHits/5 ≥ reqConf)
  if (!eligible) {
    try {
      const migrationPath = path.join(MEMORY_DIR, "_meta", "migration.json");
      if (fs.existsSync(migrationPath)) {
        const migData = JSON.parse(fs.readFileSync(migrationPath, "utf-8"));
        const daysSinceMigration = (Date.now() - (migData.timestamp || 0) * 1000) / 86400000;
        if (daysSinceMigration <= 7 && Math.floor(readhits / 5) >= reqConf) {
          eligible = true;
          method = "readhits_7day_fallback";
        }
      }
    } catch {}
  }

  if (!eligible) {
    return sendToolResult(id,
      `## Dry-run: ${atom_name}\n` +
      `Current: ${meta.confidence}\n` +
      `  Confirmations: ${confirmations}/${reqConf}\n` +
      `  ReadHits: ${readhits}/${reqRH} (auxiliary)\n` +
      `Required: Confirmations ≥ ${reqConf} OR ReadHits ≥ ${reqRH}\n` +
      `Deficit: ${Math.max(0, reqConf - confirmations)} conf / ${Math.max(0, reqRH - readhits)} rh`
    );
  }

  // Eligible for promotion
  if (!execute) {
    return sendToolResult(id,
      `## Dry-run: ${atom_name}\n` +
      `Current: ${meta.confidence}\n` +
      `  Confirmations: ${confirmations}/${reqConf}\n` +
      `  ReadHits: ${readhits}/${reqRH}\n` +
      `Eligible via: ${method} → ${next}\n` +
      `Set execute=true to apply.`
    );
  }

  // Execute promotion
  const updated = content
    .replace(/^- Confidence:\s*.+$/m, `- Confidence: ${next}`)
    .replace(/^- Last-used:\s*.+$/m, `- Last-used: ${new Date().toISOString().slice(0, 10)}`);

  // Also update individual knowledge lines: [臨] → [觀] etc.
  const finalContent = updated.replace(
    new RegExp(`- \\${meta.confidence.replace(/[[\]]/g, "\\$&")}`, "g"),
    `- ${next}`
  );

  // S3.2: 走 lib.atom_io.write_raw funnel
  const wrPromote = await funnelWriteRaw(filePath, finalContent, "mcp", "atom_promote");
  if (!wrPromote.ok) {
    return sendToolResult(id, `funnel write_raw failed: ${wrPromote.error}`, true);
  }

  triggerVectorReindex();

  // Promotion audit log
  try {
    const auditPath = path.join(MEMORY_DIR, "_promotion_audit.jsonl");
    const entry = {
      ts: new Date().toISOString().slice(0, 19),
      action: "manual_promote",
      atom: atom_name,
      from: meta.confidence,
      to: next,
      confirmations,
      readhits,
      method,
      scope,
    };
    fs.appendFileSync(auditPath, JSON.stringify(entry) + "\n");
  } catch {}

  // ─── 方案 c: [觀]→[固] 合併流程 ────────────────────────────────
  // 方案 a（自動提示）：只要晉升為 [固]，一律在回覆裡附上「是否合進 preferences.md」提示，
  // 讓 Claude 引導使用者裁決。
  // 方案 b（自動執行）：當 merge_to_preferences=true，立即把 knowledge 追加到 preferences.md、
  // 歸檔本 atom 到 _archived/，再請 Claude 後續手動移除 _ATOM_INDEX.md 的該行。
  const promotedToStable = next === "[固]";
  let mergeReport = "";
  if (promotedToStable && merge_to_preferences) {
    if (scope !== "global") {
      mergeReport = "\n\n[merge_to_preferences] 已略過：僅支援 global scope。";
    } else {
      try {
        const knowledgeLines = extractKnowledgeLines(finalContent);
        const prefPath = path.join(MEMORY_DIR, "preferences.md");
        const archiveDir = path.join(MEMORY_DIR, "_archived");
        if (!fs.existsSync(archiveDir)) fs.mkdirSync(archiveDir, { recursive: true });
        const today = new Date().toISOString().slice(0, 10);
        const archivePath = path.join(archiveDir, `${today}-${atom_name}.md`);

        let prefText = fs.existsSync(prefPath) ? fs.readFileSync(prefPath, "utf-8") : "";
        if (prefText.charCodeAt(0) === 0xFEFF) prefText = prefText.slice(1);
        const mergeSection =
          `\n\n### 歸檔合併 · ${atom_name} (${today})\n` +
          `> 自 [觀]→[固] 晉升時合併自 \`${path.basename(filePath)}\`\n\n` +
          knowledgeLines.map(l => `- ${l}`).join("\n") + "\n";
        // S3.2: 走 lib.atom_io.write_raw funnel
        const wrPref = await funnelWriteRaw(
          prefPath, prefText.trimEnd() + mergeSection, "mcp", "promote_merge_pref"
        );
        if (!wrPref.ok) throw new Error(`funnel write_raw failed: ${wrPref.error}`);

        fs.renameSync(filePath, archivePath);

        mergeReport =
          `\n\n[merge_to_preferences] 已執行：\n` +
          `  - Appended ${knowledgeLines.length} 行到 preferences.md\n` +
          `  - Archived → ${path.relative(MEMORY_DIR, archivePath)}\n` +
          `  - ⚠ 請手動移除 _ATOM_INDEX.md 中 ${atom_name} 的索引列。`;
      } catch (e) {
        mergeReport = `\n\n[merge_to_preferences] 失敗：${e.message}`;
      }
    }
  }

  const mergeHint = (promotedToStable && !merge_to_preferences)
    ? `\n\n💡 建議：${atom_name} 已達 [固]，若此知識本質為「個人偏好/操作規範」，` +
      `可用 merge_to_preferences=true 重新呼叫，將 knowledge 併入 preferences.md 並歸檔此 atom。`
    : "";

  return sendToolResult(id,
    `Promoted ${atom_name}: ${meta.confidence} → ${next}\n` +
    `Confirmations: ${confirmations} | ReadHits: ${readhits} (via ${method})\n` +
    `Knowledge lines updated to ${next}.` +
    mergeReport +
    mergeHint
  );
}

// ─── Atom Move Handler ─────────────────────────────────────────────────────

function toolAtomMove(id, args) {
  const { subcommand, atom, dry_run } = args;
  if (!subcommand || !atom) {
    return Promise.resolve(sendToolResult(id, "atom_move: subcommand and atom are required", true));
  }
  const scriptPath = path.join(TOOLS_DIR, "atom-move.py");
  if (!fs.existsSync(scriptPath)) {
    return Promise.resolve(sendToolResult(id, `atom_move: script not found at ${scriptPath}`, true));
  }
  const argv = [scriptPath, subcommand, atom];
  if (subcommand === "move") {
    if (!args.from || !args.to) {
      return Promise.resolve(sendToolResult(id, "atom_move move: --from and --to required", true));
    }
    argv.push("--from", args.from, "--to", args.to);
  } else if (subcommand === "reconcile") {
    if (!args.at) {
      return Promise.resolve(sendToolResult(id, "atom_move reconcile: --at required", true));
    }
    argv.push("--at", args.at);
  } else {
    return Promise.resolve(sendToolResult(id, `atom_move: unknown subcommand '${subcommand}'`, true));
  }
  if (dry_run) argv.push("--dry-run");

  return new Promise((resolve) => {
    const cp = require("child_process").spawn("python", argv, { windowsHide: true });
    let out = "", err = "";
    const timer = setTimeout(() => { try { cp.kill(); } catch {} }, 30000);
    cp.stdout.on("data", d => { out += d.toString(); });
    cp.stderr.on("data", d => { err += d.toString(); });
    cp.on("close", (code) => {
      clearTimeout(timer);
      const combined = (out || "") + (err ? ("\n[stderr]\n" + err) : "");
      if (code !== 0) {
        sendToolResult(id, `atom_move exited ${code}\n${combined}`, true);
      } else {
        sendToolResult(id, combined.trim() || "(no output)");
      }
      resolve();
    });
    cp.on("error", (e) => {
      clearTimeout(timer);
      sendToolResult(id, `atom_move spawn error: ${e.message}`, true);
      resolve();
    });
  });
}

function extractKnowledgeLines(content) {
  // 從 atom 檔抓「## 知識」到下個 `## ` 或 EOF 之間，保留以 `- ` 開頭的行（去掉 `- ` 前綴）
  const m = content.match(/^##\s*知識\s*$([\s\S]*?)(?=^##\s|\Z)/m);
  if (!m) return [];
  return m[1]
    .split("\n")
    .map(l => l.trim())
    .filter(l => l.startsWith("- "))
    .map(l => l.slice(2).trim())
    .filter(Boolean);
}

function sendToolResult(id, text, isError = false) {
  sendResponse(id, {
    content: [{ type: "text", text }],
    ...(isError && { isError: true }),
  });
}

// ─── v2.1 API Handlers ──────────────────────────────────────────────────────

function jsonRes(res, code, data) {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

// Build a safe python command (Windows path backslashes must be forward-slashed for exec)
function pyCmd(scriptPath, args) {
  return 'python "' + scriptPath.replace(/\\/g, "/") + '" ' + args;
}

// --- Episodic Atom Parser & API ---

function parseEpisodicAtom(filePath) {
  const content = fs.readFileSync(filePath, "utf-8");
  const atom = {
    filename: path.basename(filePath),
    title: "", confidence: "", type: "", triggers: [],
    last_used: "", created: "", ttl: "", expires_at: "",
    days_until_expiry: null, knowledge_lines: [], full_content: content,
  };
  const titleMatch = content.match(/^#\s+(.+)$/m);
  if (titleMatch) atom.title = titleMatch[1];
  const metaRe = /^-\s+([\w-]+):\s*(.+)$/gm;
  let m;
  while ((m = metaRe.exec(content)) !== null) {
    const key = m[1].toLowerCase(), val = m[2].trim();
    switch (key) {
      case "confidence": atom.confidence = val; break;
      case "type": atom.type = val; break;
      case "trigger": atom.triggers = val.split(",").map(t => t.trim()); break;
      case "last-used": atom.last_used = val; break;
      case "created": atom.created = val; break;
      case "ttl": atom.ttl = val; break;
      case "expires-at":
        atom.expires_at = val;
        const expDate = new Date(val);
        atom.days_until_expiry = Math.ceil((expDate - new Date()) / 86400000);
        break;
    }
  }
  let inKnowledge = false;
  for (const line of content.split("\n")) {
    if (/^##\s+知識/.test(line)) { inKnowledge = true; continue; }
    if (/^##\s+/.test(line) && inKnowledge) break;
    if (inKnowledge && line.trim().startsWith("-")) {
      atom.knowledge_lines.push(line.trim().replace(/^-\s*/, ""));
    }
  }
  return atom;
}

function apiEpisodic(req, res) {
  try {
    const dirsToScan = [MEMORY_DIR];
    // V2.21: scan registry project dirs (new path)
    for (const { memDir } of getRegistryMemDirs()) {
      if (!dirsToScan.includes(memDir)) dirsToScan.push(memDir);
    }
    // Also scan old project-level episodic dirs (fallback for unregistered projects)
    const projectsDir = path.join(CLAUDE_DIR, "projects");
    if (fs.existsSync(projectsDir)) {
      for (const proj of fs.readdirSync(projectsDir)) {
        const projMemDir = path.join(projectsDir, proj, "memory");
        if (fs.existsSync(projMemDir) && !dirsToScan.includes(projMemDir)) dirsToScan.push(projMemDir);
      }
    }
    const atoms = [];
    for (const dir of dirsToScan) {
      const epicDir = path.join(dir, "episodic");
      if (!fs.existsSync(epicDir)) continue;
      try {
        const files = fs.readdirSync(epicDir)
          .filter(f => f.startsWith("episodic-") && f.endsWith(".md"));
        for (const f of files) {
          try { atoms.push(parseEpisodicAtom(path.join(epicDir, f))); }
          catch {}
        }
      } catch {}
    }
    atoms.sort((a, b) => (b.created || "").localeCompare(a.created || ""));
    jsonRes(res, 200, atoms);
  } catch { jsonRes(res, 200, []); }
}

// --- Memory Health API (cached) ---

let healthCache = { data: null, timestamp: 0 };
const HEALTH_CACHE_TTL_MS = 60000;

function apiHealth(req, res, forceRefresh) {
  const now = Date.now();
  if (!forceRefresh && healthCache.data && (now - healthCache.timestamp) < HEALTH_CACHE_TTL_MS) {
    return jsonRes(res, 200, healthCache.data);
  }
  const auditScript = path.join(TOOLS_DIR, "memory-audit.py");
  const healthScript = path.join(TOOLS_DIR, "atom-health-check.py");
  // Run both tools in parallel
  let auditDone = false, healthDone = false;
  let auditData = null, healthData = null;
  let responded = false;
  const tryMerge = () => {
    if (!auditDone || !healthDone || responded) return;
    responded = true;
    const merged = auditData || {};
    if (healthData) {
      merged.broken_refs = healthData.broken_refs || [];
      merged.missing_reverse_refs = healthData.missing_reverse_refs || [];
      merged.stale_atoms = healthData.stale_atoms || [];
    }
    healthCache = { data: merged, timestamp: Date.now() };
    jsonRes(res, 200, merged);
  };
  exec(pyCmd(auditScript, "--json"), { timeout: 30000 }, (err, stdout) => {
    if (stdout) { try { auditData = JSON.parse(stdout); } catch {} }
    auditDone = true;
    tryMerge();
  });
  exec(pyCmd(healthScript, "--report --json"), { timeout: 30000 }, (err, stdout) => {
    if (stdout) { try { healthData = JSON.parse(stdout); } catch {} }
    healthDone = true;
    tryMerge();
  });
}

// --- E2E Test Runner (async jobs) ---

const testJobs = new Map();

function apiTestRunStart(req, res) {
  // Only one running test at a time
  for (const [, j] of testJobs) {
    if (j.status === "running") return jsonRes(res, 409, { error: "test already running", job_id: j.id });
  }
  const jobId = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  const job = { id: jobId, status: "running", result: null, startedAt: Date.now(), finishedAt: null };
  testJobs.set(jobId, job);

  const scriptPath = path.join(TOOLS_DIR, "test-memory-v21.py");
  exec(pyCmd(scriptPath, "--json"), { timeout: 120000 }, (err, stdout, stderr) => {
    if (!testJobs.has(jobId)) return;
    // Script exits non-zero when tests fail — still parse stdout
    if (stdout) {
      try { job.result = JSON.parse(stdout); job.status = "completed"; }
      catch { /* fall through to error handling */ }
    }
    if (!job.result) {
      if (err) { job.status = "error"; job.result = { error: err.message, stderr: (stderr || "").slice(0, 1000) }; }
      else { job.status = "error"; job.result = { error: "empty output" }; }
    }
    job.finishedAt = Date.now();
    setTimeout(() => testJobs.delete(jobId), 300000);
  });

  jsonRes(res, 202, { job_id: jobId, status: "running" });
}

function apiTestRunStatus(req, res, jobId) {
  const job = testJobs.get(jobId);
  if (!job) return jsonRes(res, 404, { error: "job not found" });
  jsonRes(res, 200, {
    job_id: jobId, status: job.status,
    elapsed_ms: (job.finishedAt || Date.now()) - job.startedAt,
    result: job.result,
  });
}

// --- Vector Status Proxy ---

function apiVectorStatus(req, res) {
  const cfg = loadConfig();
  const port = cfg.vector_search?.service_port || 3849;
  const proxyReq = http.request(
    { hostname: "127.0.0.1", port, path: "/status", method: "GET", timeout: 5000 },
    (proxyRes) => {
      let body = "";
      proxyRes.on("data", chunk => body += chunk);
      proxyRes.on("end", () => {
        try { jsonRes(res, 200, JSON.parse(body)); }
        catch { jsonRes(res, 502, { error: "invalid response from vector service" }); }
      });
    }
  );
  proxyReq.on("error", () => jsonRes(res, 503, { error: "vector service unreachable", port }));
  proxyReq.on("timeout", () => { proxyReq.destroy(); jsonRes(res, 504, { error: "vector service timeout" }); });
  proxyReq.end();
}

// --- Ollama Backends Status (30s server-side cache) ---

let _ollamaCache = { data: null, ts: 0 };
const OLLAMA_CACHE_TTL = 30000; // 30s

function apiOllamaBackendsStatus(req, res) {
  const now = Date.now();
  if (_ollamaCache.data && (now - _ollamaCache.ts) < OLLAMA_CACHE_TTL) {
    return jsonRes(res, 200, _ollamaCache.data);
  }

  const cfg = loadConfig();
  const backends = cfg.vector_search?.ollama_backends || {};
  const names = Object.keys(backends);
  if (!names.length) return jsonRes(res, 200, { backends: [], cached: false });

  // Read long_die marker
  let longDie = null;
  try {
    const marker = fs.readFileSync(path.join(WORKFLOW_DIR, ".backend_long_die.json"), "utf-8");
    longDie = JSON.parse(marker);
  } catch {}

  // Read auth token for rdchat
  let rdchatToken = null;
  try {
    const tf = fs.readFileSync(path.join(WORKFLOW_DIR, ".rdchat_token.json"), "utf-8");
    rdchatToken = JSON.parse(tf).token;
  } catch {}

  const results = [];
  let pending = names.length;

  function finish() {
    if (--pending > 0) return;
    const payload = { backends: results, long_die: longDie, cached: false, checked_at: now };
    _ollamaCache = { data: { ...payload, cached: true }, ts: now };
    payload.cached = false;
    jsonRes(res, 200, payload);
  }

  for (const name of names) {
    const b = backends[name];
    const entry = {
      name,
      base_url: b.base_url,
      llm_model: b.llm_model || "?",
      embedding_model: b.embedding_model || "?",
      priority: b.priority || 99,
      enabled: b.enabled !== false,
      status: "unknown",
      latency_ms: null,
      long_die: longDie && longDie.backend === name ? longDie : null,
    };

    if (!entry.enabled) {
      entry.status = "disabled";
      results.push(entry);
      finish();
      continue;
    }

    const url = new URL(b.base_url.replace(/\/+$/, "") + "/api/tags");
    const isHttps = url.protocol === "https:";
    const mod = isHttps ? https : http;
    const headers = {};
    if (b.auth && rdchatToken) {
      headers["Authorization"] = "Bearer " + rdchatToken;
    }
    const t0 = Date.now();
    const opts = {
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: "GET",
      headers,
      timeout: 5000,
      rejectUnauthorized: false,
    };

    const probe = mod.request(opts, (probeRes) => {
      // Drain response body
      probeRes.on("data", () => {});
      probeRes.on("end", () => {
        entry.latency_ms = Date.now() - t0;
        entry.status = probeRes.statusCode === 200 ? "online"
                     : probeRes.statusCode === 401 ? "auth_expired"
                     : "error_" + probeRes.statusCode;
        results.push(entry);
        finish();
      });
    });
    probe.on("error", () => {
      entry.latency_ms = Date.now() - t0;
      entry.status = "offline";
      results.push(entry);
      finish();
    });
    probe.on("timeout", () => {
      probe.destroy();
      entry.latency_ms = Date.now() - t0;
      entry.status = "timeout";
      results.push(entry);
      finish();
    });
    probe.end();
  }
}

// --- Knowledge Queue Aggregation ---

function apiKnowledgeQueue(req, res) {
  const sessions = listAllSessions();
  const items = [];
  for (const s of sessions) {
    if (s.ended) continue;
    const state = readState(s.session_id);
    if (!state) continue;
    for (const kq of (state.knowledge_queue || [])) {
      items.push({ session_id: s.session_id, session_name: s.name, ...kq });
    }
  }
  jsonRes(res, 200, items);
}

// --- Atoms Browser API ---

function apiProjects(req, res) {
  const reg = loadRegistry();
  const projects = [];
  for (const [slug, info] of Object.entries(reg.projects || {})) {
    const proj = {
      slug,
      root: info.root || "",
      last_seen: info.last_seen || "",
      aliases: info.aliases || [],
      has_memory: false,
      atom_count: 0,
      failure_count: 0,
      episodic_count: 0,
    };
    // V2.21: if root itself is the .claude dir, memory is at root/memory/ directly
    const rootNorm = path.resolve(info.root || "");
    const isClaudeDir = rootNorm.toLowerCase() === path.resolve(CLAUDE_DIR).toLowerCase();
    const memDir = isClaudeDir
      ? path.join(rootNorm, "memory")
      : path.join(rootNorm, ".claude", "memory");
    if (fs.existsSync(memDir) && fs.existsSync(path.join(memDir, "MEMORY.md"))) {
      proj.has_memory = true;
      try {
        proj.atom_count = fs.readdirSync(memDir).filter(f =>
          f.endsWith(".md") && f !== "MEMORY.md" && !f.startsWith("_") && !f.startsWith("SPEC_")
        ).length;
      } catch {}
      try {
        const failDir = path.join(memDir, "failures");
        if (fs.existsSync(failDir)) {
          proj.failure_count = fs.readdirSync(failDir).filter(f => f.endsWith(".md") && f !== "_INDEX.md").length;
        }
      } catch {}
      try {
        const epicDir = path.join(memDir, "episodic");
        if (fs.existsSync(epicDir)) {
          proj.episodic_count = fs.readdirSync(epicDir).filter(f => f.endsWith(".md")).length;
        }
      } catch {}
    }
    projects.push(proj);
  }
  projects.sort((a, b) => (b.last_seen || "").localeCompare(a.last_seen || ""));
  jsonRes(res, 200, projects);
}

function apiAtoms(req, res) {
  const atoms = [];
  const seenAtomFiles = new Set();
  const scanDirs = [
    { dir: MEMORY_DIR, layer: "global", scope: "global" },
    { dir: path.join(MEMORY_DIR, "failures"), layer: "failures", scope: "global" },
    { dir: path.join(MEMORY_DIR, "unity"), layer: "unity", scope: "global" },
  ];

  for (const { dir, layer, scope } of scanDirs) {
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir)) {
      if (!f.endsWith(".md")) continue;
      if (f === "MEMORY.md" || f.startsWith("SPEC_") || f.startsWith("_")) continue;

      const filePath = path.join(dir, f);
      const fileKey = path.resolve(filePath).toLowerCase();
      if (seenAtomFiles.has(fileKey)) continue;
      seenAtomFiles.add(fileKey);
      try {
        const content = fs.readFileSync(filePath, "utf-8");
        const atom = { name: f.replace(".md", ""), layer, scope, file: f };

        // Parse metadata
        const metaRe = /^-\s+([\w-]+):\s*(.+)$/gm;
        let m;
        while ((m = metaRe.exec(content)) !== null) {
          const key = m[1].toLowerCase(), val = m[2].trim();
          switch (key) {
            case "confidence": atom.confidence = val; break;
            case "last-used": atom.last_used = val; break;
            case "confirmations": atom.confirmations = parseInt(val) || 0; break;
            case "readhits": atom.readhits = parseInt(val) || 0; break;
            case "trigger": atom.triggers = val.split(",").map(t => t.trim()); break;
            case "related": atom.related = val.split(",").map(t => t.trim()); break;
            case "created": atom.created = val; break;
            case "type": atom.type = val; break;
            case "tags": atom.tags = val.split(",").map(t => t.trim()); break;
            case "scope": atom.scope = val; break;
            case "audience": atom.audience = val.split(",").map(t => t.trim()); break;
            case "author": atom.author = val; break;
          }
        }

        // Count knowledge items
        let knowledgeCount = 0;
        let inKnowledge = false;
        for (const line of content.split("\n")) {
          if (/^##\s+知識/.test(line)) { inKnowledge = true; continue; }
          if (/^##\s+/.test(line) && inKnowledge) break;
          if (inKnowledge && /^- \[/.test(line)) knowledgeCount++;
        }
        atom.knowledge_count = knowledgeCount;

        // Line count
        atom.line_count = content.split("\n").length;

        // Days since last used
        if (atom.last_used) {
          const lu = new Date(atom.last_used);
          atom.days_since_used = Math.floor((Date.now() - lu.getTime()) / 86400000);
        }

        // Full content for detail view
        atom.content = content;

        atoms.push(atom);
      } catch {}
    }
  }

  // Helper: scan a single .md as an atom (used by project + V4 shared/role scans)
  function pushAtomFromFile(filePath, fileName, layerLabel, defaultScope) {
    const fileKey = path.resolve(filePath).toLowerCase();
    if (seenAtomFiles.has(fileKey)) return;
    seenAtomFiles.add(fileKey);
    try {
      const content = fs.readFileSync(filePath, "utf-8");
      if (content.includes("Status: migrated-v2.21")) return;
      const atom = {
        name: fileName.replace(".md", ""),
        layer: layerLabel,
        scope: defaultScope,
        file: fileName,
        content,
      };
      const metaRe = /^-\s+([\w-]+):\s*(.+)$/gm;
      let m2;
      while ((m2 = metaRe.exec(content)) !== null) {
        const key = m2[1].toLowerCase(), val = m2[2].trim();
        switch (key) {
          case "confidence": atom.confidence = val; break;
          case "last-used": atom.last_used = val; break;
          case "confirmations": atom.confirmations = parseInt(val) || 0; break;
          case "readhits": atom.readhits = parseInt(val) || 0; break;
          case "related": atom.related = val.split(",").map(t => t.trim()); break;
          case "trigger": atom.triggers = val.split(",").map(t => t.trim()); break;
          case "scope": atom.scope = val; break;
          case "audience": atom.audience = val.split(",").map(t => t.trim()); break;
          case "author": atom.author = val; break;
        }
      }
      atom.line_count = content.split("\n").length;
      atoms.push(atom);
    } catch {}
  }

  // Helper: scan a flat memory dir, skip excluded dirs, optionally exclude personal/episodic/_*
  function scanFlatDir(dir, layerLabel, defaultScope) {
    if (!fs.existsSync(dir)) return;
    for (const f of fs.readdirSync(dir)) {
      if (!f.endsWith(".md")) continue;
      if (f === "MEMORY.md" || f.startsWith("_")) continue;
      pushAtomFromFile(path.join(dir, f), f, layerLabel, defaultScope);
    }
  }

  // Helper: V4 shared/ + roles/{r}/ scan for any memory root
  function scanV4ScopeDirs(memRoot, layerPrefix, scopePrefix) {
    const sharedDir = path.join(memRoot, "shared");
    if (fs.existsSync(sharedDir)) {
      scanFlatDir(sharedDir, layerPrefix + "shared", scopePrefix + "shared");
    }
    const rolesDir = path.join(memRoot, "roles");
    if (fs.existsSync(rolesDir)) {
      try {
        for (const role of fs.readdirSync(rolesDir)) {
          const roleDir = path.join(rolesDir, role);
          try {
            if (!fs.statSync(roleDir).isDirectory()) continue;
          } catch { continue; }
          scanFlatDir(roleDir, layerPrefix + "role:" + role, scopePrefix + "role:" + role);
        }
      } catch {}
    }
  }

  // Helper: scan a project memory dir (legacy flat layout) and push atoms
  function scanProjMemDir(projMemDir, slug) {
    const before = atoms.length;
    scanFlatDir(projMemDir, "project:" + slug, "project:" + slug);
    // 若 atom frontmatter 寫 `Scope: project`（V4 SPEC 允許值），把 slug 補回去，避免畫面只看到 "project"
    for (let i = before; i < atoms.length; i++) {
      if (atoms[i].scope === "project") atoms[i].scope = "project:" + slug;
    }
    scanV4ScopeDirs(projMemDir, "project:" + slug + ":", "project:" + slug + ":");
  }

  // V4: global shared/ + roles/{r}/ scan (本專案目前無此目錄，預留給未來)
  scanV4ScopeDirs(MEMORY_DIR, "", "");

  // V2.21: scan registry project dirs (new path)
  const seenProjDirs = new Set();
  for (const { slug, memDir } of getRegistryMemDirs()) {
    scanProjMemDir(memDir, slug);
    seenProjDirs.add(memDir);
  }

  // Also scan old project memory dirs (fallback for unregistered projects)
  const projectsDir = path.join(CLAUDE_DIR, "projects");
  if (fs.existsSync(projectsDir)) {
    for (const proj of fs.readdirSync(projectsDir)) {
      const projMemDir = path.join(projectsDir, proj, "memory");
      if (seenProjDirs.has(projMemDir)) continue;
      scanProjMemDir(projMemDir, proj);
    }
  }

  atoms.sort((a, b) => (b.last_used || "").localeCompare(a.last_used || ""));
  jsonRes(res, 200, atoms);
}

// ─── Skills (commands/*.md) ──────────────────────────────────────────────────
// 純檔案掃描；提供「全域 + 各 registered project」的 slash command 清單。
const SKILL_CATEGORY_MAP = {
  // V4 / V4.1 共用核心
  "memory-peek": "V4.1", "memory-undo": "V4.1", "memory-session-score": "V4.1",
  "generate-episodic": "V4.1",
  // 記憶維運
  "extract": "記憶維運", "memory-health": "記憶維運", "memory-review": "記憶維運",
  "conflict": "記憶維運", "conflict-review": "記憶維運", "atom-debug": "記憶維運",
  "fix-escalation": "記憶維運",
  // 開發協作
  "handoff": "開發協作", "continue": "開發協作", "resume": "開發協作",
  "init-project": "開發協作", "init-roles": "開發協作", "read-project": "開發協作",
  "upgrade": "開發協作", "consciousness-stream": "開發協作",
  // 工具
  "harvest": "工具", "browse-sprites": "工具", "unity-yaml": "工具",
  "svn-update": "工具", "vector": "工具",
};

function extractSkillDescription(content) {
  const lines = content.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    // 跳過 H1 與空行；找第一個 `> ...` 引言行（這是現行 commands/*.md 的描述慣例）
    if (line.startsWith("> ")) return line.slice(2).trim();
  }
  // fallback：第一個非 H1 / 非空 / 非分隔線的段落
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith("#") || line.startsWith("---")) continue;
    return line.slice(0, 200);
  }
  return "";
}

function scanCommandsDir(dir, source) {
  const skills = [];
  if (!fs.existsSync(dir)) return skills;
  for (const f of fs.readdirSync(dir)) {
    if (!f.endsWith(".md")) continue;
    const filePath = path.join(dir, f);
    try {
      const stat = fs.statSync(filePath);
      if (!stat.isFile()) continue;
      const content = fs.readFileSync(filePath, "utf-8");
      const name = f.replace(".md", "");
      skills.push({
        name,
        command: "/" + name,
        description: extractSkillDescription(content),
        category: SKILL_CATEGORY_MAP[name] || "其他",
        source,
        file: filePath,
        content,
      });
    } catch {}
  }
  return skills;
}

function apiSkills(req, res) {
  const skills = [];
  const seenFiles = new Set();
  function pushUnique(list) {
    for (const s of list) {
      const key = path.resolve(s.file).toLowerCase();
      if (seenFiles.has(key)) continue;
      seenFiles.add(key);
      skills.push(s);
    }
  }
  // 全域（優先，避免被 registered project 重複撈走）
  pushUnique(scanCommandsDir(path.join(CLAUDE_DIR, "commands"), "global"));
  // 各 registered project
  const reg = loadRegistry();
  for (const [slug, info] of Object.entries(reg.projects || {})) {
    if (!info.root) continue;
    const rootNorm = path.resolve(info.root);
    const projCmdDir = path.join(rootNorm, ".claude", "commands");
    // 若 project root 的 .claude/commands 與 CLAUDE_DIR/commands 是同一目錄（例：root=user home），跳過
    const projCmdNorm = path.resolve(projCmdDir).toLowerCase();
    const globalCmdNorm = path.resolve(path.join(CLAUDE_DIR, "commands")).toLowerCase();
    if (projCmdNorm === globalCmdNorm) continue;
    pushUnique(scanCommandsDir(projCmdDir, "project:" + slug));
  }
  // 排序：分類 → 名稱
  skills.sort((a, b) =>
    a.category.localeCompare(b.category, "zh-Hant") ||
    a.name.localeCompare(b.name)
  );
  jsonRes(res, 200, skills);
}

// ─── MCP Servers ─────────────────────────────────────────────────────────────
// 來源：~/.claude/.mcp.json + 各 registered project .mcp.json + settings.json
function readMcpJson(filePath) {
  if (!fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch { return null; }
}

function apiMcpServers(req, res) {
  const servers = [];

  // 全域 .mcp.json
  const globalMcp = readMcpJson(path.join(CLAUDE_DIR, ".mcp.json"));
  if (globalMcp && globalMcp.mcpServers) {
    for (const [name, cfg] of Object.entries(globalMcp.mcpServers)) {
      servers.push(buildMcpEntry(name, cfg, "global", path.join(CLAUDE_DIR, ".mcp.json")));
    }
  }

  // settings.json 的 enabled 狀態
  const settings = readMcpJson(path.join(CLAUDE_DIR, "settings.json")) || {};
  const enabledList = settings.enabledMcpjsonServers || [];
  const enableAll = settings.enableAllProjectMcpServers === true;

  // 各 registered project .mcp.json
  const reg = loadRegistry();
  for (const [slug, info] of Object.entries(reg.projects || {})) {
    if (!info.root) continue;
    const rootNorm = path.resolve(info.root);
    const isClaudeDir = rootNorm.toLowerCase() === path.resolve(CLAUDE_DIR).toLowerCase();
    if (isClaudeDir) continue;
    const projMcpPath = path.join(rootNorm, ".mcp.json");
    const projMcp = readMcpJson(projMcpPath);
    if (!projMcp || !projMcp.mcpServers) continue;
    for (const [name, cfg] of Object.entries(projMcp.mcpServers)) {
      const entry = buildMcpEntry(name, cfg, "project:" + slug, projMcpPath);
      // 專案 MCP 的啟用判斷：enableAllProjectMcpServers 或 enabledMcpjsonServers 含名稱
      entry.enabled = enableAll || enabledList.includes(name);
      servers.push(entry);
    }
  }

  servers.sort((a, b) =>
    a.source.localeCompare(b.source) || a.name.localeCompare(b.name)
  );
  jsonRes(res, 200, servers);
}

function buildMcpEntry(name, cfg, source, filePath) {
  return {
    name,
    type: cfg.type || "stdio",
    command: cfg.command || "",
    args: Array.isArray(cfg.args) ? cfg.args : [],
    url: cfg.url || "",
    env_keys: cfg.env ? Object.keys(cfg.env) : [],
    source,
    config_file: filePath,
    enabled: true, // 全域預設啟用；專案的會在 caller 覆寫
  };
}

// ─── HTTP Dashboard ─────────────────────────────────────────────────────────

const DASHBOARD_HTML = `<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>工作流守衛 v${VERSIONS.guardian}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 4px; font-size: 1.4em; }
  .subtitle { color: #8b949e; font-size: 0.85em; margin-bottom: 12px; }
  .stats { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
  .stat { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 14px; min-width: 100px; }
  .stat-value { font-size: 1.4em; font-weight: bold; color: #58a6ff; }
  .stat-label { font-size: 0.75em; color: #8b949e; }
  .tab-nav { display: flex; gap: 0; border-bottom: 1px solid #30363d; margin-bottom: 16px; }
  .tab-btn { padding: 8px 16px; border: none; background: none; color: #8b949e; cursor: pointer; border-bottom: 2px solid transparent; font-size: 0.9em; font-family: inherit; }
  .tab-btn:hover { color: #c9d1d9; }
  .tab-btn.active { color: #58a6ff; border-bottom-color: #58a6ff; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .sessions { display: flex; flex-direction: column; gap: 12px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
  .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .card-name { font-weight: 600; color: #e6edf3; font-size: 1.05em; }
  .card-id { font-family: monospace; color: #79c0ff; font-size: 0.85em; }
  .badge { padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600; }
  .badge-init { background: #1f6feb33; color: #58a6ff; }
  .badge-working { background: #f0883e33; color: #f0883e; }
  .badge-syncing { background: #d2a82633; color: #d2a826; }
  .badge-done { background: #23863633; color: #3fb950; }
  .badge-merged { background: #a371f733; color: #a371f7; }
  .card-meta { font-size: 0.8em; color: #8b949e; margin-bottom: 8px; }
  .card-stats { display: flex; gap: 16px; font-size: 0.85em; }
  .card-stats span { color: #8b949e; }
  .card-stats strong { color: #c9d1d9; }
  .details { margin-top: 10px; padding-top: 10px; border-top: 1px solid #30363d; font-size: 0.82em; }
  .details summary { cursor: pointer; color: #58a6ff; margin-bottom: 6px; }
  .file-list, .kq-list { list-style: none; padding-left: 8px; }
  .file-list li, .kq-list li { padding: 2px 0; color: #8b949e; font-family: monospace; font-size: 0.9em; }
  .kq-badge { font-weight: bold; }
  .kq-badge-fixed { color: #3fb950; }
  .kq-badge-observe { color: #d2a826; }
  .kq-badge-temp { color: #f0883e; }
  .actions { margin-top: 10px; display: flex; gap: 8px; }
  .btn { padding: 4px 12px; border-radius: 4px; border: 1px solid #30363d; background: #21262d; color: #c9d1d9; cursor: pointer; font-size: 0.8em; font-family: inherit; }
  .btn:hover { background: #30363d; }
  .btn-primary { border-color: #388bfd66; color: #58a6ff; }
  .btn-primary:hover { background: #388bfd22; }
  .btn-success { border-color: #3fb95066; color: #3fb950; }
  .btn-success:hover { background: #3fb95022; }
  .btn-danger { border-color: #f8514966; color: #f85149; }
  .btn-danger:hover { background: #f8514922; }
  .empty { text-align: center; color: #8b949e; padding: 40px; }
  .auto-refresh { font-size: 0.8em; color: #8b949e; }
  .auto-refresh label { cursor: pointer; }
  /* Timeline */
  .timeline { position: relative; padding-left: 28px; border-left: 2px solid #30363d; margin-left: 8px; }
  .timeline-item { position: relative; margin-bottom: 16px; }
  .timeline-dot { position: absolute; left: -35px; top: 10px; width: 12px; height: 12px; border-radius: 50%; border: 2px solid #0d1117; }
  .ttl-green { background: #3fb950; }
  .ttl-yellow { background: #d2a826; }
  .ttl-red { background: #f85149; }
  .ttl-critical { background: #f85149; animation: pulse 1s infinite; }
  .ttl-expired { background: #484f58; }
  @keyframes pulse { 50% { opacity: 0.4; } }
  .timeline-card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px; }
  .timeline-date { font-size: 0.75em; color: #8b949e; }
  .timeline-title { font-weight: 600; color: #e6edf3; margin: 4px 0; }
  .timeline-ttl { font-size: 0.8em; padding: 1px 6px; border-radius: 8px; font-weight: 600; }
  .timeline-knowledge { margin-top: 8px; font-size: 0.82em; color: #8b949e; }
  .timeline-knowledge li { padding: 2px 0; list-style: none; }
  .timeline-full { margin-top: 8px; padding-top: 8px; border-top: 1px solid #30363d; white-space: pre-wrap; font-family: monospace; font-size: 0.78em; color: #8b949e; max-height: 300px; overflow-y: auto; }
  /* Health */
  .health-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin-bottom: 16px; }
  .health-stat { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px; text-align: center; }
  .health-stat .val { font-size: 1.5em; font-weight: bold; }
  .health-stat .lbl { font-size: 0.75em; color: #8b949e; }
  .issue-table { width: 100%; border-collapse: collapse; font-size: 0.82em; margin-bottom: 16px; }
  .issue-table th { text-align: left; color: #8b949e; padding: 6px 8px; border-bottom: 1px solid #30363d; }
  .issue-table td { padding: 6px 8px; border-bottom: 1px solid #21262d; }
  .level-error { color: #f85149; }
  .level-warning { color: #d2a826; }
  .level-info { color: #58a6ff; }
  .suggest-list { list-style: none; margin-bottom: 16px; }
  .suggest-list li { padding: 6px 0; border-bottom: 1px solid #21262d; font-size: 0.85em; }
  .suggest-arrow { color: #58a6ff; font-weight: bold; }
  .cache-info { font-size: 0.75em; color: #484f58; margin-top: 8px; }
  /* Tests */
  .test-card { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-radius: 6px; margin-bottom: 6px; background: #161b22; border: 1px solid #30363d; }
  .test-pass { border-left: 3px solid #3fb950; }
  .test-fail { border-left: 3px solid #f85149; }
  .test-skip { border-left: 3px solid #8b949e; }
  .test-icon { font-size: 1.1em; width: 22px; text-align: center; }
  .test-name { font-weight: 600; color: #e6edf3; flex: 1; }
  .test-duration { font-size: 0.8em; color: #8b949e; }
  .test-msg { font-size: 0.78em; color: #8b949e; font-family: monospace; }
  .test-summary { display: flex; gap: 16px; padding: 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; margin-bottom: 12px; font-size: 0.9em; }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #30363d; border-top-color: #58a6ff; border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .run-btn { padding: 10px 24px; font-size: 1em; border-radius: 6px; border: 1px solid #3fb95066; background: #23863622; color: #3fb950; cursor: pointer; font-weight: 600; font-family: inherit; }
  .run-btn:hover { background: #23863644; }
  .run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  /* Vector */
  .vec-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .vec-section { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 14px; }
  .vec-section h3 { font-size: 0.9em; color: #58a6ff; margin-bottom: 8px; }
  .vec-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.85em; }
  .vec-row .k { color: #8b949e; }
  .vec-row .v { color: #e6edf3; font-family: monospace; }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .status-online { background: #3fb950; }
  .status-offline { background: #f85149; }
  .status-warn { background: #d2a826; }
  .status-disabled { background: #484f58; }
  .backend-card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 14px; }
  .backend-card .bc-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .backend-card .bc-name { font-weight: 600; font-size: 0.95em; }
  .backend-card .bc-tag { font-size: 0.75em; padding: 1px 6px; border-radius: 3px; background: #30363d; color: #8b949e; }
  .backend-card .bc-tag.pri { background: #58a6ff22; color: #58a6ff; }
  .section-title { font-size: 1em; font-weight: 600; color: #e6edf3; margin-bottom: 10px; }
  /* Atoms */
  .atom-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
  .atom-table th { text-align: left; color: #8b949e; padding: 8px; border-bottom: 2px solid #30363d; cursor: pointer; user-select: none; }
  .atom-table th:hover { color: #58a6ff; }
  .atom-table td { padding: 8px; border-bottom: 1px solid #21262d; }
  .atom-table tr:hover { background: #161b2288; }
  .atom-name { color: #58a6ff; font-weight: 600; cursor: pointer; }
  .atom-name:hover { text-decoration: underline; }
  .atom-layer { font-size: 0.8em; padding: 1px 6px; border-radius: 8px; background: #30363d; color: #8b949e; }
  .atom-conf { font-weight: bold; }
  .conf-fixed { color: #3fb950; }
  .conf-observe { color: #d2a826; }
  .conf-temp { color: #f0883e; }
  .atom-detail { background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin: 12px 0; white-space: pre-wrap; font-family: monospace; font-size: 0.82em; max-height: 500px; overflow-y: auto; }
  .atom-filter { padding: 6px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 4px; color: #c9d1d9; font-size: 0.9em; margin-bottom: 12px; width: 300px; font-family: inherit; }
  .atom-filter::placeholder { color: #484f58; }
  .atom-stats { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .proj-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
  .proj-table th { text-align: left; color: #8b949e; padding: 8px; border-bottom: 2px solid #30363d; }
  .proj-table td { padding: 8px; border-bottom: 1px solid #21262d; vertical-align: top; }
  .proj-table tr:hover { background: #161b2288; }
  .proj-root { font-family: monospace; font-size: 0.85em; color: #79c0ff; word-break: break-all; }
  .proj-badge-mem { background: #23863622; color: #3fb950; padding: 2px 6px; border-radius: 4px; font-size: 0.75em; }
  .proj-badge-nomem { background: #30363d; color: #8b949e; padding: 2px 6px; border-radius: 4px; font-size: 0.75em; }
  .proj-alias { font-size: 0.8em; color: #8b949e; }
  .proj-filter-btn { background: none; border: 1px solid #30363d; color: #58a6ff; padding: 2px 8px; border-radius: 4px; cursor: pointer; font-size: 0.8em; font-family: inherit; }
  .proj-filter-btn:hover { background: #58a6ff22; }
  .hot-cache-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; display: flex; align-items: center; gap: 12px; font-size: 0.85em; }
  .hot-cache-card.has-cache { border-color: #3fb95066; }
  .hot-cache-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .hot-cache-dot.green { background: #3fb950; }
  .hot-cache-dot.gray { background: #484f58; }
  .vector-indicator { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
  .vector-indicator:hover { background: #30363d; }
  .vector-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
  .vector-dot.ready { background: #3fb950; }
  .vector-dot.not-ready { background: #f85149; }
</style>
</head>
<body>
<div style="display:flex;justify-content:space-between;align-items:baseline;">
  <div><h1>工作流守衛 v${VERSIONS.guardian}</h1><p class="subtitle">記憶與對話監控</p></div>
  <div class="auto-refresh"><label><input type="checkbox" id="autoRefresh" checked> 自動重整 (5秒)</label></div>
</div>

<div class="stats" id="statsBar"></div>
<div id="hotCacheCard" class="hot-cache-card" style="display:none"></div>

<nav class="tab-nav">
  <button class="tab-btn active" data-tab="sessions">對話</button>
  <button class="tab-btn" data-tab="episodic">情境記憶</button>
  <button class="tab-btn" data-tab="health">健康檢查</button>
  <button class="tab-btn" data-tab="atoms">原子記憶 v${VERSIONS.atom_memory}</button>
  <button class="tab-btn" data-tab="projects">已知專案</button>
  <button class="tab-btn" data-tab="tests">測試</button>
  <button class="tab-btn" data-tab="vector">向量服務</button>
  <button class="tab-btn" data-tab="env">環境</button>
</nav>

<div id="panelSessions" class="tab-panel active">
  <div class="sessions" id="sessionList"></div>
</div>

<div id="panelEpisodic" class="tab-panel">
  <div id="episodicContent"></div>
</div>

<div id="panelHealth" class="tab-panel">
  <div id="healthContent"><div class="empty">載入健康資料中...</div></div>
</div>

<div id="panelAtoms" class="tab-panel">
  <div id="atomsContent"><div class="empty">載入原子記憶中...</div></div>
</div>

<div id="panelProjects" class="tab-panel">
  <div id="projectsContent"><div class="empty">載入已知專案中...</div></div>
</div>

<div id="panelTests" class="tab-panel">
  <div id="testsContent">
    <div style="text-align:center;padding:20px;">
      <button class="run-btn" id="runTestsBtn" onclick="startTestRun()">執行端對端測試</button>
    </div>
    <div id="testResults"></div>
  </div>
</div>

<div id="panelVector" class="tab-panel">
  <div id="vectorContent"><div class="empty">載入向量服務狀態中...</div></div>
</div>

<div id="panelEnv" class="tab-panel">
  <div id="envContent"><div class="empty">載入環境資訊中...</div></div>
</div>

<script>
let refreshTimer;
let currentTab = "sessions";
let testJobId = null;
let testPollTimer = null;

function switchTab(name) {
  const btn = document.querySelector('[data-tab="' + name + '"]');
  if (btn) btn.click();
}

// ─── Tab Switching ───

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const prevTab = currentTab;
    currentTab = btn.dataset.tab;
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    document.getElementById("panel" + currentTab.charAt(0).toUpperCase() + currentTab.slice(1)).classList.add("active");
    if (prevTab === "vector" && currentTab !== "vector") stopBackendsPolling();
    refreshCurrentTab();
  });
});

async function refreshCurrentTab() {
  const prevScroll = window.scrollY;
  switch (currentTab) {
    case "sessions": await renderSessions(); break;
    case "episodic": await renderEpisodic(); break;
    case "health": await renderHealth(false); break;
    case "atoms": await renderAtoms(); break;
    case "projects": await renderProjects(); break;
    case "tests": break;
    case "vector": await renderVector(); break;
    case "env": await renderEnv(); break;
  }
  window.scrollTo(0, prevScroll);
}

// ─── Sessions Panel (existing logic) ───

async function fetchSessions() {
  try { const r = await fetch("/api/sessions"); return await r.json(); }
  catch { return []; }
}

async function sendSignal(sid, signal) {
  await fetch("/api/sessions/" + sid + "/signal", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signal })
  });
  renderSessions();
}

async function deleteSession(sid) {
  if (!confirm("確定要刪除對話 " + sid.slice(0,8) + "?")) return;
  await fetch("/api/sessions/" + sid, { method: "DELETE" });
  renderSessions();
}

function badgeClass(phase) { return "badge badge-" + (phase || "init"); }

function clsBadge(c) {
  if (c === "[固]") return '<span class="kq-badge kq-badge-fixed">[固]</span>';
  if (c === "[觀]") return '<span class="kq-badge kq-badge-observe">[觀]</span>';
  return '<span class="kq-badge kq-badge-temp">[臨]</span>';
}

function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

async function renderSessions() {
  const [sessions, vecReady] = await Promise.all([fetchSessions(), fetchVectorReady()]);
  const active = sessions.filter(s => !s.ended);
  const pending = sessions.filter(s => s.sync_pending && !s.ended);
  const vecHtml = '<div class="stat"><div class="vector-indicator" onclick="switchTab(\\'vector\\')"><span class="vector-dot ' + (vecReady?"ready":"not-ready") + '"></span> Vector</div></div>';
  updateStats(sessions.length, active.length, pending.length, vecHtml);
  renderHotCache();

  if (sessions.length === 0) {
    document.getElementById("sessionList").innerHTML = '<div class="empty">無進行中的對話。</div>';
    return;
  }

  const cards = await Promise.all(sessions.map(async (s) => {
    let detail;
    try { const r = await fetch("/api/sessions/" + s.session_id); detail = await r.json(); }
    catch { detail = {}; }
    const files = detail.modified_files || [];
    const kq = detail.knowledge_queue || [];
    const uniqueFiles = [...new Set(files.map(f => f.path))];
    let fileHtml = "";
    if (uniqueFiles.length > 0) {
      fileHtml = '<details><summary>修改檔案 (' + uniqueFiles.length + ')</summary><ul class="file-list">' +
        uniqueFiles.map(f => "<li>" + esc(f.split(/[\\\\/]/).pop()) + ' <span style="color:#484f58">' + esc(f) + "</span></li>").join("") + "</ul></details>";
    }
    let kqHtml = "";
    if (kq.length > 0) {
      kqHtml = '<details><summary>知識佇列 (' + kq.length + ')</summary><ul class="kq-list">' +
        kq.map(q => "<li>" + clsBadge(q.classification) + " " + esc((q.content||"").slice(0,80)) + "</li>").join("") + "</ul></details>";
    }
    return '<div class="card">' +
      '<div class="card-header"><span class="card-name">' + esc(s.name||"?") + '</span><span class="' + badgeClass(s.phase) + '">' + s.phase + (s.muted?" (已靜音)":"") + '</span></div>' +
      '<div class="card-meta"><span class="card-id">' + s.session_id.slice(0,8) + '</span> &middot; ' + esc(s.project||"?") + ' &middot; ' + s.age_minutes + ' 分鐘' + (s.ended?" &middot; 已結束":"") + (s.merged_into?' &middot; <span style="color:#a371f7">已合併至 '+s.merged_into.slice(0,8)+'</span>':"") + '</div>' +
      '<div class="card-stats"><span>檔案：<strong>' + s.modified_files_count + '</strong></span><span>知識：<strong>' + s.knowledge_queue_count + '</strong></span><span>同步：<strong>' + (s.sync_pending?"待處理":"完成") + '</strong></span></div>' +
      (fileHtml||kqHtml ? '<div class="details">' + fileHtml + kqHtml + '</div>' : '') +
      '<div class="actions">' +
        '<button class="btn" onclick="sendSignal(\\'' + s.session_id + '\\',\\'sync_completed\\')">標記已同步</button>' +
        '<button class="btn" onclick="sendSignal(\\'' + s.session_id + '\\',\\'reset\\')">重置</button>' +
        (s.muted ? '' : '<button class="btn" onclick="sendSignal(\\'' + s.session_id + '\\',\\'mute\\')">靜音</button>') +
        '<button class="btn btn-danger" onclick="deleteSession(\\'' + s.session_id + '\\')">刪除</button>' +
      '</div></div>';
  }));
  document.getElementById("sessionList").innerHTML = cards.join("");
}

// ─── Stats Bar ───

function updateStats(total, active, pending, extra) {
  let html = '<div class="stat"><div class="stat-value">' + total + '</div><div class="stat-label">對話數</div></div>' +
    '<div class="stat"><div class="stat-value">' + active + '</div><div class="stat-label">進行中</div></div>' +
    '<div class="stat"><div class="stat-value">' + pending + '</div><div class="stat-label">待同步</div></div>';
  if (extra) html += extra;
  document.getElementById("statsBar").innerHTML = html;
}

// ─── V3: Hot Cache Card ───

async function renderHotCache() {
  const el = document.getElementById("hotCacheCard");
  try {
    const data = await (await fetch("/api/hot-cache")).json();
    if (data.empty) { el.style.display = "none"; return; }
    const hasUninjected = !data.injected && (data.knowledge||[]).length > 0;
    el.className = "hot-cache-card" + (hasUninjected ? " has-cache" : "");
    el.style.display = "flex";
    const ageMin = Math.round((data.age_seconds||0) / 60);
    const ageStr = ageMin < 1 ? "<1 分鐘" : ageMin + " 分鐘前";
    el.innerHTML =
      '<span class="hot-cache-dot ' + (hasUninjected ? "green" : "gray") + '"></span>' +
      '<span><strong>Hot Cache</strong></span>' +
      '<span>來源: ' + (data.source||"?") + '</span>' +
      '<span>知識: ' + (data.knowledge||[]).length + ' 條</span>' +
      '<span>注入: ' + (data.injected ? "已注入" : "待注入") + '</span>' +
      '<span style="color:#8b949e">' + ageStr + '</span>';
  } catch { el.style.display = "none"; }
}

// ─── V3: Vector Ready Indicator ───

async function fetchVectorReady() {
  try {
    const data = await (await fetch("/api/vector-ready")).json();
    return data.ready;
  } catch { return false; }
}

// ─── Episodic Timeline ───

async function renderEpisodic() {
  const el = document.getElementById("episodicContent");
  try {
    const atoms = await (await fetch("/api/episodic")).json();
    if (!atoms.length) {
      el.innerHTML = '<div class="empty">無情境記憶紀錄。<br><span style="font-size:0.85em">情境記憶在對話結束時自動生成。</span></div>';
      return;
    }
    let html = '<div class="timeline">';
    for (const a of atoms) {
      const d = a.days_until_expiry;
      let dotCls = "ttl-green";
      let ttlLabel = d + "天剩餘";
      let ttlStyle = "background:#3fb95022;color:#3fb950";
      if (d !== null && d <= 0) { dotCls = "ttl-expired"; ttlLabel = "已過期"; ttlStyle = "background:#484f5822;color:#484f58"; }
      else if (d !== null && d <= 3) { dotCls = "ttl-critical"; ttlLabel = d + "天剩餘"; ttlStyle = "background:#f8514922;color:#f85149"; }
      else if (d !== null && d <= 7) { dotCls = "ttl-red"; ttlStyle = "background:#f8514922;color:#f85149"; }
      else if (d !== null && d <= 14) { dotCls = "ttl-yellow"; ttlStyle = "background:#d2a82622;color:#d2a826"; }

      const knLines = (a.knowledge_lines || []).slice(0, 5).map(l => "<li>" + esc(l) + "</li>").join("");
      const moreCount = (a.knowledge_lines||[]).length - 5;
      const hasMore = moreCount > 0;

      html += '<div class="timeline-item"><div class="timeline-dot ' + dotCls + '"></div><div class="timeline-card">' +
        '<div style="display:flex;justify-content:space-between;align-items:center">' +
          '<span class="timeline-date">' + esc(a.created || "?") + '</span>' +
          '<span class="timeline-ttl" style="' + ttlStyle + '">' + ttlLabel + '</span>' +
        '</div>' +
        '<div class="timeline-title">' + esc(a.title) + '</div>' +
        '<div style="font-size:0.78em;color:#8b949e">' + esc(a.triggers.join(", ")) + '</div>' +
        (knLines ? '<ul class="timeline-knowledge">' + knLines + (hasMore ? '<li style="color:#58a6ff">... +' + moreCount + ' 更多</li>' : '') + '</ul>' : '') +
        '<details><summary style="font-size:0.8em;color:#58a6ff;cursor:pointer;margin-top:6px">完整內容</summary>' +
          '<div class="timeline-full">' + esc(a.full_content) + '</div></details>' +
      '</div></div>';
    }
    html += '</div>';
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="empty">載入情境記憶失敗：' + esc(e.message) + '</div>';
  }
}

// ─── Memory Health ───

let lastHealthData = null;

let _healthInfoVisible = false;
function toggleHealthInfo() {
  _healthInfoVisible = !_healthInfoVisible;
  document.querySelectorAll('.health-info-row').forEach(r => {
    r.style.display = _healthInfoVisible ? '' : 'none';
  });
}

async function renderHealth(force) {
  const el = document.getElementById("healthContent");
  try {
    const url = "/api/health" + (force ? "?force=1" : "");
    el.innerHTML = '<div class="empty"><span class="spinner"></span> 載入健康報告中...</div>';
    const data = await (await fetch(url)).json();
    if (data.error) { el.innerHTML = '<div class="empty">健康檢查失敗：' + esc(data.error) + '</div>'; return; }
    lastHealthData = data;

    const cc = data.confidence_counts || {};
    let html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">' +
      '<span class="section-title">記憶健康報告</span>' +
      '<button class="btn btn-primary" onclick="renderHealth(true)">立即重整</button></div>';

    // Confidence counts
    html += '<div class="health-grid">';
    html += '<div class="health-stat"><div class="val" style="color:#3fb950">' + (cc["[固]"]||0) + '</div><div class="lbl">[固] 確定</div></div>';
    html += '<div class="health-stat"><div class="val" style="color:#d2a826">' + (cc["[觀]"]||0) + '</div><div class="lbl">[觀] 觀察</div></div>';
    html += '<div class="health-stat"><div class="val" style="color:#f0883e">' + (cc["[臨]"]||0) + '</div><div class="lbl">[臨] 臨時</div></div>';
    html += '<div class="health-stat"><div class="val">' + (data.total_atoms||0) + '</div><div class="lbl">原子總數</div></div>';
    html += '<div class="health-stat"><div class="val">' + (data.distant_count||0) + '</div><div class="lbl">疏遠區</div></div>';
    html += '</div>';

    // Issues — grouped by severity
    const issues = data.issues || [];
    const errCount = issues.filter(i => i.level === "error").length;
    const warnCount = issues.filter(i => i.level === "warning").length;
    const infoCount = issues.filter(i => i.level === "info").length;
    if (issues.length) {
      html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">' +
        '<span class="section-title">問題</span>' +
        (errCount ? '<span style="color:#f85149;font-weight:bold">' + errCount + ' error</span>' : '') +
        (warnCount ? '<span style="color:#d2a826;font-weight:bold">' + warnCount + ' warning</span>' : '') +
        (infoCount ? '<span style="color:#8b949e">' + infoCount + ' info</span>' : '') +
        '<button class="btn" style="font-size:0.75em;padding:2px 8px" onclick="toggleHealthInfo()">顯示/隱藏 info</button>' +
        '</div>';
      html += '<table class="issue-table"><tr><th>等級</th><th>分類</th><th>檔案</th><th>訊息</th></tr>';
      for (const i of issues) {
        const hideClass = i.level === "info" ? ' class="health-info-row" style="display:' + (_healthInfoVisible ? '' : 'none') + '"' : '';
        html += '<tr' + hideClass + '><td class="level-' + i.level + '">' + i.level + '</td><td>' + esc(i.category) + '</td><td style="font-family:monospace;font-size:0.85em">' + esc(i.file) + '</td><td>' + esc(i.message) + '</td></tr>';
      }
      html += '</table>';
    } else {
      html += '<div style="color:#3fb950;margin-bottom:12px">✓ 無任何問題</div>';
    }

    // Promotions
    const promos = data.promotions || [];
    if (promos.length) {
      html += '<div class="section-title">晉升候選</div><ul class="suggest-list">';
      for (const p of promos) {
        html += '<li><span style="font-family:monospace">' + esc(p.file) + '</span> ' + p.current + ' <span class="suggest-arrow">&rarr;</span> ' + p.suggested + '<br><span style="color:#8b949e;font-size:0.82em">' + esc(p.reason) + '</span></li>';
      }
      html += '</ul>';
    }

    // Demotions
    const demos = data.demotions || [];
    if (demos.length) {
      html += '<div class="section-title">降級 / 過期警告</div><ul class="suggest-list">';
      for (const d of demos) {
        html += '<li><span style="font-family:monospace">' + esc(d.file) + '</span> ' + d.current + ' <span class="suggest-arrow">&rarr;</span> ' + d.suggested + '<br><span style="color:#8b949e;font-size:0.82em">' + esc(d.reason) + '</span></li>';
      }
      html += '</ul>';
    }

    // Reference integrity
    const brokenRefs = data.broken_refs || [];
    const missingRev = data.missing_reverse_refs || [];
    const staleAtoms = data.stale_atoms || [];
    html += '<div class="section-title">參照完整性</div>';
    if (!brokenRefs.length && !missingRev.length && !staleAtoms.length) {
      html += '<div style="color:#3fb950;margin-bottom:12px">✓ 所有參照完整、無過期 atom</div>';
    } else {
      if (brokenRefs.length) {
        html += '<div style="margin-bottom:8px"><strong style="color:#f85149">斷裂參照 (' + brokenRefs.length + ')</strong></div>';
        html += '<table class="issue-table"><tr><th>來源 Atom</th><th>指向（不存在）</th></tr>';
        for (const r of brokenRefs) { html += '<tr><td>' + esc(r.atom || "") + '</td><td style="color:#f85149">' + esc(r.missing_ref || "") + '</td></tr>'; }
        html += '</table>';
      }
      if (missingRev.length) {
        html += '<div style="margin-bottom:8px"><strong style="color:#d2a826">缺反向參照 (' + missingRev.length + ')</strong></div>';
        html += '<table class="issue-table"><tr><th>說明</th></tr>';
        for (const r of missingRev) { html += '<tr><td style="color:#d2a826">' + esc(r.direction || (r.atom_a + " → " + r.atom_b)) + '</td></tr>'; }
        html += '</table>';
      }
      if (staleAtoms.length) {
        html += '<div style="margin-bottom:8px"><strong style="color:#f0883e">過期 Atom (' + staleAtoms.length + ')</strong></div><ul>';
        for (const s of staleAtoms) { html += '<li>' + esc(s.name || s) + ' — Last-used: ' + esc(s.last_used || "?") + '</li>'; }
        html += '</ul>';
      }
    }

    // Audit stats
    const as = data.audit_stats || {};
    if (as.total_entries) {
      html += '<div class="section-title">審計摘要</div><div class="health-grid">';
      const ba = as.by_action || {};
      for (const [k, v] of Object.entries(ba)) {
        html += '<div class="health-stat"><div class="val">' + v + '</div><div class="lbl">' + k + '</div></div>';
      }
      html += '<div class="health-stat"><div class="val">' + as.total_entries + '</div><div class="lbl">總筆數</div></div>';
      html += '</div>';
    }

    html += '<div class="cache-info">掃描時間：' + esc(data.scan_date || "?") + ' | 層級：' + (data.layers||[]).join(", ") + '</div>';
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="empty">載入健康資料失敗：' + esc(e.message) + '</div>';
  }
}

// ─── E2E Test Runner ───

async function startTestRun() {
  const btn = document.getElementById("runTestsBtn");
  const el = document.getElementById("testResults");
  btn.disabled = true;
  el.innerHTML = '<div style="text-align:center;padding:16px"><span class="spinner"></span> 測試執行中... <span id="testElapsed">0s</span></div>';
  const startTime = Date.now();
  const elapsedTimer = setInterval(() => {
    const s = ((Date.now() - startTime) / 1000).toFixed(0);
    const te = document.getElementById("testElapsed");
    if (te) te.textContent = s + "s";
  }, 500);

  try {
    const r = await fetch("/api/test-run", { method: "POST" });
    const d = await r.json();
    if (d.error) { el.innerHTML = '<div class="empty">' + esc(d.error) + '</div>'; btn.disabled = false; clearInterval(elapsedTimer); return; }
    testJobId = d.job_id;
    testPollTimer = setInterval(async () => {
      try {
        const sr = await fetch("/api/test-run/" + testJobId);
        const sd = await sr.json();
        if (sd.status !== "running") {
          clearInterval(testPollTimer);
          clearInterval(elapsedTimer);
          testPollTimer = null;
          btn.disabled = false;
          renderTestResults(sd);
        }
      } catch {}
    }, 2000);
  } catch (e) {
    el.innerHTML = '<div class="empty">測試執行失敗：' + esc(e.message) + '</div>';
    btn.disabled = false;
    clearInterval(elapsedTimer);
  }
}

function renderTestResults(job) {
  const el = document.getElementById("testResults");
  if (job.status === "error") {
    const err = job.result || {};
    el.innerHTML = '<div class="empty" style="color:#f85149">測試失敗：' + esc(err.error || "unknown") + (err.stderr ? '<br><pre style="text-align:left;font-size:0.8em;margin-top:8px">' + esc(err.stderr) + '</pre>' : '') + '</div>';
    return;
  }
  const r = job.result || {};
  const results = r.results || [];
  let html = '<div class="test-summary">' +
    '<span style="color:#3fb950;font-weight:600">通過：' + (r.passed||0) + '</span>' +
    '<span style="color:#f85149;font-weight:600">失敗：' + (r.failed||0) + '</span>' +
    '<span style="color:#8b949e">略過：' + (r.skipped||0) + '</span>' +
    '<span style="color:#8b949e">總計：' + (r.total||0) + '</span>' +
    '<span style="color:#8b949e">耗時：' + ((job.elapsed_ms||0)/1000).toFixed(1) + 's</span>' +
  '</div>';
  for (const t of results) {
    const cls = t.skipped ? "test-skip" : (t.passed ? "test-pass" : "test-fail");
    const icon = t.skipped ? "&#9711;" : (t.passed ? "&#10003;" : "&#10007;");
    const iconColor = t.skipped ? "#8b949e" : (t.passed ? "#3fb950" : "#f85149");
    html += '<div class="test-card ' + cls + '">' +
      '<span class="test-icon" style="color:' + iconColor + '">' + icon + '</span>' +
      '<span class="test-name">' + esc(t.name) + '</span>' +
      '<span class="test-duration">' + (t.duration_ms||0).toFixed(0) + 'ms</span>' +
    '</div>';
    if (t.message) {
      html += '<div style="padding:0 14px 6px 48px"><span class="test-msg">' + esc(t.message) + '</span></div>';
    }
  }
  el.innerHTML = html;
}

// ─── Vector Status ───

let _backendsHtml = "";  // cached backend HTML (refreshed independently)
let _backendsTimer = null;

async function fetchBackendsStatus() {
  try {
    const r = await fetch("/api/ollama-backends-status");
    const d = await r.json();
    const bs = (d.backends || []).sort((a,b) => a.priority - b.priority);
    if (!bs.length) { _backendsHtml = ""; return; }

    const statusMap = {
      online: { dot: "status-online", label: "線上", color: "#3fb950" },
      offline: { dot: "status-offline", label: "離線", color: "#f85149" },
      timeout: { dot: "status-offline", label: "逾時", color: "#f85149" },
      auth_expired: { dot: "status-warn", label: "Token 過期", color: "#d2a826" },
      disabled: { dot: "status-disabled", label: "停用", color: "#484f58" },
    };
    const checkedAt = d.checked_at ? new Date(d.checked_at).toLocaleTimeString() : "?";
    const cached = d.cached ? ' <span style="color:#484f58;font-size:0.75em">(快取)</span>' : "";

    let html = '<div style="margin-top:16px"><h3 style="font-size:0.95em;color:#e6edf3;margin-bottom:8px">Ollama 後端' + cached + ' <span style="color:#484f58;font-size:0.75em;font-weight:normal">最後檢查 ' + checkedAt + '</span></h3>';

    // Long DIE warning
    if (d.long_die) {
      html += '<div style="background:#d2a82622;border:1px solid #d2a82644;border-radius:6px;padding:8px 12px;margin-bottom:10px;font-size:0.85em;color:#d2a826">';
      html += '⚠ ' + esc(d.long_die.backend) + ' 長期停用至 ' + esc(d.long_die.until||"?") + '：' + esc(d.long_die.message||"");
      html += '</div>';
    }

    html += '<div class="vec-grid">';
    for (const b of bs) {
      const s = statusMap[b.status] || { dot: "status-warn", label: b.status, color: "#d2a826" };
      const isRemote = !b.base_url.includes("127.0.0.1") && !b.base_url.includes("localhost");
      html += '<div class="backend-card">';
      html += '<div class="bc-header"><span class="status-dot ' + s.dot + '"></span>';
      html += '<span class="bc-name">' + esc(b.name) + '</span>';
      html += '<span class="bc-tag pri">P' + b.priority + '</span>';
      html += '<span class="bc-tag">' + (isRemote ? "遠端" : "本機") + '</span>';
      html += '</div>';
      html += '<div class="vec-row"><span class="k">狀態</span><span class="v" style="color:' + s.color + '">' + s.label;
      if (b.latency_ms != null && b.status === "online") html += ' (' + b.latency_ms + 'ms)';
      html += '</span></div>';
      html += '<div class="vec-row"><span class="k">URL</span><span class="v" style="font-size:0.8em;word-break:break-all">' + esc(b.base_url) + '</span></div>';
      html += '<div class="vec-row"><span class="k">LLM</span><span class="v">' + esc(b.llm_model) + '</span></div>';
      html += '<div class="vec-row"><span class="k">Embedding</span><span class="v">' + esc(b.embedding_model) + '</span></div>';
      if (b.long_die) {
        html += '<div class="vec-row"><span class="k">DIE 狀態</span><span class="v" style="color:#d2a826">長期停用至 ' + esc(b.long_die.until||"?") + '</span></div>';
      }
      html += '</div>';
    }
    html += '</div></div>';
    _backendsHtml = html;
  } catch (e) {
    _backendsHtml = '<div style="margin-top:16px;color:#8b949e;font-size:0.85em">Ollama 後端狀態載入失敗：' + esc(e.message) + '</div>';
  }
}

function startBackendsPolling() {
  if (_backendsTimer) return;
  fetchBackendsStatus();
  _backendsTimer = setInterval(fetchBackendsStatus, 30000);
}
function stopBackendsPolling() {
  if (_backendsTimer) { clearInterval(_backendsTimer); _backendsTimer = null; }
}

async function renderVector() {
  const el = document.getElementById("vectorContent");
  startBackendsPolling();
  try {
    const r = await fetch("/api/vector-status");
    const d = await r.json();
    if (d.error) {
      el.innerHTML = '<div class="card" style="text-align:center;padding:24px"><span class="status-dot status-offline"></span><strong style="color:#f85149">離線</strong><br><span style="color:#8b949e;font-size:0.85em">' + esc(d.error) + '</span></div>' + _backendsHtml;
      return;
    }
    const svc = d.service || {};
    const idx = d.index || {};
    const cfg = d.config || {};
    const job = d.index_job || {};
    const upH = Math.floor((svc.uptime_seconds||0)/3600);
    const upM = Math.floor(((svc.uptime_seconds||0)%3600)/60);

    let html = '<div style="margin-bottom:12px"><span class="status-dot status-online"></span><strong style="color:#3fb950">線上</strong> <span style="color:#8b949e;font-size:0.85em">(' + esc(svc.embedder||"?") + ' on port ' + (svc.port||3849) + ')</span></div>';
    html += '<div class="vec-grid">';

    // Service info
    html += '<div class="vec-section"><h3>服務</h3>';
    html += '<div class="vec-row"><span class="k">運行時間</span><span class="v">' + upH + 'h ' + upM + 'm</span></div>';
    html += '<div class="vec-row"><span class="k">請求次數</span><span class="v">' + (svc.requests_served||0) + '</span></div>';
    html += '<div class="vec-row"><span class="k">嵌入模型</span><span class="v">' + esc(svc.embedder||"?") + '</span></div>';
    html += '</div>';

    // Index info
    html += '<div class="vec-section"><h3>索引</h3>';
    html += '<div class="vec-row"><span class="k">總區塊數</span><span class="v">' + (idx.total_chunks||0) + '</span></div>';
    html += '<div class="vec-row"><span class="k">獨立原子</span><span class="v">' + (idx.unique_atoms||0) + '</span></div>';
    html += '<div class="vec-row"><span class="k">層級數</span><span class="v">' + (idx.layers||[]).length + '</span></div>';
    html += '</div>';

    // Config
    html += '<div class="vec-section"><h3>設定</h3>';
    html += '<div class="vec-row"><span class="k">後端</span><span class="v">' + esc(cfg.embedding_backend||"?") + '</span></div>';
    html += '<div class="vec-row"><span class="k">模型</span><span class="v">' + esc(cfg.embedding_model||"?") + '</span></div>';
    html += '<div class="vec-row"><span class="k">搜尋上限</span><span class="v">' + (cfg.search_top_k||5) + '</span></div>';
    html += '<div class="vec-row"><span class="k">最低分數</span><span class="v">' + (cfg.search_min_score||0.5) + '</span></div>';
    html += '</div>';

    // Index job
    html += '<div class="vec-section"><h3>最近索引任務</h3>';
    if (job.running) {
      html += '<div style="color:#d2a826"><span class="spinner"></span> 索引建立中...</div>';
    } else if (job.result) {
      const jr = job.result;
      html += '<div class="vec-row"><span class="k">發現原子</span><span class="v">' + (jr.atoms_found||0) + '</span></div>';
      html += '<div class="vec-row"><span class="k">已索引原子</span><span class="v">' + (jr.atoms_indexed||0) + '</span></div>';
      html += '<div class="vec-row"><span class="k">區塊數</span><span class="v">' + (jr.total_chunks||0) + '</span></div>';
      html += '<div class="vec-row"><span class="k">耗時</span><span class="v">' + ((jr.elapsed_seconds||0)).toFixed(1) + 's</span></div>';
      html += '<div class="vec-row"><span class="k">類型</span><span class="v">' + (jr.incremental?"增量":"全量") + '</span></div>';
      if (job.finished_at) {
        const fin = new Date(job.finished_at * 1000);
        html += '<div class="vec-row"><span class="k">完成時間</span><span class="v">' + fin.toLocaleString() + '</span></div>';
      }
    } else {
      html += '<div style="color:#8b949e">無近期索引紀錄</div>';
    }
    html += '</div>';

    html += '</div>';
    html += _backendsHtml;
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="empty">載入向量服務狀態失敗：' + esc(e.message) + '</div>';
  }
}

// ─── Projects Panel ───

async function renderProjects() {
  const el = document.getElementById("projectsContent");
  try {
    const projects = await (await fetch("/api/projects")).json();
    if (!projects.length) {
      el.innerHTML = '<div class="empty">project-registry.json 中無已知專案。</div>';
      return;
    }
    let html = '<p style="color:#8b949e;font-size:0.85em;margin-bottom:12px">來源：project-registry.json（共 ' + projects.length + ' 個專案，動態更新）</p>';
    html += '<table class="proj-table"><thead><tr>';
    html += '<th>Slug / 別名</th><th>根路徑</th><th>記憶層</th><th>Atoms</th><th>Failures</th><th>Episodic</th><th>最後活動</th><th>操作</th>';
    html += '</tr></thead><tbody>';
    for (const p of projects) {
      const memBadge = p.has_memory
        ? '<span class="proj-badge-mem">✓ .claude/memory</span>'
        : '<span class="proj-badge-nomem">未初始化</span>';
      const aliases = (p.aliases || []).length
        ? '<div class="proj-alias">' + p.aliases.map(a => esc(a)).join(', ') + '</div>'
        : '';
      const filterBtn = p.has_memory
        ? '<button class="proj-filter-btn" onclick="filterAtomsByProject(&#39;project:' + p.slug + '&#39;)">查看 Atoms</button>'
        : '';
      html += '<tr>';
      html += '<td><strong>' + esc(p.slug) + '</strong>' + aliases + '</td>';
      html += '<td><span class="proj-root">' + esc(p.root) + '</span></td>';
      html += '<td>' + memBadge + '</td>';
      html += '<td>' + (p.atom_count || 0) + '</td>';
      html += '<td>' + (p.failure_count || 0) + '</td>';
      html += '<td>' + (p.episodic_count || 0) + '</td>';
      html += '<td>' + esc(p.last_seen || '-') + '</td>';
      html += '<td>' + filterBtn + '</td>';
      html += '</tr>';
    }
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="empty">載入專案清單失敗：' + esc(e.message) + '</div>';
  }
}

function filterAtomsByProject(layerPrefix) {
  // Switch to atoms tab and filter by project layer
  currentTab = "atoms";
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelector('[data-tab="atoms"]').classList.add("active");
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.getElementById("panelAtoms").classList.add("active");
  renderAtoms().then(() => {
    const filterInput = document.getElementById("atomFilter");
    if (filterInput) {
      filterInput.value = layerPrefix;
      filterInput.dispatchEvent(new Event("input"));
    }
  });
}

// ─── Atoms Browser ───

let atomsData = [];
const expandedAtoms = new Set();  // track expanded detail rows across refreshes

async function renderAtoms() {
  const el = document.getElementById("atomsContent");
  const prevFilter = document.getElementById("atomFilter");
  const savedFilter = prevFilter ? prevFilter.value : "";
  try {
    atomsData = await (await fetch("/api/atoms")).json();
    if (!atomsData.length) {
      el.innerHTML = '<div class="empty">無原子記憶。</div>';
      return;
    }
    renderAtomsTable(atomsData);
    if (savedFilter) {
      const fi = document.getElementById("atomFilter");
      if (fi) { fi.value = savedFilter; filterAtoms(savedFilter); }
    } else if (atomSortKey) {
      reapplySort();
    }
  } catch (e) {
    el.innerHTML = '<div class="empty">載入原子記憶失敗：' + esc(e.message) + '</div>';
  }
}

function renderAtomsTable(atoms) {
  const el = document.getElementById("atomsContent");
  const confCounts = {};
  for (const a of atoms) { confCounts[a.confidence] = (confCounts[a.confidence]||0) + 1; }

  let html = '<div class="atom-stats">';
  html += '<div class="stat"><div class="stat-value">' + atoms.length + '</div><div class="stat-label">原子總數</div></div>';
  if (confCounts["[固]"]) html += '<div class="stat"><div class="stat-value" style="color:#3fb950">' + confCounts["[固]"] + '</div><div class="stat-label">[固] 確定</div></div>';
  if (confCounts["[觀]"]) html += '<div class="stat"><div class="stat-value" style="color:#d2a826">' + confCounts["[觀]"] + '</div><div class="stat-label">[觀] 觀察</div></div>';
  if (confCounts["[臨]"]) html += '<div class="stat"><div class="stat-value" style="color:#f0883e">' + confCounts["[臨]"] + '</div><div class="stat-label">[臨] 臨時</div></div>';
  html += '</div>';

  // 收集所有 scope 給下拉選單
  const scopeSet = new Set();
  for (const a of atoms) { if (a.scope) scopeSet.add(a.scope); }
  const scopes = [...scopeSet].sort();

  html += '<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">';
  html += '<input id="atomFilter" class="atom-filter" type="text" placeholder="搜尋原子名稱、觸發詞..." oninput="applyAtomFilters()" style="margin-bottom:0">';
  html += '<select id="atomScopeFilter" class="atom-filter" style="width:auto;margin-bottom:0" onchange="applyAtomFilters()">';
  html += '<option value="">所有 scope</option>';
  for (const s of scopes) {
    html += '<option value="' + esc(s) + '">' + esc(s) + '</option>';
  }
  html += '</select>';
  html += '</div>';

  html += '<table class="atom-table" id="atomTable">';
  html += '<thead><tr>' +
    '<th onclick="sortAtoms(\\'name\\')">名稱 &#8597;</th>' +
    '<th onclick="sortAtoms(\\'scope\\')">Scope &#8597;</th>' +
    '<th onclick="sortAtoms(\\'layer\\')">層級 &#8597;</th>' +
    '<th onclick="sortAtoms(\\'confidence\\')">信心 &#8597;</th>' +
    '<th onclick="sortAtoms(\\'confirmations\\')">確認數 &#8597;</th>' +
    '<th onclick="sortAtoms(\\'readhits\\')">讀取數 &#8597;</th>' +
    '<th onclick="sortAtoms(\\'last_used\\')">最後使用 &#8597;</th>' +
    '<th onclick="sortAtoms(\\'knowledge_count\\')">知識數 &#8597;</th>' +
    '<th>行數</th>' +
  '</tr></thead>';
  html += '<tbody id="atomTableBody">';
  html += buildAtomRows(atoms);
  html += '</tbody></table>';
  el.innerHTML = html;
}

function buildAtomRows(atoms) {
  let html = '';
  for (const a of atoms) {
    const confClass = a.confidence === "[固]" ? "conf-fixed" : a.confidence === "[觀]" ? "conf-observe" : "conf-temp";
    const daysAgo = a.days_since_used != null ? a.days_since_used + ' 天前' : '-';
    const audienceTitle = (a.audience||[]).join(", ");
    const authorBadge = a.author ? ' <span style="color:#8b949e;font-size:0.78em">@' + esc(a.author) + '</span>' : '';
    html += '<tr data-name="' + esc(a.name) + '">' +
      '<td><span class="atom-name" onclick="toggleAtomDetail(\\'' + esc(a.name) + '\\')">' + esc(a.name) + '</span>' + authorBadge + '</td>' +
      '<td><span class="atom-layer" title="audience: ' + esc(audienceTitle||"-") + '">' + esc(a.scope||"-") + '</span></td>' +
      '<td><span class="atom-layer">' + esc(a.layer) + '</span></td>' +
      '<td><span class="atom-conf ' + confClass + '">' + esc(a.confidence||"-") + '</span></td>' +
      '<td>' + (a.confirmations||0) + '</td>' +
      '<td>' + (a.readhits||0) + '</td>' +
      '<td title="' + esc(a.last_used||"") + '">' + daysAgo + '</td>' +
      '<td>' + (a.knowledge_count||'-') + '</td>' +
      '<td>' + (a.line_count||'-') + '</td>' +
    '</tr>';
    const detailVis = expandedAtoms.has(a.name) ? '' : 'none';
    html += '<tr id="detail-' + esc(a.name) + '" style="display:' + detailVis + '"><td colspan="9"><div class="atom-detail">' + esc(a.content||"") + '</div></td></tr>';
  }
  return html;
}

function toggleAtomDetail(name) {
  const row = document.getElementById("detail-" + name);
  if (!row) return;
  if (row.style.display === "none") {
    row.style.display = "";
    expandedAtoms.add(name);
  } else {
    row.style.display = "none";
    expandedAtoms.delete(name);
  }
}

let atomSortKey = "last_used";
let atomSortAsc = false;

function applySortToBody(data) {
  const sorted = [...data].sort((a, b) => {
    let va = a[atomSortKey] ?? "", vb = b[atomSortKey] ?? "";
    if (typeof va === "number" && typeof vb === "number") return atomSortAsc ? va - vb : vb - va;
    va = String(va); vb = String(vb);
    return atomSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
  });
  document.getElementById("atomTableBody").innerHTML = buildAtomRows(sorted);
}

function reapplySort() { applySortToBody(atomsData); }

function sortAtoms(key) {
  if (atomSortKey === key) atomSortAsc = !atomSortAsc;
  else { atomSortKey = key; atomSortAsc = key === "name"; }
  applySortToBody(atomsData);
}

function filterAtoms(query) {
  // 為了向後相容（既有呼叫點用 filterAtoms(saved)），轉呼叫 applyAtomFilters
  const fi = document.getElementById("atomFilter");
  if (fi && typeof query === "string") fi.value = query;
  applyAtomFilters();
}

function applyAtomFilters() {
  const fi = document.getElementById("atomFilter");
  const sf = document.getElementById("atomScopeFilter");
  const q = (fi ? fi.value : "").toLowerCase();
  const scope = sf ? sf.value : "";
  const filtered = atomsData.filter(a => {
    if (scope && (a.scope||"") !== scope) return false;
    if (!q) return true;
    if (a.name.toLowerCase().includes(q)) return true;
    if ((a.triggers||[]).some(t => t.toLowerCase().includes(q))) return true;
    if ((a.related||[]).some(r => r.toLowerCase().includes(q))) return true;
    if ((a.layer||"").toLowerCase().includes(q)) return true;
    if ((a.scope||"").toLowerCase().includes(q)) return true;
    if ((a.author||"").toLowerCase().includes(q)) return true;
    return false;
  });
  applySortToBody(filtered);
}

// ─── Env Tab (Skills + MCP Servers) ───

async function renderEnv() {
  const el = document.getElementById("envContent");
  try {
    const [skills, mcps] = await Promise.all([
      fetch("/api/skills").then(r => r.json()),
      fetch("/api/mcp-servers").then(r => r.json()),
    ]);
    el.innerHTML = renderSkillsSection(skills) + renderMcpSection(mcps);
  } catch (e) {
    el.innerHTML = '<div class="empty">載入環境資訊失敗：' + esc(e.message) + '</div>';
  }
}

function renderSkillsSection(skills) {
  let html = '<div class="section-title">Slash Commands / Skills（' + skills.length + '）</div>';
  if (!skills.length) return html + '<div class="empty">無 commands。</div>';

  // 依分類分組
  const byCat = {};
  for (const s of skills) {
    const cat = s.category || "其他";
    if (!byCat[cat]) byCat[cat] = [];
    byCat[cat].push(s);
  }
  const cats = Object.keys(byCat).sort();

  for (const cat of cats) {
    html += '<details open style="margin-bottom:12px"><summary style="color:#58a6ff;cursor:pointer;padding:6px 0">' + esc(cat) + ' （' + byCat[cat].length + '）</summary>';
    html += '<table class="atom-table">';
    html += '<thead><tr><th>指令</th><th>說明</th><th>來源</th></tr></thead><tbody>';
    for (const s of byCat[cat]) {
      const sourceLabel = s.source === "global" ?
        '<span class="atom-layer">global</span>' :
        '<span class="atom-layer" style="background:#1f6feb33;color:#58a6ff">' + esc(s.source) + '</span>';
      html += '<tr>' +
        '<td><span class="atom-name" onclick="toggleSkillDetail(\\'' + esc(s.name) + '\\')">' + esc(s.command) + '</span></td>' +
        '<td style="color:#c9d1d9">' + esc(s.description||"-") + '</td>' +
        '<td>' + sourceLabel + '</td>' +
      '</tr>';
      html += '<tr id="skill-detail-' + esc(s.name) + '" style="display:none"><td colspan="3"><div class="atom-detail">' + esc(s.content||"") + '</div></td></tr>';
    }
    html += '</tbody></table></details>';
  }
  return html;
}

function toggleSkillDetail(name) {
  const row = document.getElementById("skill-detail-" + name);
  if (!row) return;
  row.style.display = row.style.display === "none" ? "" : "none";
}

function renderMcpSection(mcps) {
  let html = '<div class="section-title" style="margin-top:24px">MCP Servers（' + mcps.length + '）</div>';
  if (!mcps.length) return html + '<div class="empty">無 MCP servers。</div>';

  // 依來源分組
  const bySource = {};
  for (const m of mcps) {
    if (!bySource[m.source]) bySource[m.source] = [];
    bySource[m.source].push(m);
  }
  const sources = Object.keys(bySource).sort();

  for (const src of sources) {
    html += '<details open style="margin-bottom:12px"><summary style="color:#58a6ff;cursor:pointer;padding:6px 0">' + esc(src) + ' （' + bySource[src].length + '）</summary>';
    html += '<table class="atom-table">';
    html += '<thead><tr><th>名稱</th><th>類型</th><th>狀態</th><th>command / url</th><th>env keys</th></tr></thead><tbody>';
    for (const m of bySource[src]) {
      const statusBadge = m.enabled ?
        '<span class="status-dot status-online"></span>啟用' :
        '<span class="status-dot status-disabled"></span>停用';
      const cmdDisplay = m.url ? esc(m.url) :
        (esc(m.command || "-") + (m.args.length ? ' ' + esc(m.args.slice(-1)[0]) : ''));
      html += '<tr>' +
        '<td><strong style="color:#e6edf3">' + esc(m.name) + '</strong></td>' +
        '<td><span class="atom-layer">' + esc(m.type) + '</span></td>' +
        '<td>' + statusBadge + '</td>' +
        '<td style="font-family:monospace;font-size:0.78em;color:#8b949e;word-break:break-all">' + cmdDisplay + '</td>' +
        '<td style="font-size:0.78em;color:#8b949e">' + (m.env_keys.length ? esc(m.env_keys.join(", ")) : '-') + '</td>' +
      '</tr>';
    }
    html += '</tbody></table>';
    html += '<div style="font-size:0.75em;color:#484f58;margin-top:4px">config: ' + esc(bySource[src][0].config_file) + '</div>';
    html += '</details>';
  }
  return html;
}

// ─── Auto Refresh ───

function startAutoRefresh() {
  clearInterval(refreshTimer);
  if (document.getElementById("autoRefresh").checked) {
    refreshTimer = setInterval(refreshCurrentTab, 5000);
  }
}

document.getElementById("autoRefresh").addEventListener("change", startAutoRefresh);
renderSessions();
startAutoRefresh();
</script>
</body>
</html>`;

const httpServer = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${DASHBOARD_PORT}`);
  const pathname = url.pathname;

  // CORS for local dev
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    return res.end();
  }

  // Dashboard
  if (pathname === "/" && req.method === "GET") {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return res.end(DASHBOARD_HTML);
  }

  // API: list sessions
  if (pathname === "/api/sessions" && req.method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify(listAllSessions()));
  }

  // API: get/delete single session
  const sessionMatch = pathname.match(/^\/api\/sessions\/([^/]+)$/);
  if (sessionMatch) {
    const sid = resolveSessionId(sessionMatch[1]) || sessionMatch[1];
    if (req.method === "GET") {
      const state = readState(sid);
      if (!state) {
        res.writeHead(404, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({ error: "not found" }));
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify(state));
    }
    if (req.method === "DELETE") {
      const ok = deleteState(sid);
      res.writeHead(ok ? 200 : 404, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ ok, deleted: `state-${sid}.json` }));
    }
  }

  // API: send signal
  const signalMatch = pathname.match(/^\/api\/sessions\/([^/]+)\/signal$/);
  if (signalMatch && req.method === "POST") {
    const sid = resolveSessionId(signalMatch[1]) || signalMatch[1];
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      try {
        const { signal } = JSON.parse(body);
        const state = readState(sid);
        if (!state) {
          res.writeHead(404, { "Content-Type": "application/json" });
          return res.end(JSON.stringify({ error: "not found" }));
        }
        switch (signal) {
          case "sync_started":
            state.phase = "syncing";
            break;
          case "sync_completed":
            state.phase = "done";
            state.sync_pending = false;
            state.knowledge_queue = [];
            state.modified_files = [];
            state.ended_at = new Date().toISOString();
            break;
          case "reset":
            state.phase = "working";
            state.sync_pending = false;
            state.stop_blocked_count = 0;
            state.remind_count = 0;
            state.muted = false;
            break;
          case "mute":
            state.muted = true;
            break;
        }
        writeState(sid, state);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, state }));
      } catch {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "invalid body" }));
      }
    });
    return;
  }

  // v2.1 API routes
  if (pathname === "/api/episodic" && req.method === "GET") {
    return apiEpisodic(req, res);
  }
  if (pathname === "/api/health" && req.method === "GET") {
    const force = url.searchParams.get("force") === "1";
    return apiHealth(req, res, force);
  }
  if (pathname === "/api/test-run" && req.method === "POST") {
    return apiTestRunStart(req, res);
  }
  const testJobMatch = pathname.match(/^\/api\/test-run\/([^/]+)$/);
  if (testJobMatch && req.method === "GET") {
    return apiTestRunStatus(req, res, testJobMatch[1]);
  }
  if (pathname === "/api/vector-status" && req.method === "GET") {
    return apiVectorStatus(req, res);
  }
  if (pathname === "/api/ollama-backends-status" && req.method === "GET") {
    return apiOllamaBackendsStatus(req, res);
  }
  if (pathname === "/api/knowledge-queue" && req.method === "GET") {
    return apiKnowledgeQueue(req, res);
  }
  if (pathname === "/api/atoms" && req.method === "GET") {
    return apiAtoms(req, res);
  }
  if (pathname === "/api/projects" && req.method === "GET") {
    return apiProjects(req, res);
  }
  if (pathname === "/api/skills" && req.method === "GET") {
    return apiSkills(req, res);
  }
  if (pathname === "/api/mcp-servers" && req.method === "GET") {
    return apiMcpServers(req, res);
  }

  // ── V3: Hot Cache status ──
  if (pathname === "/api/hot-cache" && req.method === "GET") {
    const cachePath = path.join(WORKFLOW_DIR, "hot_cache.json");
    try {
      const raw = fs.readFileSync(cachePath, "utf-8");
      const data = JSON.parse(raw);
      data.age_seconds = Math.round(Date.now() / 1000 - (data.timestamp || 0));
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify(data));
    } catch {
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ empty: true }));
    }
  }

  // ── V3: Vector Ready indicator ──
  if (pathname === "/api/vector-ready" && req.method === "GET") {
    const flagPath = path.join(WORKFLOW_DIR, "vector_ready.flag");
    const ready = fs.existsSync(flagPath);
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ ready }));
  }

  res.writeHead(404);
  res.end("Not found");
});

// ─── Dashboard port binding with recovery heartbeat ─────────────────────────
// When multiple Claude Code instances exist, only one binds port 3848.
// If that instance dies, a surviving instance must reclaim the port.
const HEARTBEAT_INTERVAL_MS = 15000;
let dashboardHeartbeat = null;

function tryBindDashboard() {
  if (httpServer.listening) return;

  const probe = http.request(
    { hostname: "127.0.0.1", port: DASHBOARD_PORT, path: "/", method: "HEAD", timeout: 500 },
    () => {
      // Port occupied by another instance — keep heartbeat running
      probe.destroy();
    }
  );

  probe.on("error", () => {
    // Connection refused → port is free, attempt to bind
    if (httpServer.listening) return;
    httpServer.listen(DASHBOARD_PORT, "127.0.0.1", () => {
      process.stderr.write(`[workflow-guardian] Dashboard: http://127.0.0.1:${DASHBOARD_PORT}\n`);
      if (dashboardHeartbeat) {
        clearInterval(dashboardHeartbeat);
        dashboardHeartbeat = null;
      }
    });
  });

  probe.on("timeout", () => probe.destroy());
  probe.end();
}

httpServer.on("error", (err) => {
  if (err.code === "EADDRINUSE") {
    process.stderr.write(`[workflow-guardian] Dashboard port ${DASHBOARD_PORT} taken (race), will retry.\n`);
    if (!dashboardHeartbeat) {
      dashboardHeartbeat = setInterval(tryBindDashboard, HEARTBEAT_INTERVAL_MS);
      dashboardHeartbeat.unref();
    }
  } else {
    process.stderr.write(`[workflow-guardian] Dashboard failed: ${err.message}\n`);
  }
});

tryBindDashboard();
setImmediate(() => {
  if (!httpServer.listening && !dashboardHeartbeat) {
    dashboardHeartbeat = setInterval(tryBindDashboard, HEARTBEAT_INTERVAL_MS);
    dashboardHeartbeat.unref();
  }
});

// Keep MCP alive
process.stdin.resume();
