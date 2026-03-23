/**
 * Claude Code Inbox Checker (PreToolUse hook)
 * - 輸出 hookSpecificOutput JSON 格式，讓 additionalContext 注入 AI context
 * - 無訊息時靜默退出（exit 0，不影響工具調用）
 */
const fs = require("fs");
const path = require("path");

const INBOX = path.join(__dirname, "..", "inbox.jsonl");

try {
  if (!fs.existsSync(INBOX)) process.exit(0);

  const content = fs.readFileSync(INBOX, "utf-8").trim();
  if (!content) process.exit(0);

  const lines = content.split("\n").filter(Boolean);
  const messages = [];

  for (const line of lines) {
    try {
      const msg = JSON.parse(line);
      messages.push(msg);
    } catch {
      messages.push({ from: "unknown", text: line, ts: null });
    }
  }

  if (messages.length === 0) process.exit(0);

  // Build readable context string
  const parts = [`[INBOX] ${messages.length} new message(s):`];
  for (const msg of messages) {
    const time = msg.ts
      ? new Date(msg.ts).toLocaleTimeString("zh-TW", { hour12: false })
      : "?";
    parts.push(`  [${time}] ${msg.from || "?"}: ${msg.text}`);
  }
  const contextText = parts.join("\n");

  // Output hookSpecificOutput JSON so Claude Code injects into AI context
  const output = {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      additionalContext: contextText,
    },
  };
  console.log(JSON.stringify(output));

  // Update last-comm timestamp (for watcher debounce)
  const TS_FILE = path.join(__dirname, "..", ".last-comm-ts");
  fs.writeFileSync(TS_FILE, String(Date.now()), "utf-8");

  // Clear inbox after successful output
  fs.writeFileSync(INBOX, "", "utf-8");
} catch (e) {
  // Never block tool use on error
  process.exit(0);
}
