from telegram_memory.archive import Archive
from telegram_memory.cli import build_parser, run
from telegram_memory.config import Config, initialize


def test_parser_accepts_agent_json_file_search():
    args = build_parser().parse_args(
        ["--config", "/tmp/tgmem.toml", "files", "--type", "pdf", "--json"]
    )
    assert args.command == "files"
    assert args.file_type == "pdf"
    assert args.json is True


def test_local_files_command_emits_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    config_path, channels_path = initialize(tmp_path / "config" / "config.toml")
    config_path.write_text(
        '[telegram]\napi_id=123\napi_hash="abc"\n'
        f'[storage]\ndatabase="{tmp_path / "archive.sqlite3"}"\n'
        '[channels]\nfile="channels.txt"\n',
        encoding="utf-8",
    )
    config = Config.load(config_path)
    with Archive(config.database_path) as archive:
        archive.upsert(
            {
                "channel_id": "123",
                "channel_name": "my_channel",
                "message_id": 8,
                "sent_at": "2026-05-01T00:00:00+00:00",
                "message_url": "https://t.me/my_channel/8",
                "text": "monthly report",
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 1000,
                "file_path": None,
            }
        )
    args = build_parser().parse_args(
        ["--config", str(config_path), "files", "--name", "report", "--json"]
    )

    assert run(args) == 0
    output = capsys.readouterr().out
    assert '"file_name": "report.pdf"' in output
