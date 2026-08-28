from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import TaskPriority, TaskStatus


class ConfigError(RuntimeError):
    """ProjectControlの設定ファイルが不正な場合に送出する例外。"""


@dataclass(frozen=True)
class ProjectConfig:
    """検証済みのProjectControl設定を保持する不変オブジェクト。"""

    config_file: Path
    data_file: Path
    default_status: TaskStatus
    default_priority: TaskPriority
    date_format: str


def _require_key(config_data: dict[str, Any], key: str) -> Any:
    """必須設定キーを取得し、欠損時は設定エラーとして明示する。"""

    if key not in config_data:
        raise ConfigError(f"Missing required config key: {key}")
    return config_data[key]


def _parse_enum(
    enum_type: type[TaskStatus] | type[TaskPriority],
    value: Any,
    key: str,
) -> TaskStatus | TaskPriority:
    """設定文字列をEnumへ変換し、許可値を含むエラーへ整形する。"""

    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string.")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed_values = ", ".join(item.value for item in enum_type)
        raise ConfigError(
            f"Invalid {key}: {value}. Allowed values: {allowed_values}."
        ) from exc


def load_config(
    repo_root: Path | str = ".",
    config_path: Path | str | None = None,
) -> ProjectConfig:
    """設定JSONを読み込み、パスと各値を検証したProjectConfigを返す。"""

    repository_root = Path(repo_root).resolve()
    config_file_path = (
        Path(config_path)
        if config_path is not None
        else repository_root / "config" / "project-control.json"
    )
    if not config_file_path.is_absolute():
        config_file_path = repository_root / config_file_path
    config_file_path = config_file_path.resolve()

    if not config_file_path.exists():
        raise ConfigError(f"Config file was not found: {config_file_path}")

    try:
        raw_config = json.loads(config_file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Config file contains invalid JSON: {config_file_path}"
        ) from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file: {config_file_path}") from exc

    if not isinstance(raw_config, dict):
        raise ConfigError("Config JSON root must be an object.")

    data_file_value = _require_key(raw_config, "data_file")
    default_status_value = _require_key(raw_config, "default_status")
    default_priority_value = _require_key(raw_config, "default_priority")
    date_format_value = _require_key(raw_config, "date_format")

    if not isinstance(data_file_value, str) or not data_file_value.strip():
        raise ConfigError("data_file must be a non-empty relative path.")

    relative_data_file = Path(data_file_value)
    if relative_data_file.is_absolute():
        raise ConfigError("data_file must be relative to the repository root.")

    resolved_data_file = (repository_root / relative_data_file).resolve()
    # 設定値を悪用した `../` などで、リポジトリ外へ読み書きしないように制限する。
    if not resolved_data_file.is_relative_to(repository_root):
        raise ConfigError("data_file must not point outside the repository root.")

    if not isinstance(date_format_value, str) or not date_format_value:
        raise ConfigError("date_format must be a non-empty string.")

    return ProjectConfig(
        config_file=config_file_path,
        data_file=resolved_data_file,
        default_status=_parse_enum(TaskStatus, default_status_value, "default_status"),
        default_priority=_parse_enum(TaskPriority, default_priority_value, "default_priority"),
        date_format=date_format_value,
    )
