/**
 * Claude Code Inbox Watcher (background polling)
 * - 每 INTERVAL ms 輪詢 inbox.jsonl
 * - 發現訊息後輸出並 exit（Claude Code 會收到 background task 通知）
 * - Debounce: 若最近一次通訊 < INTERVAL ms，遞延本次檢查
 * - MAX_RUNTIME 後自動結束（避免殭屍程序）
 *
 * 用法: node inbox-watcher.js   (由 Claude Code run_in_background 啟動)
 */
const fs = require("fs");
const path = require("path");

const INBOX = path.join(__dirname, "..", "inbox.jsonl");
const TS_FILE = path.join(__dirname, "..", ".last-comm-ts");
const INTERVAL = parseInt(process.env.INBOX_INTERVAL || "5000", 10);
const MAX_RUNTIME = parseInt(process.env.INBOX_MAX_RUNTIME || "300000", 10);
const startTime = Date.now();

function checkInbox() {
  // Guard: 超過最大運行時間就靜默退出
  if (Date.now() - startTime > MAX_RUNTIME) {
    console.log("[INBOX-WATCHER] max runtime reached, exiting");
    process.exit(0);
  }

  // Debounce: 最近有通訊就遞延
  try {
    const lastComm = parseInt(fs.readFileSync(TS_FILE, "utf-8").trim(), 10);
    if (Date.now() - lastComm < INTERVAL) {
      setTimeout(checkInbox, INTERVAL);
      return;
    }
  } catch {
    // 無時戳檔 = 繼續檢查
  }

  // 讀取 inbox
  try {
    if (!fs.existsSync(INBOX)) {
      setTimeout(checkInbox, INTERVAL);
      return;
    }

    const content = fs.readFileSync(INBOX, "utf-8").trim();
    if (!content) {
      setTimeout(checkInbox, INTERVAL);
      return;
    }

    const lines = content.split("\n").filter(Boolean);
    const messages = lines
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return { from: "unknown", text: l, ts: null };
        }
      })
      .filter(Boolean);

    if (messages.length === 0) {
      setTimeout(checkInbox, INTERVAL);
      return;
    }

    // 找到訊息！更新時戳、清空 inbox、輸出、退出
    fs.writeFileSync(TS_FILE, String(Date.now()), "utf-8");
    fs.writeFileSync(INBOX, "", "utf-8");

    const formatted = messages
      .map((m) => {
        const time = m.ts
          ? new Date(m.ts).toLocaleTimeString("zh-TW", { hour12: false })
          : "??:??:??";
        return `  [${time}] ${m.from || "unknown"}: ${m.text || m.message || ""}`;
      })
      .join("\n");

    console.log(
      `[INBOX-WATCHER] ${messages.length} new message(s):\n${formatted}`
    );
    process.exit(0);
  } catch {
    setTimeout(checkInbox, INTERVAL);
  }
}

checkInbox();
