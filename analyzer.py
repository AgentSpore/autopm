from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone, date

import aiosqlite

SQL_TABLES = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_path TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'unknown',
    summary TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


async def init_db(path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.executescript(SQL_TABLES)
    await db.commit()
    return db


def _run(cmd: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception:
        return ""


def _days_since(date_str: str) -> int:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return -1


def _extract_todos(repo_path: str, active_files: list[str]) -> list[str]:
    todos = []
    todo_re = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)[:\s]+(.+)", re.IGNORECASE)
    for rel in active_files[:15]:
        fpath = os.path.join(repo_path, rel)
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = todo_re.search(line)
                    if m:
                        todos.append(f"{rel}: {m.group(2).strip()}")
        except OSError:
            continue
    return todos[:10]


def _infer_next_steps(commits: list[dict], active_files: list[str]) -> list[str]:
    steps = []
    messages = " ".join(c["message"].lower() for c in commits)

    if "wip" in messages or "work in progress" in messages:
        steps.append("Finish WIP: check last commit for incomplete work")
    if "test" not in messages and any(f.endswith((".py", ".ts", ".js")) for f in active_files):
        steps.append("Add tests — no test commits in recent history")
    if "readme" not in messages and "docs" not in messages:
        steps.append("Update README / documentation")
    if any(kw in messages for kw in ["bug", "fix", "broken", "error"]):
        steps.append("Review open bugs from recent commit messages")
    if not steps:
        steps.append("Continue from last commit: " + (commits[0]["message"] if commits else "unknown"))
    return steps[:4]


def analyze_repo(repo_path: str, max_commits: int = 20) -> dict:
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise ValueError(f"Not a git repository: {repo_path}")

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path) or "unknown"

    # Get recent commits
    log_out = _run([
        "git", "log", f"-{max_commits}",
        "--pretty=format:%H|%an|%ai|%s",
        "--name-only",
    ], repo_path)

    commits: list[dict] = []
    current: dict | None = None
    for line in log_out.splitlines():
        if "|" in line and len(line.split("|")) == 4:
            if current:
                commits.append(current)
            sha, author, dt, msg = line.split("|", 3)
            current = {"sha": sha[:8], "author": author, "date": dt, "message": msg, "files_changed": []}
        elif line.strip() and current is not None:
            current["files_changed"].append(line.strip())
    if current:
        commits.append(current)

    last_commit_date = commits[0]["date"] if commits else datetime.now(timezone.utc).isoformat()
    days_ago = _days_since(last_commit_date)

    # Most-touched files across recent commits
    file_counts: dict[str, int] = {}
    for c in commits:
        for f in c["files_changed"]:
            file_counts[f] = file_counts.get(f, 0) + 1
    active_files = sorted(file_counts, key=lambda x: file_counts[x], reverse=True)[:20]

    todos = _extract_todos(repo_path, active_files)
    next_steps = _infer_next_steps(commits, active_files)

    recent_msg = commits[0]["message"] if commits else "no commits"
    summary = (
        f"Branch '{branch}', last commit {days_ago}d ago: \"{recent_msg}\". "
        f"Most active files: {', '.join(active_files[:3]) or 'none'}. "
        f"Next: {next_steps[0] if next_steps else 'unknown'}."
    )

    return {
        "repo_path": repo_path,
        "branch": branch,
        "last_commit_date": last_commit_date,
        "days_since_last_commit": days_ago,
        "recent_commits": commits[:max_commits],
        "active_files": active_files,
        "likely_next_steps": next_steps,
        "open_todos": todos,
        "summary": summary,
    }


async def save_session(db: aiosqlite.Connection, repo_path: str, summary: str, branch: str, notes: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cur = await db.execute(
        "INSERT INTO sessions (repo_path, branch, summary, notes, created_at) VALUES (?, ?, ?, ?, ?)",
        (repo_path, branch, summary, notes, now),
    )
    await db.commit()
    rows = await db.execute_fetchall("SELECT * FROM sessions WHERE id = ?", (cur.lastrowid,))
    r = rows[0]
    return {"id": r["id"], "repo_path": r["repo_path"], "branch": r["branch"],
            "summary": r["summary"], "notes": r["notes"], "created_at": r["created_at"]}


async def list_sessions(db: aiosqlite.Connection, repo_path: str | None = None) -> list[dict]:
    if repo_path:
        rows = await db.execute_fetchall(
            "SELECT * FROM sessions WHERE repo_path = ? ORDER BY created_at DESC", (repo_path,)
        )
    else:
        rows = await db.execute_fetchall("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 50")
    return [{"id": r["id"], "repo_path": r["repo_path"], "branch": r["branch"],
             "summary": r["summary"], "notes": r["notes"], "created_at": r["created_at"]} for r in rows]
