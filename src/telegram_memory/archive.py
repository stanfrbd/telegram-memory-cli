from __future__ import annotations

import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import Any


class Archive:
    """SQLite index for message text, file metadata, and favorites."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        if os.name != "nt":
            path.chmod(0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                channel_id TEXT NOT NULL,
                channel_name TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                sent_at TEXT,
                message_url TEXT,
                text TEXT NOT NULL DEFAULT '',
                file_name TEXT,
                mime_type TEXT,
                file_size INTEGER,
                file_path TEXT,
                favorite INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (channel_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at);
            CREATE INDEX IF NOT EXISTS idx_messages_file_name ON messages(file_name);
            """
        )
        try:
            self.connection.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
                    channel_id UNINDEXED, channel_name, text, file_name
                )"""
            )
            self.fts_enabled = True
        except sqlite3.OperationalError:
            self.fts_enabled = False
        self.connection.commit()

    def upsert(self, message: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO messages
              (channel_id, channel_name, message_id, sent_at, message_url, text, file_name,
               mime_type, file_size, file_path)
            VALUES
              (:channel_id, :channel_name, :message_id, :sent_at, :message_url, :text, :file_name,
               :mime_type, :file_size, :file_path)
            ON CONFLICT(channel_id, message_id) DO UPDATE SET
              channel_name=excluded.channel_name, sent_at=excluded.sent_at,
              message_url=excluded.message_url,
              text=excluded.text, file_name=excluded.file_name,
              mime_type=excluded.mime_type, file_size=excluded.file_size,
              file_path=COALESCE(excluded.file_path, messages.file_path)
            """,
            message,
        )
        if self.fts_enabled:
            row = self.connection.execute(
                "SELECT rowid FROM messages WHERE channel_id=? AND message_id=?",
                (message["channel_id"], message["message_id"]),
            ).fetchone()
            self.connection.execute(
                "DELETE FROM message_fts WHERE rowid=?", (row["rowid"],)
            )
            self.connection.execute(
                """INSERT INTO message_fts(rowid, channel_id, channel_name, text, file_name)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    row["rowid"],
                    message["channel_id"],
                    message["channel_name"],
                    message.get("text", ""),
                    message.get("file_name") or "",
                ),
            )
        self.connection.commit()

    def search(
        self, query: str, channel: str | None = None, files_only: bool = False, limit: int = 50
    ) -> list[dict[str, Any]]:
        terms = query.strip()
        if not terms:
            return []
        filters = []
        parameters: list[Any] = []
        if channel:
            channel_id, channel_name = _normalize_channel_ref(channel)
            filters.append("(m.channel_id=? OR lower(m.channel_name)=lower(?))")
            parameters.extend([channel_id, channel_name])
        if files_only:
            filters.append("m.file_name IS NOT NULL")
        where = (" AND " + " AND ".join(filters)) if filters else ""
        if self.fts_enabled:
            phrase = '"' + terms.replace('"', '""') + '"'
            sql = f"""
                SELECT m.* FROM message_fts f
                JOIN messages m ON m.rowid=f.rowid
                WHERE message_fts MATCH ? {where}
                ORDER BY m.sent_at DESC LIMIT ?
            """
            try:
                rows = self.connection.execute(sql, [phrase, *parameters, limit]).fetchall()
            except sqlite3.OperationalError:
                pattern = f"%{terms.lower()}%"
                fallback_sql = f"""
                    SELECT * FROM messages
                    WHERE (lower(text) LIKE ? OR lower(COALESCE(file_name, '')) LIKE ?) {where.replace('m.', '')}
                    ORDER BY sent_at DESC LIMIT ?
                """
                rows = self.connection.execute(
                    fallback_sql, [pattern, pattern, *parameters, limit]
                ).fetchall()
        else:
            pattern = f"%{terms.lower()}%"
            sql = f"""
                SELECT * FROM messages
                WHERE (lower(text) LIKE ? OR lower(COALESCE(file_name, '')) LIKE ?) {where}
                ORDER BY sent_at DESC LIMIT ?
            """
            rows = self.connection.execute(
                sql, [pattern, pattern, *parameters, limit]
            ).fetchall()
        return [dict(row) for row in rows]

    def list_files(
        self,
        channel: str | None = None,
        name: str | None = None,
        file_type: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        after: str | None = None,
        before: str | None = None,
        favorite: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        filters = ["file_name IS NOT NULL"]
        parameters: list[Any] = []
        if channel:
            channel_id, channel_name = _normalize_channel_ref(channel)
            filters.append("(channel_id=? OR lower(channel_name)=lower(?))")
            parameters.extend([channel_id, channel_name])
        if name:
            filters.append("lower(file_name) LIKE ?")
            parameters.append(f"%{name.lower()}%")
        if file_type:
            filters.append("lower(COALESCE(mime_type, '')) LIKE ?")
            parameters.append(f"%{file_type.lower()}%")
        if min_size is not None:
            filters.append("file_size >= ?")
            parameters.append(min_size)
        if max_size is not None:
            filters.append("file_size <= ?")
            parameters.append(max_size)
        if after:
            filters.append("sent_at >= ?")
            parameters.append(_normalize_date(after, end=False))
        if before:
            filters.append("sent_at <= ?")
            parameters.append(_normalize_date(before, end=True))
        if favorite:
            filters.append("favorite=1")
        rows = self.connection.execute(
            f"""SELECT * FROM messages WHERE {' AND '.join(filters)}
                ORDER BY sent_at DESC LIMIT ?""",
            [*parameters, limit],
        ).fetchall()
        return [dict(row) for row in rows]

    def set_favorite(self, channel: str, message_id: int, favorite: bool) -> bool:
        channel_id, channel_name = _normalize_channel_ref(channel)
        cursor = self.connection.execute(
            "UPDATE messages SET favorite=? WHERE (channel_id=? OR lower(channel_name)=lower(?)) AND message_id=?",
            (int(favorite), channel_id, channel_name, message_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def get_message(self, channel: str, message_id: int) -> dict[str, Any] | None:
        channel_id, channel_name = _normalize_channel_ref(channel)
        row = self.connection.execute(
            """SELECT * FROM messages
               WHERE (channel_id=? OR lower(channel_name)=lower(?)) AND message_id=?
               LIMIT 1""",
            (channel_id, channel_name, message_id),
        ).fetchone()
        return dict(row) if row else None

    def favorites(self, channel: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if channel:
            channel_id, channel_name = _normalize_channel_ref(channel)
            rows = self.connection.execute(
                """SELECT * FROM messages WHERE favorite=1
                   AND (channel_id=? OR lower(channel_name)=lower(?))
                   ORDER BY sent_at DESC LIMIT ?""",
                (channel_id, channel_name, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM messages WHERE favorite=1 ORDER BY sent_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Archive":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _normalize_date(value: str, end: bool) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or an ISO 8601 timestamp.") from exc
    if len(value) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59) if end else parsed
    return parsed.isoformat()


def _normalize_channel_ref(value: str) -> tuple[str, str]:
    ref = value.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if ref.lower().startswith(prefix):
            ref = ref[len(prefix):].split("/", 1)[0]
            break
    ref = ref.lstrip("@")
    if ref.startswith("-100") and ref[4:].isdigit():
        return ref[4:], ref
    return value.strip(), ref
