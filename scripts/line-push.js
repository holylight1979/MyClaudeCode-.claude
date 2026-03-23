/**
 * Direct LINE Push API — bypass OpenClaw, send message directly to LINE user
 * Usage: node line-push.js "your message here"
 *
 * Reads channel access token from openclaw.json config.
 * Default recipient: holylight (LINE userId from identityLinks)
 */
const https = require("https");
const fs = require("fs");
const path = require("path");

const CONFIG_PATH = process.env.OPENCLAW_CONFIG
  || path.join(process.env.OPENCLAW_STATE_DIR || "E:\\.openclaw", "openclaw.json");

let channelAccessToken, defaultTo;
try {
  const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"));
  channelAccessToken = cfg.channels?.line?.channelAccessToken;
  // Get holylight's LINE userId from identityLinks
  const lineLinks = cfg.session?.identityLinks?.holylight?.filter(l => l.startsWith("line:")) || [];
  defaultTo = lineLinks.length > 0 ? lineLinks[0].replace("line:", "") : null;
} catch (e) {
  console.error(JSON.stringify({ status: "error", error: "Failed to read config: " + e.message }));
  process.exit(1);
}

if (!channelAccessToken) {
  console.error(JSON.stringify({ status: "error", error: "No LINE channelAccessToken in config" }));
  process.exit(1);
}

const to = process.env.LINE_TO || defaultTo;
if (!to) {
  console.error(JSON.stringify({ status: "error", error: "No LINE recipient. Set LINE_TO env var." }));
  process.exit(1);
}

const message = process.argv.slice(2).join(" ");
if (!message) {
  console.error("Usage: node line-push.js <message>");
  process.exit(1);
}

const body = JSON.stringify({
  to,
  messages: [{ type: "text", text: message }]
});

const req = https.request({
  hostname: "api.line.me",
  path: "/v2/bot/message/push",
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${channelAccessToken}`,
    "Content-Length": Buffer.byteLength(body)
  }
}, (res) => {
  let data = "";
  res.on("data", (chunk) => data += chunk);
  res.on("end", () => {
    if (res.statusCode === 200) {
      console.log(JSON.stringify({ status: "delivered", to, messageLength: message.length }));
    } else {
      console.error(JSON.stringify({ status: "error", httpStatus: res.statusCode, body: data }));
      process.exit(1);
    }
  });
});

req.on("error", (e) => {
  console.error(JSON.stringify({ status: "error", error: e.message }));
  process.exit(1);
});

req.write(body);
req.end();
