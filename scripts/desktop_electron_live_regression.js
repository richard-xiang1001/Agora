#!/usr/bin/env node

const fs = require("fs");
const fsp = fs.promises;
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const repoRoot = path.resolve(__dirname, "..");
const defaultElectronBin = path.join(repoRoot, "node_modules", ".bin", "electron");
const defaultPythonBin = process.env.AGORA_PYTHON_BIN || path.join(repoRoot, ".venv", "bin", "python");
const currentDesktopConfigPath = path.join(os.homedir(), "Library", "Application Support", "agora-desktop", "desktop-config.json");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function nowIso() {
  return new Date().toISOString();
}

function parseArgs(argv) {
  const args = {
    provider: "live",
    initialProvider: "mock",
    agentMode: "solo",
    teamId: "research-implement-verify",
    validateTeamWorkspace: false,
    timeoutMs: 180000,
    cdpPort: 0,
    userDataDir: "",
    output: "",
    electronBin: defaultElectronBin,
    pythonBin: defaultPythonBin,
    keepArtifacts: false,
    openrouterApiKey: process.env.OPENROUTER_API_KEY || "",
    expectedMarker: "AGORA_ELECTRON_LIVE_OK",
    prompt: "Return exactly this token and nothing else:\nAGORA_ELECTRON_LIVE_OK",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const key = String(argv[i] || "");
    const value = String(argv[i + 1] || "");
    if (key === "--provider") {
      args.provider = value || args.provider;
      i += 1;
    } else if (key === "--initial-provider") {
      args.initialProvider = value || args.initialProvider;
      i += 1;
    } else if (key === "--agent-mode") {
      args.agentMode = value || args.agentMode;
      i += 1;
    } else if (key === "--team-id") {
      args.teamId = value || args.teamId;
      i += 1;
    } else if (key === "--validate-team-workspace") {
      args.validateTeamWorkspace = true;
    } else if (key === "--timeout-ms") {
      args.timeoutMs = Math.max(10000, Number(value) || args.timeoutMs);
      i += 1;
    } else if (key === "--cdp-port") {
      args.cdpPort = Math.max(0, Number(value) || 0);
      i += 1;
    } else if (key === "--user-data-dir") {
      args.userDataDir = value;
      i += 1;
    } else if (key === "--output") {
      args.output = value;
      i += 1;
    } else if (key === "--electron-bin") {
      args.electronBin = value;
      i += 1;
    } else if (key === "--python-bin") {
      args.pythonBin = value;
      i += 1;
    } else if (key === "--openrouter-api-key") {
      args.openrouterApiKey = value;
      i += 1;
    } else if (key === "--prompt") {
      args.prompt = value || args.prompt;
      i += 1;
    } else if (key === "--expected-marker") {
      args.expectedMarker = value || args.expectedMarker;
      i += 1;
    } else if (key === "--keep-artifacts") {
      args.keepArtifacts = true;
    }
  }
  return args;
}

function sanitizeForSessionId(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

function normalizeText(value) {
  return String(value || "")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\u00a0/g, " ")
    .trim();
}

function redactSecretString(value) {
  return String(value || "").replace(/sk-or-v1-[A-Za-z0-9]+/g, "[REDACTED_OPENROUTER_KEY]");
}

function redactSecrets(value) {
  if (typeof value === "string") {
    return redactSecretString(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactSecrets(item));
  }
  if (value && typeof value === "object") {
    const next = {};
    for (const [key, item] of Object.entries(value)) {
      next[key] = redactSecrets(item);
    }
    return next;
  }
  return value;
}

function artifactDesktopConfig(payload) {
  return {
    mode: String((payload || {}).mode || ""),
    runtimeAutostart: Boolean((payload || {}).runtimeAutostart),
    openrouterApiKey: (payload || {}).openrouterApiKey ? "[REDACTED_OPENROUTER_KEY]" : "",
    hasOpenrouterApiKey: Boolean((payload || {}).openrouterApiKey),
  };
}

function loadExistingDesktopConfig() {
  try {
    if (!fs.existsSync(currentDesktopConfigPath)) return {};
    return JSON.parse(fs.readFileSync(currentDesktopConfigPath, "utf8"));
  } catch {
    return {};
  }
}

async function ensureDir(targetPath) {
  await fsp.mkdir(targetPath, { recursive: true });
}

function fail(message, extra = {}) {
  const error = new Error(message);
  Object.assign(error, extra);
  throw error;
}

async function findFreePort(preferred = 0) {
  if (preferred > 0) {
    return preferred;
  }
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = Number(address && address.port ? address.port : 0);
      server.close((error) => {
        if (error) reject(error);
        else resolve(port);
      });
    });
  });
}

async function waitFor(check, timeoutMs, label) {
  const started = Date.now();
  let lastError = null;
  while (Date.now() - started < timeoutMs) {
    try {
      const value = await check();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await sleep(250);
  }
  fail(`timeout waiting for ${label}`, { lastError: lastError ? String(lastError.message || lastError) : "" });
}

async function fetchJson(url, options = {}) {
  const nextOptions = { ...options };
  if (nextOptions.body != null) {
    const headers = new Headers(nextOptions.headers || {});
    if (!headers.has("content-type")) {
      headers.set("content-type", "application/json");
    }
    nextOptions.headers = headers;
  }
  const response = await fetch(url, nextOptions);
  const text = await response.text();
  if (!response.ok) {
    fail(`http_error:${response.status} ${url}`, { body: text.slice(0, 1200) });
  }
  return text ? JSON.parse(text) : {};
}

class CdpClient {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.seq = 0;
    this.pending = new Map();
  }

  async connect() {
    const WebSocketCtor = globalThis.WebSocket;
    if (!WebSocketCtor) {
      fail("global WebSocket is unavailable in this Node runtime");
    }
    await new Promise((resolve, reject) => {
      const ws = new WebSocketCtor(this.url);
      this.ws = ws;
      ws.onopen = () => resolve();
      ws.onerror = (event) => reject(new Error(`cdp_websocket_error:${String(event?.message || "")}`));
      ws.onclose = () => {
        for (const [, entry] of this.pending) {
          entry.reject(new Error("cdp_socket_closed"));
        }
        this.pending.clear();
      };
      ws.onmessage = (event) => {
        let message = {};
        try {
          message = JSON.parse(String(event.data || "{}"));
        } catch {
          message = {};
        }
        const id = Number(message.id || 0);
        if (!id || !this.pending.has(id)) return;
        const entry = this.pending.get(id);
        this.pending.delete(id);
        if (message.error) {
          entry.reject(new Error(String(message.error.message || JSON.stringify(message.error))));
          return;
        }
        entry.resolve(message.result || {});
      };
    });
  }

  async send(method, params = {}) {
    if (!this.ws || this.ws.readyState !== 1) {
      fail(`cdp_not_connected:${method}`);
    }
    this.seq += 1;
    const id = this.seq;
    const payload = JSON.stringify({ id, method, params });
    return await new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try {
        this.ws.send(payload);
      } catch (error) {
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  async evaluate(expression, { returnByValue = true, awaitPromise = true } = {}) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue,
      awaitPromise,
    });
    const value = result && result.result ? result.result.value : undefined;
    return value;
  }

  async close() {
    if (!this.ws) return;
    try {
      this.ws.close();
    } catch {}
    this.ws = null;
  }
}

function bootstrapWorkspace(root, pythonBin) {
  const code = [
    "from pathlib import Path",
    "from agora.bootstrap_profile import apply_bootstrap",
    `apply_bootstrap(Path(${JSON.stringify(String(root))}), {})`,
  ].join("\n");
  const result = spawnSync(pythonBin, ["-c", code], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONPATH: repoRoot },
    encoding: "utf8",
  });
  if (result.status !== 0) {
    fail("bootstrap_workspace_failed", {
      stdout: String(result.stdout || ""),
      stderr: String(result.stderr || ""),
    });
  }
}

function ensureGitRepo(root) {
  const gitDir = path.join(root, ".git");
  if (fs.existsSync(gitDir)) {
    return { initialized: false, reason: "already_git_repo" };
  }
  const markerPath = path.join(root, ".agora-regression-seed");
  fs.writeFileSync(markerPath, `${nowIso()}\n`, "utf8");
  const commands = [
    ["init"],
    ["config", "user.name", "Agora Regression"],
    ["config", "user.email", "agora-regression@example.com"],
    ["add", ".agora-regression-seed"],
    ["commit", "-m", "bootstrap", "--allow-empty"],
  ];
  for (const args of commands) {
    const result = spawnSync("git", args, {
      cwd: root,
      env: { ...process.env },
      encoding: "utf8",
    });
    if (result.status !== 0) {
      fail(`ensure_git_repo_failed:${args.join(" ")}`, {
        stdout: String(result.stdout || ""),
        stderr: String(result.stderr || ""),
      });
    }
  }
  return { initialized: true, markerPath };
}

function writeDesktopConfig(userDataDir, args) {
  const existing = loadExistingDesktopConfig();
  const key = String(args.openrouterApiKey || existing.openrouterApiKey || "").trim();
  if (String(args.provider).trim() === "live" && !key) {
    fail("missing_openrouter_api_key", {
      hint: "Pass --openrouter-api-key or set OPENROUTER_API_KEY, or ensure ~/Library/Application Support/agora-desktop/desktop-config.json already has one.",
    });
  }
  const payload = {
    mode: String(args.initialProvider || "mock").trim() === "live" ? "live" : "mock",
    runtimeAutostart: true,
    openrouterApiKey: key,
  };
  fs.mkdirSync(userDataDir, { recursive: true });
  fs.writeFileSync(path.join(userDataDir, "desktop-config.json"), JSON.stringify(payload, null, 2));
  return payload;
}

async function waitForDebuggerTargets(cdpPort, timeoutMs) {
  const versionUrl = `http://127.0.0.1:${cdpPort}/json/version`;
  const listUrl = `http://127.0.0.1:${cdpPort}/json/list`;
  return await waitFor(async () => {
    const version = await fetchJson(versionUrl);
    const targets = await fetchJson(listUrl);
    const page = (Array.isArray(targets) ? targets : []).find((item) => {
      return String(item.type || "") === "page" && /\/app\/?$/.test(String(item.url || ""));
    });
    if (!page) return null;
    return {
      version,
      page,
    };
  }, timeoutMs, "electron remote debugging targets");
}

async function waitForPageReady(cdp, timeoutMs) {
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await waitFor(async () => {
    const state = await cdp.evaluate("document.readyState");
    return state === "complete";
  }, timeoutMs, "document.readyState=complete");
  await waitFor(async () => {
    const exists = await cdp.evaluate("Boolean(document.querySelector('#composer-input') && document.querySelector('#composer-send') && document.querySelector('#new-session'))");
    return Boolean(exists);
  }, timeoutMs, "composer controls");
}

async function click(cdp, selector) {
  const expression = `(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    if (!node) return { ok: false, reason: "missing" };
    node.scrollIntoView({ block: "center", inline: "center" });
    if (Boolean(node.disabled) || String(node.getAttribute("aria-disabled") || "").toLowerCase() === "true") {
      return { ok: false, reason: "disabled", text: String(node.innerText || node.textContent || "").trim() };
    }
    const event = new MouseEvent("click", { bubbles: true, cancelable: true, composed: true, view: window });
    const dispatched = node.dispatchEvent(event);
    return {
      ok: true,
      dispatched,
      defaultPrevented: event.defaultPrevented,
      text: String(node.innerText || node.textContent || "").trim(),
    };
  })()`;
  const result = await cdp.evaluate(expression);
  if (!result || !result.ok) {
    fail(`click_failed:${selector}`, { result });
  }
  return result;
}

async function clickButtonByText(cdp, text, { rootSelector = "body" } = {}) {
  const expression = `(() => {
    const root = document.querySelector(${JSON.stringify(rootSelector)});
    if (!root) return { ok: false, reason: "missing_root" };
    const wanted = ${JSON.stringify(String(text || "").trim())};
    const buttons = [...root.querySelectorAll("button")];
    const node = buttons.find((item) => String(item.innerText || item.textContent || "").trim() === wanted);
    if (!node) return { ok: false, reason: "missing_button" };
    node.scrollIntoView({ block: "center", inline: "center" });
    if (typeof node.click === "function") node.click();
    return { ok: true };
  })()`;
  const result = await cdp.evaluate(expression);
  if (!result || !result.ok) {
    fail(`click_button_by_text_failed:${rootSelector}:${text}`);
  }
  return result;
}

async function setTextareaValue(cdp, selector, value) {
  const expression = `(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    if (!node) return { ok: false, reason: "missing" };
    node.focus();
    node.value = ${JSON.stringify(value)};
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true, length: String(node.value || "").length };
  })()`;
  const result = await cdp.evaluate(expression);
  if (!result || !result.ok) {
    fail(`set_textarea_failed:${selector}`);
  }
  return result;
}

async function setInputValue(cdp, selector, value, { inputType = "text" } = {}) {
  const expression = `(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    if (!node) return { ok: false, reason: "missing" };
    node.focus();
    if (${JSON.stringify(inputType)} === "checkbox") {
      node.checked = Boolean(${JSON.stringify(Boolean(value))});
    } else {
      node.value = ${JSON.stringify(String(value ?? ""))};
    }
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return {
      ok: true,
      value: ${JSON.stringify(inputType)} === "checkbox" ? String(Boolean(node.checked)) : String(node.value || ""),
    };
  })()`;
  const result = await cdp.evaluate(expression);
  if (!result || !result.ok) {
    fail(`set_input_failed:${selector}`);
  }
  return result;
}

async function setSelectValue(cdp, selector, value) {
  const expression = `(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    if (!node) return { ok: false, reason: "missing" };
    node.value = ${JSON.stringify(String(value ?? ""))};
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true, value: String(node.value || "") };
  })()`;
  const result = await cdp.evaluate(expression);
  if (!result || !result.ok) {
    fail(`set_select_failed:${selector}`);
  }
  return result;
}

async function waitForElementState(cdp, selector, { visible = true, timeoutMs = 15000 } = {}) {
  return await waitFor(async () => {
    const state = await cdp.evaluate(`(() => {
      const node = document.querySelector(${JSON.stringify(selector)});
      if (!node) return { exists: false, visible: false };
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      const hiddenByClass = node.classList.contains("hidden");
      const visibleNow = !hiddenByClass && style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || "1") !== 0 && rect.width >= 0 && rect.height >= 0;
      return { exists: true, visible: visibleNow, text: String(node.innerText || node.textContent || "").trim() };
    })()`);
    if (!state || !state.exists) {
      return visible ? null : { exists: false, visible: false, text: "" };
    }
    if (Boolean(state.visible) !== Boolean(visible)) return null;
    return state;
  }, timeoutMs, `element_state:${selector}:${visible ? "visible" : "hidden"}`);
}

async function waitForTextIncludes(cdp, selector, expected, timeoutMs = 15000) {
  const wanted = String(expected || "").trim().toUpperCase();
  return await waitFor(async () => {
    const result = await cdp.evaluate(`(() => {
      const node = document.querySelector(${JSON.stringify(selector)});
      return node ? String(node.innerText || node.textContent || "").trim() : "";
    })()`);
    const text = String(result || "").trim();
    if (!text) return null;
    return text.toUpperCase().includes(wanted) ? text : null;
  }, timeoutMs, `text:${selector}:${expected}`);
}

async function cdpText(cdp, selector) {
  return String(
    (await cdp.evaluate(`(() => {
      const node = document.querySelector(${JSON.stringify(selector)});
      return node ? String(node.innerText || node.textContent || "").trim() : "";
    })()`)) || ""
  ).trim();
}

async function waitForButtonByText(cdp, text, { rootSelector = "body", timeoutMs = 15000 } = {}) {
  return await waitFor(async () => {
    const result = await cdp.evaluate(`(() => {
      const root = document.querySelector(${JSON.stringify(rootSelector)});
      if (!root) return null;
      const wanted = ${JSON.stringify(String(text || "").trim())};
      const buttons = [...root.querySelectorAll("button")];
      const node = buttons.find((item) => String(item.innerText || item.textContent || "").trim() === wanted);
      if (!node) return null;
      return String(node.innerText || node.textContent || "").trim();
    })()`);
    return result ? String(result) : null;
  }, timeoutMs, `button:${rootSelector}:${text}`);
}

async function getDomSnapshot(cdp) {
  return await cdp.evaluate(`(() => {
    const thread = document.querySelector("#conversation-thread");
    const pill = document.querySelector("#model-status-pill");
    const active = document.querySelector("#active-session-label");
    return {
      threadText: String(thread ? thread.innerText || "" : ""),
      modelStatus: String(pill ? pill.innerText || pill.textContent || "" : "").trim(),
      activeSessionLabel: String(active ? active.innerText || active.textContent || "" : "").trim(),
    };
  })()`);
}

async function waitForSession(baseUrl, timeoutMs) {
  return await waitFor(async () => {
    const payload = await fetchJson(`${baseUrl}/v1/ui/sessions`);
    const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    if (!sessions.length) return null;
    return sessions[0];
  }, timeoutMs, "ui session");
}

function readJsonFile(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readJsonl(filePath) {
  const text = fs.readFileSync(filePath, "utf8");
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function latestTaskForSession(queuePath, sessionId) {
  const rows = readJsonl(queuePath).filter((row) => String(row.session_id || "") === String(sessionId || ""));
  return rows.length ? rows[rows.length - 1] : null;
}

function latestResumeQueueTask(queuePath, sessionId, workflowId) {
  const rows = readJsonl(queuePath).filter((row) => {
    if (String(row.session_id || "") !== String(sessionId || "")) return false;
    const resumeWorkflow = ((row.request || {}).resume_workflow) || {};
    return String(resumeWorkflow.workflow_id || "") === String(workflowId || "");
  });
  return rows.length ? rows[rows.length - 1] : null;
}

function setAssertion(output, key, patch = {}) {
  if (!output || typeof output !== "object") return {};
  if (!output.assertions || typeof output.assertions !== "object") {
    output.assertions = {};
  }
  const current = output.assertions[key] && typeof output.assertions[key] === "object" ? output.assertions[key] : {};
  const next = { key: String(key || "").trim(), ...current, ...patch };
  output.assertions[key] = next;
  return next;
}

function compactProviderStreamActorEvent(value) {
  const actor = value && typeof value === "object" ? value : {};
  return {
    created_at: String(actor.created_at || "").trim(),
    workflow_id: String(actor.workflow_id || "").trim(),
    call_id: String(actor.call_id || "").trim(),
    continuity_reason: String(actor.continuity_reason || "").trim(),
    continuity_kind: String(actor.continuity_kind || "").trim(),
    actor_reason: String(actor.actor_reason || "").trim(),
    event_type: String(actor.event_type || "").trim(),
    delta_type: String(actor.delta_type || "").trim(),
    dispatch_recommended: Boolean(actor.dispatch_recommended),
    text_preview: String(actor.text_preview || "").trim().slice(0, 240),
    delta_preview: String(actor.delta_preview || "").trim().slice(0, 240),
    tool_name: String(actor.tool_name || "").trim(),
    finish_reason: String(actor.finish_reason || "").trim(),
    stop_reason: String(actor.stop_reason || "").trim(),
    event_count: Number(actor.event_count || 0),
  };
}

function summarizeProviderStreamEvidence(rows, sidechainPath = "") {
  const entries = Array.isArray(rows) ? rows.filter((item) => item && typeof item === "object") : [];
  const streamRows = entries.filter((row) => String(row.kind || "").trim() === "provider_stream_event");
  const actorRows = entries.filter((row) => String(row.kind || "").trim() === "provider_stream_actor_event");
  const calls = new Map();
  const ensureCall = (callId) => {
    const normalized = String(callId || "").trim() || "call:unknown";
    if (!calls.has(normalized)) {
      calls.set(normalized, {
        call_id: normalized,
        workflow_id: "",
        updated_at: "",
        provider_stream_event_count: 0,
        provider_stream_actor_event_count: 0,
        latest_stream_event_type: "",
        latest_actor: null,
      });
    }
    return calls.get(normalized);
  };
  for (const row of streamRows) {
    const summary = ensureCall(row.call_id);
    summary.provider_stream_event_count += 1;
    if (!summary.workflow_id) {
      summary.workflow_id = String(row.workflow_id || "").trim();
    }
    summary.updated_at = String(row.created_at || summary.updated_at || "").trim();
    const event = row.event && typeof row.event === "object" ? row.event : {};
    summary.latest_stream_event_type = String(event.type || summary.latest_stream_event_type || "").trim();
  }
  for (const row of actorRows) {
    const summary = ensureCall(row.call_id);
    summary.provider_stream_actor_event_count += 1;
    if (!summary.workflow_id) {
      summary.workflow_id = String(row.workflow_id || "").trim();
    }
    summary.updated_at = String(row.created_at || summary.updated_at || "").trim();
    const actor = row.actor_event && typeof row.actor_event === "object" ? row.actor_event : row;
    summary.latest_actor = compactProviderStreamActorEvent(actor);
  }
  const orderedCalls = [...calls.values()]
    .filter((item) => item.provider_stream_event_count || item.provider_stream_actor_event_count)
    .sort((left, right) => {
      const updatedCompare = String(left.updated_at || "").localeCompare(String(right.updated_at || ""));
      if (updatedCompare !== 0) return updatedCompare;
      return String(left.call_id || "").localeCompare(String(right.call_id || ""));
    });
  const readyCalls = orderedCalls.filter((item) => item.provider_stream_event_count > 0 && item.provider_stream_actor_event_count > 0);
  const selected = readyCalls.length ? readyCalls[readyCalls.length - 1] : null;
  return {
    sidechain_path: String(sidechainPath || "").trim(),
    total_sidechain_rows: entries.length,
    provider_stream_event_count: streamRows.length,
    provider_stream_actor_event_count: actorRows.length,
    call_count: orderedCalls.length,
    ready: Boolean(selected),
    workflow_id: selected ? String(selected.workflow_id || "").trim() : "",
    call_id: selected ? String(selected.call_id || "").trim() : "",
    latest_stream_event_type: selected ? String(selected.latest_stream_event_type || "").trim() : "",
    latest_actor: selected ? compactProviderStreamActorEvent(selected.latest_actor || {}) : null,
    calls: orderedCalls.slice(-3),
  };
}

function latestQueueTaskByTaskId(queuePath, taskId) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!normalizedTaskId || !fs.existsSync(queuePath)) return null;
  const rows = readJsonl(queuePath).filter((row) => String(row.task_id || "").trim() === normalizedTaskId);
  return rows.length ? rows[rows.length - 1] : null;
}

function compactRuntimeQueueTask(task) {
  const row = task && typeof task === "object" ? task : {};
  const response = row.response && typeof row.response === "object" ? row.response : {};
  const events = Array.isArray(row.events) ? row.events.filter((item) => item && typeof item === "object") : [];
  const latestEvent = events.length ? events[events.length - 1] : {};
  return {
    task_id: String(row.task_id || "").trim(),
    status: String(row.status || "").trim(),
    workflow_id: String(row.workflow_id || "").trim(),
    error: String(row.error || "").trim(),
    response_workflow_status: String(response.workflow_status || "").trim(),
    response_stop_reason: String(response.stop_reason || "").trim(),
    execution_mode: String(response.execution_mode || "").trim(),
    runtime_mode: String(response.runtime_mode || "").trim(),
    started_at: String(row.started_at || "").trim(),
    completed_at: String(row.completed_at || "").trim(),
    event_count: events.length,
    latest_event_stage: String(latestEvent.stage || "").trim(),
    latest_event_status: String(latestEvent.status || "").trim(),
    latest_event_message: String(latestEvent.message || "").trim(),
  };
}

async function waitForTask(queuePath, sessionId, timeoutMs) {
  return await waitFor(async () => {
    if (!fs.existsSync(queuePath)) return null;
    const row = latestTaskForSession(queuePath, sessionId);
    if (!row) return null;
    if (["completed", "failed", "waiting_user", "cancelled", "aborted"].includes(String(row.status || ""))) {
      return row;
    }
    return null;
  }, timeoutMs, `terminal task for session ${sessionId}`);
}

async function waitForStreamActor(sidechainPath, timeoutMs) {
  return await waitFor(async () => {
    if (!fs.existsSync(sidechainPath)) return null;
    const evidence = summarizeProviderStreamEvidence(readJsonl(sidechainPath), sidechainPath);
    return evidence.ready ? evidence : null;
  }, timeoutMs, `provider stream actor ledger ${sidechainPath}`);
}

async function waitForTeamRun(baseUrl, sessionId, teamId, timeoutMs) {
  return await waitFor(async () => {
    const payload = await fetchJson(`${baseUrl}/v1/ui/agents`);
    const teamRuns = Array.isArray(payload.team_runs) ? payload.team_runs : [];
    const match = teamRuns
      .filter((item) => String(item.session_id || "") === String(sessionId || ""))
      .filter((item) => !teamId || String(item.team_id || "") === String(teamId || ""))
      .slice(-1)[0];
    return match || null;
  }, timeoutMs, `team run for session ${sessionId}`);
}

async function waitForWorkspaceMemberSelected(cdp, memberId, timeoutMs = 15000) {
  return await waitFor(async () => {
    const selected = await cdp.evaluate(`(() => {
      const active = document.querySelector(".team-workspace-member-button.active");
      return active ? String(active.dataset.teamWorkspaceMember || "").trim() : "";
    })()`);
    return String(selected || "").trim() === String(memberId || "").trim() ? selected : null;
  }, timeoutMs, `workspace member ${memberId}`);
}

async function waitForWorkspaceMemberContext(cdp, memberId, timeoutMs = 15000) {
  const wanted = String(memberId || "").trim();
  return await waitFor(async () => {
    const state = await cdp.evaluate(`(() => {
      const wanted = ${JSON.stringify(wanted)};
      const active = document.querySelector(".team-workspace-member-button.active");
      const activeMember = active ? String(active.dataset.teamWorkspaceMember || "").trim() : "";
      const headings = [...document.querySelectorAll("#team-workspace-content h4")].map((node) => String(node.innerText || node.textContent || "").trim());
      const activeHeading = headings.find((text) => text.includes("Active Workspace")) || "";
      const liveSave = document.querySelector('[data-workspace-runtime-save="live"]');
      const nextSave = document.querySelector('[data-workspace-runtime-save="next"]');
      return {
        activeMember,
        activeHeading,
        liveReady: Boolean(liveSave && !liveSave.disabled),
        nextReady: Boolean(nextSave && !nextSave.disabled),
        ok: activeMember === wanted && activeHeading.includes(wanted) && Boolean(liveSave && !liveSave.disabled) && Boolean(nextSave && !nextSave.disabled),
      };
    })()`);
    return state && state.ok ? state : null;
  }, timeoutMs, `workspace member context ${memberId}`);
}

async function waitForWorkspaceMembers(cdp, memberIds, timeoutMs = 15000) {
  const wanted = [...new Set((Array.isArray(memberIds) ? memberIds : []).map((item) => String(item || "").trim()).filter(Boolean))];
  return await waitFor(async () => {
    const rows = await cdp.evaluate(`(() => {
      return [...document.querySelectorAll("[data-team-workspace-member]")].map((node) => String(node.dataset.teamWorkspaceMember || "").trim()).filter(Boolean);
    })()`);
    const values = Array.isArray(rows) ? rows.map((item) => String(item || "").trim()) : [];
    return wanted.every((item) => values.includes(item)) ? values : null;
  }, timeoutMs, `workspace members ${wanted.join(",")}`);
}

async function clickWorkspaceMember(cdp, memberId) {
  const expression = `(() => {
    const wanted = ${JSON.stringify(String(memberId || "").trim())};
    const node = [...document.querySelectorAll("[data-team-workspace-member]")].find((item) => String(item.dataset.teamWorkspaceMember || "").trim() === wanted);
    if (!node) return { ok: false, reason: "missing_member" };
    node.scrollIntoView({ block: "center", inline: "center" });
    if (typeof node.click === "function") node.click();
    return { ok: true };
  })()`;
  const result = await cdp.evaluate(expression);
  if (!result || !result.ok) {
    fail(`click_workspace_member_failed:${memberId}`);
  }
  return result;
}

async function waitForResumeQueueTask(queuePath, sessionId, workflowId, timeoutMs) {
  return await waitFor(async () => {
    if (!fs.existsSync(queuePath)) return null;
    return latestResumeQueueTask(queuePath, sessionId, workflowId);
  }, timeoutMs, `resume queue task ${workflowId}`);
}

async function waitForResumeQueueTaskWithPrompt(queuePath, sessionId, workflowId, promptAppend, timeoutMs) {
  return await waitFor(async () => {
    if (!fs.existsSync(queuePath)) return null;
    const rows = readJsonl(queuePath).filter((row) => {
      if (String(row.session_id || "") !== String(sessionId || "")) return false;
      const resumeWorkflow = ((row.request || {}).resume_workflow) || {};
      return String(resumeWorkflow.workflow_id || "") === String(workflowId || "");
    });
    if (!rows.length) return null;
    const match = [...rows].reverse().find((row) => {
      const continuation = normalizeText(String((((row.request || {}).resume_workflow) || {}).continuation_context || ""));
      return continuation.includes("Next launch operator instructions") && continuation.includes(String(promptAppend || ""));
    });
    return match || null;
  }, timeoutMs, `resume queue task with prompt ${workflowId}`);
}

async function waitForApprovalActorState(baseUrl, teamRunId, actorId, timeoutMs) {
  return await waitFor(async () => {
    const payload = await fetchJson(`${baseUrl}/v1/ui/agents/teams/${encodeURIComponent(teamRunId)}/workspace`);
    const approvalQueue = (payload.workspace || {}).approval_queue || {};
    const items = Array.isArray(approvalQueue.items) ? approvalQueue.items : [];
    const match = items.find((item) => String(item.actor_id || "") === String(actorId || ""));
    if (match) {
      const status = String(match.status || "").trim();
      if (status && status !== "pending") return match;
    }
    const actors = Array.isArray(approvalQueue.actors) ? approvalQueue.actors : [];
    const actorRow = actors.find((item) => String(item.actor_id || "") === String(actorId || ""));
    if (!actorRow) return null;
    const actorStatus = String(actorRow.status || "").trim();
    return actorStatus && actorStatus !== "pending" ? actorRow : null;
  }, timeoutMs, `approval actor ${actorId} resolution`);
}

function listTeamFreshTasks(taskPayloadPath, sourceMemberId, { spawnTurnKey = "", requireInstance = false } = {}) {
  if (!fs.existsSync(taskPayloadPath)) return [];
  const payload = readJsonFile(taskPayloadPath);
  const tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  const wantedSourceMemberId = String(sourceMemberId || "").trim();
  const wantedTurnKey = String(spawnTurnKey || "").trim();
  return tasks
    .filter((item) => {
      if (String(item.source_member_id || "").trim() !== wantedSourceMemberId) return false;
      if (String(item.member_id || "").trim() === wantedSourceMemberId) return false;
      if (wantedTurnKey && String(item.spawn_turn_key || "").trim() !== wantedTurnKey) return false;
      if (requireInstance && !String(item.instance_id || "").trim()) return false;
      return true;
    })
    .sort((left, right) => {
      const updatedCompare = String(left.updated_at || "").localeCompare(String(right.updated_at || ""));
      if (updatedCompare !== 0) return updatedCompare;
      return String(left.task_id || "").localeCompare(String(right.task_id || ""));
    });
}

async function waitForTeamFreshTask(taskPayloadPath, sourceMemberId, options = {}) {
  const timeoutMs = Math.max(1000, Number(options.timeoutMs) || 0);
  const spawnTurnKey = String(options.spawnTurnKey || "").trim();
  const requireInstance = options.requireInstance !== false;
  return await waitFor(async () => {
    const matches = listTeamFreshTasks(taskPayloadPath, sourceMemberId, { spawnTurnKey, requireInstance });
    const match = matches.length ? matches[matches.length - 1] : null;
    return match || null;
  }, timeoutMs, `fresh team task for ${sourceMemberId}${spawnTurnKey ? ` (${spawnTurnKey})` : ""}`);
}

async function waitForInstanceSidechain(sidechainPath, timeoutMs) {
  return await waitFor(async () => {
    if (!fs.existsSync(sidechainPath)) return null;
    const rows = readJsonl(sidechainPath);
    return rows.length ? rows : null;
  }, timeoutMs, `instance sidechain ${sidechainPath}`);
}

function collectFreshTaskCandidates(taskPayloadPath, queuePath, sourceMemberId) {
  const runtimeDir = path.resolve(path.dirname(taskPayloadPath), "..");
  return listTeamFreshTasks(taskPayloadPath, sourceMemberId).map((task) => {
    const instanceId = String(task.instance_id || "").trim();
    const runtimeTaskId = String(task.runtime_task_id || "").trim();
    const sidechainPath = instanceId
      ? path.join(runtimeDir, "agent_sidechains", `agent-${instanceId}.jsonl`)
      : "";
    const sidechainEvidence = sidechainPath && fs.existsSync(sidechainPath)
      ? summarizeProviderStreamEvidence(readJsonl(sidechainPath), sidechainPath)
      : null;
    const queueTask = compactRuntimeQueueTask(latestQueueTaskByTaskId(queuePath, runtimeTaskId));
    return {
      task_id: String(task.task_id || "").trim(),
      member_id: String(task.member_id || "").trim(),
      source_member_id: String(task.source_member_id || "").trim(),
      status: String(task.status || "").trim(),
      worktree_mode: String(task.worktree_mode || "").trim(),
      instance_id: instanceId,
      runtime_task_id: runtimeTaskId,
      workflow_id: String(task.workflow_id || "").trim(),
      spawn_turn_key: String(task.spawn_turn_key || "").trim(),
      spawn_reason: String(task.spawn_reason || "").trim(),
      updated_at: String(task.updated_at || "").trim(),
      queue: queueTask,
      sidechain_path: sidechainEvidence ? sidechainEvidence.sidechain_path : sidechainPath,
      total_sidechain_rows: sidechainEvidence ? sidechainEvidence.total_sidechain_rows : 0,
      provider_stream_event_count: sidechainEvidence ? sidechainEvidence.provider_stream_event_count : 0,
      provider_stream_actor_event_count: sidechainEvidence ? sidechainEvidence.provider_stream_actor_event_count : 0,
      stream_ready: Boolean(sidechainEvidence && sidechainEvidence.ready),
      live_provider: sidechainEvidence && sidechainEvidence.ready
        ? {
            workflow_id: sidechainEvidence.workflow_id,
            call_id: sidechainEvidence.call_id,
            latest_stream_event_type: sidechainEvidence.latest_stream_event_type,
            latest_actor: sidechainEvidence.latest_actor,
          }
        : null,
    };
  });
}

async function waitForFreshTaskWithStreamActor(taskPayloadPath, queuePath, sourceMemberId, timeoutMs) {
  const started = Date.now();
  let lastCandidates = [];
  while (Date.now() - started < timeoutMs) {
    const candidates = collectFreshTaskCandidates(taskPayloadPath, queuePath, sourceMemberId);
    lastCandidates = candidates;
    const match = [...candidates].reverse().find((item) => item.stream_ready);
    if (match) {
      return {
        freshTask: match,
        candidates,
      };
    }
    await sleep(250);
  }
  fail(`timeout waiting for fresh live provider stream actor ${sourceMemberId}`, {
    fresh_candidates: lastCandidates,
  });
}

async function gracefulClose(browserWsUrl) {
  if (!browserWsUrl) return;
  const browser = new CdpClient(browserWsUrl);
  try {
    await browser.connect();
    await browser.send("Browser.close");
  } catch {}
  await browser.close();
}

async function waitForChildExit(child, timeoutMs = 5000) {
  if (!child) return true;
  if (child.exitCode !== null || child.signalCode !== null) return true;
  return await new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(true);
    };
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve(false);
    }, timeoutMs);
    child.once("exit", finish);
    child.once("close", finish);
  });
}

async function removeDirWithRetry(target, attempts = 6) {
  for (let index = 0; index < attempts; index += 1) {
    try {
      await fsp.rm(target, { recursive: true, force: true, maxRetries: 3, retryDelay: 150 });
      if (!fs.existsSync(target)) return { ok: true };
    } catch (error) {
      if (index >= attempts - 1) {
        return { ok: false, error };
      }
    }
    await sleep(250 + index * 150);
  }
  return { ok: !fs.existsSync(target) };
}

function childLogTail(lines, max = 40) {
  return lines.slice(-max);
}

async function validateCapabilitiesToggle(baseUrl, output) {
  const before = await fetchJson(`${baseUrl}/v1/ui/capabilities`);
  const skills = Array.isArray(before.rows) ? before.rows.filter((row) => String(row.kind || "") === "skill") : [];
  const target = skills.find((row) => String(row.id || "").trim()) || null;
  if (!target) {
    fail("capabilities_toggle_missing_skill", { summary: before.summary || {} });
  }
  const skillId = String(target.id || "").trim();
  const originalEnabled = Boolean(target.enabled);
  const toggled = await fetchJson(`${baseUrl}/v1/ui/capabilities/skill/${encodeURIComponent(skillId)}/enabled`, {
    method: "POST",
    body: JSON.stringify({ enabled: !originalEnabled }),
  });
  const toggledRow = (Array.isArray(toggled.catalog?.rows) ? toggled.catalog.rows : []).find((row) => String(row.id || "") === skillId && String(row.kind || "") === "skill");
  if (!toggledRow || Boolean(toggledRow.enabled) === originalEnabled) {
    fail("capabilities_toggle_state_not_changed", { skill_id: skillId, original_enabled: originalEnabled, toggled: toggledRow || null });
  }
  const restored = await fetchJson(`${baseUrl}/v1/ui/capabilities/skill/${encodeURIComponent(skillId)}/enabled`, {
    method: "POST",
    body: JSON.stringify({ enabled: originalEnabled }),
  });
  const restoredRow = (Array.isArray(restored.catalog?.rows) ? restored.catalog.rows : []).find((row) => String(row.id || "") === skillId && String(row.kind || "") === "skill");
  if (!restoredRow || Boolean(restoredRow.enabled) !== originalEnabled) {
    fail("capabilities_toggle_restore_failed", { skill_id: skillId, original_enabled: originalEnabled, restored: restoredRow || null });
  }
  output.capabilities_toggle = {
    skill_id: skillId,
    original_enabled: originalEnabled,
    toggled_enabled: Boolean(toggledRow.enabled),
    restored_enabled: Boolean(restoredRow.enabled),
  };
  output.checks.push("capabilities_toggle_api_verified");
}

async function validateProjectMcpApproval(baseUrl, dataDir, pythonBin, output) {
  const serverPath = path.join(dataDir, "fake_project_mcp_server.py");
  const mcpPath = path.join(dataDir, ".mcp.json");
  fs.writeFileSync(
    serverPath,
    [
      "import json, sys",
      "for line in sys.stdin:",
      "    msg = json.loads(line)",
      "    sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':msg.get('id'),'result':{}}) + '\\n')",
      "    sys.stdout.flush()",
      "",
    ].join("\n"),
    "utf8",
  );
  fs.writeFileSync(
    mcpPath,
    JSON.stringify(
      {
        mcpServers: {
          dogfoodFake: {
            command: pythonBin,
            args: [serverPath],
            description: "Temporary reliability dogfood fake MCP server",
          },
        },
      },
      null,
      2,
    ),
    "utf8",
  );
  const refreshed = await fetchJson(`${baseUrl}/v1/ui/mcp/approvals`, {
    method: "POST",
    body: JSON.stringify({ decisions: [] }),
  });
  const pending = (Array.isArray(refreshed.mcp_project_servers) ? refreshed.mcp_project_servers : []).find((row) => {
    return String(row.server_id || "") === "dogfoodFake" || String(row.server_id || "") === "dogfoodfake";
  });
  if (!pending || String(pending.approval_state || "") !== "pending") {
    fail("project_mcp_pending_approval_missing", { servers: refreshed.mcp_project_servers || [] });
  }
  const serverId = String(pending.server_id || "").trim();
  const approved = await fetchJson(`${baseUrl}/v1/ui/mcp/approvals`, {
    method: "POST",
    body: JSON.stringify({ decisions: [{ server_id: serverId, decision: "approve" }] }),
  });
  const approvedRow = (Array.isArray(approved.mcp_project_servers) ? approved.mcp_project_servers : []).find((row) => String(row.server_id || "") === serverId);
  if (!approvedRow || String(approvedRow.approval_state || "") !== "approved") {
    fail("project_mcp_approval_not_persisted", { server_id: serverId, servers: approved.mcp_project_servers || [] });
  }
  output.project_mcp_approval = {
    server_id: serverId,
    pending_state: String(pending.approval_state || ""),
    approved_state: String(approvedRow.approval_state || ""),
    source_path: String(approvedRow.source_path || ""),
  };
  output.checks.push("project_mcp_approval_api_verified");
}

function validateMemoryConflictFixture(dataDir, pythonBin, output) {
  const code = [
    "import json, subprocess",
    "from pathlib import Path",
    "from agora.memory.project_memory import persist_project_shared_memory, sync_project_memory, project_memory_audit",
    `root = Path(${JSON.stringify(String(dataDir))})`,
    "remote = root / 'team-memory-remote'",
    "repo = root / 'memory-conflict-project'",
    "repo.mkdir(parents=True, exist_ok=True)",
    "subprocess.run(['git','init'], cwd=repo, check=True, stdout=subprocess.DEVNULL)",
    "subprocess.run(['git','config','user.name','Agora Dogfood'], cwd=repo, check=True)",
    "subprocess.run(['git','config','user.email','dogfood@example.com'], cwd=repo, check=True)",
    "local = persist_project_shared_memory(root=root, workspace_root=repo, layer='semantic', content='Topic: conflict\\nTakeaway: local reliability dogfood memory.', source_workflow_id='wf_desktop_dogfood', confidence=0.95, tags=['desktop_dogfood'])",
    "pushed = sync_project_memory(root, workspace_root=repo, remote_dir=remote, direction='push')",
    "remote_path = Path(str(pushed.get('remote_path') or ''))",
    "payload = json.loads(remote_path.read_text(encoding='utf-8'))",
    "payload['entries'][0]['content'] = 'Topic: conflict\\nTakeaway: remote teammate edited reliability dogfood memory.'",
    "remote_path.write_text(json.dumps(payload, ensure_ascii=True), encoding='utf-8')",
    "conflict = sync_project_memory(root, workspace_root=repo, remote_dir=remote, direction='bidirectional')",
    "after = json.loads(remote_path.read_text(encoding='utf-8'))",
    "audit = project_memory_audit(root, workspace_root=repo)",
    "print(json.dumps({'conflict': conflict, 'audit': audit, 'local_record': local, 'remote_after': after}, sort_keys=True))",
  ].join("\n");
  const result = spawnSync(pythonBin, ["-c", code], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONPATH: repoRoot },
    encoding: "utf8",
  });
  if (result.status !== 0) {
    fail("memory_conflict_fixture_failed", {
      stdout: String(result.stdout || ""),
      stderr: String(result.stderr || ""),
    });
  }
  const payload = JSON.parse(String(result.stdout || "{}"));
  const conflict = payload.conflict || {};
  const conflicts = Number(conflict.conflicts || 0);
  const remoteAfter = JSON.stringify(payload.remote_after || {});
  if (conflicts < 1) {
    fail("memory_conflict_not_visible", { payload });
  }
  if (!remoteAfter.includes("remote teammate edited")) {
    fail("memory_conflict_remote_was_overwritten", { payload });
  }
  output.memory_conflict = {
    conflict_count: conflicts,
    sync_status: String(conflict.reason || ""),
    auto_overwrite: Boolean(conflict.auto_overwrite || false),
    audit_summary: payload.audit?.summary || {},
  };
  output.checks.push("project_memory_conflict_fixture_visible");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const startedAt = Date.now();
  const userDataDir = args.userDataDir
    ? path.resolve(args.userDataDir)
    : await fsp.mkdtemp(path.join(os.tmpdir(), "agora-electron-live-regression-"));
  const dataDir = path.join(userDataDir, "agora-data");
  const output = {
    schema_version: "agora_desktop_electron_live_regression_v2",
    generated_at: nowIso(),
    status: "running",
    provider: String(args.provider || "live").trim(),
    initial_provider: String(args.initialProvider || "mock").trim(),
    repo_root: repoRoot,
    user_data_dir: userDataDir,
    data_dir: dataDir,
    checks: [],
    assertions: {},
  };
  let electron = null;
  let page = null;
  let browserWsUrl = "";
  const stdoutLines = [];
  const stderrLines = [];
  let currentPhase = "bootstrap";
  let currentAssertionKey = "";
  const setPhase = (value) => {
    currentPhase = String(value || "").trim() || currentPhase;
    output.current_stage = currentPhase;
  };
  const startAssertion = (key, stage, patch = {}) => {
    currentAssertionKey = String(key || "").trim();
    setPhase(stage);
    return setAssertion(output, currentAssertionKey, {
      stage: String(stage || "").trim(),
      status: "running",
      ...patch,
    });
  };
  const passAssertion = (key, patch = {}) => {
    const normalizedKey = String(key || "").trim();
    if (currentAssertionKey === normalizedKey) {
      currentAssertionKey = "";
    }
    return setAssertion(output, normalizedKey, {
      status: "passed",
      ...patch,
    });
  };
  const remainingTimeout = (minimumMs = 1000) => {
    const floorMs = Math.max(1000, Number(minimumMs) || 1000);
    const remaining = Number(args.timeoutMs || 0) - (Date.now() - startedAt);
    return Math.max(floorMs, remaining);
  };
  try {
    setPhase("bootstrap.workspace");
    await ensureDir(userDataDir);
    await ensureDir(dataDir);
    const desktopConfig = writeDesktopConfig(userDataDir, args);
    output.desktop_config = artifactDesktopConfig(desktopConfig);
    bootstrapWorkspace(dataDir, args.pythonBin);
    output.checks.push("bootstrap_workspace");

    setPhase("electron.launch");
    const cdpPort = await findFreePort(args.cdpPort);
    output.cdp_port = cdpPort;

    electron = spawn(args.electronBin, [".", `--remote-debugging-port=${cdpPort}`], {
      cwd: repoRoot,
      env: {
        ...process.env,
        AGORA_PYTHON_BIN: args.pythonBin,
        AGORA_DESKTOP_USER_DATA_DIR: userDataDir,
        AGORA_ENABLE_TEST_SUPPORT: args.validateTeamWorkspace ? "1" : String(process.env.AGORA_ENABLE_TEST_SUPPORT || ""),
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    electron.stdout.on("data", (chunk) => {
      stdoutLines.push(String(chunk || ""));
    });
    electron.stderr.on("data", (chunk) => {
      stderrLines.push(String(chunk || ""));
    });
    output.electron_pid = electron.pid;
    output.checks.push("launch_electron");

    setPhase("electron.debugger");
    const targets = await waitForDebuggerTargets(cdpPort, Math.min(args.timeoutMs, 40000));
    browserWsUrl = String((targets.version || {}).webSocketDebuggerUrl || "").trim();
    output.page_url = String((targets.page || {}).url || "");
    output.base_url = new URL(output.page_url).origin;
    output.checks.push("electron_remote_debugging");

    page = new CdpClient(String((targets.page || {}).webSocketDebuggerUrl || "").trim());
    await page.connect();
    setPhase("electron.page_ready");
    await waitForPageReady(page, Math.min(args.timeoutMs, 30000));
    output.checks.push("page_ready");

    const initialPillText = await waitForTextIncludes(
      page,
      "#model-status-pill",
      String(args.initialProvider || "mock").trim() === "live" ? "LIVE" : "MOCK",
      Math.min(args.timeoutMs, 12000),
    );
    output.model_status_before = initialPillText;
    output.checks.push("initial_model_status_pill");

    await click(page, "#open-settings");
    await waitForElementState(page, "#settings-overlay", { visible: true, timeoutMs: Math.min(args.timeoutMs, 12000) });
    output.checks.push("settings_overlay_opened");

    await setSelectValue(page, "#settings-provider", String(args.provider || "live").trim() === "mock" ? "mock" : "live");
    if (String(args.provider || "live").trim() === "live") {
      await setInputValue(page, "#settings-api-key", String(args.openrouterApiKey || desktopConfig.openrouterApiKey || "").trim());
    }
    await click(page, "#settings-save");

    const expectedProviderLabel = String(args.provider || "live").trim() === "mock" ? "MOCK" : "LIVE";
    output.model_status_after_save = await waitForTextIncludes(page, "#model-status-pill", expectedProviderLabel, Math.min(args.timeoutMs, 20000));
    output.checks.push("settings_saved_via_ui");
    output.checks.push("model_status_pill_updated");

    const settings = await fetchJson(`${output.base_url}/v1/ui/settings`);
    output.live_ready = Boolean(settings.live_ready);
    output.settings_mode = String(settings.mode || "");
    if (String(args.provider || "live").trim() === "live") {
      if (!settings.live_ready || String(settings.mode || "") !== "live") {
        fail("desktop_settings_not_live_ready", {
          live_ready: settings.live_ready,
          mode: settings.mode,
          validation_error: String(settings.validation_error || ""),
        });
      }
      output.checks.push("backend_settings_switched_to_live");
      output.checks.push("live_provider_ready");
    } else {
      output.checks.push("backend_settings_switched_to_mock");
    }

    await click(page, "#close-settings");
    await waitForElementState(page, "#settings-overlay", { visible: false, timeoutMs: Math.min(args.timeoutMs, 12000) });
    output.checks.push("settings_overlay_closed");

    setPhase("desktop_dogfood.capabilities_toggle");
    await validateCapabilitiesToggle(output.base_url, output);
    setPhase("desktop_dogfood.project_mcp_approval");
    await validateProjectMcpApproval(output.base_url, dataDir, args.pythonBin, output);
    setPhase("desktop_dogfood.memory_conflict");
    validateMemoryConflictFixture(dataDir, args.pythonBin, output);

    await click(page, "#new-session");
    output.checks.push("new_session_clicked");
    setPhase("session.bootstrap");
    const session = await waitForSession(output.base_url, Math.min(args.timeoutMs, 20000));
    output.session_id = String(session.session_id || "");
    output.session_title = String(session.title || session.session_topic || "");

    const domBefore = await getDomSnapshot(page);
    output.active_session_label_before = String(domBefore.activeSessionLabel || "");

    if (String(args.agentMode || "solo").trim() === "team") {
      setPhase("team.launch");
      await click(page, "#mode-debate");
      output.checks.push("team_mode_selected");
      await setSelectValue(page, "#debate-depth-select", String(args.teamId || "research-implement-verify").trim());
      output.team_id = String(args.teamId || "research-implement-verify").trim();
      output.checks.push("team_id_selected");
      await setTextareaValue(page, "#composer-input", args.prompt);
      await click(page, "#composer-send");
      output.checks.push("team_prompt_submitted_via_electron_ui");
        await waitForButtonByText(page, "Workspace", { rootSelector: "#conversation-thread", timeoutMs: Math.min(args.timeoutMs, 30000) });
        output.checks.push("team_run_rendered_in_conversation");
        if (args.validateTeamWorkspace) {
          setAssertion(output, "approval_member_tool", {
            stage: "team_workspace.approval.member_tool",
            status: "pending",
            request_class: "member_tool",
          });
          setAssertion(output, "approval_member_resume", {
            stage: "team_workspace.approval.member_resume",
            status: "pending",
            request_class: "member_resume",
          });
          setAssertion(output, "approval_leader_decision", {
            stage: "team_workspace.approval.leader_decision",
            status: "pending",
            request_class: "leader_decision",
          });
          setAssertion(output, "next_launch_member_resume", {
            stage: "team_workspace.next_launch.member_resume",
            status: "pending",
          });
          setAssertion(output, "next_launch_spawn_fresh", {
            stage: "team_workspace.next_launch.spawn_fresh",
            status: "pending",
          });
          setAssertion(output, "leader_live_provider", {
            stage: "team_workspace.live_provider.leader_plan",
            status: String(args.provider || "live").trim() === "live" ? "pending" : "skipped",
          });
          setAssertion(output, "live_provider_spawn_fresh", {
            stage: "team_workspace.live_provider.spawn_fresh",
            status: String(args.provider || "live").trim() === "live" ? "pending" : "skipped",
          });
          setPhase("team_workspace.open");
          const teamRun = await waitForTeamRun(output.base_url, output.session_id, output.team_id, Math.min(args.timeoutMs, 30000));
          output.team_run_id = String(teamRun.team_run_id || "");
          await clickButtonByText(page, "Workspace", { rootSelector: "#conversation-thread" });
          await waitForElementState(page, "#team-workspace-page", { visible: true, timeoutMs: Math.min(args.timeoutMs, 20000) });
          await waitForTextIncludes(page, "#team-workspace-content", "Team Summary", Math.min(args.timeoutMs, 20000));
          await waitForWorkspaceMembers(page, ["research", "implement"], Math.min(args.timeoutMs, 20000));
          output.team_workspace_title = await cdpText(page, "#team-workspace-title");
          output.team_workspace_status = await cdpText(page, "#team-workspace-status");
          output.team_workspace_preview = await cdpText(page, "#team-workspace-content");
          const explainabilityWorkspace = await fetchJson(`${output.base_url}/v1/ui/agents/teams/${encodeURIComponent(output.team_run_id)}/workspace?member_id=research`);
          const explainability = explainabilityWorkspace.workspace?.explainability || {};
          const explanationText = normalizeText(await cdpText(page, "#team-workspace-content"));
          for (const marker of ["Unified Explanation", "Leader Decision", "Dispatch Plan", "Approval", "Governor", "Immediate effect", "Next launch effect"]) {
            if (!explanationText.includes(marker)) {
              fail("team_workspace_explainability_marker_missing", { marker, preview: explanationText.slice(0, 1600) });
            }
          }
          if (String(explainability.schema_version || "") !== "agora_team_workspace_explainability_v1") {
            fail("team_workspace_explainability_schema_missing", { explainability });
          }
          if (!Array.isArray(explainability.member_explanations) || !explainability.member_explanations.length) {
            fail("team_workspace_explainability_members_missing", { explainability });
          }
          output.team_workspace_explainability = {
            schema_version: String(explainability.schema_version || ""),
            headline: String((explainability.summary || {}).headline || ""),
            member_count: Array.isArray(explainability.member_explanations) ? explainability.member_explanations.length : 0,
            governor_state: String((explainability.summary || {}).governor_state || ""),
            pending_approval_count: Number((explainability.summary || {}).pending_approval_count || 0),
          };
          output.checks.push("team_workspace_explainability_visible");
          output.checks.push("team_workspace_opened");

          await clickWorkspaceMember(page, "implement");
          await waitForWorkspaceMemberSelected(page, "implement", Math.min(args.timeoutMs, 15000));
          await waitForWorkspaceMemberContext(page, "implement", Math.min(args.timeoutMs, 15000));
          await clickWorkspaceMember(page, "research");
          await waitForWorkspaceMemberSelected(page, "research", Math.min(args.timeoutMs, 15000));
          await waitForWorkspaceMemberContext(page, "research", Math.min(args.timeoutMs, 15000));
          output.checks.push("team_workspace_member_switch");

          const liveBudgetHint = { token_budget: 77 };
          const researchResumePromptAppend = "Electron research resume next-launch prompt.";
          const implementFreshPromptAppend = "Electron implement fresh worker next-launch prompt.";
          await setSelectValue(page, '[data-runtime-config-field="access_mode"]', "chat_only");
          await setSelectValue(page, '[data-runtime-config-field="permission_mode"]', "plan");
          await setTextareaValue(page, '[data-runtime-config-field="budget_hint"]', JSON.stringify(liveBudgetHint, null, 2));
          await click(page, '[data-workspace-runtime-save="live"]');

          const liveWorkspace = await waitFor(async () => {
            const payload = await fetchJson(`${output.base_url}/v1/ui/agents/teams/${encodeURIComponent(output.team_run_id)}/workspace?member_id=research`);
            const member = (Array.isArray(payload.workspace?.members) ? payload.workspace.members : []).find((item) => String(item.member_id || "") === "research");
            const runtimeConfig = member?.runtime_config || {};
            if (String(runtimeConfig.access_mode || "") !== "chat_only") return null;
            if (String(runtimeConfig.permission_mode || "") !== "plan") return null;
            if (Number((runtimeConfig.budget_hint || {}).token_budget || 0) !== 77) return null;
            return payload;
          }, Math.min(args.timeoutMs, 20000), "workspace live runtime config save");
          output.workspace_live_runtime_config = (liveWorkspace.workspace.members || []).find((item) => String(item.member_id || "") === "research")?.runtime_config || {};
          output.checks.push("team_workspace_live_runtime_editor_saved");
          if (String(args.provider || "live").trim() === "live") {
            startAssertion("leader_live_provider", "team_workspace.live_provider.leader_plan");
            const leaderPlanEvidence = await waitFor(async () => {
              const payload = await fetchJson(`${output.base_url}/v1/ui/agents/teams/${encodeURIComponent(output.team_run_id)}/workspace?member_id=research`);
              const leaderTranscript = Array.isArray(payload.workspace?.selected_member_detail?.leader_transcript)
                ? payload.workspace.selected_member_detail.leader_transcript
                : [];
              const liveTurn = leaderTranscript.find((item) => {
                const meta = item && typeof item === "object" ? (item.llm_meta || {}) : {};
                return String(meta.provider || "").trim() === "openrouter";
              });
              return liveTurn || null;
            }, Math.min(args.timeoutMs, 60000), "team leader live provider evidence");
            output.team_live_provider_leader_plan = {
              provider: String((leaderPlanEvidence.llm_meta || {}).provider || ""),
              model: String((leaderPlanEvidence.llm_meta || {}).model || ""),
              round_name: String((leaderPlanEvidence.llm_meta || {}).round_name || ""),
              kind: String(leaderPlanEvidence.kind || ""),
            };
            passAssertion("leader_live_provider", {
              provider: output.team_live_provider_leader_plan.provider,
              model: output.team_live_provider_leader_plan.model,
              round_name: output.team_live_provider_leader_plan.round_name,
              kind: output.team_live_provider_leader_plan.kind,
            });
            output.checks.push("team_workspace_live_provider_leader_plan");
          }

          await setSelectValue(page, '[data-runtime-config-field="worktree_mode"]', "isolated");
          await setTextareaValue(page, '[data-runtime-config-field="prompt_append"]', researchResumePromptAppend);
          await click(page, '[data-workspace-runtime-save="next"]');

          const nextWorkspace = await waitFor(async () => {
            const payload = await fetchJson(`${output.base_url}/v1/ui/agents/teams/${encodeURIComponent(output.team_run_id)}/workspace?member_id=research`);
            const member = (Array.isArray(payload.workspace?.members) ? payload.workspace.members : []).find((item) => String(item.member_id || "") === "research");
            const nextLaunchConfig = member?.next_launch_config || {};
            const applyState = member?.apply_state || {};
            if (String(nextLaunchConfig.worktree_mode || "") !== "isolated") return null;
            if (String(nextLaunchConfig.prompt_append || "") !== researchResumePromptAppend) return null;
            if (String(applyState.worktree_mode || "") !== "next_spawn_or_retry") return null;
            return payload;
          }, Math.min(args.timeoutMs, 20000), "workspace next launch config save");
          output.workspace_next_launch_config = (nextWorkspace.workspace.members || []).find((item) => String(item.member_id || "") === "research")?.next_launch_config || {};
          output.checks.push("team_workspace_next_launch_editor_saved");

          await clickWorkspaceMember(page, "implement");
          await waitForWorkspaceMemberSelected(page, "implement", Math.min(args.timeoutMs, 15000));
          await waitForWorkspaceMemberContext(page, "implement", Math.min(args.timeoutMs, 15000));
          await setSelectValue(page, '[data-runtime-config-field="access_mode"]', "chat_only");
          await setSelectValue(page, '[data-runtime-config-field="permission_mode"]', "default");
          await setTextareaValue(page, '[data-runtime-config-field="budget_hint"]', JSON.stringify({ token_budget: 33 }, null, 2));
          await click(page, '[data-workspace-runtime-save="live"]');

          const implementLiveWorkspace = await waitFor(async () => {
            const payload = await fetchJson(`${output.base_url}/v1/ui/agents/teams/${encodeURIComponent(output.team_run_id)}/workspace?member_id=implement`);
            const member = (Array.isArray(payload.workspace?.members) ? payload.workspace.members : []).find((item) => String(item.member_id || "") === "implement");
            const runtimeConfig = member?.runtime_config || {};
            if (String(runtimeConfig.access_mode || "") !== "chat_only") return null;
            if (String(runtimeConfig.permission_mode || "") !== "default") return null;
            if (Number((runtimeConfig.budget_hint || {}).token_budget || 0) !== 33) return null;
            return payload;
          }, Math.min(args.timeoutMs, 20000), "workspace implement live runtime config save");
          output.workspace_live_runtime_config_implement = (implementLiveWorkspace.workspace.members || []).find((item) => String(item.member_id || "") === "implement")?.runtime_config || {};
          output.checks.push("team_workspace_live_runtime_editor_saved_implement");

          await setSelectValue(page, '[data-runtime-config-field="worktree_mode"]', "isolated");
          await setTextareaValue(page, '[data-runtime-config-field="prompt_append"]', implementFreshPromptAppend);
          await click(page, '[data-workspace-runtime-save="next"]');

          const implementNextWorkspace = await waitFor(async () => {
            const payload = await fetchJson(`${output.base_url}/v1/ui/agents/teams/${encodeURIComponent(output.team_run_id)}/workspace?member_id=implement`);
            const member = (Array.isArray(payload.workspace?.members) ? payload.workspace.members : []).find((item) => String(item.member_id || "") === "implement");
            const nextLaunchConfig = member?.next_launch_config || {};
            const applyState = member?.apply_state || {};
            if (String(nextLaunchConfig.worktree_mode || "") !== "isolated") return null;
            if (String(nextLaunchConfig.prompt_append || "") !== implementFreshPromptAppend) return null;
            if (String(applyState.worktree_mode || "") !== "next_spawn_or_retry") return null;
            return payload;
          }, Math.min(args.timeoutMs, 20000), "workspace implement next launch config save");
          output.workspace_next_launch_config_implement = (implementNextWorkspace.workspace.members || []).find((item) => String(item.member_id || "") === "implement")?.next_launch_config || {};
          output.checks.push("team_workspace_spawn_fresh_next_launch_editor_saved");

          output.workspace_git_ready = ensureGitRepo(dataDir);
          output.checks.push("team_workspace_git_ready");

          const seeded = await fetchJson(`${output.base_url}/v1/ui/agents/teams/${encodeURIComponent(output.team_run_id)}/test-support/approval-plane`, {
            method: "POST",
            body: JSON.stringify({
              tool_member_id: "implement",
              tool_action_id: "act_tool",
              tool_action: "read_file",
              tool_title: "Read file",
              tool_command_text: "Need tool approval",
              resume_member_id: "research",
              resume_outcome: "requeued",
              resume_message: "Resume the interrupted research workflow with the mailbox delta.",
              leader_task_member_id: "implement",
              leader_target_member_id: "implement",
              leader_route: "spawn_fresh",
              leader_summary: "Require explicit approval before spawning a fresh implement worker.",
              leader_message: "Spawn a fresh implement worker using the next-launch runtime config.",
            }),
          });
          output.approval_plane_seed = seeded.seed || {};
          output.checks.push("team_workspace_approval_plane_seeded");
          await clickWorkspaceMember(page, "research");
          await waitForWorkspaceMemberSelected(page, "research", Math.min(args.timeoutMs, 15000));
          await waitForWorkspaceMemberContext(page, "research", Math.min(args.timeoutMs, 15000));

          const toolActorId = String((((seeded.seed || {}).member_tool) || {}).actor_id || "").trim();
          const resumeActorId = String((((seeded.seed || {}).member_resume) || {}).actor_id || "").trim();
          const leaderActorId = String((((seeded.seed || {}).leader_decision) || {}).actor_id || "").trim();
          if (!toolActorId || !resumeActorId || !leaderActorId) {
            fail("approval_plane_seed_missing_actor_ids", { seeded });
          }

          await click(page, '[data-workspace-approval-filter="all"]');
          await waitForElementState(page, `[data-workspace-approval-card="${toolActorId}"]`, {
            visible: true,
            timeoutMs: Math.min(args.timeoutMs, 20000),
          });
          await waitForElementState(page, `[data-workspace-approval-card="${resumeActorId}"]`, {
            visible: true,
            timeoutMs: Math.min(args.timeoutMs, 20000),
          });
          await waitForElementState(page, `[data-workspace-approval-card="${leaderActorId}"]`, {
            visible: true,
            timeoutMs: Math.min(args.timeoutMs, 20000),
          });
          output.approval_plane_cards = {
            member_tool: await cdpText(page, `[data-workspace-approval-card="${toolActorId}"]`),
            member_resume: await cdpText(page, `[data-workspace-approval-card="${resumeActorId}"]`),
            leader_decision: await cdpText(page, `[data-workspace-approval-card="${leaderActorId}"]`),
          };
          output.checks.push("team_workspace_all_approval_classes_visible");

          await click(page, '[data-workspace-approval-filter="member_tool"]');
          await waitForElementState(page, `[data-workspace-approval-card="${toolActorId}"]`, {
            visible: true,
            timeoutMs: Math.min(args.timeoutMs, 20000),
          });
          startAssertion("approval_member_tool", "team_workspace.approval.member_tool", { actor_id: toolActorId });
          await click(page, `[data-workspace-approval-card="${toolActorId}"] [data-workspace-approval="approve"]`);
          const resolvedToolApproval = await waitForApprovalActorState(
            output.base_url,
            output.team_run_id,
            toolActorId,
            Math.min(args.timeoutMs, 30000),
          );
          output.member_tool_approval = {
            actor_id: String(resolvedToolApproval.actor_id || ""),
            status: String(resolvedToolApproval.status || ""),
            request_class: String(resolvedToolApproval.request_class || ""),
          };
          passAssertion("approval_member_tool", {
            actor_id: output.member_tool_approval.actor_id,
            approval_status: output.member_tool_approval.status,
            request_class: output.member_tool_approval.request_class,
          });
          output.checks.push("team_workspace_member_tool_approved");

          await click(page, '[data-workspace-approval-filter="member_resume"]');
          await waitForElementState(page, `[data-workspace-approval-card="${resumeActorId}"]`, {
            visible: true,
            timeoutMs: Math.min(args.timeoutMs, 20000),
          });
          output.member_resume_card_preview = await cdpText(page, `[data-workspace-approval-card="${resumeActorId}"]`);
          output.checks.push("team_workspace_member_resume_visible");

          startAssertion("approval_member_resume", "team_workspace.approval.member_resume", { actor_id: resumeActorId });
          await click(page, `[data-workspace-approval-card="${resumeActorId}"] [data-workspace-approval="approve"]`);
          const resolvedApproval = await waitForApprovalActorState(
            output.base_url,
            output.team_run_id,
            resumeActorId,
            Math.min(args.timeoutMs, 30000),
          );
          output.member_resume_approval = {
            actor_id: String(resolvedApproval.actor_id || ""),
            status: String(resolvedApproval.status || ""),
            request_class: String(resolvedApproval.request_class || ""),
          };
          passAssertion("approval_member_resume", {
            actor_id: output.member_resume_approval.actor_id,
            approval_status: output.member_resume_approval.status,
            request_class: output.member_resume_approval.request_class,
          });
          output.checks.push("team_workspace_member_resume_approved");

          const queuePath = path.join(dataDir, "runtime", "task_queue.jsonl");
          startAssertion("next_launch_member_resume", "team_workspace.next_launch.member_resume", {
            workflow_id: String((((seeded.seed || {}).member_resume) || {}).workflow_id || "").trim(),
          });
          const resumeTask = await waitForResumeQueueTaskWithPrompt(
            queuePath,
            output.session_id,
            String((((seeded.seed || {}).member_resume) || {}).workflow_id || "").trim(),
            researchResumePromptAppend,
            Math.min(args.timeoutMs, 30000),
          );
          output.member_resume_task = {
            task_id: String(resumeTask.task_id || ""),
            status: String(resumeTask.status || ""),
            workflow_id: String((((resumeTask.request || {}).resume_workflow) || {}).workflow_id || ""),
          };
          const memberResumeContinuation = normalizeText(String((((resumeTask.request || {}).resume_workflow) || {}).continuation_context || ""));
          output.member_resume_continuation_preview = memberResumeContinuation.slice(0, 800);
          if (!memberResumeContinuation.includes("Next launch operator instructions")) {
            fail("member_resume_missing_next_launch_overlay", { resumeTask });
          }
          if (!memberResumeContinuation.includes(researchResumePromptAppend)) {
            fail("member_resume_missing_prompt_append", { continuation_preview: output.member_resume_continuation_preview });
          }
          passAssertion("next_launch_member_resume", {
            task_id: output.member_resume_task.task_id,
            workflow_id: output.member_resume_task.workflow_id,
            task_status: output.member_resume_task.status,
            overlay_present: true,
            prompt_append_present: true,
            prompt_append: researchResumePromptAppend,
          });
          output.checks.push("team_workspace_member_resume_enqueued");
          output.checks.push("team_workspace_member_resume_consumed_next_launch_config");

          await click(page, '[data-workspace-approval-filter="leader_decision"]');
          await waitForElementState(page, `[data-workspace-approval-card="${leaderActorId}"]`, {
            visible: true,
            timeoutMs: Math.min(args.timeoutMs, 20000),
          });
          output.leader_decision_card_preview = await cdpText(page, `[data-workspace-approval-card="${leaderActorId}"]`);
          startAssertion("approval_leader_decision", "team_workspace.approval.leader_decision", {
            actor_id: leaderActorId,
            route: String((((seeded.seed || {}).leader_decision) || {}).route || "").trim(),
            turn_key: String((((seeded.seed || {}).leader_decision) || {}).turn_key || "").trim(),
          });
          await click(page, `[data-workspace-approval-card="${leaderActorId}"] [data-workspace-approval="approve"]`);
          const resolvedLeaderApproval = await waitForApprovalActorState(
            output.base_url,
            output.team_run_id,
            leaderActorId,
            Math.min(args.timeoutMs, 30000),
          );
          output.leader_decision_approval = {
            actor_id: String(resolvedLeaderApproval.actor_id || ""),
            status: String(resolvedLeaderApproval.status || ""),
            request_class: String(resolvedLeaderApproval.request_class || ""),
          };
          passAssertion("approval_leader_decision", {
            actor_id: output.leader_decision_approval.actor_id,
            approval_status: output.leader_decision_approval.status,
            request_class: output.leader_decision_approval.request_class,
          });
          output.checks.push("team_workspace_leader_decision_approved");

          const taskPayloadPath = path.join(dataDir, "runtime", "agent_team_tasks", `${output.team_run_id}.json`);
          const leaderDecisionTurnKey = String((((seeded.seed || {}).leader_decision) || {}).turn_key || "").trim();
          startAssertion("next_launch_spawn_fresh", "team_workspace.next_launch.spawn_fresh", {
            source_member_id: "implement",
            spawn_turn_key: leaderDecisionTurnKey,
          });
          const freshTask = await waitForTeamFreshTask(taskPayloadPath, "implement", {
            timeoutMs: Math.min(args.timeoutMs, 30000),
            spawnTurnKey: leaderDecisionTurnKey,
          });
          output.leader_spawn_fresh_task = {
            task_id: String(freshTask.task_id || ""),
            member_id: String(freshTask.member_id || ""),
            source_member_id: String(freshTask.source_member_id || ""),
            worktree_mode: String(freshTask.worktree_mode || ""),
            instance_id: String(freshTask.instance_id || ""),
            spawn_turn_key: String(freshTask.spawn_turn_key || ""),
          };
          if (String(freshTask.worktree_mode || "").trim() !== "isolated") {
            fail("spawn_fresh_task_missing_isolated_worktree", { freshTask });
          }
          if (!String(freshTask.instance_id || "").trim()) {
            fail("spawn_fresh_task_missing_instance", { freshTask });
          }
          const freshSidechainPath = path.join(dataDir, "runtime", "agent_sidechains", `agent-${String(freshTask.instance_id || "").trim()}.jsonl`);
          const freshSidechainRows = await waitForInstanceSidechain(freshSidechainPath, Math.min(args.timeoutMs, 30000));
          const initialPromptRow = freshSidechainRows.find((row) => String(row.kind || "").trim() === "initial_prompt") || freshSidechainRows[0] || {};
          const initialPromptText = normalizeText(String(initialPromptRow.text || initialPromptRow.preview || ""));
          output.leader_spawn_fresh_sidechain_preview = initialPromptText.slice(0, 800);
          if (!initialPromptText.includes("Next launch operator instructions")) {
            fail("spawn_fresh_sidechain_missing_next_launch_overlay", { initialPromptText });
          }
          if (!initialPromptText.includes(implementFreshPromptAppend)) {
            fail("spawn_fresh_sidechain_missing_prompt_append", { initialPromptText });
          }
          passAssertion("next_launch_spawn_fresh", {
            task_id: output.leader_spawn_fresh_task.task_id,
            member_id: output.leader_spawn_fresh_task.member_id,
            source_member_id: output.leader_spawn_fresh_task.source_member_id,
            instance_id: output.leader_spawn_fresh_task.instance_id,
            worktree_mode: output.leader_spawn_fresh_task.worktree_mode,
            spawn_turn_key: output.leader_spawn_fresh_task.spawn_turn_key,
            overlay_present: true,
            prompt_append_present: true,
            prompt_append: implementFreshPromptAppend,
            sidechain_path: freshSidechainPath,
          });
          output.checks.push("team_workspace_spawn_fresh_consumed_next_launch_config");
          if (String(args.provider || "live").trim() === "live") {
            startAssertion("live_provider_spawn_fresh", "team_workspace.live_provider.spawn_fresh", {
              source_member_id: "implement",
            });
            const liveFresh = await waitForFreshTaskWithStreamActor(
              taskPayloadPath,
              queuePath,
              "implement",
              remainingTimeout(15000),
            );
            output.spawn_fresh_candidates = liveFresh.candidates;
            output.team_live_provider_spawn_fresh = {
              task_id: String((liveFresh.freshTask || {}).task_id || ""),
              member_id: String((liveFresh.freshTask || {}).member_id || ""),
              instance_id: String((liveFresh.freshTask || {}).instance_id || ""),
              runtime_task_id: String((liveFresh.freshTask || {}).runtime_task_id || ""),
              workflow_id: String((((liveFresh.freshTask || {}).live_provider) || {}).workflow_id || ""),
              call_id: String((((liveFresh.freshTask || {}).live_provider) || {}).call_id || ""),
              sidechain_path: String((liveFresh.freshTask || {}).sidechain_path || ""),
              provider_stream_event_count: Number((liveFresh.freshTask || {}).provider_stream_event_count || 0),
              provider_stream_actor_event_count: Number((liveFresh.freshTask || {}).provider_stream_actor_event_count || 0),
              latest_stream_event_type: String((((liveFresh.freshTask || {}).live_provider) || {}).latest_stream_event_type || ""),
              latest_actor: (((liveFresh.freshTask || {}).live_provider) || {}).latest_actor || null,
              queue: ((liveFresh.freshTask || {}).queue) || {},
            };
            passAssertion("live_provider_spawn_fresh", {
              task_id: output.team_live_provider_spawn_fresh.task_id,
              member_id: output.team_live_provider_spawn_fresh.member_id,
              instance_id: output.team_live_provider_spawn_fresh.instance_id,
              runtime_task_id: output.team_live_provider_spawn_fresh.runtime_task_id,
              workflow_id: output.team_live_provider_spawn_fresh.workflow_id,
              call_id: output.team_live_provider_spawn_fresh.call_id,
              provider_stream_event_count: output.team_live_provider_spawn_fresh.provider_stream_event_count,
              provider_stream_actor_event_count: output.team_live_provider_spawn_fresh.provider_stream_actor_event_count,
              latest_actor: output.team_live_provider_spawn_fresh.latest_actor,
            });
            output.checks.push("team_workspace_spawn_fresh_live_provider_stream");
          }

          setPhase("team_workspace.native_pane_focus_mock");
          const paneFocus = await fetchJson(`${output.base_url}/v1/ui/agents/teams/${encodeURIComponent(output.team_run_id)}/pane/focus`, {
            method: "POST",
            body: JSON.stringify({ member_id: "research" }),
          });
          const nativeFocus = paneFocus.native_focus || {};
          const pane = paneFocus.pane || {};
          const reason = String(nativeFocus.reason || "");
          if (!Boolean(pane.focus_supported) || !["browser_runtime_output_pane", "no_native_pane_backend"].includes(reason)) {
            fail("native_pane_focus_mock_unexpected", { native_focus: nativeFocus, pane: paneFocus.pane || {} });
          }
          output.native_pane_focus = {
            member_id: String((paneFocus.member || {}).member_id || (paneFocus.member || {}).team_member_id || ""),
            pane_id: String(pane.pane_id || ""),
            focus_supported: Boolean(pane.focus_supported),
            native_focus_supported: Boolean(nativeFocus.native_focus_supported),
            reason,
          };
          output.checks.push("native_pane_focus_mock_verified");

          await click(page, "#team-workspace-back");
          await waitForElementState(page, "#team-workspace-page", { visible: false, timeoutMs: Math.min(args.timeoutMs, 12000) });
          output.checks.push("team_workspace_closed");
        }
    } else {
      await setTextareaValue(page, "#composer-input", args.prompt);
      await click(page, "#composer-send");
      output.checks.push("prompt_submitted_via_electron_ui");

      const queuePath = path.join(dataDir, "runtime", "task_queue.jsonl");
      const task = await waitForTask(queuePath, output.session_id, args.timeoutMs);
      output.task_id = String(task.task_id || "");
      output.task_status = String(task.status || "");
      output.task_error = String(task.error || "");
      output.workflow_id = String(task.workflow_id || "");

      const sidechainPath = path.join(dataDir, "runtime", "agent_sidechains", `agent-chat_runtime_${output.task_id}.jsonl`);
      const actorCounts = await waitForStreamActor(sidechainPath, Math.min(args.timeoutMs, 30000));
      output.sidechain_path = sidechainPath;
      output.provider_stream_event_count = actorCounts.provider_stream_event_count;
      output.provider_stream_actor_event_count = actorCounts.provider_stream_actor_event_count;
      output.provider_stream_call_id = String(actorCounts.call_id || "");
      output.provider_stream_latest_actor = actorCounts.latest_actor || null;
      output.checks.push("provider_stream_actor_ledger");

      if (output.task_status !== "completed") {
        fail("task_not_completed", { task_status: output.task_status, task_error: output.task_error });
      }
      output.checks.push("queue_terminal_completed");

      const workflowPath = path.join(dataDir, "sessions", output.session_id, "workflows", output.workflow_id, "workflow.json");
      if (!fs.existsSync(workflowPath)) {
        fail("workflow_json_missing", { workflowPath });
      }
      const workflow = readJsonFile(workflowPath);
      output.workflow_path = workflowPath;
      output.workflow_status = String(workflow.status || workflow.workflow_status || "");
      output.answer_text = normalizeText(((workflow.chat_result || {}).answer_text) || "");
      output.llm_provider = String((((workflow.chat_result || {}).llm_meta) || {}).provider || "");
      output.model_id = String((((workflow.chat_result || {}).llm_meta) || {}).model || workflow.chat_model_id || "");
      if (output.workflow_status !== "completed") {
        fail("workflow_not_completed", { workflow_status: output.workflow_status });
      }
      if (args.provider === "live" && output.llm_provider !== "openrouter") {
        fail("unexpected_llm_provider", { llm_provider: output.llm_provider });
      }
      output.checks.push("workflow_completed");

      const requiredMarker = String(args.expectedMarker || "").trim().toUpperCase();
      const normalizedAnswer = normalizeText(output.answer_text).toUpperCase();
      if (requiredMarker && !normalizedAnswer.includes(requiredMarker)) {
        fail("answer_missing_expected_marker", {
          marker: requiredMarker,
          answer_text: output.answer_text,
        });
      }
      output.checks.push("workflow_answer_contains_expected_markers");

      const domAfter = await waitFor(async () => {
        const snapshot = await getDomSnapshot(page);
        const text = normalizeText(snapshot.threadText).toUpperCase();
        if (requiredMarker && !text.includes(requiredMarker)) {
          return null;
        }
        return snapshot;
      }, Math.min(args.timeoutMs, 30000), "rendered conversation answer");
      output.model_status_after = String(domAfter.modelStatus || "");
      output.active_session_label_after = String(domAfter.activeSessionLabel || "");
      output.rendered_thread_preview = normalizeText(String(domAfter.threadText || "")).slice(0, 800);
      output.checks.push("electron_dom_rendered_answer");
    }

    output.duration_ms = Date.now() - startedAt;
    setPhase("completed");
    output.status = "passed";
    await page.close();
    page = null;
  } catch (error) {
    output.duration_ms = Date.now() - startedAt;
    output.status = "failed";
    output.failure_stage = currentPhase;
    output.error = String(error && error.message ? error.message : error);
    if (currentAssertionKey) {
      setAssertion(output, currentAssertionKey, {
        status: "failed",
        stage: currentPhase,
        error: output.error,
      });
      currentAssertionKey = "";
    }
    if (error && typeof error === "object") {
      if (error.body) output.error_body = String(error.body);
      if (error.stdout) output.error_stdout = String(error.stdout);
      if (error.stderr) output.error_stderr = String(error.stderr);
      if (error.hint) output.error_hint = String(error.hint);
      if (error.lastError) output.last_error = String(error.lastError);
      const errorContext = {};
      for (const [key, value] of Object.entries(error)) {
        if (["body", "stdout", "stderr", "hint", "lastError", "stack"].includes(String(key || ""))) continue;
        errorContext[key] = value;
      }
      if (Object.keys(errorContext).length) {
        output.error_context = errorContext;
      }
    }
    throw error;
  } finally {
    output.electron_stdout_tail = childLogTail(stdoutLines.map((item) => item.trim()).filter(Boolean));
    output.electron_stderr_tail = childLogTail(stderrLines.map((item) => item.trim()).filter(Boolean));
    const cleanup = {
      required: true,
      passed: false,
      cdp_closed: false,
      browser_close_requested: false,
      process_exited: false,
      temp_dir_removed: false,
      keep_artifacts: Boolean(args.keepArtifacts),
      errors: [],
    };
    try {
      if (page) {
        await page.close();
        cleanup.cdp_closed = true;
      } else {
        cleanup.cdp_closed = true;
      }
    } catch (error) {
      cleanup.errors.push(`page_close:${String(error && error.message ? error.message : error)}`);
    }
    try {
      await gracefulClose(browserWsUrl);
      cleanup.browser_close_requested = true;
    } catch (error) {
      cleanup.errors.push(`browser_close:${String(error && error.message ? error.message : error)}`);
    }
    if (electron && !electron.killed) {
      try {
        electron.kill("SIGTERM");
      } catch (error) {
        cleanup.errors.push(`electron_sigterm:${String(error && error.message ? error.message : error)}`);
      }
    }
    cleanup.process_exited = await waitForChildExit(electron, 7000);
    if (electron && !cleanup.process_exited) {
      try {
        electron.kill("SIGKILL");
      } catch (error) {
        cleanup.errors.push(`electron_sigkill:${String(error && error.message ? error.message : error)}`);
      }
      cleanup.process_exited = await waitForChildExit(electron, 3000);
    }
    if (!args.keepArtifacts) {
      const removed = await removeDirWithRetry(userDataDir);
      cleanup.temp_dir_removed = Boolean(removed.ok && !fs.existsSync(userDataDir));
      if (!cleanup.temp_dir_removed && removed.error) {
        cleanup.errors.push(`temp_dir_remove:${String(removed.error && removed.error.message ? removed.error.message : removed.error)}`);
      }
    } else {
      cleanup.temp_dir_removed = false;
    }
    cleanup.passed = Boolean(cleanup.cdp_closed && cleanup.browser_close_requested && cleanup.process_exited && (cleanup.temp_dir_removed || args.keepArtifacts));
    output.cleanup = cleanup;
    output.cleaned_up = cleanup.passed;
    if (cleanup.required && !cleanup.passed && output.status === "passed") {
      output.status = "failed";
      output.failure_stage = output.failure_stage || "cleanup";
      output.error = output.error || "desktop_cleanup_failed";
    }
    const text = JSON.stringify(redactSecrets(output), null, 2);
    if (args.output) {
      await ensureDir(path.dirname(path.resolve(args.output)));
      await fsp.writeFile(path.resolve(args.output), text + "\n", "utf8");
    }
    process.stdout.write(`${text}\n`);
    if (output.status !== "passed") {
      process.exitCode = 1;
    }
  }
}

main().catch(() => {
  process.exitCode = 1;
});
