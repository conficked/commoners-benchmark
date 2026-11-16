// Lived-in learning pass for OpenBot, run inside the finished task container after launch.sh.
// Archives the task's thread from its tab menu (a normal user action), which makes OpenBot run its
// own memory review of that thread, then waits for the review's model call to be recorded.
// Run with: <bundled bun> learn.js
const { Database } = require("bun:sqlite");
const DB = "/root/.config/OpenBot/openbot.db";
const port = process.env.CDP_PORT || "9222";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString(), ...a);

let ws, nextId = 1;
const pending = new Map();
const send = (method, params = {}) => {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
};
const evaluate = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
  return r.result.value;
};

async function attach() {
  for (let i = 0; i < 120; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = targets.find((t) => t.type === "page" && t.url.endsWith("/index.html"));
      if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); break; }
    } catch {}
    await sleep(1000);
  }
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

const usageSince = (iso) => {
  const db = new Database(DB, { readonly: true });
  try {
    return db.query("select model, tokens_json from agent_usage_records where occurred_at > ?").all(iso);
  } finally { db.close(); }
};
const memoryCount = () => {
  const db = new Database(DB, { readonly: true });
  try { return db.query("select count(*) as n from projection_agent_memories").get().n; } finally { db.close(); }
};

const tabCount = () => evaluate(`document.querySelectorAll('[role=tab]').length`);

async function mouseClick(x, y, button) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none" });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button, buttons: button === "right" ? 2 : 1, clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button, buttons: 0, clickCount: 1 });
}

// Right-click the first thread tab (index 0 is the agent's own chat) and choose Archive, with real
// mouse input (the menu ignores a synthetic element.click()); success = the tab is gone.
async function archiveOneThread() {
  const before = await tabCount();
  const box = await evaluate(`(() => {
    const t = [...document.querySelectorAll('[role=tab]')][1]; if (!t) return null;
    const r = t.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, name: t.innerText };
  })()`);
  if (!box) return null;
  await mouseClick(box.x, box.y, "right");
  await sleep(800);
  const item = await evaluate(`(() => {
    const e = [...document.querySelectorAll('[role=menuitem]')].find(e => e.innerText.split('\\n').some(l => l.trim() === 'Archive'));
    if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  })()`);
  if (!item) return null;
  await mouseClick(item.x, item.y, "left");
  for (let i = 0; i < 10; i++) {
    await sleep(500);
    if ((await tabCount()) < before) return box.name;
  }
  return null;
}

async function main() {
  await attach();
  for (let i = 0; i < 180; i++) {
    if (await evaluate(`!!document.querySelector('button[aria-label="New thread"]')`)) break;
    await sleep(1000);
  }
  await sleep(3000);
  const before = memoryCount();
  const since = new Date().toISOString();
  const archived = [];
  for (let i = 0; i < 5; i++) {
    const name = await archiveOneThread();
    if (!name) break;
    archived.push(name.slice(0, 40));
  }
  log("archived", archived.length, "thread(s)");
  if (!archived.length) { console.log("NO THREAD TO ARCHIVE"); process.exit(1); }

  // Review starts within seconds of the archive; OpenBot skips it when the agent already saved
  // memories during that turn or the thread has nothing new, so no usage within 2 min = no review.
  const end = Date.now() + 120000;
  let usage = [];
  while (Date.now() < end) {
    usage = usageSince(since);
    if (usage.length) break;
    await sleep(3000);
  }
  if (usage.length) await sleep(15000);
  usage = usageSince(since);
  const tok = usage.reduce((a, u) => {
    const t = JSON.parse(u.tokens_json);
    return { in: a.in + (t.uncachedInput || 0) + (t.cacheCreation || 0), cached: a.cached + (t.cachedInput || 0), out: a.out + (t.output || 0) };
  }, { in: 0, cached: 0, out: 0 });
  const models = [...new Set(usage.map((u) => u.model))].join(",");
  console.log(usage.length
    ? `Memory review complete: calls=${usage.length} model=${models} in=${tok.in} out=${tok.out} cache_read=${tok.cached} memories=${before}->${memoryCount()}`
    : `No memory review (OpenBot skipped it) memories=${before}->${memoryCount()}`);
  ws.close();
}

main().catch((e) => { console.log("learn error:", e.message); process.exit(1); });
