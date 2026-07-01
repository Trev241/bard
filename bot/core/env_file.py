from pathlib import Path
from typing import Dict, Iterable, Optional


def read_env_values(path: Path) -> Dict[str, str]:
    values = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = unquote_env_value(value)
    return values


def update_env_file(
    path: Path,
    updates: Dict[str, Optional[str]],
    *,
    remove_keys: Iterable[str] = (),
) -> None:
    remove_key_set = set(remove_keys)
    remaining_updates = dict(updates)
    output_lines = []

    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    for line in lines:
        parsed = parse_env_line(line)
        if parsed is None:
            output_lines.append(line)
            continue

        key, _value = parsed
        if key in remove_key_set:
            continue
        if key in remaining_updates:
            value = remaining_updates.pop(key)
            if value is not None:
                output_lines.append(format_env_line(key, value))
            continue
        output_lines.append(line)

    for key, value in remaining_updates.items():
        if key in remove_key_set or value is None:
            continue
        output_lines.append(format_env_line(key, value))

    path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")


def parse_env_line(line: str):
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip()


def format_env_line(key: str, value: str) -> str:
    if needs_quoting(value):
        return f'{key}="{escape_env_value(value)}"'
    return f"{key}={value}"


def needs_quoting(value: str) -> bool:
    return any(char.isspace() for char in value) or any(
        char in value for char in {'"', "'", "#", "\\"}
    )


def escape_env_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace('"', '\\"')
    )


def unquote_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
        return (
            value.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value
