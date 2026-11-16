// Drives the OpenBot UI over CDP from inside the task container.
// Run with: <bundled bun> driver.js <instruction-file> <transcript-file>
const fs = require("fs");

const [instructionFile, transcriptFile] = process.argv.slice(2);
const instruction = instructionFile === "--stop" ? "" : fs.readFileSync(instructionFile, "utf8");
const port = process.env.CDP_PORT || "9222";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString(), ...a);

async function connect() {
  for (let i = 0; i < 120; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = targets.find((t) => t.type === "page" && t.url.endsWith("/index.html"));
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(1000);
  }
  throw new Error("OpenBot page target never appeared");
}

let ws, nextId = 1;
const pending = new Map();
function send(method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
async function evaluate(expression) {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + JSON.stringify(r.exceptionDetails.exception?.description));
  return r.result.value;
}
const has = (label) => evaluate(`!!document.querySelector('button[aria-label=${JSON.stringify(label)}]')`);
const click = (label) => evaluate(`(() => { const b = document.querySelector('button[aria-label=${JSON.stringify(label)}]'); if (!b) return false; b.click(); return true; })()`);
const transcript = () => evaluate(`(document.querySelector("main") || document.body).innerText`);

async function waitFor(fn, timeoutMs, what) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (await fn()) return;
    await sleep(1000);
  }
  throw new Error(`timed out waiting for ${what}`);
}

// OpenBot validates its saved OpenRouter catalog at startup; a model OpenRouter has since dropped
// puts the provider in "error", which usually self-recovers. Like a user, wait for it, and restart
// the app if it stays broken. Every incident is logged for the write-up.
function providerState() {
  const states = [...fs.readFileSync("/tmp/openbot.log", "utf8").matchAll(/"provider":"openrouter","from":"[a-z-]+","to":"([a-z-]+)"/g)];
  return states.length ? states[states.length - 1][1] : "not-started";
}

async function waitForProvider() {
  for (let attempt = 0; attempt < 3; attempt++) {
    const end = Date.now() + 180000;
    while (Date.now() < end) {
      if (providerState() === "available") return;
      await sleep(2000);
    }
    log("INCIDENT openrouter provider stuck in", providerState(), "- restarting OpenBot");
    ws.close();
    // The relaunch must wait for the killed app to release the CDP port, or it can't bind it.
    Bun.spawnSync(["bash", "-c", "pkill -TERM -f '^/opt/openbot/app/openbot --no-sandbox'; sleep 5; pkill -KILL -f '^/opt/openbot/app/openbot'; for _ in $(seq 60); do pgrep -f '^/opt/openbot/app/openbot' >/dev/null || grep -q ':2406 .* 0A ' /proc/net/tcp || break; sleep 0.5; done; rm -f /root/.config/OpenBot/Singleton*; : > /tmp/openbot.log; bash /opt/openbot/launch.sh"]);
    await attach();
    await waitFor(() => has("New thread"), 180000, "OpenBot UI after restart");
    log("OpenBot restarted, provider", providerState());
  }
  throw new Error("openrouter provider never became available");
}

async function attach() {
  ws = new WebSocket(await connect());
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    }
  };
  await send("Runtime.enable");
}

// Timeout path: press Stop like a user giving up, so OpenBot closes the turn and records its usage.
async function stop() {
  await attach();
  if (await click("Stop agent")) {
    log("stop pressed");
    await waitFor(async () => !(await has("Stop agent")), 30000, "agent to stop").catch(() => {});
    await sleep(5000);
  }
  fs.writeFileSync(transcriptFile, await transcript());
  ws.close();
}

async function main() {
  if (instructionFile === "--stop") return stop();
  await attach();
  await waitFor(() => has("New thread"), 180000, "OpenBot UI");
  await waitForProvider();
  await click("New thread");
  await sleep(1500);
  const focused = await evaluate(`(() => {
    const els = [...document.querySelectorAll('[contenteditable=true], textarea')].filter(e => e.offsetParent);
    const box = els[els.length - 1]; if (!box) return false; box.focus(); return true; })()`);
  if (!focused) throw new Error("composer not found");
  await send("Input.insertText", { text: instruction });
  await sleep(500);
  for (const type of ["keyDown", "keyUp"])
    await send("Input.dispatchKeyEvent", { type, key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  log("instruction sent", instruction.length, "chars");

  await waitFor(() => has("Stop agent"), 300000, "agent to start");
  log("agent working");

  let idle = 0, last = 0;
  while (idle < 3) {
    await sleep(5000);
    idle = (await has("Stop agent")) ? 0 : idle + 1;
    if (Date.now() - last > 30000) {
      fs.writeFileSync(transcriptFile, await transcript());
      last = Date.now();
    }
  }
  fs.writeFileSync(transcriptFile, await transcript());
  log("agent finished");
  ws.close();
}

main().catch(async (e) => {
  log("driver error:", e.message);
  try { fs.writeFileSync(transcriptFile, await transcript()); } catch {}
  process.exit(1);
});
