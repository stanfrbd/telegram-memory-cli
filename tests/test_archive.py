import pytest

from telegram_memory.archive import Archive


def sample(**overrides):
    return {
        "channel_id": "100",
        "channel_name": "my_channel",
        "message_id": 7,
        "sent_at": "2026-04-01T12:30:00+00:00",
        "message_url": "https://t.me/my_channel/7",
        "text": "Here is the incident report",
        "file_name": "incident-report.pdf",
        "mime_type": "application/pdf",
        "file_size": 2048,
        "file_path": None,
        **overrides,
    }


def test_upsert_search_and_file_filters(tmp_path):
    with Archive(tmp_path / "archive.sqlite3") as archive:
        archive.upsert(sample())
        archive.upsert(
            sample(
                message_id=8,
                text="Reference notes",
                file_name="notes.txt",
                mime_type="text/plain",
                file_size=200,
            )
        )

        assert [item["message_id"] for item in archive.search("incident report")] == [7]
        files = archive.list_files(file_type="pdf", min_size=1000, name="report")
        assert [item["file_name"] for item in files] == ["incident-report.pdf"]
        assert archive.search("incident", files_only=True)[0]["message_id"] == 7


def test_upsert_preserves_favorite_and_download_path(tmp_path):
    with Archive(tmp_path / "archive.sqlite3") as archive:
        archive.upsert(sample())
        assert archive.set_favorite("my_channel", 7, True)
        archive.upsert(sample(text="Updated text", file_path="/tmp/report.pdf"))

        message = archive.get_message("100", 7)
        assert message["favorite"] == 1
        assert message["file_path"] == "/tmp/report.pdf"
        assert message["text"] == "Updated text"


def test_favorites_include_messages_without_files(tmp_path):
    with Archive(tmp_path / "archive.sqlite3") as archive:
        archive.upsert(sample(message_id=9, file_name=None, mime_type=None, file_size=None))
        assert archive.set_favorite("@my_channel", 9, True)
        assert [item["message_id"] for item in archive.favorites("@my_channel")] == [9]


def test_channel_url_and_marked_id_resolve_to_local_rows(tmp_path):
    with Archive(tmp_path / "archive.sqlite3") as archive:
        archive.upsert(sample())
        assert archive.search("incident", channel="https://t.me/my_channel")
        assert archive.set_favorite("@my_channel", 7, True)
        assert archive.favorites("t.me/my_channel")[0]["message_id"] == 7


def test_invalid_date_filter_is_reported(tmp_path):
    with Archive(tmp_path / "archive.sqlite3") as archive:
        with pytest.raises(ValueError, match="Invalid date"):
            archive.list_files(after="not-a-date")


@pytest.mark.parametrize("fts", [True, False])
def test_search_separate_words_and_quoted_phrases(tmp_path, fts):
    with Archive(tmp_path / "index.db") as archive:
        archive.upsert(sample(text="Incident triage and response checklist", file_name="guide.pdf"))
        archive.fts_enabled = fts and archive.fts_enabled
        assert len(archive.search("incident response")) == 1
        assert archive.search('"incident response"') == []
        assert len(archive.search('"response checklist"')) == 1
        assert len(archive.search("check")) == 1
