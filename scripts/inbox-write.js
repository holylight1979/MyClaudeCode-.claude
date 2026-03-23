/**
 * Claude Code Inbox Writer
 * - 外部來源用：寫入訊息到 inbox.jsonl
 * - Usage: node inbox-write.js <from> <message>
 * - Example: node inbox-write.js "OpenClaw" "Hello from OpenClaw!"
 */
const fs = require("fs");
const path = require("path");

const INBOX = path.join(__dirname, "..", "inbox.jsonl");

const from = process.argv[2];
const text = process.argv.slice(3).join(" ");

if (!from || !text) {
  console.error("Usage: node inbox-write.js <from> <message>");
  process.exit(1);
}

const entry =
  JSON.stringify({ from, text, ts: new Date().toISOString() }) + "\n";
fs.appendFileSync(INBOX, entry, "utf-8");
console.log(`Queued: [${from}] ${text}`);
