const sessionId = crypto.randomUUID();
const thread = document.querySelector("#thread");
const runlog = document.querySelector("#runlog");
const runlogList = document.querySelector("#runlog-list");
const runlogEmpty = document.querySelector("#runlog-empty");
const runlogStatus = document.querySelector("#runlog-status");
const runlogCopy = document.querySelector("#runlog-copy");
const sendButton = document.querySelector("#send");
const messageInput = document.querySelector("#message");
let busy = false;
let rows = [];
let spinner = null;

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
  document.querySelector("#upload-form button").disabled = on;
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

function renderStatus() {
  const last = rows[rows.length - 1];
  runlogStatus.replaceChildren();
  if (busy) {
    const mark = document.createElement("span");
    mark.className = "spinner";
    mark.setAttribute("aria-hidden", "true");
    runlogStatus.append(mark);
  }
  const text = !last ? (busy ? "waiting for the first step…" : "idle") : `${busy ? "running · " : ""}${last.step} · ${last.message}`;
  runlogStatus.append(document.createTextNode(text));
}

function addLog(row) {
  rows.push(row);
  runlogEmpty.hidden = true;
  const item = document.createElement("li");
  item.className = `log-line ${row.step || ""}`;
  const step = document.createElement("span");
  step.className = "log-step";
  step.textContent = `${row.step} (${rows.length})`;
  const msg = document.createElement("span");
  msg.className = "log-msg";
  msg.textContent = row.message || "";
  item.append(step, msg);
  runlogList.appendChild(item);
  runlogCopy.disabled = false;
  renderStatus();
}

function clearLog() {
  rows = [];
  runlogList.replaceChildren();
  runlogEmpty.hidden = false;
  runlogCopy.disabled = true;
  renderStatus();
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
  clearLog();
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
  } catch (error) {
    show(error.message || "The agent did not answer.", "agent");
  } finally {
    setBusy(false);
  }
}

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  setBusy(true);
  try {
    const file = document.querySelector("#file").files[0];
    const data = new FormData();
    data.append("file", file);
    const uploaded = await fetch("/api/upload", { method: "POST", body: data });
    const body = await uploaded.json();
    await chat(`Train this rent roll. file_id=${body.file_id}`);
  } catch (error) {
    show(error.message || "Upload failed.", "agent");
  } finally {
    setBusy(false);
  }
});

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
  const message = messageInput.value.trim();
  if (!message) return;
  messageInput.value = "";
  await chat(message);
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
runlogCopy.addEventListener("click", async () => {
  if (!rows.length) return;
  const text = rows.map((row, index) => `${row.step} (${index + 1}) ${row.message}`).join("\n");
  await navigator.clipboard.writeText(text);
  runlogCopy.textContent = "Copied";
  setTimeout(() => {
    runlogCopy.textContent = "Copy";
  }, 1200);
});
