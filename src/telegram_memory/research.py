"""Web-only discovery, account searches, and keyword monitoring.

Extension point: register a router with the app and submit Telegram work through enqueue.
The shared queue owns the Telethon client and serializes account operations.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import read_channels
from .database import transaction
from .telegram import (
    discover_channels,
    search_account,
    search_channels,
    search_public_posts,
)


class ResearchQuery(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    limit: int = Field(default=50, ge=1, le=100)


class RuleInput(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    channel: str | None = None
    interval: int = Field(default=3600, ge=300, le=604800)
    enabled: bool = True


class ResearchStore:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS monitor_rules (
                id TEXT PRIMARY KEY, query TEXT NOT NULL, channel TEXT,
                interval INTEGER NOT NULL, enabled INTEGER NOT NULL,
                last_run REAL DEFAULT 0, last_error TEXT);
            CREATE TABLE IF NOT EXISTS monitor_hits (
                rule_id TEXT NOT NULL, channel_id TEXT NOT NULL, message_id INTEGER NOT NULL,
                message TEXT NOT NULL, found_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(rule_id, channel_id, message_id));
            """)

    def connect(self):
        return transaction(self.path)

    def rules(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM monitor_rules ORDER BY rowid DESC")]

    def save(self, body: RuleInput):
        rule_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO monitor_rules(id,query,channel,interval,enabled) VALUES (?,?,?,?,?)",
                (rule_id, body.query, body.channel, body.interval, body.enabled),
            )
        return rule_id

    def record(self, rule_id, result):
        with self.connect() as db:
            for item in result["results"]:
                db.execute(
                    "INSERT OR IGNORE INTO monitor_hits(rule_id,channel_id,message_id,message) "
                    "VALUES (?,?,?,?)",
                    (rule_id, item["channel_id"], item["message_id"], json.dumps(item)),
                )
            errors = result.get("errors", [])
            db.execute(
                "UPDATE monitor_rules SET last_error=? WHERE id=?",
                (json.dumps(errors) if errors else None, rule_id),
            )

    def hits(self, rule_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT h.message, h.found_at, COALESCE(m.favorite,0) AS favorite, m.file_path "
                "FROM monitor_hits h LEFT JOIN messages m "
                "ON m.channel_id=h.channel_id AND m.message_id=h.message_id WHERE h.rule_id=? "
                "ORDER BY h.found_at DESC, h.rowid DESC LIMIT 100",
                (rule_id,),
            ).fetchall()
        return [
            {
                **json.loads(row["message"]),
                "found_at": row["found_at"],
                "favorite": row["favorite"],
                "file_path": row["file_path"],
            }
            for row in rows
        ]


def register_research(app, config, enqueue):
    router = APIRouter(prefix="/api", tags=["Research"])
    store = ResearchStore(config.database_path)
    pending_rules = set()

    @router.post("/discover", status_code=202)
    async def discover(body: ResearchQuery):
        async def operation(client, archive):
            return {"channels": await discover_channels(client, body.query, body.limit)}

        return enqueue("discovery", operation)

    @router.post("/search/account", status_code=202)
    async def account_search(body: ResearchQuery):
        async def operation(client, archive):
            return await search_account(client, archive, body.query, body.limit)

        return enqueue("account-search", operation)

    @router.post("/search/public", status_code=202)
    async def public_search(body: ResearchQuery):
        async def operation(client, archive):
            return await search_public_posts(client, archive, body.query, body.limit)

        return enqueue("public-search", operation)

    @router.get("/rules")
    async def rules():
        return store.rules()

    @router.post("/rules", status_code=201)
    async def add_rule(body: RuleInput):
        if not body.channel and not read_channels(config.channels_path):
            raise HTTPException(400, "Add saved channels first or choose a channel.")
        return {"id": store.save(body)}

    @router.put("/rules/{rule_id}/enabled")
    async def toggle_rule(rule_id: str, enabled: bool):
        with store.connect() as db:
            cursor = db.execute("UPDATE monitor_rules SET enabled=? WHERE id=?", (enabled, rule_id))
            if not cursor.rowcount:
                raise HTTPException(404, "Rule not found.")
        return {"enabled": enabled}

    @router.delete("/rules/{rule_id}")
    async def remove_rule(rule_id: str):
        if rule_id in pending_rules:
            raise HTTPException(409, "Wait for the running rule to finish before deleting it.")
        with store.connect() as db:
            db.execute("DELETE FROM monitor_rules WHERE id=?", (rule_id,))
            db.execute("DELETE FROM monitor_hits WHERE rule_id=?", (rule_id,))
        return {"deleted": rule_id}

    @router.get("/rules/{rule_id}/hits")
    async def hits(rule_id: str):
        return store.hits(rule_id)

    def submit_rule(rule):
        rule_id = rule["id"]
        if rule_id in pending_rules:
            raise HTTPException(409, "This rule is already running.")
        selected = [rule["channel"]] if rule["channel"] else read_channels(config.channels_path)

        async def operation(client, archive):
            outcome = await search_channels(client, archive, selected, rule["query"], limit=1000)
            store.record(rule_id, outcome)
            return {
                "rule_id": rule_id,
                "matches": len(outcome["results"]),
                "errors": outcome["errors"],
            }

        pending_rules.add(rule_id)
        try:
            job = enqueue("monitor", operation, lambda: pending_rules.discard(rule_id))
        except Exception:
            pending_rules.discard(rule_id)
            raise
        with store.connect() as db:
            db.execute("UPDATE monitor_rules SET last_run=? WHERE id=?", (time.time(), rule_id))
        return job

    @router.post("/rules/{rule_id}/run", status_code=202)
    async def run_rule(rule_id: str):
        for rule in store.rules():
            if rule["id"] == rule_id:
                return submit_rule(rule)
        raise HTTPException(404, "Rule not found.")

    async def scheduler():
        while True:
            for rule in store.rules():
                if (
                    rule["enabled"]
                    and rule["id"] not in pending_rules
                    and time.time() >= rule["last_run"] + rule["interval"]
                ):
                    try:
                        submit_rule(rule)
                    except HTTPException:
                        break  # Queue full: try on the next tick.
            await asyncio.sleep(30)

    app.include_router(router)
    return scheduler
