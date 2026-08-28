from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .models import Task, TaskModelError


class RepositoryError(RuntimeError):
    """タスクの読み書きやバックアップ処理に失敗した場合に送出する例外。"""


class JsonTaskRepository:
    """TaskをJSONファイルへ安全に永続化するRepository。

    読み込み時にもTaskモデルを通して再検証し、保存時は一時ファイルへ
    書き込んでから置換することで、途中失敗によるデータ破損を避ける。
    """

    def __init__(self, path: Path | str) -> None:
        # `path` はService側からも参照する公開属性のため、互換性を保ったまま維持する。
        self.path = Path(path)

    def load(self) -> list[Task]:
        """JSONファイルから全Taskを読み込み、形式・重複IDを検証して返す。"""

        if not self.path.exists():
            return []

        try:
            file_text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RepositoryError(f"Could not read task file: {self.path}") from exc

        # 空ファイルを「タスク0件」とみなすと、次回保存で破損データを上書きするため停止する。
        if file_text == "":
            raise RepositoryError(f"Task file is empty and will not be overwritten: {self.path}")

        try:
            raw_tasks = json.loads(file_text)
        except json.JSONDecodeError as exc:
            raise RepositoryError(
                f"Task file contains invalid JSON and will not be overwritten: {self.path}"
            ) from exc
        if not isinstance(raw_tasks, list):
            raise RepositoryError("Task JSON root must be an array.")

        loaded_tasks: list[Task] = []
        seen_task_ids: set[str] = set()
        for raw_task in raw_tasks:
            try:
                task = Task.from_dict(raw_task)
            except TaskModelError as exc:
                raise RepositoryError(f"Invalid task data: {exc}") from exc
            if task.id in seen_task_ids:
                raise RepositoryError(f"Duplicate task id found: {task.id}")
            seen_task_ids.add(task.id)
            loaded_tasks.append(task)
        return loaded_tasks

    def find_by_id(self, task_id: str) -> Task | None:
        """指定IDのTaskを検索し、存在しなければNoneを返す。"""

        for task in self.load():
            if task.id == task_id:
                return task
        return None

    def save(self, tasks: list[Task]) -> None:
        """全Taskを再検証した上で、JSONファイルへ原子的に保存する。"""

        validated_tasks = _validate_tasks(tasks)
        try:
            json_payload = (
                json.dumps(
                    [task.to_dict() for task in validated_tasks],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        except OSError as exc:
            raise RepositoryError(f"Could not save task file safely: {self.path}") from exc

        _atomic_write_text(
            self.path,
            json_payload,
            error_prefix="Could not save task file safely",
        )

    def create_backup(self, destination: Path | str) -> tuple[Path, int]:
        """現在のTaskを検証して別ファイルへバックアップし、保存先と件数を返す。"""

        if not self.path.exists():
            raise RepositoryError(f"Task file was not found: {self.path}")

        loaded_tasks = self.load()
        destination_path = Path(destination)
        backup_path = _next_available_path(destination_path)
        json_payload = (
            json.dumps(
                [task.to_dict() for task in loaded_tasks],
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        _atomic_write_text(
            backup_path,
            json_payload,
            error_prefix="Could not create backup file safely",
        )
        return backup_path, len(loaded_tasks)


def _validate_tasks(tasks: list[Task]) -> list[Task]:
    """保存対象をTaskとして再生成し、型・値・重複IDをまとめて検証する。"""

    if not isinstance(tasks, list):
        raise RepositoryError("tasks must be a list.")

    validated_tasks: list[Task] = []
    seen_task_ids: set[str] = set()
    for task_candidate in tasks:
        if not isinstance(task_candidate, Task):
            raise RepositoryError("tasks must contain only Task instances.")
        try:
            validated_task = Task.from_dict(task_candidate.to_dict())
        except TaskModelError as exc:
            raise RepositoryError(f"Invalid task data: {exc}") from exc
        if validated_task.id in seen_task_ids:
            raise RepositoryError(f"Duplicate task id found: {validated_task.id}")
        seen_task_ids.add(validated_task.id)
        validated_tasks.append(validated_task)
    return validated_tasks


def _next_available_path(path: Path) -> Path:
    """既存ファイルを上書きしないよう、未使用の連番付きパスを返す。"""

    if not path.exists():
        return path

    counter = 1
    while True:
        candidate_path = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate_path.exists():
            return candidate_path
        counter += 1


def _atomic_write_text(path: Path, content: str, *, error_prefix: str) -> None:
    """一時ファイルへ書き込んだ後に置換し、途中失敗による破損を防ぐ。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as file_handle:
            file_handle.write(content)
            file_handle.flush()
            # Python側のバッファだけでなくOS側へも反映してから置換する。
            os.fsync(file_handle.fileno())

        # 同一ファイルシステム内で最後に置換し、半端なJSONが正本になる時間を作らない。
        os.replace(temp_path, path)
    except OSError as exc:
        raise RepositoryError(f"{error_prefix}: {path}") from exc
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            # 本処理のエラーを、一時ファイル掃除の失敗で上書きしない。
            pass
