from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .models import Task, TaskModelError


class RepositoryError(RuntimeError):
    """Raised when task persistence fails."""


class JsonTaskRepository:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> list[Task]:
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RepositoryError(f"Could not read task file: {self.path}") from exc
        if text == "":
            raise RepositoryError(f"Task file is empty and will not be overwritten: {self.path}")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RepositoryError(f"Task file contains invalid JSON and will not be overwritten: {self.path}") from exc
        if not isinstance(raw, list):
            raise RepositoryError("Task JSON root must be an array.")

        tasks: list[Task] = []
        seen_ids: set[str] = set()
        for item in raw:
            try:
                task = Task.from_dict(item)
            except TaskModelError as exc:
                raise RepositoryError(f"Invalid task data: {exc}") from exc
            if task.id in seen_ids:
                raise RepositoryError(f"Duplicate task id found: {task.id}")
            seen_ids.add(task.id)
            tasks.append(task)
        return tasks

    def find_by_id(self, task_id: str) -> Task | None:
        for task in self.load():
            if task.id == task_id:
                return task
        return None

    def save(self, tasks: list[Task]) -> None:
        validated_tasks = _validate_tasks(tasks)
        try:
            payload = json.dumps([task.to_dict() for task in validated_tasks], ensure_ascii=False, indent=2) + "\n"
        except OSError as exc:
            raise RepositoryError(f"Could not save task file safely: {self.path}") from exc
        _atomic_write_text(self.path, payload, error_prefix="Could not save task file safely")

    def create_backup(self, destination: Path | str) -> tuple[Path, int]:
        if not self.path.exists():
            raise RepositoryError(f"Task file was not found: {self.path}")
        tasks = self.load()
        destination_path = Path(destination)
        final_path = _next_available_path(destination_path)
        payload = json.dumps([task.to_dict() for task in tasks], ensure_ascii=False, indent=2) + "\n"
        _atomic_write_text(final_path, payload, error_prefix="Could not create backup file safely")
        return final_path, len(tasks)


def _validate_tasks(tasks: list[Task]) -> list[Task]:
    if not isinstance(tasks, list):
        raise RepositoryError("tasks must be a list.")
    validated_tasks: list[Task] = []
    seen_ids: set[str] = set()
    for item in tasks:
        if not isinstance(item, Task):
            raise RepositoryError("tasks must contain only Task instances.")
        try:
            validated_task = Task.from_dict(item.to_dict())
        except TaskModelError as exc:
            raise RepositoryError(f"Invalid task data: {exc}") from exc
        if validated_task.id in seen_ids:
            raise RepositoryError(f"Duplicate task id found: {validated_task.id}")
        seen_ids.add(validated_task.id)
        validated_tasks.append(validated_task)
    return validated_tasks


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _atomic_write_text(path: Path, content: str, *, error_prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        raise RepositoryError(f"{error_prefix}: {path}") from exc
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
