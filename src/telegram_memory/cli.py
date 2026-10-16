from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .archive import Archive
from .config import Config, default_config_path, initialize, read_channels, write_channels
from .telegram import download_message, login, search_channel, sync_channel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tgmem",
        description="Search and archive Telegram messages locally. Commands are read-only on Telegram.",
    )
    parser.add_argument("--config", type=Path, default=None, help="Path to config.toml.")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create a local config and empty channel list.")
    init.add_argument("--force", action="store_true", help="Overwrite the config template.")

    commands.add_parser("login", help="Authenticate and create a local Telethon session.")

    channel_parser = commands.add_parser("channels", help="Manage the local channel list.")
    channel_actions = channel_parser.add_subparsers(dest="channel_action", required=True)
    channel_list = channel_actions.add_parser("list", help="List saved channels.")
    channel_list.add_argument("--json", action="store_true")
    channel_add = channel_actions.add_parser("add", help="Add a channel username, URL, or ID.")
    channel_add.add_argument("channel")
    channel_add.add_argument("--json", action="store_true")
    channel_remove = channel_actions.add_parser("remove", help="Remove a channel.")
    channel_remove.add_argument("channel")
    channel_remove.add_argument("--json", action="store_true")

    sync_parser = commands.add_parser("sync", help="Index recent messages and file metadata.")
    sync_parser.add_argument("channel", nargs="?", help="One saved or accessible channel.")
    sync_parser.add_argument("--limit", type=int, default=1000, help="Messages per channel.")
    sync_parser.add_argument("--all", action="store_true", help="Read full channel history.")
    sync_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    search_parser = commands.add_parser(
        "search", help="Search Telegram itself in one channel or across the saved channel list."
    )
    search_parser.add_argument("query")
    search_parser.add_argument("--channel", help="Search only this channel.")
    search_parser.add_argument("--limit", type=int, default=50)
    search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    find_parser = commands.add_parser("find", help="Search the local SQLite archive.")
    find_parser.add_argument("query")
    find_parser.add_argument("--channel")
    find_parser.add_argument("--files-only", action="store_true")
    find_parser.add_argument("--limit", type=int, default=50)
    find_parser.add_argument("--json", action="store_true")

    files_parser = commands.add_parser("files", help="Find indexed Telegram attachments.")
    files_parser.add_argument("--channel")
    files_parser.add_argument("--name", help="Substring of a filename.")
    files_parser.add_argument("--type", dest="file_type", help="MIME type or substring, e.g. pdf.")
    files_parser.add_argument("--min-size", type=int, help="Minimum size in bytes.")
    files_parser.add_argument("--max-size", type=int, help="Maximum size in bytes.")
    files_parser.add_argument("--after", help="Include files on or after YYYY-MM-DD.")
    files_parser.add_argument("--before", help="Include files on or before YYYY-MM-DD.")
    files_parser.add_argument("--favorites", action="store_true")
    files_parser.add_argument("--limit", type=int, default=100)
    files_parser.add_argument("--json", action="store_true")

    download_parser = commands.add_parser("download", help="Download media from a message.")
    download_parser.add_argument("--channel", required=True)
    download_parser.add_argument("--message-id", required=True, type=int)
    download_parser.add_argument("--output", type=Path, help="Destination directory.")
    download_parser.add_argument("--json", action="store_true")

    favorite_parser = commands.add_parser("favorite", help="Manage locally saved favorites.")
    favorite_actions = favorite_parser.add_subparsers(dest="favorite_action", required=True)
    for action in ("add", "remove"):
        item = favorite_actions.add_parser(action)
        item.add_argument("--channel", required=True)
        item.add_argument("--message-id", required=True, type=int)
    list_favorites = favorite_actions.add_parser("list")
    list_favorites.add_argument("--channel")
    list_favorites.add_argument("--limit", type=int, default=100)
    list_favorites.add_argument("--json", action="store_true")

    return parser


def _emit(value: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    elif isinstance(value, list):
        for item in value:
            print(item)
    else:
        print(value)


def _message_summary(item: dict[str, Any]) -> str:
    text = " ".join(str(item.get("text") or "").split())
    if len(text) > 180:
        text = text[:177] + "..."
    attachment = f" | {item['file_name']}" if item.get("file_name") else ""
    return (
        f"{item['channel_name']} #{item['message_id']} {item.get('sent_at') or ''}"
        f"{attachment}\n  {text}"
    )


def _open_archive(config: Config) -> Archive:
    return Archive(config.database_path)


def _load_config(args: argparse.Namespace) -> Config:
    return Config.load(args.config)


async def _run_remote(args: argparse.Namespace, config: Config) -> int:
    client = await login(config)
    try:
        if args.command == "sync":
            targets = [args.channel] if args.channel else read_channels(config.channels_path)
            if not targets:
                raise ValueError("No channels configured. Add one with 'tgmem channels add'.")
            limit = None if args.all else args.limit
            with _open_archive(config) as archive:
                results = []
                for target in targets:
                    count = await sync_channel(client, archive, target, limit=limit)
                    results.append({"channel": target, "indexed_messages": count})
            _emit(results if args.json else [f"{x['channel']}: indexed {x['indexed_messages']} messages" for x in results])
            return 0

        if args.command == "search":
            targets = [args.channel] if args.channel else read_channels(config.channels_path)
            if not targets:
                raise ValueError("No channels configured. Add one or pass --channel.")
            with _open_archive(config) as archive:
                results = []
                for target in targets:
                    results.extend(await search_channel(client, archive, target, args.query, args.limit))
            _emit(results if args.json else [_message_summary(item) for item in results])
            return 0

        if args.command == "download":
            with _open_archive(config) as archive:
                destination = args.output or config.download_dir
                path = await download_message(
                    client, archive, args.channel, args.message_id, destination
                )
            if path is None:
                raise ValueError("The selected message has no downloadable media.")
            _emit({"downloaded": True, "path": str(path)} if args.json else path)
            return 0
    finally:
        await client.disconnect()
    return 1


def run(args: argparse.Namespace) -> int:
    if args.command == "init":
        config_path = args.config or default_config_path()
        if args.force and config_path.exists():
            config_path.unlink()
        config_path, channels_path = initialize(config_path)
        print(f"Config: {config_path}\nChannels: {channels_path}")
        return 0

    config = _load_config(args)

    if args.command == "login":
        async def do_login() -> None:
            client = await login(config)
            await client.disconnect()
        asyncio.run(do_login())
        print(f"Telegram session saved at {config.session_path}")
        return 0

    if args.command == "channels":
        channels = read_channels(config.channels_path)
        if args.channel_action == "list":
            _emit(channels, args.json)
        elif args.channel_action == "add":
            write_channels(config.channels_path, [*channels, args.channel])
            _emit({"added": args.channel}, args.json)
        else:
            remaining = [channel for channel in channels if channel.casefold() != args.channel.casefold()]
            if len(remaining) == len(channels):
                raise ValueError(f"Channel not found in list: {args.channel}")
            write_channels(config.channels_path, remaining)
            _emit({"removed": args.channel}, args.json)
        return 0

    if args.command in {"sync", "search", "download"}:
        return asyncio.run(_run_remote(args, config))

    if args.command in {"find", "files"}:
        with _open_archive(config) as archive:
            if args.command == "find":
                results = archive.search(
                    args.query, channel=args.channel, files_only=args.files_only, limit=args.limit
                )
                as_json = args.json
            else:
                results = archive.list_files(
                    channel=args.channel,
                    name=args.name,
                    file_type=args.file_type,
                    min_size=args.min_size,
                    max_size=args.max_size,
                    after=args.after,
                    before=args.before,
                    favorite=args.favorites,
                    limit=args.limit,
                )
                as_json = args.json
        _emit(results if as_json else [_message_summary(item) for item in results], as_json)
        return 0

    if args.command == "favorite":
        with _open_archive(config) as archive:
            if args.favorite_action in {"add", "remove"}:
                success = archive.set_favorite(
                    args.channel, args.message_id, args.favorite_action == "add"
                )
                if not success:
                    raise ValueError("Message is not in the local archive. Run sync or search first.")
                verb = "Added" if args.favorite_action == "add" else "Removed"
                print(f"{verb} favorite: {args.channel} #{args.message_id}")
            else:
                results = archive.favorites(channel=args.channel, limit=args.limit)
                _emit(
                    results if args.json else [_message_summary(item) for item in results],
                    args.json,
                )
        return 0

    return 2


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code = run(args)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"tgmem: {exc}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        print("tgmem: interrupted", file=sys.stderr)
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
