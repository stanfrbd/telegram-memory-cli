"""Local web UI and authenticated REST API over the existing archive."""

from __future__ import annotations

import asyncio
import hmac
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware
from telethon.errors import RPCError

from .archive import Archive
from .config import Config, read_channels, resolve_api_token, write_channels
from .downloads import BrowserDownloads
from .jobs import Jobs
from .research import register_research
from .telegram import (
    download_message,
    make_client,
    search_channels,
    sync_channel,
    upload_file,
)
from .web_models import (
    ChannelInput,
    DownloadInput,
    FavoriteInput,
    RemoteSearch,
    SyncInput,
)


def create_app(
    config: Config,
    token: str | None = None,
    *,
    client_factory=make_client,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    token = resolve_api_token(config, token)
    remote_lock = asyncio.Lock()
    tasks: dict[str, asyncio.Task] = {}
    client = None
    with Archive(config.database_path):
        pass
    jobs = Jobs(config.database_path)
    browser_downloads = BrowserDownloads()

    async def get_client():
        nonlocal client
        if client is None:
            client = client_factory(config)
        if not client.is_connected():
            await client.connect()
        if not await client.is_user_authorized():
            raise ValueError("Telegram session unavailable. Run 'tgmem login' before serving.")
        return client

    async def execute(job_id, operation, cleanup=None):
        try:
            async with remote_lock:
                jobs.update(job_id, "running")
                telegram = await get_client()
                with Archive(config.database_path) as archive:
                    result = await operation(telegram, archive)
                jobs.update(job_id, "completed", result)
        except asyncio.CancelledError:
            jobs.update(job_id, "interrupted", error="Server stopped; retry manually.")
            raise
        except Exception as exc:
            jobs.update(job_id, "failed", error=str(exc))
        finally:
            if cleanup:
                cleanup()
            tasks.pop(job_id, None)

    def enqueue(kind, operation, cleanup=None):
        if len(tasks) >= 32:
            raise HTTPException(429, "Too many pending jobs. Wait for transfers to finish.")
        job_id = jobs.create(kind)
        tasks[job_id] = asyncio.create_task(execute(job_id, operation, cleanup))
        return {"job_id": job_id, "status": "queued"}

    @asynccontextmanager
    async def lifespan(app):
        async def expire_downloads():
            while True:
                browser_downloads.expire()
                await asyncio.sleep(30)

        expiry = asyncio.create_task(expire_downloads())
        scheduler = asyncio.create_task(research_scheduler())
        try:
            yield
        finally:
            scheduler.cancel()
            expiry.cancel()
            await asyncio.gather(scheduler, expiry, return_exceptions=True)
            pending = list(tasks.values())
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            browser_downloads.close()
            if client:
                await client.disconnect()

    app = FastAPI(title="Telegram Memory API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts or ["localhost", "127.0.0.1", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def protect(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin requests are disabled."}, status_code=403)
        protected = request.url.path.startswith(("/api/", "/docs", "/openapi.json", "/redoc"))
        if token and protected and request.url.path != "/api/auth":
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return JSONResponse(
                    {"detail": "A valid Bearer token is required."}, status_code=401
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RPCError)
    async def telegram_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    static = Path(__file__).parent / "static"

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static / "index.html")

    @app.get("/app.js", include_in_schema=False)
    async def javascript():
        return FileResponse(static / "app.js", media_type="text/javascript")

    @app.get("/auth.js", include_in_schema=False)
    async def auth_script():
        return FileResponse(static / "auth.js", media_type="text/javascript")

    @app.get("/api/auth")
    async def auth_settings():
        # Public capability flag only: no credential, account data or archive statistics.
        return {"token_required": bool(token)}

    @app.get("/search.js", include_in_schema=False)
    async def search_script():
        return FileResponse(static / "search.js", media_type="text/javascript")

    @app.get("/theme.js", include_in_schema=False)
    async def theme_script():
        return FileResponse(static / "theme.js", media_type="text/javascript")

    @app.get("/style.css", include_in_schema=False)
    async def stylesheet():
        return FileResponse(static / "style.css", media_type="text/css")

    @app.get("/api/status")
    async def status():
        with Archive(config.database_path) as archive:
            return {
                "stats": archive.stats(),
                "saved_channels": len(read_channels(config.channels_path)),
                "telegram_connected": bool(client and client.is_connected()),
            }

    @app.get("/api/channels")
    async def channels():
        return read_channels(config.channels_path)

    @app.post("/api/channels", status_code=201)
    async def add_channel(body: ChannelInput):
        write_channels(config.channels_path, [*read_channels(config.channels_path), body.channel])
        return read_channels(config.channels_path)

    @app.delete("/api/channels")
    async def remove_channel(body: ChannelInput):
        write_channels(
            config.channels_path,
            [
                c
                for c in read_channels(config.channels_path)
                if c.casefold() != body.channel.casefold()
            ],
        )
        return read_channels(config.channels_path)

    @app.get("/api/search")
    async def search(
        q: str = "",
        channel: str | None = None,
        media: Literal["image", "video", "audio", "document", "text"] | None = None,
        mime_type: str | None = None,
        after: str | None = None,
        before: str | None = None,
        favorite: bool = False,
        downloaded: bool = False,
        min_size: int | None = Query(None, ge=0),
        max_size: int | None = Query(None, ge=0),
        limit: int = Query(50, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        with Archive(config.database_path) as archive:
            rows = archive.search(
                q,
                channel,
                limit=limit + 1,
                media=media,
                mime_type=mime_type,
                after=after,
                before=before,
                favorite=favorite,
                downloaded=downloaded,
                offset=offset,
                min_size=min_size,
                max_size=max_size,
            )
        return {"results": rows[:limit], "offset": offset, "has_more": len(rows) > limit}

    @app.get("/api/search/metadata")
    async def search_metadata():
        with Archive(config.database_path) as archive:
            return archive.search_metadata()

    @app.post("/api/favorites")
    async def favorite(body: FavoriteInput):
        with Archive(config.database_path) as archive:
            if not archive.set_favorite(body.channel, body.message_id, body.favorite):
                raise HTTPException(404, "Message not indexed.")
        return {"favorite": body.favorite}

    def targets(channel):
        values = [channel] if channel else read_channels(config.channels_path)
        if not values:
            raise HTTPException(400, "Add a channel first.")
        return values

    @app.post("/api/search/remote", status_code=202)
    async def remote_search(body: RemoteSearch):
        selected = targets(body.channel)

        async def operation(telegram, archive):
            return await search_channels(telegram, archive, selected, body.query, body.limit)

        return enqueue("search", operation)

    @app.post("/api/sync", status_code=202)
    async def sync(body: SyncInput):
        selected = targets(body.channel)

        async def operation(telegram, archive):
            results, errors = [], []
            for channel in selected:
                try:
                    results.append(
                        {
                            "channel": channel,
                            "indexed_messages": await sync_channel(
                                telegram, archive, channel, body.limit
                            ),
                        }
                    )
                except Exception as exc:
                    errors.append({"channel": channel, "error": str(exc)})
            return {"results": results, "errors": errors}

        return enqueue("sync", operation)

    @app.post("/api/downloads", status_code=202)
    async def download(body: DownloadInput):
        async def operation(telegram, archive):
            if body.destination == "server":
                destination = config.download_dir / uuid.uuid4().hex
                path = await download_message(
                    telegram, archive, body.channel, body.message_id, destination
                )
                if path is None:
                    raise ValueError("Message has no downloadable attachment.")
                return {
                    "channel": body.channel,
                    "message_id": body.message_id,
                    "path": str(path),
                    "destination": "server",
                }
            directory = tempfile.TemporaryDirectory(prefix="tgmem-browser-")
            try:
                path = await download_message(
                    telegram,
                    archive,
                    body.channel,
                    body.message_id,
                    Path(directory.name),
                    persist=False,
                )
                if path is None:
                    raise ValueError("Message has no downloadable attachment.")
                browser_downloads.add(job["job_id"], directory, path)
                return {
                    "destination": "browser",
                    "file_name": path.name,
                    "download_url": f"/api/downloads/browser/{job['job_id']}",
                    "expires_in": browser_downloads.ttl,
                }
            except BaseException:
                directory.cleanup()
                raise

        job = enqueue("download", operation)
        return job

    @app.get("/api/downloads/browser/{job_id}")
    async def browser_file(job_id: str):
        path = browser_downloads.get(job_id)
        if path is None:
            raise HTTPException(
                404, "Browser download expired or was already retrieved. Retry the download."
            )
        return FileResponse(
            path,
            filename=path.name,
            media_type="application/octet-stream",
            background=BackgroundTask(browser_downloads.remove, job_id),
        )

    @app.get("/api/downloads/file")
    async def downloaded_file(channel: str, message_id: int):
        with Archive(config.database_path) as archive:
            item = archive.get_message(channel, message_id)
        if not item or not item["file_path"]:
            raise HTTPException(404, "File has not been downloaded.")
        path = Path(item["file_path"]).resolve()
        if not path.is_relative_to(config.download_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "Downloaded file is unavailable.")
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.post("/api/uploads", status_code=202)
    async def upload(
        channel: str = Form(...),
        caption: str = Form(""),
        document: bool = Form(False),
        file: UploadFile = File(...),
    ):
        if not channel.strip() or len(channel) > 256:
            raise HTTPException(422, "A destination channel is required.")
        temporary = tempfile.TemporaryDirectory(prefix="tgmem-upload-")
        filename = Path((file.filename or "upload.bin").replace("\\", "/")).name
        path = Path(temporary.name) / (
            filename if filename not in {"", ".", ".."} else "upload.bin"
        )
        try:
            size = 0
            with path.open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 2 * 1024**3:
                        raise HTTPException(413, "Web uploads are limited to 2 GiB.")
                    handle.write(chunk)

            async def operation(telegram, archive):
                return await upload_file(telegram, archive, channel, path, caption, document)

            return enqueue("upload", operation, temporary.cleanup)
        except BaseException:
            temporary.cleanup()
            raise
        finally:
            await file.close()

    @app.get("/api/jobs")
    async def job_list():
        return jobs.list()

    @app.get("/api/jobs/{job_id}")
    async def job_detail(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        return job

    research_scheduler = register_research(app, config, enqueue)
    return app


def serve(config: Config, host="127.0.0.1", port=8765, token=None):
    import uvicorn

    token = resolve_api_token(config, token)
    if host not in {"127.0.0.1", "localhost", "::1"} and not token:
        raise ValueError(
            "Set server.api_token in config.toml, TGMEM_API_TOKEN, or --token before exposing the server to the network."
        )
    hosts = ["localhost", "127.0.0.1", "[::1]"]
    if host in {"0.0.0.0", "::"}:
        hosts = ["*"]
    else:
        hosts.append(host)
    print(f"Telegram Memory: http://{host}:{port} (one worker; Ctrl+C to stop)")
    uvicorn.run(create_app(config, token, allowed_hosts=hosts), host=host, port=port, workers=1)
