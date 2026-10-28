const sessionId = crypto.randomUUID();
const thread = document.querySelector("#thread");
const runlog = document.querySelector("#runlog");
const runlogList = document.querySelector("#runlog-list");
const runlogEmpty = document.querySelector("#runlog-empty");
const runlogStatus = document.querySelector("#runlog-status");
const runlogCopy = document.querySelector("#runlog-copy");
const runlogClear = document.querySelector("#runlog-clear");
const sendButton = document.querySelector("#send");
const messageInput = document.querySelector("#message");
const TOOL_NAMES = [
  "parse_rent_roll_file",
  "score_vacancy",
  "fit_vacancy",
  "load_skill",
  "save_fit",
  "load_fit",
  "update_plan_status",
  "create_plan",
  "update_plan",
  "reflection",
];
const TOOL_NAME_RE = new RegExp(`\\b(${TOOL_NAMES.join("|")})\\b`, "g");

let busy = false;
let rows = [];
let spinner = null;
let turn = 0;

function show(text, who) {
  const item = document.createElement("div");
  item.className = `bubble ${who}`;
  item.textContent = text;
  thread.appendChild(item);
  item.scrollIntoView({ behavior: "smooth" });
  return item;
}

function setBusy(on) {
  busy = on;
  sendButton.disabled = on;
  messageInput.disabled = on;
  document.querySelector("#file").disabled = on;
  document.querySelectorAll("#chips .chip").forEach((chip) => {
    chip.disabled = on;
  });
  if (on) {
    if (!spinner) {
      spinner = show("", "agent");
      spinner.classList.add("working");
      spinner.setAttribute("aria-busy", "true");
      const mark = document.createElement("span");
      mark.className = "spinner";
      mark.setAttribute("aria-hidden", "true");
      spinner.append(mark, document.createTextNode("Agent is working…"));
    }
  } else if (spinner) {
    spinner.remove();
    spinner = null;
  }
  renderStatus();
}

function statusText() {
  const last = rows[rows.length - 1];
  if (!last) return busy ? "waiting for the first step…" : "idle";
  const step = last.step || "log";
  const msg = String(last.message || "").split("\n")[0].trim();
  if (!busy && step === "summary") return msg;
  const line = msg ? `${step} · ${msg}` : step;
  return busy ? `running · ${line}` : line;
}

function renderStatus() {
  runlogStatus.replaceChildren();
  if (busy) {
    const mark = document.createElement("span");
    mark.className = "spinner";
    mark.setAttribute("aria-hidden", "true");
    runlogStatus.append(mark);
  }
  runlogStatus.append(document.createTextNode(statusText()));
}

function fillToolMessage(el, text) {
  const source = String(text || "");
  el.replaceChildren();
  TOOL_NAME_RE.lastIndex = 0;
  let last = 0;
  let match;
  while ((match = TOOL_NAME_RE.exec(source))) {
    if (match.index > last) el.append(document.createTextNode(source.slice(last, match.index)));
    const strong = document.createElement("strong");
    strong.textContent = match[0];
    el.append(strong);
    last = match.index + match[0].length;
  }
  if (last < source.length) el.append(document.createTextNode(source.slice(last)));
}

function checklistRow(item) {
  const row = document.createElement("li");
  row.className = `check-row ${item.status || ""}`.trim();
  const status = document.createElement("span");
  status.className = "check-status";
  status.textContent = item.status ? `[${item.status}]` : "";
  const tool = document.createElement("span");
  tool.className = "check-tool";
  tool.textContent = item.tool || "";
  row.append(status, tool);
  if (item.reason) {
    const reason = document.createElement("span");
    reason.className = "check-reason";
    reason.textContent = item.reason;
    row.append(reason);
  }
  return row;
}

function renderLog() {
  runlogList.replaceChildren();
  rows.forEach((row, index) => {
    const item = document.createElement("li");
    item.className = `log-line ${row.step || ""} ${row.status || ""}`.trim();
    const step = document.createElement("span");
    step.className = "log-step";
    step.textContent = `${row.step} (${index + 1})`;
    const msg = document.createElement("span");
    msg.className = "log-msg";
    if (row.step === "plan" && Array.isArray(row.items)) {
      const list = document.createElement("ol");
      list.className = "check-rows";
      list.dataset.checklist = "turn";
      row.items.forEach((entry) => list.append(checklistRow(entry)));
      msg.append(list);
    } else if (row.step === "tool") {
      fillToolMessage(msg, row.message || "");
    } else {
      msg.textContent = row.message || "";
    }
    item.append(step, msg);
    runlogList.appendChild(item);
  });
  runlogEmpty.hidden = rows.length > 0;
  runlogCopy.disabled = rows.length === 0;
  runlogClear.disabled = rows.length === 0;
  renderStatus();
  const body = document.querySelector("#runlog-body");
  if (body && body.scrollHeight > body.clientHeight + 8) body.scrollTop = body.scrollHeight;
}

function addLog(row) {
  const stamped = { ...row, turn };
  if (row.step === "plan" && Array.isArray(row.items)) {
    const idx = rows.findIndex(
      (item) => item.turn === turn && item.step === "plan" && Array.isArray(item.items),
    );
    if (idx >= 0) rows[idx] = stamped;
    else rows.push(stamped);
  } else if (row.id) {
    const idx = rows.findIndex((item) => item.turn === turn && item.id === row.id);
    if (idx >= 0) rows[idx] = stamped;
    else rows.push(stamped);
  } else {
    rows.push(stamped);
  }
  renderLog();
}

function clearLog() {
  rows = [];
  renderLog();
}

function formatRunLogText() {
  return rows
    .map((row) => {
      const step = String(row.step || "").trim();
      const msg = String(row.message || "").trim();
      if (step && msg) return `${step}  ${msg}`;
      return step || msg;
    })
    .join("\n");
}

function setLogOpen(open) {
  runlog.classList.toggle("open", open);
  const expanded = runlog.classList.contains("expanded");
  document.querySelector("#runlog-toggle").setAttribute("aria-expanded", String(open || expanded));
  document.querySelector("#runlog-status-hit").setAttribute("aria-expanded", String(open || expanded));
  document.querySelector("#runlog-toggle").title = open || expanded ? "Close run log" : "Open run log";
}

async function readEvents(response, onLog) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload = null;
  let errorPayload = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      let event = "message";
      const dataLines = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (!dataLines.length) continue;
      let data;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }
      if (event === "log") onLog(data);
      else if (event === "done") donePayload = data;
      else if (event === "error") errorPayload = data;
    }
  }
  if (errorPayload) throw new Error(errorPayload.message || "The agent failed.");
  if (!donePayload) throw new Error("The run ended without an answer.");
  return donePayload;
}

async function chat(message) {
  show(message, "user");
  turn += 1;
  setLogOpen(true);
  setBusy(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    if (!response.ok || !response.body) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "The agent did not answer.");
    }
    const done = await readEvents(response, addLog);
    show(done.message || "The agent did not answer.", "agent");
    return true;
  } catch (error) {
    show(error.message || "The agent did not answer.", "agent");
    return false;
  } finally {
    setBusy(false);
  }
}

function messageWithRentRoll(typed, fileId) {
  const train = `Train this rent roll. file_id=${fileId}`;
  return typed ? `${typed}\n${train}` : train;
}

async function uploadRentRoll(file) {
  const data = new FormData();
  data.append("file", file);
  const uploaded = await fetch("/api/upload", { method: "POST", body: data });
  const body = await uploaded.json().catch(() => ({}));
  if (!uploaded.ok || !body.file_id) {
    throw new Error(body.detail || "Upload failed.");
  }
  return body.file_id;
}

function addChip(label, prompt) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "chip";
  button.textContent = label;
  button.addEventListener("click", () => {
    if (busy) return;
    messageInput.value = prompt;
    messageInput.focus();
  });
  document.querySelector("#chips").appendChild(button);
}

const DEFAULT_PROPERTIES = [
  "La Cordoba",
  "Bay View Gardens Apartments",
  "Chambers Hill Elementary School",
];

async function renderChips() {
  const chips = document.querySelector("#chips");
  chips.replaceChildren();
  addChip("What properties are you trained on?", "What properties are you trained on?");
  let extra = [];
  try {
    const response = await fetch("/api/fits");
    const body = await response.json();
    extra = (body.buildings || []).map((item) => item.property).filter(Boolean);
  } catch {
    extra = [];
  }
  const seen = new Set();
  const names = [];
  for (const name of [...DEFAULT_PROPERTIES, ...extra]) {
    if (!name || seen.has(name)) continue;
    seen.add(name);
    names.push(name);
  }
  for (const name of names) {
    addChip(`Predicted vacancy · ${name}`, `What's the predicted vacancy for ${name}?`);
  }
}

renderChips();

document.querySelector("#ask").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const typed = messageInput.value.trim();
  const fileInput = document.querySelector("#file");
  const file = fileInput.files && fileInput.files[0];
  if (!typed && !file) return;
  messageInput.value = "";
  let message = typed;
  if (file) {
    busy = true;
    sendButton.disabled = true;
    messageInput.disabled = true;
    fileInput.disabled = true;
    document.querySelectorAll("#chips .chip").forEach((chip) => {
      chip.disabled = true;
    });
    try {
      const fileId = await uploadRentRoll(file);
      message = messageWithRentRoll(typed, fileId);
    } catch (error) {
      messageInput.value = typed;
      show(error.message || "Upload failed.", "agent");
      setBusy(false);
      return;
    }
  }
  const sent = await chat(message);
  if (sent && file) fileInput.value = "";
});

function toggleLog() {
  if (runlog.classList.contains("expanded")) {
    runlog.classList.remove("expanded");
    document.querySelector("#runlog-expand").setAttribute("aria-pressed", "false");
    document.querySelector("#runlog-expand").title = "Expand run log";
  }
  setLogOpen(!runlog.classList.contains("open"));
}

document.querySelector("#runlog-toggle").addEventListener("click", toggleLog);
document.querySelector("#runlog-status-hit").addEventListener("click", toggleLog);
document.querySelector("#runlog-expand").addEventListener("click", () => {
  const expanded = runlog.classList.toggle("expanded");
  if (expanded) setLogOpen(true);
  document.querySelector("#runlog-expand").setAttribute("aria-pressed", String(expanded));
  document.querySelector("#runlog-expand").title = expanded ? "Exit full screen" : "Expand run log";
});
runlogClear.addEventListener("click", () => {
  clearLog();
});
runlogCopy.addEventListener("click", async () => {
  if (!rows.length) return;
  const text = formatRunLogText();
  await navigator.clipboard.writeText(text);
  runlogCopy.textContent = "Copied";
  setTimeout(() => {
    runlogCopy.textContent = "Copy";
  }, 1200);
});
