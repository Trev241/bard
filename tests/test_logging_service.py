import logging

from bot import config
from bot.core import logging_service


def test_recent_logs_reads_latest_lines_across_rotated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "bard.log")

    backup = tmp_path / "bard.log.1"
    active = tmp_path / "bard.log"
    backup.write_text("old one\nold two\n", encoding="utf-8")
    active.write_text("new one\nnew two\n", encoding="utf-8")

    assert logging_service.recent_logs(max_lines=3) == [
        "old two",
        "new one",
        "new two",
    ]


def test_configure_logging_redacts_sensitive_values(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "bard.log")
    monkeypatch.setattr(config, "TOKEN", "secret-token")

    logging_service.configure_logging()
    logging.getLogger("test.logging").error("token=%s", "secret-token")

    text = config.LOG_FILE.read_text(encoding="utf-8")
    assert "secret-token" not in text
    assert "[REDACTED]" in text
