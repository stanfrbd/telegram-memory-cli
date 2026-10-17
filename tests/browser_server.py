"""Disposable real FastAPI server with a deterministic Telegram test double."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from telethon.tl import types
from telethon.tl.functions.channels import (
    CheckSearchPostsFloodRequest,
    SearchPostsRequest,
)
from telethon.tl.functions.contacts import SearchRequest

from telegram_memory.archive import Archive
from telegram_memory.config import Config, write_channels
from telegram_memory.web import create_app


def entity(reference):
    return SimpleNamespace(
        id=123 if reference != "@second" else 456,
        username="security" if reference != "@second" else "second",
        title="Security",
    )


def message(mid, text="Threat intelligence report", mime="application/pdf", name=None):
    async def get_chat():
        return types.User(id=999, username="analyst", first_name="Analyst")

    return SimpleNamespace(
        id=mid,
        date=datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc),
        raw_text=text,
        media=object(),
        get_chat=get_chat,
        file=SimpleNamespace(name=name or f"report-{mid}.pdf", mime_type=mime, size=1024),
    )


class FakeTelegram:
    def is_connected(self):
        return True

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def is_user_authorized(self):
        return True

    async def get_entity(self, reference):
        return entity(reference)

    async def iter_messages(self, target, **kwargs):
        yield message(900, "Remote threat research result")

    async def get_messages(self, target, ids):
        return message(ids)

    async def download_media(self, target, file):
        path = Path(file) / f"report-{target.id}.pdf"
        path.write_bytes(b"%PDF-test fixture")
        return str(path)

    async def send_file(self, target, file, **kwargs):
        return message(1000, kwargs.get("caption", ""), "text/plain", Path(file).name)

    async def __call__(self, request):
        if isinstance(request, SearchRequest):
            return SimpleNamespace(
                chats=[
                    types.Channel(
                        id=777,
                        title="Discovered Security",
                        username="discovered_security",
                        broadcast=True,
                        photo=None,
                        date=None,
                    )
                ]
            )
        if isinstance(request, CheckSearchPostsFloodRequest):
            return SimpleNamespace(query_is_free=True, remains=1)
        if isinstance(request, SearchPostsRequest):
            post = types.Message(
                id=1100,
                peer_id=types.PeerChannel(777),
                message="Public threat research result",
                date=datetime(2026, 10, 17, tzinfo=timezone.utc),
            )
            return SimpleNamespace(
                chats=[
                    types.Channel(
                        id=777,
                        title="Public Security",
                        username="public_security",
                        broadcast=True,
                        photo=None,
                        date=None,
                    )
                ],
                messages=[post],
            )
        raise AssertionError(f"Unexpected request: {request}")


if __name__ == "__main__":
    root = Path(sys.argv[1])
    port = int(sys.argv[2])
    token = sys.argv[3] if len(sys.argv) > 3 else None
    config = Config(
        123,
        "fake-only",
        "",
        root / "session",
        root / "archive.db",
        root / "downloads",
        root / "channels.txt",
    )
    write_channels(config.channels_path, ["@security", "@second"])
    with Archive(config.database_path) as archive:
        for mid in range(1, 64):
            archive.upsert(
                {
                    "channel_id": "123",
                    "channel_name": "security",
                    "message_id": mid,
                    "sent_at": f"2026-10-17T12:{mid // 60:02d}:{mid % 60:02d}+00:00",
                    "message_url": f"https://t.me/security/{mid}",
                    "text": "Threat report" if mid > 1 else "<img src=x onerror=alert(1)>",
                    "file_name": f"report-{mid}.pdf" if mid != 2 else "diagram.png",
                    "mime_type": "application/pdf" if mid != 2 else "image/png",
                    "file_size": 1024,
                    "file_path": None,
                }
            )
    uvicorn.run(
        create_app(config, token, client_factory=lambda _: FakeTelegram()),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
