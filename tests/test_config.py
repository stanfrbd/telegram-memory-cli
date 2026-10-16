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
        '[telegram]\napi_id = 123\napi_hash = "abc"\n'
        '[channels]\nfile = "channels.txt"\n',
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
