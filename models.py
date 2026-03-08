from __future__ import annotations
from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    repo_path: str = Field(description="Absolute path to git repository on disk")
    max_commits: int = Field(default=20, description="How many recent commits to scan")


class CommitSummary(BaseModel):
    sha: str
    author: str
    date: str
    message: str
    files_changed: list[str]


class ContextReport(BaseModel):
    repo_path: str
    branch: str
    last_commit_date: str
    days_since_last_commit: int
    recent_commits: list[CommitSummary]
    active_files: list[str]
    likely_next_steps: list[str]
    open_todos: list[str]
    summary: str


class SessionCreate(BaseModel):
    repo_path: str
    notes: str = ""


class SessionResponse(BaseModel):
    id: int
    repo_path: str
    branch: str
    summary: str
    notes: str
    created_at: str
