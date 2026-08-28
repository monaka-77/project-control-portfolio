from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class TaskModelError(ValueError):
    """タスクデータの形式や値が不正な場合に送出する例外。"""


class TaskStatus(str, Enum):
    """タスクの進行状態。JSONへ保存する値と1対1で対応する。"""

    INBOX = "inbox"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """タスクの優先度。値はCLI・JSON・集計処理で共通利用する。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


def utc_now_iso() -> str:
    """比較・保存しやすいよう、UTC現在時刻を秒精度のISO 8601文字列で返す。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    """文字列をEnumへ変換し、利用可能な値を含む分かりやすいエラーへ変換する。"""

    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TaskModelError(f"{field_name} must be a string.")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed_values = ", ".join(item.value for item in enum_type)
        raise TaskModelError(
            f"Invalid {field_name}: {value}. Allowed values: {allowed_values}."
        ) from exc


def _require_text(value: Any, field_name: str) -> str:
    """必須テキストを検証し、前後空白を除去した値を返す。"""

    if not isinstance(value, str):
        raise TaskModelError(f"{field_name} must be a string.")
    normalized_text = value.strip()
    if not normalized_text:
        raise TaskModelError(f"{field_name} must not be empty.")
    return normalized_text


def _optional_text(value: Any, field_name: str) -> str | None:
    """任意テキストが文字列またはNoneであることを検証する。"""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TaskModelError(f"{field_name} must be a string or null.")
    return value


def _validate_iso_datetime(value: Any, field_name: str) -> str:
    """日時文字列がPythonで解釈可能なISO 8601形式であることを確認する。"""

    if not isinstance(value, str) or not value.strip():
        raise TaskModelError(f"{field_name} must be an ISO 8601 string.")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise TaskModelError(f"{field_name} must be ISO 8601 format.") from exc
    return value


def _validate_tags(value: Any) -> list[str]:
    """タグ配列を検証し、空文字を除いた正規化済みリストを返す。"""

    if value is None:
        return []
    if not isinstance(value, list):
        raise TaskModelError("tags must be a list of strings.")

    validated_tags: list[str] = []
    for tag in value:
        if not isinstance(tag, str):
            raise TaskModelError("tags must be a list of strings.")
        normalized_tag = tag.strip()
        if normalized_tag:
            validated_tags.append(normalized_tag)
    return validated_tags


@dataclass
class Task:
    """ProjectControlの中心となるタスクモデル。

    生成時に公開データをまとめて検証することで、不正な状態のTaskが
    RepositoryやServiceへ流れ込むことを早い段階で防ぐ。
    """

    title: str
    project: str
    status: TaskStatus | str = TaskStatus.INBOX
    priority: TaskPriority | str = TaskPriority.MEDIUM
    description: str = ""
    due_date: str | None = None
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None
    archived_at: str | None = None

    def __post_init__(self) -> None:
        """生成されたTaskを正規化し、保存前に必要な整合性を確認する。"""

        self.id = self._validate_id(self.id)
        self.title = _require_text(self.title, "title")
        self.project = _require_text(self.project, "project")
        self.status = _parse_enum(TaskStatus, self.status, "status")
        self.priority = _parse_enum(TaskPriority, self.priority, "priority")
        if not isinstance(self.description, str):
            raise TaskModelError("description must be a string.")
        self.due_date = _optional_text(self.due_date, "due_date")
        self.created_at = _validate_iso_datetime(self.created_at, "created_at")
        self.updated_at = _validate_iso_datetime(self.updated_at, "updated_at")
        self.completed_at = self._validate_optional_iso_datetime(self.completed_at, "completed_at")
        self.archived_at = self._validate_optional_iso_datetime(self.archived_at, "archived_at")
        self.tags = _validate_tags(self.tags)

    @staticmethod
    def _validate_id(value: Any) -> str:
        """IDをUUID文字列として検証し、表記を正規化する。"""

        if not isinstance(value, str) or not value.strip():
            raise TaskModelError("id must be a UUID string.")
        try:
            return str(UUID(value))
        except ValueError as exc:
            raise TaskModelError("id must be a valid UUID.") from exc

    @staticmethod
    def _validate_optional_iso_datetime(value: Any, field_name: str) -> str | None:
        """任意日時フィールドを、Noneを許可した上で検証する。"""

        if value is None:
            return None
        return _validate_iso_datetime(value, field_name)

    def to_dict(self) -> dict[str, Any]:
        """JSONへ安全に保存できるプリミティブ型の辞書へ変換する。"""

        return {
            "id": self.id,
            "title": self.title,
            "project": self.project,
            "status": self.status.value,
            "priority": self.priority.value,
            "description": self.description,
            "due_date": self.due_date,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "archived_at": self.archived_at,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """JSON由来の辞書からTaskを復元し、必須項目と各値を再検証する。"""

        if not isinstance(data, dict):
            raise TaskModelError("task must be a JSON object.")

        # 欠損した古い・壊れたデータを暗黙補完せず、保存前に明示的に検出する。
        required_fields = {"id", "title", "project", "status", "priority", "created_at", "updated_at"}
        missing_fields = sorted(required_fields - set(data))
        if missing_fields:
            raise TaskModelError(
                f"task is missing required field(s): {', '.join(missing_fields)}."
            )

        return cls(
            id=data["id"],
            title=data["title"],
            project=data["project"],
            status=data["status"],
            priority=data["priority"],
            description=data.get("description", ""),
            due_date=data.get("due_date"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            completed_at=data.get("completed_at"),
            archived_at=data.get("archived_at"),
            tags=data.get("tags", []),
        )
