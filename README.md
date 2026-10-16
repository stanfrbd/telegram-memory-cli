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
- Read-only on Telegram: the CLI does not send, edit, forward, join, or delete messages.

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
