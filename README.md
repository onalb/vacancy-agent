# Vacancy prediction agent

A train and answer agent for current vacancy. Microsoft Foundry runs the chat model. The agent decides whether to ask, refuse, fit, or score. Python tools parse a rent roll, fit a logistic regression, score that fit, and read or write one JSON fit per building.

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
