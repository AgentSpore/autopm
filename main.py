from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from models import AnalyzeRequest, ContextReport, SessionCreate, SessionResponse
from analyzer import init_db, analyze_repo, save_session, list_sessions, get_session, delete_session, get_sessions_stats

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
    version="0.5.0",
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



@app.get("/sessions/search", response_model=list[SessionResponse])
async def search_sessions_endpoint(q: str = Query(..., min_length=1, description="Search query — matches repo_path, summary, branch, or notes")):
    """Search sessions by repo path, summary, branch, or notes. Useful for finding past work context."""
    return await search_sessions(app.state.db, q)

@app.get("/sessions/stats")
async def sessions_stats():
    """Aggregate stats: total sessions, repos tracked, most active repo, repo breakdown."""
    return await get_sessions_stats(app.state.db)


@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session_detail(session_id: int):
    """Get a single saved session by ID."""
    s = await get_session(app.state.db, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s




@app.get("/sessions/export/csv")
async def export_sessions(repo_path: str | None = Query(None, description="Filter by repo path")):
    """Export all sessions as CSV (id, repo_path, branch, summary, notes, created_at)."""
    from fastapi.responses import Response
    csv_text = await export_sessions_csv(app.state.db, repo_path)
    return Response(content=csv_text, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sessions.csv"})



@app.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(session_id: int, notes: str | None = None):
    """Update the notes on a saved session. Useful for adding context after review."""
    result = await update_session_notes(app.state.db, session_id, notes)
    if not result:
        raise HTTPException(404, "Session not found")
    return result

@app.delete("/sessions/{session_id}", status_code=204)
async def remove_session(session_id: int):
    """Delete a saved session."""
    ok = await delete_session(app.state.db, session_id)
    if not ok:
        raise HTTPException(404, "Session not found")
