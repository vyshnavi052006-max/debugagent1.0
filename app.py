"""
app.py
------
FastAPI entrypoint for DebugMate.

Routes:
  GET  /                      -> serves the frontend (static/index.html)
  POST /api/chat              -> main agent endpoint (plan -> act -> remember)
  GET  /api/memory/{session}  -> memory snapshot for the frontend's memory indicator
  POST /api/remember          -> let the user explicitly tell the agent to remember something
  GET  /api/health            -> simple uptime check used by deploy platforms
"""

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import DebugMateAgent

app = FastAPI(title="DebugMate Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = DebugMateAgent()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class RememberRequest(BaseModel):
    session_id: str
    constraint: str


@app.get("/api/health")
def health():
    return {"status": "ok", "agent": agent.name, "domain": agent.domain}


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    try:
        result = agent.handle(req.session_id, req.message.strip())
        return result
    except RuntimeError as exc:
        # Most likely a missing GROQ_API_KEY -- surface a clear, actionable error.
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/memory/{session_id}")
def memory(session_id: str):
    return agent.memory.snapshot(session_id)


@app.post("/api/remember")
def remember(req: RememberRequest):
    agent.remember_constraint(req.session_id, req.constraint.strip())
    return agent.memory.snapshot(req.session_id)


# Serve the attractive static frontend at the root.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
