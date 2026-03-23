/**
 * Send message to OpenClaw via Bridge
 * Usage: node send-to-openclaw.js <message>
 * Claude Code 用這個腳本向 OpenClaw 發送訊息
 */
const http = require("http");

const BRIDGE_HOST = "127.0.0.1";
const BRIDGE_PORT = 3847;
const BRIDGE_TOKEN = "openclaw-bridge-default-token";

const message = process.argv.slice(2).join(" ");
if (!message) {
  console.error("Usage: node send-to-openclaw.js <message>");
  process.exit(1);
}

const data = JSON.stringify({
  from: "Claude Code",
  message: message,
});

const req = http.request(
  {
    hostname: BRIDGE_HOST,
    port: BRIDGE_PORT,
    path: "/message/to-openclaw",
    method: "POST",
    headers: {
      Authorization: `Bearer ${BRIDGE_TOKEN}`,
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(data),
    },
  },
  (res) => {
    let body = "";
    res.on("data", (chunk) => (body += chunk));
    res.on("end", () => {
      try {
        const result = JSON.parse(body);
        if (result.success) {
          console.log(`Sent to OpenClaw: "${message}"`);
        } else {
          console.error("Failed:", result.error);
          process.exit(1);
        }
      } catch {
        console.error("Unexpected response:", body);
        process.exit(1);
      }
    });
  }
);

req.on("error", (e) => {
  console.error("Bridge unreachable:", e.message);
  process.exit(1);
});

req.write(data);
req.end();
