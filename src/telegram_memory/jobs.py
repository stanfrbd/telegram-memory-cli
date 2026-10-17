"""Durable web job history, shared by transfers and research modules."""

import json
import uuid
from pathlib import Path

from .database import transaction


class Jobs:
    """Persist outcomes; interrupted jobs are visible after restart, never replay uploads."""

    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS web_jobs "
                "(id TEXT PRIMARY KEY, kind TEXT, status TEXT, result TEXT, error TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            db.execute(
                "UPDATE web_jobs SET status='interrupted', error='Server stopped; retry manually.' "
                "WHERE status IN ('queued', 'running')"
            )

    def connect(self):
        return transaction(self.path)

    def create(self, kind):
        job_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO web_jobs(id,kind,status) VALUES (?,?,'queued')", (job_id, kind))
        return job_id

    def update(self, job_id, status, result=None, error=None):
        with self.connect() as db:
            db.execute(
                "UPDATE web_jobs SET status=?,result=?,error=? WHERE id=?",
                (status, json.dumps(result), error, job_id),
            )

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM web_jobs WHERE id=?", (job_id,)).fetchone()
        return {**dict(row), "result": json.loads(row["result"] or "null")} if row else None

    def list(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM web_jobs ORDER BY created_at DESC, rowid DESC LIMIT 100"
            ).fetchall()
        return [{**dict(row), "result": json.loads(row["result"] or "null")} for row in rows]
