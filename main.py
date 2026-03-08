from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from models import AnalyzeRequest, ContextReport, SessionCreate, SessionResponse
from analyzer import init_db, analyze_repo, save_session, list_sessions

DB_PATH = "autopm.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await init_db(DB_PATH)
    yield
    await app.state.db.close()


app = FastAPI(
    title="AutoPM",
    description=(
        "Auto Project Manager. Point it at any local git repo — get instant context: "
        "what changed, which files are hot, open TODOs, and suggested next steps. "
        "No more staring at old code wondering where you left off."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/analyze", response_model=ContextReport)
async def analyze(body: AnalyzeRequest):
    """
    Analyze a git repository and return a full context report.
    Reads git log, active files, TODO comments, and infers next steps.
    """
    try:
        report = analyze_repo(body.repo_path, body.max_commits)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return report


@app.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(body: SessionCreate):
    """
    Save a work session snapshot for a repo (auto-analyzes and stores summary).
    Useful for resuming work later.
    """
    try:
        report = analyze_repo(body.repo_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    session = await save_session(
        app.state.db, body.repo_path, report["summary"], report["branch"], body.notes
    )
    return session


@app.get("/sessions", response_model=list[SessionResponse])
async def get_sessions(repo_path: str | None = Query(None, description="Filter by repo path")):
    """List saved sessions, optionally filtered by repo path."""
    return await list_sessions(app.state.db, repo_path)
