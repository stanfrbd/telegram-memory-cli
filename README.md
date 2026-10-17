# Telegram Memory CLI

tgmem is a local-first command-line archive for Telegram. It uses your Telegram user account through Telethon to search channels, index message text and attachment metadata in SQLite, save favorites, and download files. It is designed for both terminal use and AI agents.

The Telegram integration targets Telethon 1.45.0 or newer within the 1.x series and uses its current message iteration, server search, and media download methods.

## Features

- Search Telegram messages in one channel or across a locally managed list of channels.
- Keep a local SQLite index for fast searches without contacting Telegram.
- Index attachment names, MIME types, sizes, captions, and message dates.
- Filter indexed files by channel, filename, type, date, size, and favorite status.
- Download an attachment by channel and message ID.
- Emit JSON for agent workflows with the --json option.
- Optional web workspace/API, source discovery, and keyword monitoring.
- Explicit file uploads to Telegram; other operations do not send or modify messages.

The local index stores message text and file metadata. It does not currently extract text from document contents or OCR images.

## Requirements

- Python 3.11 or newer
- Telegram API credentials from https://my.telegram.org/apps
- Access to the chats you want to search

## Install

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install .
    tgmem init

On Windows, activate the environment with .venv\Scripts\activate.

Edit ~/.config/tgmem/config.toml and set telegram.api_id and telegram.api_hash. Then authenticate once:

    tgmem login

Telegram sends a login code to your Telegram app. If the account uses two-step verification, Telethon will also ask for the password. The reusable session file is stored locally under ~/.local/share/tgmem/; keep it private and never commit it.

## Manage channels

Channels can be entered as a username, public URL, or numeric chat ID. Private channels must be accessible to the authenticated account.

    tgmem channels add @my_channel
    tgmem channels add https://t.me/another_channel
    tgmem channels list
    tgmem channels list --json
    tgmem channels remove @another_channel

The list is a plain text file at ~/.config/tgmem/channels.txt, one channel per line. Blank lines and lines starting with # are ignored.

## Search and index

Search Telegram directly in a particular channel:

    tgmem search "incident response" --channel @my_channel --json

Search every channel in the saved list:

    tgmem search "meeting notes" --json

Build or refresh the local index. By default the newest 1,000 messages per channel are indexed; use --all for full history.

    tgmem sync
    tgmem sync @my_channel --limit 5000 --json
    tgmem sync @my_channel --all

Search the local index later:

    tgmem find "incident response" --channel @my_channel
    tgmem find report --files-only --json

## Find and download files

The files command searches attachment metadata already present in the local index:

    tgmem files --name report --type pdf
    tgmem files --after 2026-01-01 --before 2026-06-30 --min-size 100000 --json
    tgmem files --favorites

Download media from a message ID:

    tgmem download --channel @my_channel --message-id 1234
    tgmem download --channel @my_channel --message-id 1234 --output ./selected-files --json

Files go to the configured download directory by default (~/Downloads/Telegram). The command prints the resulting local path.

## Favorites

Favorites are stored only in the local index:

    tgmem favorite add --channel @my_channel --message-id 1234
    tgmem favorite list --json
    tgmem favorite remove --channel @my_channel --message-id 1234

The message must be present in the local index first. Run tgmem sync or tgmem search to index it.

## Configuration and data

The default config is ~/.config/tgmem/config.toml. The database and Telethon session are under ~/.local/share/tgmem/, except downloads which default to ~/Downloads/Telegram. Paths can be changed in the config file. Pass --config /path/to/config.toml before the command to use another config.

Never put api_hash, phone login codes, two-step verification passwords, or Telethon session files in a public repository. The config file is created with owner-only permissions where the operating system supports it.

## Development

    python -m pip install -e '.[test]'
    pytest

All source code, documentation, command names, and user-facing output are in English.

## License

MIT

## Web workspace and REST API

Install the optional web dependencies and start the server with your existing configuration:

```bash
python -m pip install -e '.[web]'
tgmem serve
# Custom configuration / port:
tgmem --config /path/to/config.toml serve --port 9000
```

Open **http://127.0.0.1:8765**. No Node build or external frontend assets are needed.
Authenticate once using `tgmem login` before remote operations. The server connects lazily;
local archive searches work without a live Telegram connection. Stop with Ctrl+C and run the
same command to restart. Run one server worker and avoid simultaneous CLI Telegram commands
using the same session file.

The responsive workspace provides:

- Full-text archive search across indexed sources, with channel, media category, MIME,
  date, byte-size, favorite, and downloaded filters; paginated results.
- Saved channel management and sync (latest 1,000 messages per source from the UI).
- Telegram searches over saved sources, account conversations, or public posts.
- Public channel/group discovery and one-click saving, without joining automatically.
- Downloads, browser file retrieval, favorites, and explicit file uploads with captions.
- Persistent job history and keyword monitoring rules.

Local search includes **all indexed sources**, including removed saved sources and discoveries
indexed by remote searches. Removing a source only removes it from the saved list; it does
not delete archive data or unsubscribe on Telegram. Search covers text/captions and filenames,
not OCR, extracted document contents, or semantic similarity. Use a blank query in the web UI
to browse by filters. A MIME filter is exact unless it contains `*` (e.g. `image/*`). Media
categories derive from MIME; “Documents” excludes image, audio, and video MIME types.
Remote results can be opened directly from their job in Transfers, then filtered in the archive.

### Search scopes and Telegram limits

| Scope | What it searches | Limitations |
| --- | --- | --- |
| Archive | Locally indexed messages and attachment metadata | Only messages previously synced or found |
| Saved channels | Every saved channel, concurrently (3 at a time) | Access required; channel failures are reported separately |
| Account conversations | Telegram's account-global message search | Server visibility and indexing; not every public post |
| Public posts | Telegram's `channels.searchPosts` endpoint | One result page, up to 100 results; Premium/free quota restrictions |
| Discover | Telegram's public directory by name/username | Server-ranked, incomplete results; not message-content search |

Public-post search checks `channels.checkSearchPostsFlood` first and **never authorizes
Telegram Stars payments**. When no free searches remain, it fails with an explanation. Premium,
quota, private-channel access, deleted content, and `FloodWait` restrictions are controlled by
Telegram. Telethon handles short flood waits according to its default policy; longer waits are
reported in jobs/errors. No fixed universal request rate or exhaustive search is promised.
Public discovery/account/public-post scopes are web/API features, not additional CLI commands.

Official references: [Telethon message iteration](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.messages.MessageMethods.iter_messages),
[Telegram discovery](https://core.telegram.org/method/contacts.search),
[Public-post search](https://core.telegram.org/method/channels.searchPosts),
[Search quotas](https://core.telegram.org/api/search).

### Keyword monitoring

Create a keyword/phrase rule in **Monitoring**, choose one source or leave the source blank
for the current saved channel list, and set an interval (minimum 5 minutes, default 60).
Rules can be paused, resumed, deleted, or run immediately. Matching messages and deduplicated
rule hits are stored in SQLite; View matches displays the latest 100 recorded hits.

The scheduler runs **only while `tgmem serve` is running**, checking due rules every 30 seconds.
Rules and results survive restarts. A rule is never queued twice concurrently. Each poll searches
up to 1,000 matches per source and retains the latest 1,000 across sources. This is a bounded
search, not a lossless collector: busy sources and long downtime can cause missed matches.
The first poll may include historical results. Scheduled queries use saved sources, not paid
public-post searches. There are no external notifications or webhooks in this version.

Remote jobs are serialized through one session queue (at most 32 pending jobs). The UI stays
usable during work. Failed channels are reported independently; inspect the job's `errors`,
including when a job completed with partial results. Interrupted jobs are marked after restart
and are **not automatically retried**, especially uploads which could otherwise duplicate posts.

### API usage and authentication

OpenAPI: `/openapi.json`; interactive documentation: `/docs` (internet access is needed for
Swagger's documentation assets). Core endpoints:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/status` | Archive counters and current connection state |
| GET / POST / DELETE | `/api/channels` | List/add/remove saved sources |
| GET | `/api/search` | Local filters; `q`, `channel`, `media`, `mime_type`, `after`, `before`, `min_size`, `max_size`, `favorite`, `downloaded`, `limit`, `offset` |
| POST | `/api/search/remote` | Search saved sources; optional `channel` |
| POST | `/api/search/account` | Account-wide Telegram search |
| POST | `/api/search/public` | Free-quota public-post search |
| POST | `/api/discover` | Public source discovery |
| POST | `/api/sync` | Index saved sources; optional `channel`, `limit` |
| POST | `/api/favorites` | Set `favorite` for `channel`, `message_id` |
| POST | `/api/downloads` | Queue `channel`, `message_id` download |
| GET | `/api/downloads/file` | Retrieve downloaded attachment by channel/message ID |
| POST | `/api/uploads` | Multipart `file`, `channel`, optional `caption`, `document` |
| GET | `/api/jobs` | Latest 100 jobs |
| GET | `/api/jobs/{id}` | Job status/result/error |
| GET / POST | `/api/rules` | List/create monitoring rules |
| PUT | `/api/rules/{id}/enabled?enabled=true` | Enable/pause a rule |
| DELETE | `/api/rules/{id}` | Remove a rule and its hit history |
| POST | `/api/rules/{id}/run` | Run a rule now |
| GET | `/api/rules/{id}/hits` | Latest 100 deduplicated hits |

Remote operations return HTTP 202 with `job_id`; poll the job for completion. Discovery and
account/public queries accept `{"query":"security","limit":50}`. Rule creation accepts
`{"query":"CVE-2026","channel":null,"interval":3600,"enabled":true}` (interval in seconds).

```bash
curl 'http://127.0.0.1:8765/api/search?q=report&media=document&mime_type=application/pdf'
curl -X POST http://127.0.0.1:8765/api/search/remote \
  -H 'Content-Type: application/json' -d '{"query":"security","limit":100}'
curl -X POST http://127.0.0.1:8765/api/uploads \
  -F channel=me -F file=@report.pdf -F caption='My report' -F document=true
```

The server binds to localhost by default. Set `TGMEM_API_TOKEN` for authentication; a token is
mandatory for non-loopback binds. Use the **Set API token** button in the UI (token is kept only
in page memory), and send `Authorization: Bearer TOKEN` from API clients. API and documentation
routes are protected; the UI shell itself contains no account data. For authenticated interactive
API browsing, load `/openapi.json` with an API client; Swagger's initial schema fetch also needs
the Bearer header. Cross-origin requests are rejected and no CORS access is enabled.

```bash
export TGMEM_API_TOKEN='replace-with-a-long-random-token'
tgmem serve --host 0.0.0.0
curl -H "Authorization: Bearer $TGMEM_API_TOKEN" http://127.0.0.1:8765/api/status
```

Network deployments need HTTPS through a reverse proxy and appropriate network restrictions.
The token grants access to the connected Telegram account's supported operations. The web UI
never asks for login codes or passwords: authenticate in the CLI. Downloads are served only
from the configured download directory and always as attachments. Web uploads are streamed
to a temporary file, capped at 2 GiB, and removed after the task. Uploading sends a Telegram
message; searches, indexing, favorites, and source-list edits do not modify Telegram content.

## Upload from the CLI

```bash
tgmem upload ./report.pdf --channel @my_channel --caption 'Investigation report' --document --json
tgmem upload ./photo.jpg --channel me
```

`--document` prevents photo/video conversion. Uploads index the resulting Telegram message;
the original local file is not considered a downloaded archive attachment.

Additional local search filters:

```bash
tgmem find report --media document --mime-type application/pdf --after 2026-01-01 --json
tgmem find holiday --media image --offset 50
```

`tgmem search` now searches saved channels with bounded concurrency, removes duplicate messages,
sorts results newest-first, and applies `--limit` globally (previously the limit was per source).
JSON remains a result array; per-channel errors go to stderr.

## Architecture and extending the project

The project stays Python-first; FastAPI/Uvicorn are optional extras. The frontend is plain
HTML/CSS/JavaScript shipped inside the wheel, with no build step or CDN dependency.

| Module | Responsibility |
| --- | --- |
| `config.py` | Configuration paths, API credentials, saved channel list |
| `archive.py` | SQLite schema, message indexing, full-text queries and metadata filters |
| `telegram.py` | Telethon operations and message serialization |
| `cli.py` | Argument parsing, terminal output, CLI orchestration |
| `web.py` | App factory, lifecycle, session queue, core API routes and static assets |
| `web_models.py` | Validated request contracts |
| `jobs.py` / `database.py` | Durable background-job history and short SQLite transactions |
| `research.py` | Research router, rule storage, keyword scheduler |
| `static/` | Responsive web interface (rendered with textContent for untrusted messages) |

To add an integration, implement its Telegram operation in `telegram.py`, create an API router
following `register_research`, and submit remote work through the shared `enqueue` function
rather than opening another session. Use separate request models and small storage services.
`create_app(config, client_factory=...)` supports fake clients for offline integration tests.
Existing SQLite message rows are retained; web job/rule tables are added automatically. WAL
mode improves local reader/writer coexistence. Back up the database while the server is stopped,
or use SQLite's backup API (copying only the main file during WAL writes is insufficient).

```bash
python -m pip install -e '.[web,test]'
python -m pytest
python -m build
```

Tests cover archive filtering/pagination, concurrent partial results, auth/origin restrictions,
file retrieval boundaries, upload jobs, discovery/account search, free public-search quota,
rule deduplication, and restart recovery. They use fake Telegram clients and temporary databases;
real-account smoke tests remain a separate manual check.


### Real-browser integration tests

The optional Playwright suite starts a real Uvicorn/FastAPI server with a temporary SQLite
archive and a deterministic fake Telegram client. Browser requests reach the actual API;
HTTP endpoints are not mocked in Playwright. No personal session or Telegram network access
is required, and uploads/downloads use disposable fixtures.

```bash
python -m pip install -e '.[web,test,browser]'
python -m playwright install chromium
TGMEM_BROWSER_TESTS=1 python -m pytest tests/test_browser.py -q
```

On Linux CI, use `python -m playwright install --with-deps chromium` to install browser system
dependencies too. To use an existing Chromium binary, set `TGMEM_BROWSER_EXECUTABLE=/path/to/chromium`
instead of `TGMEM_BROWSER_TESTS`. Without either opt-in, normal test runs skip browser tests.

Coverage includes desktop pagination and MIME/media filters, favorites, real browser downloads,
source management/discovery, all three remote search scopes, file uploads, monitoring rules and
restart recovery, token entry on mobile, horizontal overflow, JavaScript errors, unexpected HTTP
failures, and inert rendering of message markup. Fake Telegram responses do not validate real
account permissions, flood limits, or Premium/free-search availability.
