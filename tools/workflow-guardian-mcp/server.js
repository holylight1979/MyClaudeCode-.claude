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

// ─── Crash protection & logging ─────────────────────────────────────────────

const CLAUDE_DIR = path.join(require("os").homedir(), ".claude");
const WORKFLOW_DIR = path.join(CLAUDE_DIR, "workflow");
const CRASH_LOG = path.join(WORKFLOW_DIR, "guardian-crash.log");

function crashLog(label, err) {
  const ts = new Date().toISOString();
  const msg = `[${ts}] ${label}: ${err?.stack || err}\n`;
  try { fs.appendFileSync(CRASH_LOG, msg); } catch {}
  process.stderr.write(`[workflow-guardian] ${label}: ${err?.message || err}\n`);
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
const CONFIG_PATH = path.join(WORKFLOW_DIR, "config.json");
const DASHBOARD_PORT = loadConfig().dashboard_port || 3848;

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
  const DONE_TTL_MS = 60 * 1000; // 1 minute: auto-cleanup finished sessions
  return listStatePaths().map((p) => {
    try {
      const state = JSON.parse(fs.readFileSync(p, "utf-8"));
      const sid = state.session?.id || path.basename(p).replace("state-", "").replace(".json", "");

      // Auto-cleanup: delete state files for sessions done > 1 min ago
      if (state.ended_at) {
        const endedAge = Date.now() - new Date(state.ended_at).getTime();
        if (endedAge > DONE_TTL_MS) {
          try { fs.unlinkSync(p); } catch {}
          return null;
        }
      }

      const startedAt = state.session?.started_at || "";
      const ageMs = startedAt ? Date.now() - new Date(startedAt).getTime() : 0;
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
        serverInfo: { name: "workflow-guardian", version: "1.0.0" },
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
    default:
      sendError(id, -32601, `Unknown tool: ${toolName}`);
  }
}

function toolWorkflowStatus(id, args) {
  if (args.session_id) {
    const state = readState(args.session_id);
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
  const state = readState(session_id);
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

  writeState(session_id, state);
  return sendToolResult(id, `Signal '${signal}' applied. Phase: ${state.phase}`);
}

function toolMemoryQueueAdd(id, args) {
  const { session_id, content, classification, trigger_context } = args;
  const state = readState(session_id);
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
  writeState(session_id, state);

  return sendToolResult(
    id,
    `Added to knowledge queue (${state.knowledge_queue.length} items): ${classification} ${content.slice(0, 60)}`
  );
}

function toolMemoryQueueFlush(id, args) {
  const { session_id } = args;
  const state = readState(session_id);
  if (!state) {
    return sendToolResult(id, `No state found for session ${session_id}`, true);
  }

  const count = (state.knowledge_queue || []).length;
  state.knowledge_queue = [];
  writeState(session_id, state);

  return sendToolResult(id, `Flushed ${count} knowledge queue items.`);
}

function sendToolResult(id, text, isError = false) {
  sendResponse(id, {
    content: [{ type: "text", text }],
    ...(isError && { isError: true }),
  });
}

// ─── HTTP Dashboard ─────────────────────────────────────────────────────────

const DASHBOARD_HTML = `<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Workflow Guardian Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 4px; font-size: 1.4em; }
  .subtitle { color: #8b949e; font-size: 0.85em; margin-bottom: 20px; }
  .stats { display: flex; gap: 16px; margin-bottom: 20px; }
  .stat { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px 16px; }
  .stat-value { font-size: 1.6em; font-weight: bold; color: #58a6ff; }
  .stat-label { font-size: 0.8em; color: #8b949e; }
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
  .btn { padding: 4px 12px; border-radius: 4px; border: 1px solid #30363d; background: #21262d; color: #c9d1d9; cursor: pointer; font-size: 0.8em; }
  .btn:hover { background: #30363d; }
  .btn-danger { border-color: #f8514966; color: #f85149; }
  .btn-danger:hover { background: #f8514922; }
  .empty { text-align: center; color: #8b949e; padding: 40px; }
  .auto-refresh { float: right; font-size: 0.8em; color: #8b949e; }
  .auto-refresh label { cursor: pointer; }
</style>
</head>
<body>
<div style="display:flex;justify-content:space-between;align-items:baseline;">
  <div><h1>Workflow Guardian</h1><p class="subtitle">Session workflow monitor</p></div>
  <div class="auto-refresh"><label><input type="checkbox" id="autoRefresh" checked> Auto-refresh (5s)</label></div>
</div>

<div class="stats" id="statsBar"></div>
<div class="sessions" id="sessionList"></div>

<script>
let refreshTimer;

async function fetchSessions() {
  try {
    const res = await fetch("/api/sessions");
    return await res.json();
  } catch { return []; }
}

async function sendSignal(sid, signal) {
  await fetch("/api/sessions/" + sid + "/signal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signal })
  });
  render();
}

async function deleteSession(sid) {
  if (!confirm("Delete state for session " + sid.slice(0,8) + "?")) return;
  await fetch("/api/sessions/" + sid, { method: "DELETE" });
  render();
}

function badgeClass(phase) {
  return "badge badge-" + (phase || "init");
}

function classificationBadge(c) {
  if (c === "[固]") return '<span class="kq-badge kq-badge-fixed">[固]</span>';
  if (c === "[觀]") return '<span class="kq-badge kq-badge-observe">[觀]</span>';
  return '<span class="kq-badge kq-badge-temp">[臨]</span>';
}

async function render() {
  const sessions = await fetchSessions();
  const active = sessions.filter(s => !s.ended);
  const pending = sessions.filter(s => s.sync_pending && !s.ended);

  document.getElementById("statsBar").innerHTML =
    '<div class="stat"><div class="stat-value">' + sessions.length + '</div><div class="stat-label">Total Sessions</div></div>' +
    '<div class="stat"><div class="stat-value">' + active.length + '</div><div class="stat-label">Active</div></div>' +
    '<div class="stat"><div class="stat-value">' + pending.length + '</div><div class="stat-label">Pending Sync</div></div>';

  if (sessions.length === 0) {
    document.getElementById("sessionList").innerHTML = '<div class="empty">No workflow sessions found.</div>';
    return;
  }

  // Fetch full state for each
  const cards = await Promise.all(sessions.map(async (s) => {
    let detail;
    try {
      const res = await fetch("/api/sessions/" + s.session_id);
      detail = await res.json();
    } catch { detail = {}; }

    const files = (detail.modified_files || []);
    const kq = (detail.knowledge_queue || []);
    const uniqueFiles = [...new Set(files.map(f => f.path))];

    let fileHtml = "";
    if (uniqueFiles.length > 0) {
      fileHtml = '<details><summary>Modified files (' + uniqueFiles.length + ')</summary><ul class="file-list">' +
        uniqueFiles.map(f => { const name = f.replace(/\\\\/g,"/").split("/").pop(); return "<li>" + name + " <span style='color:#484f58'>" + f + "</span></li>"; }).join("") +
        "</ul></details>";
    }

    let kqHtml = "";
    if (kq.length > 0) {
      kqHtml = '<details><summary>Knowledge queue (' + kq.length + ')</summary><ul class="kq-list">' +
        kq.map(q => "<li>" + classificationBadge(q.classification) + " " + (q.content || "").slice(0,80) + "</li>").join("") +
        "</ul></details>";
    }

    return '<div class="card">' +
      '<div class="card-header">' +
        '<span class="card-name">' + (s.name || "?") + '</span>' +
        '<span class="' + badgeClass(s.phase) + '">' + s.phase + (s.muted ? ' (muted)' : '') + '</span>' +
      '</div>' +
      '<div class="card-meta"><span class="card-id">' + s.session_id.slice(0,8) + '</span> &middot; ' + (s.project || "?") + ' &middot; ' + s.age_minutes + ' min' + (s.ended ? ' &middot; ended' : '') + '</div>' +
      '<div class="card-stats">' +
        '<span>Files: <strong>' + s.modified_files_count + '</strong></span>' +
        '<span>Knowledge: <strong>' + s.knowledge_queue_count + '</strong></span>' +
        '<span>Sync: <strong>' + (s.sync_pending ? "pending" : "ok") + '</strong></span>' +
      '</div>' +
      (fileHtml || kqHtml ? '<div class="details">' + fileHtml + kqHtml + '</div>' : '') +
      '<div class="actions">' +
        '<button class="btn" onclick="sendSignal(\\''+s.session_id+'\\',\\'sync_completed\\')">Mark Synced</button>' +
        '<button class="btn" onclick="sendSignal(\\''+s.session_id+'\\',\\'reset\\')">Reset</button>' +
        (s.muted ? '' : '<button class="btn" onclick="sendSignal(\\''+s.session_id+'\\',\\'mute\\')">Mute</button>') +
        '<button class="btn btn-danger" onclick="deleteSession(\\''+s.session_id+'\\')">Delete</button>' +
      '</div>' +
    '</div>';
  }));

  document.getElementById("sessionList").innerHTML = cards.join("");
}

function startAutoRefresh() {
  clearInterval(refreshTimer);
  if (document.getElementById("autoRefresh").checked) {
    refreshTimer = setInterval(render, 5000);
  }
}

document.getElementById("autoRefresh").addEventListener("change", startAutoRefresh);
render();
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
    const sid = sessionMatch[1];
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
    const sid = signalMatch[1];
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
