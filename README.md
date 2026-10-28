# Vacancy prediction agent

A train and answer agent for current vacancy. Microsoft Foundry runs the chat model. The agent decides whether to ask, refuse, fit, score, or delete. Python tools parse a rent roll, fit a logistic regression, score that fit, and read, write, or delete one JSON fit per building.

The vacancy skill is not in this repo. When the agent starts it fetches `GET {CAPABILITIES_GATEWAY_URL}/skills/vacancy` and pastes that markdown into the instructions. `CAPABILITIES_GATEWAY_URL` is required for a chat turn. Math tools stay local only when that variable is unset; the agent itself still needs the gateway for the skill.

`delete_fit` asks before it removes a fit. The first call records a pending confirmation on this process's session and does not delete. A later call with `confirm=true` deletes only that pending scope. When `CAPABILITIES_GATEWAY_URL` is set, this process then calls the gateway, and the gateway deletes the JSON only on that confirmed call. The gateway does not store the pending question. This process is the user gate, so a direct gateway call is not how the model skips the user. The model-facing tool still requires the two-step flow.

## Run

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn vacancy_agent.server:app --reload --port 8000
```

Open http://127.0.0.1:8000. Sign in with `az login` before the first chat. The page is light mode, in blue.

External apps and agents (including CRE Deal Rentroll) must call this app **only** via MCP: streamable HTTP `POST /mcp` tool `ask_vacancy` with `{question, session_id}`. Reuse `session_id` on follow-ups. That tool does not train and does not accept a rent roll. Do not POST `/api/chat` or `/api/upload` from an external agent. `/api/chat` is SSE for this app's static UI only. The public MCP endpoint is `https://vacancy-agent.purplegrass-79f82a02.eastus.azurecontainerapps.io/mcp`.

Raw rent rolls stay off this repo. They contain resident names. The parser drops those names before anything is saved.
