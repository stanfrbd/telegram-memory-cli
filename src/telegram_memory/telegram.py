from __future__ import annotations

from datetime import timezone
from mimetypes import guess_extension
from pathlib import Path
from typing import Any

from telethon import TelegramClient

from .archive import Archive
from .config import Config


def make_client(config: Config) -> TelegramClient:
    config.session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        config.session_path.parent.chmod(0o700)
    except OSError:
        pass
    return TelegramClient(str(config.session_path), config.api_id, config.api_hash)


async def login(config: Config) -> TelegramClient:
    client = make_client(config)
    await client.start(phone=config.phone or None)
    return client


def serialize_message(message: Any, channel: Any) -> dict[str, Any]:
    sent_at = message.date
    if sent_at and sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    file = getattr(message, "file", None)
    file_name = getattr(file, "name", None)
    mime_type = getattr(file, "mime_type", None)
    if file is not None and not file_name:
        suffix = guess_extension(mime_type or "") or ".bin"
        file_name = f"media_{message.id}{suffix}"
    username = getattr(channel, "username", None)
    channel_id = getattr(channel, "id", "")
    message_url = (
        f"https://t.me/{username}/{message.id}"
        if username
        else f"https://t.me/c/{channel_id}/{message.id}"
    )
    return {
        "channel_id": str(channel_id),
        "channel_name": username
        or getattr(channel, "title", None)
        or str(channel_id),
        "message_id": int(message.id),
        "message_url": message_url,
        "sent_at": sent_at.isoformat() if sent_at else None,
        "text": message.raw_text or "",
        "file_name": file_name,
        "mime_type": mime_type,
        "file_size": getattr(file, "size", None),
        "file_path": None,
    }


async def sync_channel(
    client: TelegramClient, archive: Archive, channel_ref: str, limit: int | None = 1000
) -> int:
    entity = await client.get_entity(channel_ref)
    count = 0
    async for message in client.iter_messages(entity, limit=limit):
        archive.upsert(serialize_message(message, entity))
        count += 1
    return count


async def search_channel(
    client: TelegramClient, archive: Archive, channel_ref: str, query: str, limit: int = 50
) -> list[dict[str, Any]]:
    entity = await client.get_entity(channel_ref)
    results = []
    async for message in client.iter_messages(entity, search=query, limit=limit):
        item = serialize_message(message, entity)
        archive.upsert(item)
        results.append(item)
    return results


async def download_message(
    client: TelegramClient,
    archive: Archive,
    channel_ref: str,
    message_id: int,
    destination: Path,
) -> Path | None:
    entity = await client.get_entity(channel_ref)
    messages = await client.get_messages(entity, ids=message_id)
    if not messages or not messages.media:
        return None
    destination.mkdir(parents=True, exist_ok=True)
    path = await client.download_media(messages, file=str(destination))
    if not path:
        return None
    item = serialize_message(messages, entity)
    item["file_path"] = path
    archive.upsert(item)
    return Path(path)
