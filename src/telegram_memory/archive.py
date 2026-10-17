from __future__ import annotations

import os
import re
import sqlite3
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
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
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
            self.connection.execute("DELETE FROM message_fts WHERE rowid=?", (row["rowid"],))
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
        self,
        query: str = "",
        channel: str | None = None,
        files_only: bool = False,
        limit: int = 50,
        *,
        media: str | None = None,
        mime_type: str | None = None,
        after: str | None = None,
        before: str | None = None,
        favorite: bool = False,
        downloaded: bool = False,
        offset: int = 0,
        min_size: int | None = None,
        max_size: int | None = None,
    ) -> list[dict[str, Any]]:
        filters = ["1=1"]
        parameters: list[Any] = []
        if channel:
            channel_id, channel_name = _normalize_channel_ref(channel)
            filters.append("(m.channel_id=? OR lower(m.channel_name)=lower(?))")
            parameters.extend([channel_id, channel_name])
        if files_only or media == "document":
            filters.append("m.file_name IS NOT NULL")
        if media in {"image", "video", "audio"}:
            filters.append("lower(m.mime_type) LIKE ?")
            parameters.append(media + "/%")
        elif media == "document":
            filters.append(
                "COALESCE(m.mime_type, '') NOT LIKE 'image/%' AND "
                "COALESCE(m.mime_type, '') NOT LIKE 'video/%' AND "
                "COALESCE(m.mime_type, '') NOT LIKE 'audio/%'"
            )
        elif media == "text":
            filters.append("m.file_name IS NULL")
        elif media:
            raise ValueError("Unknown media type.")
        if mime_type:
            filters.append("lower(COALESCE(m.mime_type, '')) LIKE ?")
            parameters.append(mime_type.lower().replace("*", "%"))
        for value, column, operator in [
            (after, "sent_at", ">="),
            (before, "sent_at", "<="),
            (min_size, "file_size", ">="),
            (max_size, "file_size", "<="),
        ]:
            if value is not None:
                filters.append(f"m.{column} {operator} ?")
                parameters.append(
                    _normalize_date(value, end=operator == "<=") if column == "sent_at" else value
                )
        if favorite:
            filters.append("m.favorite=1")
        if downloaded:
            filters.append("m.file_path IS NOT NULL")
        terms = query.strip()
        parts = re.findall(r'"([^"\n]+)"|(\w+)', terms)
        join = ""
        if terms and self.fts_enabled:
            join = "JOIN message_fts ON message_fts.rowid=m.rowid"
            filters.append("message_fts MATCH ?")
            # Bare words may occur separately, and prefix matches find partial filenames.
            # Explicitly quoted groups keep their phrase semantics.
            expression = " AND ".join(
                '"' + (phrase or word).replace('"', '""') + '"' + ("" if phrase else "*")
                for phrase, word in parts
            )
            parameters.append(expression or '"' + terms.replace('"', '""') + '"')
        elif terms:
            for phrase, word in parts or [(terms, "")]:
                filters.append(
                    "(lower(m.text) LIKE ? ESCAPE '\\' OR lower(COALESCE(m.file_name,'')) LIKE ? ESCAPE '\\')"
                )
                literal = (
                    (phrase or word)
                    .lower()
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                parameters.extend([f"%{literal}%"] * 2)
        rows = self.connection.execute(
            f"SELECT m.* FROM messages m {join} WHERE {' AND '.join(filters)} "
            "ORDER BY m.sent_at DESC, m.channel_id, m.message_id DESC LIMIT ? OFFSET ?",
            [*parameters, max(1, min(limit, 1001)), max(0, offset)],
        ).fetchall()
        return [dict(row) for row in rows]

    def search_metadata(self) -> dict[str, Any]:
        return {
            "mime_types": [
                row[0]
                for row in self.connection.execute(
                    "SELECT DISTINCT lower(mime_type) FROM messages WHERE mime_type IS NOT NULL "
                    "AND mime_type != '' ORDER BY lower(mime_type)"
                )
            ],
            "channels": [
                dict(row)
                for row in self.connection.execute(
                    "SELECT channel_id, MAX(channel_name) AS channel_name FROM messages "
                    "GROUP BY channel_id ORDER BY lower(channel_name)"
                )
            ],
        }

    def stats(self) -> dict[str, int]:
        row = self.connection.execute(
            "SELECT count(*) messages, count(DISTINCT channel_id) channels, "
            "count(file_name) files, count(file_path) downloads FROM messages"
        ).fetchone()
        return dict(row)

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
            f"""SELECT * FROM messages WHERE {" AND ".join(filters)}
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
        raise ValueError(
            f"Invalid date '{value}'. Use YYYY-MM-DD or an ISO 8601 timestamp."
        ) from exc
    if len(value) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59) if end else parsed
    return parsed.isoformat()


def _normalize_channel_ref(value: str) -> tuple[str, str]:
    ref = value.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if ref.lower().startswith(prefix):
            ref = ref[len(prefix) :].split("/", 1)[0]
            break
    ref = ref.lstrip("@")
    if ref.startswith("-100") and ref[4:].isdigit():
        return ref[4:], ref
    return value.strip(), ref
