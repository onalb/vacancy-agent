const sessionId = crypto.randomUUID();
const thread = document.querySelector("#thread");
const train = document.querySelector("#train");
const answer = document.querySelector("#answer");

function show(text, who) {
  const item = document.createElement("div");
  item.className = `bubble ${who}`;
  item.textContent = text;
  thread.appendChild(item);
  item.scrollIntoView({ behavior: "smooth" });
}

async function chat(message) {
  show(message, "user");
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  const body = await response.json();
  show(body.message || body.detail || "The agent did not answer.", "agent");
}

document.querySelector("#train-tab").addEventListener("click", () => {
  train.classList.remove("hidden");
  answer.classList.add("hidden");
  document.querySelector("#train-tab").classList.add("active");
  document.querySelector("#answer-tab").classList.remove("active");
});

document.querySelector("#answer-tab").addEventListener("click", () => {
  answer.classList.remove("hidden");
  train.classList.add("hidden");
  document.querySelector("#answer-tab").classList.add("active");
  document.querySelector("#train-tab").classList.remove("active");
});

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.querySelector("#file").files[0];
  const data = new FormData();
  data.append("file", file);
  const uploaded = await fetch("/api/upload", { method: "POST", body: data });
  const body = await uploaded.json();
  await chat(`Train this rent roll. file_id=${body.file_id}`);
});

document.querySelector("#ask").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#message");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  await chat(message);
});
