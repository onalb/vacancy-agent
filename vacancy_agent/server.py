"""Train and answer UI for the vacancy agent."""

from __future__ import annotations

import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vacancy_agent.agent import build_agent
from vacancy_agent.store import open_store
from vacancy_agent.tools import configure

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = ROOT / "data" / "uploads"
STATIC = ROOT / "static"
UPLOADS.mkdir(parents=True, exist_ok=True)

configure(open_store(), {})
app = FastAPI(title="Vacancy prediction agent")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_agent = None
_sessions: dict[str, object] = {}
_files: dict[str, Path] = {}


class ChatRequest(BaseModel):
    session_id: str
    message: str


def agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    file_id = uuid.uuid4().hex
    suffix = Path(file.filename or "roll.xlsx").suffix or ".xlsx"
    path = UPLOADS / f"{file_id}{suffix}"
    path.write_bytes(await file.read())
    _files[file_id] = path
    configure(open_store(), _files)
    return {"file_id": file_id}


@app.post("/api/chat")
async def chat(body: ChatRequest):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Say something.")
    try:
        vacancy = agent()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    session = _sessions.get(body.session_id)
    if session is None:
        session = vacancy.create_session()
        _sessions[body.session_id] = session
    result = await vacancy.run(body.message.strip(), session=session)
    text = getattr(result, "text", None) or str(result)
    return {"session_id": body.session_id, "message": text}
