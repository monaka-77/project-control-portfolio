from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import TaskPriority, TaskStatus


class ConfigError(RuntimeError):
    """Raised when ProjectControl configuration is invalid."""


@dataclass(frozen=True)
class ProjectConfig:
    config_file: Path
    data_file: Path
    default_status: TaskStatus
    default_priority: TaskPriority
    date_format: str


def _require_key(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ConfigError(f"Missing required config key: {key}")
    return data[key]


def _parse_enum(enum_type: type[TaskStatus] | type[TaskPriority], value: Any, key: str):
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string.")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ConfigError(f"Invalid {key}: {value}. Allowed values: {allowed}.") from exc


def load_config(repo_root: Path | str = ".", config_path: Path | str | None = None) -> ProjectConfig:
    root = Path(repo_root).resolve()
    path = Path(config_path) if config_path is not None else root / "config" / "project-control.json"
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.exists():
        raise ConfigError(f"Config file was not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file contains invalid JSON: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file: {path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("Config JSON root must be an object.")

    data_file_value = _require_key(raw, "data_file")
    default_status_value = _require_key(raw, "default_status")
    default_priority_value = _require_key(raw, "default_priority")
    date_format_value = _require_key(raw, "date_format")

    if not isinstance(data_file_value, str) or not data_file_value.strip():
        raise ConfigError("data_file must be a non-empty relative path.")
    data_file = Path(data_file_value)
    if data_file.is_absolute():
        raise ConfigError("data_file must be relative to the repository root.")
    resolved_data_file = (root / data_file).resolve()
    if not resolved_data_file.is_relative_to(root):
        raise ConfigError("data_file must not point outside the repository root.")
    if not isinstance(date_format_value, str) or not date_format_value:
        raise ConfigError("date_format must be a non-empty string.")

    return ProjectConfig(
        config_file=path,
        data_file=resolved_data_file,
        default_status=_parse_enum(TaskStatus, default_status_value, "default_status"),
        default_priority=_parse_enum(TaskPriority, default_priority_value, "default_priority"),
        date_format=date_format_value,
    )
