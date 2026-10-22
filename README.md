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

Raw rent rolls stay off this repo. They contain resident names. The parser drops those names before anything is saved.
