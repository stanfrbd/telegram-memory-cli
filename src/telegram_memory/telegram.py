from __future__ import annotations

import asyncio
from datetime import timezone
from mimetypes import guess_extension
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.tl import types
from telethon.tl.functions.contacts import SearchRequest

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
    if isinstance(channel, types.User):
        channel_id = f"user:{channel.id}"
        message_url = None
    elif isinstance(channel, types.Chat):
        channel_id = f"chat:{channel.id}"
        message_url = None
    return {
        "channel_id": str(channel_id),
        "channel_name": username or getattr(channel, "title", None) or str(channel_id),
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
    entity = await client.get_entity(channel_reference(channel_ref))
    count = 0
    async for message in client.iter_messages(entity, limit=limit):
        archive.upsert(serialize_message(message, entity))
        count += 1
    return count


async def search_channel(
    client: TelegramClient, archive: Archive, channel_ref: str, query: str, limit: int = 50
) -> list[dict[str, Any]]:
    entity = await client.get_entity(channel_reference(channel_ref))
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
    entity = await client.get_entity(channel_reference(channel_ref))
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


def channel_reference(value: str) -> str | int:
    """Telethon requires integers for numeric peer IDs."""
    if value.startswith("user:"):
        return types.PeerUser(int(value[5:]))
    if value.startswith("chat:"):
        return types.PeerChat(int(value[5:]))
    return int(value) if value.lstrip("-").isdigit() else value


async def search_channels(
    client, archive: Archive, channels: list[str], query: str, limit: int = 50, concurrency: int = 3
) -> dict[str, Any]:
    """Search saved channels concurrently; report failures without hiding results."""
    semaphore = asyncio.Semaphore(concurrency)

    async def search_one(channel):
        async with semaphore:
            try:
                return await search_channel(client, archive, channel, query, limit), None
            except Exception as exc:
                return [], {"channel": channel, "error": str(exc)}

    outcomes = await asyncio.gather(*(search_one(c) for c in dict.fromkeys(channels)))
    messages = {(m["channel_id"], m["message_id"]): m for rows, _ in outcomes for m in rows}
    return {
        "results": sorted(messages.values(), key=lambda m: m.get("sent_at") or "", reverse=True)[
            :limit
        ],
        "errors": [error for _, error in outcomes if error],
    }


async def upload_file(
    client,
    archive: Archive,
    channel_ref: str,
    path: Path,
    caption: str = "",
    force_document: bool = False,
) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Upload file not found: {path}")
    entity = await client.get_entity(channel_reference(channel_ref))
    message = await client.send_file(
        entity, str(path), caption=caption, force_document=force_document, parse_mode=None
    )
    item = serialize_message(message, entity)
    archive.upsert(item)
    return item


async def discover_channels(client, query: str, limit: int = 30) -> list[dict[str, Any]]:
    """Telegram directory discovery; results depend on server ranking and visibility."""
    found = await client(SearchRequest(q=query, limit=limit))
    return [
        {
            "id": str(chat.id),
            "title": chat.title,
            "username": chat.username,
            "reference": f"@{chat.username}",
            "kind": "channel" if chat.broadcast else "group",
        }
        for chat in found.chats
        if isinstance(chat, types.Channel) and chat.username
    ]


async def search_account(client, archive: Archive, query: str, limit: int = 100):
    """Search account-accessible conversations, not all public Telegram posts."""
    results = []
    async for message in client.iter_messages(None, search=query, limit=limit):
        entity = await message.get_chat()
        if entity is None:
            continue
        item = serialize_message(message, entity)
        archive.upsert(item)
        results.append(item)
    return {"results": results, "errors": []}


async def search_public_posts(client, archive: Archive, query: str, limit: int = 50):
    """One free result page only. Never authorize spending Telegram Stars."""
    from telethon.tl.functions.channels import (
        CheckSearchPostsFloodRequest,
        SearchPostsRequest,
    )

    quota = await client(CheckSearchPostsFloodRequest(query=query))
    if not getattr(quota, "query_is_free", False) and getattr(quota, "remains", 0) <= 0:
        raise ValueError(
            "No free public-post searches available. Telegram may require Premium "
            f"or Stars. Retry after {getattr(quota, 'wait_till', 'the quota resets')}. "
            "This application never authorizes payment."
        )
    found = await client(
        SearchPostsRequest(
            query=query,
            offset_rate=0,
            offset_peer=types.InputPeerEmpty(),
            offset_id=0,
            limit=limit,
            allow_paid_stars=None,
        )
    )
    entities = {chat.id: chat for chat in found.chats}
    results = []
    for message in found.messages:
        entity = entities.get(getattr(getattr(message, "peer_id", None), "channel_id", None))
        if entity is None:
            continue
        item = serialize_message(message, entity)
        archive.upsert(item)
        results.append(item)
    return {
        "results": results,
        "errors": [],
        "scope": "public-posts",
        "note": "One Telegram result page; free quota only. Premium may be required.",
    }
