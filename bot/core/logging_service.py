import logging
import sys
from collections import deque
from logging.handlers import RotatingFileHandler

from bot import config


LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
MANAGED_HANDLER_ATTR = "_bard_managed_handler"


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt, sensitive_values=None):
        super().__init__(fmt)
        self.sensitive_values = [value for value in (sensitive_values or []) if value]

    def format(self, record):
        message = super().format(record)
        return redact_text(message, self.sensitive_values)


def sensitive_values():
    return [
        config.TOKEN,
        config.WEBHOOK_SECRET,
        config.ASSISTANT_OPENROUTER_API_KEY,
    ]


def redact_text(text, values=None):
    redacted = text
    for value in values or sensitive_values():
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def configure_logging():
    config.ensure_runtime_dirs()

    formatter = RedactingFormatter(LOG_FORMAT, sensitive_values())
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    for handler in list(root_logger.handlers):
        if getattr(handler, MANAGED_HANDLER_ATTR, False):
            root_logger.removeHandler(handler)
            handler.close()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    setattr(stream_handler, MANAGED_HANDLER_ATTR, True)

    file_handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    setattr(file_handler, MANAGED_HANDLER_ATTR, True)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    return {"strm": stream_handler, "file": file_handler}, formatter


def log_files_newest_first():
    files = []
    for path in config.LOG_DIR.glob(f"{config.LOG_FILE.name}*"):
        if path.is_file():
            files.append(path)

    return sorted(files, key=log_file_age_index)


def log_file_age_index(path):
    if path.name == config.LOG_FILE.name:
        return 0

    suffix = path.name.removeprefix(f"{config.LOG_FILE.name}.")
    try:
        return int(suffix)
    except ValueError:
        return 9999


def recent_logs(max_lines=None):
    max_lines = max_lines or config.LOG_SNIPPET_LINES
    lines = deque(maxlen=max_lines)

    for path in reversed(log_files_newest_first()):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fp:
                for line in fp:
                    lines.append(line.rstrip("\n"))
        except OSError:
            continue

    return list(lines)


def recent_log_text(max_lines=None):
    return "\n".join(recent_logs(max_lines=max_lines))
