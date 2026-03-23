/**
 * Claude Code -> OpenClaw Gateway WebSocket Chat
 * Usage: node gateway-chat.js "your message here"
 *
 * Connects to Gateway WebSocket, authenticates, sends chat message,
 * captures streaming response, outputs result.
 */
const http = require("http");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

// --- Config ---
const GATEWAY_HOST = "127.0.0.1";
const GATEWAY_PORT = 18789;
const CONFIG_PATH = process.env.OPENCLAW_CONFIG
  || path.join(process.env.OPENCLAW_STATE_DIR || "E:\\.openclaw", "openclaw.json");

let TOKEN;
try {
  const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"));
  TOKEN = cfg.gateway?.auth?.token;
} catch {
  TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN;
}
if (!TOKEN) {
  console.error("No gateway token found");
  process.exit(1);
}

const SESSION = process.env.OPENCLAW_SESSION || "agent:main:direct:holylight";
const TIMEOUT_MS = parseInt(process.env.OPENCLAW_TIMEOUT || "120000", 10);
const message = process.argv.slice(2).join(" ");
if (!message) {
  console.error("Usage: node gateway-chat.js <message>");
  process.exit(1);
}

// --- WebSocket helpers ---
function sendWsFrame(socket, text) {
  const payload = Buffer.from(text, "utf-8");
  const mask = crypto.randomBytes(4);
  let header;
  if (payload.length < 126) {
    header = Buffer.alloc(6);
    header[0] = 0x81;
    header[1] = 0x80 | payload.length;
    mask.copy(header, 2);
  } else if (payload.length < 65536) {
    header = Buffer.alloc(8);
    header[0] = 0x81;
    header[1] = 0x80 | 126;
    header.writeUInt16BE(payload.length, 2);
    mask.copy(header, 4);
  } else {
    header = Buffer.alloc(14);
    header[0] = 0x81;
    header[1] = 0x80 | 127;
    header.writeBigUInt64BE(BigInt(payload.length), 2);
    mask.copy(header, 10);
  }
  const masked = Buffer.alloc(payload.length);
  for (let i = 0; i < payload.length; i++) masked[i] = payload[i] ^ mask[i % 4];
  socket.write(Buffer.concat([header, masked]));
}

function wsRequest(socket, method, params) {
  const id = crypto.randomUUID();
  sendWsFrame(socket, JSON.stringify({ type: "req", id, method, params }));
  return id;
}

// --- Main ---
let phase = "wait";
let responseText = "";

const req = http.request({
  hostname: GATEWAY_HOST,
  port: GATEWAY_PORT,
  path: "/ws",
  method: "GET",
  headers: {
    Connection: "Upgrade",
    Upgrade: "websocket",
    "Sec-WebSocket-Version": "13",
    "Sec-WebSocket-Key": crypto.randomBytes(16).toString("base64"),
    Origin: `http://${GATEWAY_HOST}:${GATEWAY_PORT}`,
  },
});

req.on("upgrade", (res, socket) => {
  let buf = Buffer.alloc(0);

  socket.on("data", (d) => {
    buf = Buffer.concat([buf, d]);
    while (buf.length >= 2) {
      const op = buf[0] & 0x0f;
      let len = buf[1] & 0x7f;
      let off = 2;
      if (len === 126) {
        if (buf.length < 4) break;
        len = buf.readUInt16BE(2);
        off = 4;
      } else if (len === 127) {
        if (buf.length < 10) break;
        len = Number(buf.readBigUInt64BE(2));
        off = 10;
      }
      if (buf.length < off + len) break;

      if (op === 1) {
        try {
          const p = JSON.parse(buf.slice(off, off + len).toString("utf-8"));

          // Step 1: Challenge -> Auth
          if (p.event === "connect.challenge" && phase === "wait") {
            phase = "auth";
            wsRequest(socket, "connect", {
              minProtocol: 3,
              maxProtocol: 3,
              client: {
                id: "webchat",
                version: "dev",
                platform: "win32",
                mode: "webchat",
                instanceId: crypto.randomUUID(),
              },
              role: "operator",
              scopes: [
                "operator.admin",
                "operator.approvals",
                "operator.pairing",
              ],
              caps: [],
              auth: { token: TOKEN },
              userAgent: "Claude-Code-Gateway-Chat/1.0",
              locale: "zh-TW",
            });
          }

          // Step 2: Auth OK -> Send chat
          else if (p.type === "res" && p.ok && phase === "auth") {
            phase = "chatting";
            wsRequest(socket, "chat.send", {
              sessionKey: SESSION,
              message,
              idempotencyKey: crypto.randomUUID(),
            });
          }

          // Step 3: Chat accepted
          else if (p.type === "res" && phase === "chatting") {
            if (p.ok) {
              phase = "streaming";
              console.log(
                JSON.stringify({ status: "sent", runId: p.payload?.runId })
              );
            } else {
              console.error(
                JSON.stringify({ status: "error", error: p.error })
              );
              socket.destroy();
              process.exit(1);
            }
          }

          // Step 4: Stream events — two event patterns:
          //   agent + stream:"assistant" + data.delta  (incremental text)
          //   chat  + state:"final"                    (complete message)
          else if (p.type === "event" && phase === "streaming") {
            const payload = p.payload || {};

            // Pattern A: agent assistant stream (delta tokens)
            if (p.event === "agent" && payload.stream === "assistant" && payload.data?.delta) {
              responseText += payload.data.delta;
            }
            // Pattern B: chat final (complete response)
            else if (p.event === "chat" && payload.state === "final") {
              const text = payload.message?.content
                ?.filter(c => c.type === "text")
                .map(c => c.text)
                .join("") || "";
              console.log(
                JSON.stringify({
                  status: "complete",
                  response: responseText || text,
                })
              );
              socket.destroy();
              process.exit(0);
            }
            // Pattern C: agent lifecycle end (fallback if no chat final)
            else if (p.event === "agent" && payload.stream === "lifecycle" && payload.data?.phase === "end") {
              if (responseText) {
                console.log(JSON.stringify({ status: "complete", response: responseText }));
                socket.destroy();
                process.exit(0);
              }
            }
          }

          // Auth error
          else if (p.type === "res" && !p.ok) {
            console.error(JSON.stringify({ status: "error", error: p.error }));
            socket.destroy();
            process.exit(1);
          }
        } catch (e) {}
      }
      buf = buf.slice(off + len);
    }
  });

  socket.on("close", () => {
    if (phase === "streaming" && responseText) {
      console.log(JSON.stringify({ status: "partial", response: responseText }));
    }
    process.exit(0);
  });

  setTimeout(() => {
    if (phase === "streaming") {
      console.log(
        JSON.stringify({
          status: "timeout",
          response: responseText || null,
          note: "OpenClaw LLM may not be running",
        })
      );
    } else {
      console.error(
        JSON.stringify({ status: "timeout", phase, note: "stuck at " + phase })
      );
    }
    socket.destroy();
    process.exit(0);
  }, TIMEOUT_MS);
});

req.on("error", (e) => {
  console.error(JSON.stringify({ status: "error", error: e.message }));
  process.exit(1);
});
req.end();
