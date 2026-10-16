from datetime import datetime, timezone
from types import SimpleNamespace

from telegram_memory.archive import Archive
from telegram_memory.telegram import download_message, search_channel, serialize_message, sync_channel


def test_serialize_message_keeps_plain_text_and_file_metadata():
    message = SimpleNamespace(
        id=42,
        date=datetime(2026, 6, 2, tzinfo=timezone.utc),
        raw_text="A document",
        file=SimpleNamespace(name="document.pdf", mime_type="application/pdf", size=500),
    )
    channel = SimpleNamespace(id=123, username="my_channel", title="My Channel")

    item = serialize_message(message, channel)
    assert item == {
        "channel_id": "123",
        "channel_name": "my_channel",
        "message_id": 42,
        "message_url": "https://t.me/my_channel/42",
        "sent_at": "2026-06-02T00:00:00+00:00",
        "text": "A document",
        "file_name": "document.pdf",
        "mime_type": "application/pdf",
        "file_size": 500,
        "file_path": None,
    }


def test_serialize_message_handles_text_only_messages():
    message = SimpleNamespace(id=3, date=None, raw_text="", file=None)
    channel = SimpleNamespace(id=9, username=None, title="Private channel")

    item = serialize_message(message, channel)
    assert item["channel_name"] == "Private channel"
    assert item["file_name"] is None
    assert item["text"] == ""


def test_serialize_message_assigns_a_searchable_name_to_photo():
    message = SimpleNamespace(
        id=15,
        date=None,
        raw_text="holiday",
        file=SimpleNamespace(name=None, mime_type="image/jpeg", size=1200),
    )
    channel = SimpleNamespace(id=9, username="photos", title="Photos")

    item = serialize_message(message, channel)
    assert item["file_name"] == "media_15.jpg"
    assert item["message_url"] == "https://t.me/photos/15"


def test_sync_and_remote_search_index_messages(tmp_path):
    message = SimpleNamespace(
        id=22,
        date=datetime(2026, 6, 2, tzinfo=timezone.utc),
        raw_text="Useful saved note",
        file=None,
        media=None,
    )
    entity = SimpleNamespace(id=123, username="my_channel", title="My Channel")

    class FakeClient:
        async def get_entity(self, reference):
            assert reference == "@my_channel"
            return entity

        async def iter_messages(self, target, **kwargs):
            assert target is entity
            yield message

    import asyncio

    with Archive(tmp_path / "archive.sqlite3") as archive:
        client = FakeClient()
        assert asyncio.run(sync_channel(client, archive, "@my_channel", limit=10)) == 1
        results = asyncio.run(search_channel(client, archive, "@my_channel", "saved"))
        assert results[0]["message_id"] == 22
        assert archive.search("saved")[0]["message_id"] == 22


def test_download_saves_media_path_in_archive(tmp_path):
    entity = SimpleNamespace(id=123, username="my_channel", title="My Channel")
    message = SimpleNamespace(
        id=33,
        date=datetime(2026, 6, 2, tzinfo=timezone.utc),
        raw_text="A file",
        file=SimpleNamespace(name="file.pdf", mime_type="application/pdf", size=99),
        media=object(),
    )
    downloaded = tmp_path / "file.pdf"
    downloaded.write_bytes(b"test")

    class FakeClient:
        async def get_entity(self, reference):
            return entity

        async def get_messages(self, target, ids):
            assert ids == 33
            return message

        async def download_media(self, target, file):
            assert target is message
            assert Path(file) == tmp_path / "downloads"
            return str(downloaded)

    import asyncio
    from pathlib import Path

    with Archive(tmp_path / "archive.sqlite3") as archive:
        result = asyncio.run(
            download_message(FakeClient(), archive, "@my_channel", 33, tmp_path / "downloads")
        )
        assert result == downloaded
        assert archive.get_message("@my_channel", 33)["file_path"] == str(downloaded)
