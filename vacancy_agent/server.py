"""Train and answer UI for the vacancy agent."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vacancy_agent.agent import answer_question
from vacancy_agent.mcp_server import http_app, mcp
from vacancy_agent.runlog import begin_turn, bind, emit, end_turn, reset
from vacancy_agent.store import open_store
from vacancy_agent.tools import configure

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = ROOT / "data" / "uploads"
STATIC = ROOT / "static"
UPLOADS.mkdir(parents=True, exist_ok=True)

_store = open_store()
configure(_store, {})
_files: dict[str, Path] = {}


_mcp_http = http_app()


@asynccontextmanager
async def lifespan(_app):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Vacancy prediction agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.router.routes.extend(_mcp_http.routes)


class ChatRequest(BaseModel):
    session_id: str
    message: str


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
    configure(_store, _files)
    return {"file_id": file_id}


def _frame(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@app.post("/api/chat")
async def chat(body: ChatRequest):
    """Local vacancy UI contract (SSE). External agents must use /mcp ask_vacancy."""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Say something.")
    queue: asyncio.Queue = asyncio.Queue()

    async def run() -> None:
        token = bind(queue)
        begin_turn()
        try:
            emit("llm", "Starting ReAct")
            try:
                text = await answer_question(body.message, body.session_id)
            except RuntimeError as exc:
                end_turn(ok=False)
                await queue.put({"_event": "error", "message": str(exc)})
                return
            end_turn(ok=True)
            await queue.put({"_event": "done", "session_id": body.session_id, "message": text})
        except Exception as exc:
            end_turn(ok=False)
            await queue.put({"_event": "error", "message": str(exc)})
        finally:
            reset(token)
            await queue.put(None)

    task = asyncio.create_task(run())

    async def frames():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event = item.pop("_event", "log")
                yield _frame(event, item)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
