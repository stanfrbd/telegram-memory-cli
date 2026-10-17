from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "tgmem"


def _make_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)


def default_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tgmem/config.toml"


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    phone: str
    session_path: Path
    database_path: Path
    download_dir: Path
    channels_path: Path
    server_api_token: str | None = field(default=None, repr=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        config_path = path or default_config_path()
        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration not found at {config_path}. Run 'tgmem init' first."
            )
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
        telegram = raw.get("telegram", {})
        storage = raw.get("storage", {})
        channels = raw.get("channels", {})
        server = raw.get("server", {})
        if not isinstance(server, dict):
            raise ValueError("The server configuration must be a TOML table.")
        server_token = server.get("api_token", "")
        if not isinstance(server_token, str):
            raise ValueError("server.api_token must be a string.")
        try:
            api_id = int(telegram["api_id"])
            api_hash = str(telegram["api_hash"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Set telegram.api_id and telegram.api_hash in config.toml.") from exc
        if api_id <= 0 or not api_hash or api_hash == "YOUR_API_HASH":
            raise ValueError("Set valid Telegram API credentials in config.toml.")
        data_dir = default_data_dir()

        def configured_path(section: dict, key: str, fallback: Path) -> Path:
            value = section.get(key)
            if not value:
                return fallback
            configured = Path(os.path.expandvars(os.path.expanduser(value)))
            return configured if configured.is_absolute() else config_path.parent / configured

        return cls(
            api_id=api_id,
            api_hash=api_hash,
            phone=str(telegram.get("phone", "")).strip(),
            session_path=configured_path(telegram, "session_path", data_dir / "session"),
            database_path=configured_path(storage, "database", data_dir / "archive.sqlite3"),
            download_dir=configured_path(storage, "download_dir", data_dir / "downloads"),
            channels_path=configured_path(channels, "file", config_path.parent / "channels.txt"),
            server_api_token=server_token.strip() or None,
        )


def initialize(config_path: Path | None = None) -> tuple[Path, Path]:
    target = config_path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data_dir = default_data_dir()
    _make_private_directory(data_dir)
    channels_path = target.parent / "channels.txt"
    if not target.exists():
        target.write_text(
            """# Create an API ID and API hash at https://my.telegram.org/apps
[telegram]
api_id = 0
api_hash = "YOUR_API_HASH"
phone = ""
session_path = "~/.local/share/tgmem/session"

[storage]
database = "~/.local/share/tgmem/archive.sqlite3"
download_dir = "~/Downloads/Telegram"

[channels]
file = "channels.txt"

[server]
# Optional persistent token for the web interface and API.
# Required for non-localhost binds unless supplied by environment or --token.
api_token = ""
""",
            encoding="utf-8",
        )
        try:
            target.chmod(0o600)
        except OSError:
            pass
    if not channels_path.exists():
        channels_path.write_text(
            "# One Telegram channel username, URL, or numeric chat ID per line.\n",
            encoding="utf-8",
        )
    if os.name != "nt":
        channels_path.chmod(0o600)
    return target, channels_path


def read_channels(path: Path) -> list[str]:
    if not path.exists():
        return []
    return list(
        dict.fromkeys(
            value
            for line in path.read_text(encoding="utf-8").splitlines()
            if (value := line.strip()) and not value.startswith("#")
        )
    )


def write_channels(path: Path, channels: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = list(dict.fromkeys(channel.strip() for channel in channels if channel.strip()))
    path.write_text(
        "# One Telegram channel username, URL, or numeric chat ID per line.\n"
        + "".join(f"{channel}\n" for channel in cleaned),
        encoding="utf-8",
    )
    if os.name != "nt":
        path.chmod(0o600)


def resolve_api_token(config: Config, token: str | None = None) -> str | None:
    """Resolve explicit CLI value, environment, then persistent server configuration."""
    for value in (token, os.environ.get("TGMEM_API_TOKEN"), config.server_api_token):
        if value and value.strip():
            return value.strip()
    return None
