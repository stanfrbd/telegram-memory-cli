import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from telegram_memory.archive import Archive
from telegram_memory.config import Config, write_channels
from telegram_memory.jobs import Jobs
from telegram_memory.research import ResearchStore, RuleInput
from telegram_memory.telegram import search_channels
from telegram_memory.web import create_app


@pytest.fixture
def config(tmp_path):
    return Config(
        123,
        "test-hash",
        "",
        tmp_path / "session",
        tmp_path / "archive.db",
        tmp_path / "downloads",
        tmp_path / "channels.txt",
    )


def message(mid=1, mime="application/pdf", channel="123"):
    return {
        "channel_id": channel,
        "channel_name": "security",
        "message_id": mid,
        "message_url": f"https://t.me/security/{mid}",
        "sent_at": "2026-10-17T12:00:00+00:00",
        "text": "Threat intelligence report",
        "file_name": f"report{mid}.pdf",
        "mime_type": mime,
        "file_size": 1024,
        "file_path": None,
    }


def test_search_filters_and_pagination(config):
    with Archive(config.database_path) as archive:
        for mid in range(1, 5):
            archive.upsert(message(mid, "image/jpeg" if mid == 4 else "application/pdf"))
        archive.set_favorite("123", 1, True)
    with TestClient(create_app(config)) as client:
        data = client.get(
            "/api/search?q=report&media=document&mime_type=application/pdf&limit=2"
        ).json()
        assert len(data["results"]) == 2
        assert data["has_more"] is True
        assert client.get("/api/search?media=image").json()["results"][0]["message_id"] == 4
        assert len(client.get("/api/search?favorite=true").json()["results"]) == 1
        assert client.get("/api/search?after=garbage").status_code == 400
        assert client.get("/api/search?media=garbage").status_code == 422
        assert client.get("/api/search?min_size=2048").json()["results"] == []
        assert client.get("/api/search?offset=3").json()["has_more"] is False


def test_auth_origin_and_channel_validation(config):
    with TestClient(create_app(config, token="secret")) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/auth").json() == {"token_required": True}
        assert client.get("/api/status").status_code == 401
        client.headers["Authorization"] = "Bearer secret"
        assert client.get("/api/status").status_code == 200
        assert (
            client.post(
                "/api/channels",
                json={"channel": "@security"},
                headers={"Origin": "https://evil.test"},
            ).status_code
            == 403
        )
        assert client.post("/api/channels", json={"channel": "@security"}).status_code == 201
        assert client.post("/api/channels", json={"channel": "@bad\n@injection"}).status_code == 422
        assert client.get("/api/channels").json() == ["@security"]
        assert client.request("DELETE", "/api/channels", json={"channel": "@security"}).json() == []
        assert client.get("/api/status", headers={"Host": "attacker.test"}).status_code == 400


def test_download_file_cannot_escape_root(config, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    item = message()
    item["file_path"] = str(secret)
    with Archive(config.database_path) as archive:
        archive.upsert(item)
    with TestClient(create_app(config)) as client:
        assert client.get("/api/downloads/file?channel=123&message_id=1").status_code == 404
        config.download_dir.mkdir()
        stored = config.download_dir / "report.pdf"
        stored.write_bytes(b"PDF")
        item["file_path"] = str(stored)
        with Archive(config.database_path) as archive:
            archive.upsert(item)
        response = client.get("/api/downloads/file?channel=123&message_id=1")
        assert response.content == b"PDF"
        assert response.headers["content-disposition"].startswith("attachment")


def test_restart_marks_jobs_interrupted(config):
    with Archive(config.database_path):
        pass
    jobs = Jobs(config.database_path)
    job = jobs.create("upload")
    jobs.update(job, "running")
    assert Jobs(config.database_path).list()[0]["status"] == "interrupted"


def test_monitor_deduplicates_and_keeps_rules(config):
    with Archive(config.database_path):
        pass
    store = ResearchStore(config.database_path)
    rid = store.save(RuleInput(query="threat", interval=300))
    store.record(rid, {"results": [message()], "errors": []})
    store.record(rid, {"results": [message()], "errors": []})
    assert len(store.hits(rid)) == 1
    assert ResearchStore(config.database_path).rules()[0]["query"] == "threat"


class FakeClient:
    def is_connected(self):
        return True

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def is_user_authorized(self):
        return True

    async def get_entity(self, ref):
        return SimpleNamespace(id=123, username="security", title="Security")

    async def iter_messages(self, entity, **kwargs):
        yield SimpleNamespace(
            id=1,
            date=datetime(2026, 10, 17, tzinfo=timezone.utc),
            raw_text="Threat report",
            file=None,
        )

    async def send_file(self, entity, path, **kwargs):
        from pathlib import Path

        assert Path(path).name == "report.txt"
        assert kwargs["caption"] == "caption"
        return SimpleNamespace(
            id=2,
            date=None,
            raw_text="caption",
            file=SimpleNamespace(name="report.txt", mime_type="text/plain", size=4),
        )


async def wait_job(client, job_id):
    for _ in range(100):
        response = await client.get("/api/jobs/" + job_id)
        if response.json()["status"] not in {"queued", "running"}:
            return response.json()
        await asyncio.sleep(0.01)
    pytest.fail("Job did not finish")


@pytest.mark.asyncio
async def test_upload_remote_search_and_monitor_jobs(config):
    import httpx

    write_channels(config.channels_path, ["@security"])
    app = create_app(config, client_factory=lambda _: FakeClient())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/uploads",
                data={"channel": "@security", "caption": "caption"},
                files={"file": ("../report.txt", b"test", "text/plain")},
            )
            assert response.status_code == 202
            assert (await wait_job(client, response.json()["job_id"]))["status"] == "completed"
            response = await client.post("/api/search/remote", json={"query": "threat"})
            outcome = await wait_job(client, response.json()["job_id"])
            assert outcome["result"]["results"][0]["message_id"] == 1
            response = await client.post(
                "/api/rules", json={"query": "threat", "enabled": False, "interval": 300}
            )
            rid = response.json()["id"]
            response = await client.post("/api/rules/" + rid + "/run")
            assert (await wait_job(client, response.json()["job_id"]))["status"] == "completed"
            assert len((await client.get("/api/rules/" + rid + "/hits")).json()) == 1


@pytest.mark.asyncio
async def test_concurrent_search_reports_partial_errors(tmp_path):
    running = 0
    peak = 0

    class Client(FakeClient):
        async def get_entity(self, ref):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            if ref == "@bad":
                raise ValueError("inaccessible")
            return SimpleNamespace(id=ref, username=ref, title=ref)

    with Archive(tmp_path / "index.db") as archive:
        outcome = await search_channels(
            Client(), archive, ["@a", "@b", "@bad"], "threat", limit=1, concurrency=2
        )
    assert peak == 2
    assert len(outcome["results"]) == 1
    assert outcome["errors"][0]["channel"] == "@bad"


def test_web_assets_and_openapi(config):
    with TestClient(create_app(config)) as client:
        assert client.get("/app.js").status_code == 200
        assert client.get("/style.css").status_code == 200
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/uploads" in paths and "/api/rules" in paths


@pytest.mark.asyncio
async def test_public_search_never_spends_stars(config):
    from telethon.tl.functions.channels import (
        CheckSearchPostsFloodRequest,
        SearchPostsRequest,
    )

    from telegram_memory.telegram import search_public_posts

    requests = []

    class Client:
        async def __call__(self, request):
            requests.append(request)
            if isinstance(request, CheckSearchPostsFloodRequest):
                return SimpleNamespace(query_is_free=False, remains=0, wait_till=123)
            pytest.fail("Must not search after quota is exhausted")

    with Archive(config.database_path) as archive:
        with pytest.raises(ValueError, match="never authorizes payment"):
            await search_public_posts(Client(), archive, "security")

    class FreeClient:
        async def __call__(self, request):
            if isinstance(request, CheckSearchPostsFloodRequest):
                return SimpleNamespace(query_is_free=True, remains=0)
            assert isinstance(request, SearchPostsRequest)
            assert request.allow_paid_stars is None
            return SimpleNamespace(chats=[], messages=[])

    with Archive(config.database_path) as archive:
        assert (await search_public_posts(FreeClient(), archive, "security"))["results"] == []


@pytest.mark.asyncio
async def test_discovery_and_account_search(config):
    from telethon.tl.types import Channel, User

    from telegram_memory.telegram import discover_channels, search_account

    class Client:
        async def __call__(self, request):
            return SimpleNamespace(
                chats=[
                    Channel(
                        id=123,
                        title="Security",
                        photo=None,
                        date=None,
                        broadcast=True,
                        username="security",
                    )
                ]
            )

        async def iter_messages(self, entity, **kwargs):
            assert entity is None
            user = User(id=456, first_name="Example", username="example")

            async def get_chat():
                return user

            yield SimpleNamespace(
                id=1, date=None, raw_text="security", file=None, get_chat=get_chat
            )

    assert (await discover_channels(Client(), "security"))[0]["reference"] == "@security"
    with Archive(config.database_path) as archive:
        item = (await search_account(Client(), archive, "security"))["results"][0]
        assert item["channel_id"] == "user:456"
        assert item["message_url"] is None


def test_new_cli_commands():
    from telegram_memory.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["serve"]).port == 8765
    assert parser.parse_args(["upload", "file.txt", "--channel", "me"]).channel == "me"
    args = parser.parse_args(["find", "report", "--media", "image", "--mime-type", "image/*"])
    assert args.media == "image"


@pytest.mark.asyncio
async def test_browser_download_is_temporary_and_not_indexed_as_permanent(config):
    import httpx

    class Client(FakeClient):
        async def get_messages(self, entity, ids):
            return SimpleNamespace(
                id=ids,
                date=None,
                raw_text="fixture",
                media=True,
                file=SimpleNamespace(name="report.pdf", mime_type="application/pdf", size=8),
            )

        async def download_media(self, message, file):
            from pathlib import Path

            target = Path(file) / "report.pdf"
            target.write_bytes(b"fixture")
            return str(target)

    app = create_app(config, client_factory=lambda _: Client())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/downloads",
                json={"channel": "@security", "message_id": 7, "destination": "browser"},
            )
            outcome = await wait_job(client, response.json()["job_id"])
            assert outcome["status"] == "completed"
            url = outcome["result"]["download_url"]
            assert (await client.get(url)).content == b"fixture"
            assert (await client.get(url)).status_code == 404
            assert not config.download_dir.exists()
            with Archive(config.database_path) as archive:
                assert archive.get_message("123", 7)["file_path"] is None


def test_search_metadata_lists_indexed_mime_types(config):
    with Archive(config.database_path) as archive:
        archive.upsert(message(mime="application/x-threat-log"))
    with TestClient(create_app(config)) as client:
        data = client.get("/api/search/metadata").json()
        assert "application/x-threat-log" in data["mime_types"]
        assert data["channels"][0]["channel_name"] == "security"


def test_expired_browser_downloads_are_removed(tmp_path, monkeypatch):
    import tempfile
    from pathlib import Path

    from telegram_memory.downloads import BrowserDownloads

    directory = tempfile.TemporaryDirectory(dir=tmp_path)
    path = Path(directory.name) / "file"
    path.write_bytes(b"data")
    downloads = BrowserDownloads(ttl=10)
    downloads.add("job", directory, path)
    monkeypatch.setattr("telegram_memory.downloads.time.monotonic", lambda: 10**15)
    assert downloads.get("job") is None
    assert not path.exists()
