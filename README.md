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
Use the header's Dark/Light button to switch themes. On the first visit, the interface follows
your system theme; an explicit choice is saved in this browser and retained after reloads.
The theme is applied before the stylesheet loads to prevent a flash of the wrong background.
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
Choose the source above the search bar: **Local index**, **Telegram · saved channels**,
**Telegram · my conversations**, or **Telegram · public posts**. There is one Search button,
whose label reflects the selected source. Queued/running/error states appear below it; Telegram
results appear there automatically when the specific search job finishes. Changing source
prevents an older search from replacing the newly selected view.

Advanced filters are collapsed by default. MIME types are selected from a dropdown combining
common formats and types actually present in the archive. Filters on Telegram results apply to
that returned batch only; they do not request more history. The UI shows returned and matching
counts, result limits, and per-source failures. A filter hiding all results is distinguished from
an API failure. Reset filters clears the selection. Transfers retains the original task details.

Local search now matches separate query words in any order, with FTS prefix matching for partial
words/filenames. Use double quotes for an exact phrase: `"incident response"`. This also applies
to `tgmem find`. SQLite builds without FTS use literal substring conditions for each word/phrase.

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
| POST | `/api/downloads` | Queue `channel`, `message_id`, optional `destination` (`server` or `browser`) |
| GET | `/api/downloads/browser/{job_id}` | Retrieve a temporary browser download once |
| GET | `/api/search/metadata` | Available indexed MIME types and sources |
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

The server binds to localhost by default. Configure a persistent token in your existing
`~/.config/tgmem/config.toml` (or the file supplied via `--config`):

```toml
[server]
api_token = "replace-with-a-long-random-token"
```

Then run `tgmem serve --host 0.0.0.0 --port 9080`; no environment variable is needed.
The `[server]` section is optional, so existing configurations remain compatible. Newly
initialized configuration templates include it. A blank token is treated as unset.
Precedence is **`--token` → `TGMEM_API_TOKEN` → `[server].api_token`**; the first non-empty value
wins. The environment variable remains supported for containers and temporary overrides.
Restart the server after changing the configured token. A token is mandatory for non-loopback binds. When authentication is enabled, the web page first shows
an API-token connection screen; the workspace stays hidden until the server validates the token.
The token is saved in browser `localStorage` and checked automatically after reloads or reopening
the page. A valid saved token opens the workspace immediately; a rejected one is forgotten and
the connection screen asks for the current token. **Set API token** reopens that screen to change
credentials; **Forget saved token** clears storage and returns to the connection screen.
The public `/api/auth` endpoint exposes only whether a token is required, never credentials or
account data. Servers without token authentication open the workspace directly. Storage is
specific to the browser profile and origin (scheme, host, and port), so another machine/browser
or address needs its own initial token entry. If storage is blocked, the token works for the
current page only. API clients send `Authorization: Bearer TOKEN`. API and documentation
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
never asks for login codes or passwords: authenticate in the CLI. Persistent downloads are served only
from the configured download directory; browser-only downloads use isolated temporary files.
Both are served as attachments. Web uploads are streamed
to a temporary file, capped at 2 GiB, and removed after the task. Uploading sends a Telegram
message; searches, indexing, favorites, and source-list edits do not modify Telegram content.

## Run automatically as a service (Linux)

For a Linux VM, use **systemd** unless you already manage your applications with **Supervisor**.
Both examples below run the same `tgmem serve` process in the foreground, start it at boot
through the process manager, and restart it after an unexpected failure. Choose **one** manager
for this instance: do not run both against the same port, SQLite database, or Telegram session.
These are Debian/Ubuntu examples; adjust package names and paths for other distributions.

### Prepare the service account, installation, and configuration

The examples use a dedicated `tgmem` account, an installation in `/opt/telegram-memory-cli`,
and persistent configuration/session/archive/downloads in `/var/lib/tgmem`. Python 3.11 or
newer is required. Run these commands once on the server (skip the user/clone commands if
those already exist):

```bash
sudo apt-get update
sudo apt-get install git python3-venv
sudo useradd --system --user-group --create-home --home-dir /var/lib/tgmem --shell /usr/sbin/nologin tgmem
sudo install -d -o tgmem -g tgmem -m 0755 /opt/telegram-memory-cli
sudo -H -u tgmem git clone https://github.com/stanfrbd/telegram-memory-cli.git /opt/telegram-memory-cli
sudo -H -u tgmem python3 -m venv /opt/telegram-memory-cli/.venv
sudo -H -u tgmem /opt/telegram-memory-cli/.venv/bin/python -m pip install '/opt/telegram-memory-cli[web]'
sudo chmod 700 /var/lib/tgmem
sudo -H -u tgmem /opt/telegram-memory-cli/.venv/bin/tgmem --config /var/lib/tgmem/config.toml init
sudoedit /var/lib/tgmem/config.toml
```

Edit the configuration with your real Telegram credentials and a server token. Use **absolute
paths** so the service uses the same files regardless of its environment or working directory:

```toml
[telegram]
api_id = 12345
api_hash = "YOUR_API_HASH"
phone = ""
session_path = "/var/lib/tgmem/session"

[storage]
database = "/var/lib/tgmem/archive.sqlite3"
download_dir = "/var/lib/tgmem/downloads"

[channels]
file = "/var/lib/tgmem/channels.txt"

[server]
api_token = "REPLACE_WITH_A_LONG_RANDOM_TOKEN"
```

For example, generate a token with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`
and paste it into `server.api_token`. The configuration file must remain readable by `tgmem`.
Authenticate **interactively as that same account with that same config**, before starting the
background service; Telegram login codes and two-step verification cannot be entered through
the web interface or the service manager:

```bash
sudo chown tgmem:tgmem /var/lib/tgmem/config.toml
sudo chmod 600 /var/lib/tgmem/config.toml
sudo -H -u tgmem /opt/telegram-memory-cli/.venv/bin/tgmem --config /var/lib/tgmem/config.toml login
sudo -H -u tgmem /opt/telegram-memory-cli/.venv/bin/tgmem --config /var/lib/tgmem/config.toml channels add @my_channel
```

`serve` reuses this session. It never prompts for Telegram login interactively. Stop the service
before running another Telegram CLI operation with this session (including a fresh `login`).

### Option A: systemd (recommended for a VM)

The repository includes [deploy/tgmem.service](deploy/tgmem.service):

```ini
[Unit]
Description=Telegram Memory web interface and API
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=tgmem
Group=tgmem
WorkingDirectory=/opt/telegram-memory-cli
ExecStart=/opt/telegram-memory-cli/.venv/bin/tgmem --config /var/lib/tgmem/config.toml serve --host 0.0.0.0 --port 9080
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
Environment=PYTHONUNBUFFERED=1
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Install, enable at boot, and start it:

```bash
sudo cp /opt/telegram-memory-cli/deploy/tgmem.service /etc/systemd/system/tgmem.service
sudo systemctl daemon-reload
sudo systemctl enable --now tgmem
sudo systemctl status tgmem --no-pager
sudo journalctl -u tgmem -f
```

To restart or stop it:

```bash
sudo systemctl restart tgmem
sudo systemctl stop tgmem
```

Change `--host` and `--port` in `/etc/systemd/system/tgmem.service` to suit your VM, then run
`sudo systemctl daemon-reload` and `sudo systemctl restart tgmem`. After editing only
`config.toml` (for example, the API token), a service restart is sufficient.

### Option B: Supervisor

On Debian/Ubuntu, install Supervisor and ensure its daemon starts at boot:

```bash
sudo apt-get install supervisor
sudo systemctl enable --now supervisor
sudo install -d -o tgmem -g tgmem -m 0750 /var/log/tgmem
sudo cp /opt/telegram-memory-cli/deploy/supervisor.conf /etc/supervisor/conf.d/tgmem.conf
```

The included [deploy/supervisor.conf](deploy/supervisor.conf) contains:

```ini
[program:tgmem]
command=/opt/telegram-memory-cli/.venv/bin/tgmem --config /var/lib/tgmem/config.toml serve --host 0.0.0.0 --port 9080
directory=/opt/telegram-memory-cli
user=tgmem
autostart=true
autorestart=unexpected
startsecs=5
startretries=3
stopsignal=TERM
stopwaitsecs=45
stopasgroup=true
killasgroup=true
umask=0077
environment=PYTHONUNBUFFERED="1"
redirect_stderr=true
stdout_logfile=/var/log/tgmem/server.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
```

Load the program, check it, and follow its logs:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status tgmem
sudo supervisorctl tail -f tgmem
```

For routine management:

```bash
sudo supervisorctl restart tgmem
sudo supervisorctl stop tgmem
sudo supervisorctl start tgmem
```

Change `command=` to select a different bind/port. After editing the Supervisor program
configuration, use `reread` and `update`; after editing only `config.toml`, use `restart tgmem`.
If it reaches `FATAL` because initial startup repeatedly failed, fix the configuration and use
`sudo supervisorctl start tgmem`. Supervisor must itself be running for `autostart` to apply.
Its include-directory conventions vary by distribution. Absolute data paths also avoid relying
on Supervisor changing `HOME` when applying `user=tgmem` (it does not start a login shell).

### Access, updates, and troubleshooting

With the example bind, open `http://YOUR_VM_IP:9080` and enter the configured token on the
connection screen. For a reverse proxy running on the same VM/network namespace, change the
bind to `127.0.0.1` and proxy to that address/port instead. A proxy in another container cannot
reach the VM's loopback address directly. Preserve the original `Host` and `Authorization`
headers and configure HTTPS at the proxy. If direct LAN access fails, check the chosen IP/port
and your VM's firewall. `0.0.0.0` is a listen address, not the address to open in your browser.

For an update, stop **your chosen manager's** tgmem instance, update and reinstall the project,
then start the same instance again. Example with systemd:

```bash
sudo systemctl stop tgmem
sudo -H -u tgmem git -C /opt/telegram-memory-cli pull --ff-only
sudo -H -u tgmem /opt/telegram-memory-cli/.venv/bin/python -m pip install --upgrade '/opt/telegram-memory-cli[web]'
sudo systemctl start tgmem
```

For Supervisor, use `sudo supervisorctl stop tgmem` and `sudo supervisorctl start tgmem` around
the same update commands. Do not run the service with multiple workers or enable a development
reloader. Monitoring runs while the service is up; rules survive restarts. Interrupted jobs
are marked as such after restart and are not automatically replayed, including uploads.

If startup fails, inspect the manager's logs first. Common causes are an invalid Telegram API
configuration, a missing server token for a network bind, a port already in use, or file paths
not writable by the service account. A server that opens but cannot perform remote operations
may need a valid Telegram session: stop it, rerun the interactive `login` command above, then
start it again. These templates have been checked as configuration examples; the repository's
browser/API tests do not verify your distribution's boot process or service installation.

References: [systemd service directives](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml),
[systemd execution settings](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml),
[Supervisor configuration](https://supervisord.org/configuration.html),
[Supervisor subprocess environment](https://supervisord.org/subprocess.html).

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
| `downloads.py` | Temporary browser-download lifecycle |
| `static/` | Responsive UI; `search.js` owns source selection, filters, and search state |

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


### Browser downloads versus server storage

Each attachment offers two explicit actions:

- **Download to device** retrieves the file in your browser, including when it has never been
  downloaded before. Telegram transfers through the server into a private temporary directory;
  it does not save a new copy in the configured permanent download directory. The temporary
  file is deleted after retrieval, expires after 30 minutes if abandoned, and is removed on
  orderly server shutdown. A previously saved permanent copy can be reused without contacting
  Telegram again. Browser delivery currently buffers the response as a browser Blob.
- **Save on server** saves the file in the configured download directory on the machine running
  `tgmem serve`, with a visible queued/running/saved state. It does not trigger a browser download.

API clients can POST `{"channel":"@source","message_id":123,"destination":"browser"}` to
`/api/downloads`, poll the returned job ID, then GET its result's `download_url` with the same
Bearer authentication. The URL is single-use and valid only in that server process. Repeat the
POST if it has expired or the server restarted. Browser-only transfers do not set the archive's
permanent `file_path` or count as saved-on-server files. The omitted destination defaults to
`server`, preserving existing API behavior; the CLI download command still saves on the server.

The UI bounds each Telegram query to 100 returned messages. Reaching that limit is displayed;
this version does not automatically page through all Telegram history or spend Telegram Stars.
Narrow the query/source or sync more history and search the local index. Local indexing and
message filtering cannot override Telegram account access, server indexing, quota, or API limits.
