from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class TaskModelError(ValueError):
    """Raised when task data is invalid."""


class TaskStatus(str, Enum):
    INBOX = "inbox"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TaskModelError(f"{field_name} must be a string.")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise TaskModelError(f"Invalid {field_name}: {value}. Allowed values: {allowed}.") from exc


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TaskModelError(f"{field_name} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise TaskModelError(f"{field_name} must not be empty.")
    return cleaned


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TaskModelError(f"{field_name} must be a string or null.")
    return value


def _validate_iso_datetime(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskModelError(f"{field_name} must be an ISO 8601 string.")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise TaskModelError(f"{field_name} must be ISO 8601 format.") from exc
    return value


def _validate_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TaskModelError("tags must be a list of strings.")
    tags: list[str] = []
    for tag in value:
        if not isinstance(tag, str):
            raise TaskModelError("tags must be a list of strings.")
        cleaned = tag.strip()
        if cleaned:
            tags.append(cleaned)
    return tags


@dataclass
class Task:
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
        if not isinstance(value, str) or not value.strip():
            raise TaskModelError("id must be a UUID string.")
        try:
            return str(UUID(value))
        except ValueError as exc:
            raise TaskModelError("id must be a valid UUID.") from exc

    @staticmethod
    def _validate_optional_iso_datetime(value: Any, field_name: str) -> str | None:
        if value is None:
            return None
        return _validate_iso_datetime(value, field_name)

    def to_dict(self) -> dict[str, Any]:
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
        if not isinstance(data, dict):
            raise TaskModelError("task must be a JSON object.")
        required = {"id", "title", "project", "status", "priority", "created_at", "updated_at"}
        missing = sorted(required - set(data))
        if missing:
            raise TaskModelError(f"task is missing required field(s): {', '.join(missing)}.")
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
