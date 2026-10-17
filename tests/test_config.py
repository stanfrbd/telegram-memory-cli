from telegram_memory.config import Config, initialize, read_channels, write_channels


def test_initialize_creates_config_and_empty_channel_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    config_path = tmp_path / "config" / "tgmem.toml"
    created_config, channels_path = initialize(config_path)

    assert created_config == config_path
    assert channels_path.exists()
    assert "YOUR_API_HASH" in config_path.read_text()
    assert read_channels(channels_path) == []


def test_config_load_resolves_relative_channels_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    config_path, channels_path = initialize(tmp_path / "config" / "config.toml")
    config_path.write_text(
        '[telegram]\napi_id = 123\napi_hash = "abc"\n[channels]\nfile = "channels.txt"\n',
        encoding="utf-8",
    )

    config = Config.load(config_path)
    assert config.api_id == 123
    assert config.channels_path == channels_path
    assert config.database_path == tmp_path / "data/tgmem/archive.sqlite3"


def test_channel_list_ignores_comments_and_deduplicates(tmp_path):
    path = tmp_path / "channels.txt"
    path.write_text("# comment\n@one\n\n @two \n@one\n", encoding="utf-8")

    assert read_channels(path) == ["@one", "@two"]
    write_channels(path, ["@one", " @two ", "@one", ""])
    assert read_channels(path) == ["@one", "@two"]


def test_config_loads_optional_server_token(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[telegram]\napi_id=123\napi_hash="abc"\n[server]\napi_token="persistent-token"\n'
    )
    config = Config.load(path)
    assert config.server_api_token == "persistent-token"
    assert "persistent-token" not in repr(config)
    path.write_text('[telegram]\napi_id=123\napi_hash="abc"\n')
    assert Config.load(path).server_api_token is None


def test_api_token_priority(tmp_path, monkeypatch):
    from dataclasses import replace

    from telegram_memory.config import resolve_api_token

    path = tmp_path / "config.toml"
    path.write_text('[telegram]\napi_id=123\napi_hash="abc"\n[server]\napi_token="config-token"\n')
    config = Config.load(path)
    monkeypatch.delenv("TGMEM_API_TOKEN", raising=False)
    assert resolve_api_token(config) == "config-token"
    monkeypatch.setenv("TGMEM_API_TOKEN", "env-token")
    assert resolve_api_token(config) == "env-token"
    assert resolve_api_token(config, "cli-token") == "cli-token"
    monkeypatch.setenv("TGMEM_API_TOKEN", "  ")
    assert resolve_api_token(config, "") == "config-token"
    assert resolve_api_token(replace(config, server_api_token=None)) is None
