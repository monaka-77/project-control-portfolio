from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .models import Task, TaskPriority, TaskStatus, utc_now_iso
from .repository import JsonTaskRepository, RepositoryError


# 優先度を画面表示・一覧表示で一貫して並べるためのソート順位。
PRIORITY_ORDER = {
    TaskPriority.URGENT: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 3,
}

# 完了・取消は「現在対応中のタスク」から除外するため、共通集合として定義する。
DONE_LIKE_STATUSES = {TaskStatus.DONE, TaskStatus.CANCELLED}


class ServiceError(ValueError):
    """利用者の操作内容や業務ルールに問題がある場合に送出する例外。"""


@dataclass(frozen=True)
class ProgressEntry:
    """プロジェクト別進捗を表示するための集計結果。"""

    project: str
    total: int
    todo: int
    in_progress: int
    blocked: int
    review: int
    done: int
    overdue: int
    completion_rate: float


@dataclass(frozen=True)
class DashboardProject:
    """ダッシュボードに表示するプロジェクト単位の集計結果。"""

    project: str
    total: int
    active: int
    todo: int
    in_progress: int
    blocked: int
    review: int
    done: int
    overdue: int
    due_today: int
    due_soon: int
    urgent_high: int
    completion_rate: float


@dataclass(frozen=True)
class DashboardData:
    """ダッシュボード生成に必要な全体集計と表示対象Taskをまとめたデータ。"""

    total: int
    active: int
    completed: int
    archived: int
    overdue: int
    due_today: int
    due_soon: int
    blocked: int
    review: int
    urgent_high: int
    no_due_active: int
    projects: list[DashboardProject]
    next_tasks: list[Task]
    tasks: list[Task]


class ProjectControlService:
    """CLIとRepositoryの間で、Taskに関する業務ルールを担当するService。

    CLI側へ永続化や状態遷移の詳細を漏らさず、入力検証・状態変更・集計・
    バックアップ・CSV出力などのユースケースをここへ集約する。
    """

    def __init__(
        self,
        repository: JsonTaskRepository,
        *,
        repo_root: Path | str | None = None,
        date_format: str = "%Y-%m-%d",
        now_provider: Callable[[], str] | None = None,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self.repository = repository
        self.repo_root = Path(repo_root).resolve() if repo_root is not None else repository.path.parent.parent.resolve()
        self.date_format = date_format
        # 時刻取得を差し替え可能にし、テスト結果を実行時刻へ依存させない。
        self.now_provider = now_provider or utc_now_iso
        self.today_provider = today_provider or date.today

    def add_task(
        self,
        *,
        title: str,
        project: str,
        status: TaskStatus | str,
        priority: TaskPriority | str,
        description: str = "",
        due_date: str | None = None,
        tags: list[str] | None = None,
    ) -> Task:
        """入力を検証してTaskを追加し、Repositoryへ保存する。"""

        self._validate_due_date(due_date)
        tasks = self.repository.load()
        task = Task(
            title=title,
            project=project,
            status=status,
            priority=priority,
            description=description,
            due_date=due_date,
            tags=tags or [],
        )
        if task.status == TaskStatus.DONE and task.completed_at is None:
            now_iso = self.now_provider()
            task.completed_at = now_iso
            task.updated_at = now_iso
        tasks.append(task)
        self.repository.save(tasks)
        return task

    def get_task(self, task_id: str) -> Task:
        """UUIDを検証した上でTaskを取得し、存在しなければ明示的に失敗する。"""

        task_id = Task._validate_id(task_id)
        task = self.repository.find_by_id(task_id)
        if task is None:
            raise ServiceError(f"Task was not found: {task_id}")
        return task

    def update_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        project: str | None = None,
        status: TaskStatus | str | None = None,
        priority: TaskPriority | str | None = None,
        description: str | None = None,
        due_date: str | None = None,
        clear_due_date: bool = False,
        tags: list[str] | None = None,
        clear_tags: bool = False,
    ) -> Task:
        """指定された項目だけを更新し、Task全体を再検証してから保存する。"""

        if due_date is not None and clear_due_date:
            raise ServiceError("--due-date and --clear-due-date cannot be used together.")
        if tags is not None and clear_tags:
            raise ServiceError("--tag and --clear-tags cannot be used together.")
        if all(
            value is None or value is False
            for value in (title, project, status, priority, description, due_date, tags, clear_due_date, clear_tags)
        ):
            raise ServiceError("No changes were specified.")

        tasks = self.repository.load()
        task = self._find_task_in_list(tasks, task_id)
        self._ensure_not_archived(task)

        if title is not None:
            task.title = title
        if project is not None:
            task.project = project
        if priority is not None:
            task.priority = TaskPriority(priority)
        if description is not None:
            task.description = description
        if due_date is not None:
            self._validate_due_date(due_date)
            task.due_date = due_date
        elif clear_due_date:
            task.due_date = None
        if tags is not None:
            task.tags = tags
        elif clear_tags:
            task.tags = []

        if status is not None:
            self._apply_status(task, TaskStatus(status), allow_same=True)

        task.updated_at = self.now_provider()
        # 変更後のTaskを再生成して、保存前に型・日時・Enum等の整合性を再確認する。
        Task.from_dict(task.to_dict())
        self.repository.save(tasks)
        return task

    def change_status(self, task_id: str, new_status: TaskStatus | str) -> tuple[Task, TaskStatus]:
        """Taskの状態を変更し、変更前の状態も呼び出し元へ返す。"""

        tasks = self.repository.load()
        task = self._find_task_in_list(tasks, task_id)
        self._ensure_not_archived(task)
        parsed_status = TaskStatus(new_status)
        old_status = task.status
        if old_status == parsed_status:
            raise ServiceError(f"Task is already in status '{parsed_status.value}'.")
        self._apply_status(task, parsed_status)
        task.updated_at = self.now_provider()
        self.repository.save(tasks)
        return task, old_status

    def complete_task(self, task_id: str) -> Task:
        """Taskを完了状態へ変更し、完了日時を設定して保存する。"""

        tasks = self.repository.load()
        task = self._find_task_in_list(tasks, task_id)
        self._ensure_not_archived(task)
        if task.status == TaskStatus.DONE:
            raise ServiceError("Task is already completed.")
        self._apply_status(task, TaskStatus.DONE)
        task.updated_at = self.now_provider()
        self.repository.save(tasks)
        return task

    def archive_task(self, task_id: str) -> Task:
        """Taskを物理削除せず、アーカイブ日時を設定して履歴として残す。"""

        tasks = self.repository.load()
        task = self._find_task_in_list(tasks, task_id)
        if task.archived_at is not None:
            raise ServiceError("Task is already archived.")
        now_iso = self.now_provider()
        task.archived_at = now_iso
        task.updated_at = now_iso
        self.repository.save(tasks)
        return task

    def list_tasks(
        self,
        *,
        project: str | None = None,
        status: TaskStatus | str | None = None,
        priority: TaskPriority | str | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        overdue: bool = False,
        due_soon_days: int | None = None,
        completed: bool = False,
        active: bool = False,
    ) -> list[Task]:
        """複数条件をANDで適用し、通常表示対象のTaskを優先度・期限順で返す。"""

        if overdue and due_soon_days is not None:
            raise ServiceError("--overdue and --due-soon cannot be used together.")
        if completed and active:
            raise ServiceError("--completed and --active cannot be used together.")
        if due_soon_days is not None and due_soon_days < 0:
            raise ServiceError("--due-soon must be 0 or greater.")

        tasks = self.repository.load()
        if not include_archived:
            tasks = [task for task in tasks if task.archived_at is None]
        if project is not None:
            tasks = [task for task in tasks if task.project == project]
        if status is not None:
            status_value = TaskStatus(status)
            tasks = [task for task in tasks if task.status == status_value]
        if priority is not None:
            priority_value = TaskPriority(priority)
            tasks = [task for task in tasks if task.priority == priority_value]
        if tag is not None:
            tasks = [task for task in tasks if tag in task.tags]
        if completed:
            tasks = [task for task in tasks if task.status == TaskStatus.DONE and task.archived_at is None]
        if active:
            tasks = [task for task in tasks if task.archived_at is None and task.status not in DONE_LIKE_STATUSES]
        if overdue:
            tasks = [task for task in tasks if self.get_due_state(task) == "期限切れ"]
        if due_soon_days is not None:
            tasks = [task for task in tasks if self._is_due_soon(task, due_soon_days)]
        return sorted(tasks, key=_task_sort_key)

    def list_archived_tasks(
        self,
        *,
        project: str | None = None,
        status: TaskStatus | str | None = None,
        priority: TaskPriority | str | None = None,
        tag: str | None = None,
    ) -> list[Task]:
        """アーカイブ済みTaskだけを抽出し、更新の新しい順で返す。"""

        tasks = [task for task in self.repository.load() if task.archived_at is not None]
        if project is not None:
            tasks = [task for task in tasks if task.project == project]
        if status is not None:
            status_value = TaskStatus(status)
            tasks = [task for task in tasks if task.status == status_value]
        if priority is not None:
            priority_value = TaskPriority(priority)
            tasks = [task for task in tasks if task.priority == priority_value]
        if tag is not None:
            tasks = [task for task in tasks if tag in task.tags]
        return sorted(
            tasks,
            key=lambda task: (task.archived_at or "", task.updated_at),
            reverse=True,
        )

    def get_due_state(self, task: Task, *, today: date | None = None) -> str:
        """Taskの状態と期限から、画面表示用の期限状態を判定する。"""

        base_today = today or self.today_provider()
        if task.status == TaskStatus.DONE:
            return "完了済み"
        if task.status == TaskStatus.CANCELLED:
            return "対象外"
        if not task.due_date:
            return "期限なし"
        due = self._parse_due_date(task.due_date)
        if due < base_today:
            return "期限切れ"
        if due == base_today:
            return "今日"
        if due <= base_today + timedelta(days=3):
            return "期限間近"
        return "予定"

    def get_progress(self, *, project: str | None = None) -> list[ProgressEntry]:
        """アーカイブを除外し、プロジェクトごとの進捗率と状態件数を集計する。"""

        tasks = [task for task in self.repository.load() if task.archived_at is None]
        if project is not None:
            tasks = [task for task in tasks if task.project == project]
        grouped: dict[str, list[Task]] = {}
        for task in tasks:
            grouped.setdefault(task.project, []).append(task)

        entries: list[ProgressEntry] = []
        for project_name in sorted(grouped):
            group = grouped[project_name]
            # CANCELLEDは「完了率」の母数へ含めず、実際に完了したTaskの進捗を表す。
            denominator = sum(1 for task in group if task.status != TaskStatus.CANCELLED)
            done_count = sum(1 for task in group if task.status == TaskStatus.DONE)
            entries.append(
                ProgressEntry(
                    project=project_name,
                    total=len(group),
                    todo=sum(1 for task in group if task.status in {TaskStatus.INBOX, TaskStatus.PLANNED}),
                    in_progress=sum(1 for task in group if task.status == TaskStatus.IN_PROGRESS),
                    blocked=sum(1 for task in group if task.status == TaskStatus.BLOCKED),
                    review=sum(1 for task in group if task.status == TaskStatus.REVIEW),
                    done=done_count,
                    overdue=sum(1 for task in group if self.get_due_state(task) == "期限切れ"),
                    completion_rate=round((done_count / denominator * 100) if denominator else 0.0, 1),
                )
            )
        return entries

    def summary(self) -> dict[str, Any]:
        """全Taskを対象に、CLIサマリー表示用の件数を集計する。"""

        tasks = self.repository.load()
        active_tasks = [task for task in tasks if task.archived_at is None and task.status not in DONE_LIKE_STATUSES]
        visible_tasks = [task for task in tasks if task.archived_at is None]
        return {
            "total": len(tasks),
            "active": len(active_tasks),
            "completed": sum(1 for task in visible_tasks if task.status == TaskStatus.DONE),
            "archived": sum(1 for task in tasks if task.archived_at is not None),
            "overdue": sum(1 for task in visible_tasks if self.get_due_state(task) == "期限切れ"),
            "due_soon": sum(1 for task in visible_tasks if self.get_due_state(task) == "期限間近"),
            "by_project": dict(sorted(Counter(task.project for task in tasks).items())),
            "by_status": {status.value: sum(1 for task in tasks if task.status == status) for status in TaskStatus},
            "by_priority": {priority.value: sum(1 for task in tasks if task.priority == priority) for priority in TaskPriority},
        }

    def get_dashboard(
        self,
        *,
        project: str | None = None,
        due_soon_days: int = 3,
        limit: int = 5,
    ) -> DashboardData:
        """ダッシュボード表示用に、全体・プロジェクト別・注目Taskを集計する。"""

        if due_soon_days < 0:
            raise ServiceError("--due-soon must be 0 or greater.")
        if limit < 0:
            raise ServiceError("--limit must be 0 or greater.")

        tasks = self.repository.load()
        if project is not None:
            tasks = [task for task in tasks if task.project == project]
        visible_tasks = [task for task in tasks if task.archived_at is None]
        active_tasks = [task for task in visible_tasks if task.status not in DONE_LIKE_STATUSES]

        projects = self._dashboard_projects(visible_tasks, due_soon_days)
        next_tasks = sorted(
            [
                task
                for task in active_tasks
                if self._is_dashboard_focus_task(task, due_soon_days)
            ],
            key=lambda task: self._dashboard_focus_sort_key(task, due_soon_days),
        )[:limit]

        return DashboardData(
            total=len(tasks),
            active=len(active_tasks),
            completed=sum(1 for task in visible_tasks if task.status == TaskStatus.DONE),
            archived=sum(1 for task in tasks if task.archived_at is not None),
            overdue=sum(1 for task in visible_tasks if self.get_due_state(task) == "期限切れ"),
            due_today=sum(1 for task in visible_tasks if self.get_due_state(task) == "今日"),
            due_soon=sum(1 for task in active_tasks if self._is_due_soon(task, due_soon_days)),
            blocked=sum(1 for task in active_tasks if task.status == TaskStatus.BLOCKED),
            review=sum(1 for task in active_tasks if task.status == TaskStatus.REVIEW),
            urgent_high=sum(1 for task in active_tasks if task.priority in {TaskPriority.URGENT, TaskPriority.HIGH}),
            no_due_active=sum(1 for task in active_tasks if task.due_date is None),
            projects=projects,
            next_tasks=next_tasks,
            tasks=sorted(visible_tasks, key=_task_sort_key),
        )

    def create_backup(self) -> tuple[Path, int]:
        """現在のTaskデータを、上書きを避けたJSONバックアップとして保存する。"""

        backup_dir = self.repo_root / "backups"
        timestamp = self._timestamp_slug()
        destination = backup_dir / f"tasks-{timestamp}.json"
        return self.repository.create_backup(destination)

    def export_csv(
        self,
        *,
        output: str | None = None,
        include_archived: bool = False,
    ) -> tuple[Path, int]:
        """TaskをUTF-8 BOM付きCSVへ安全に書き出し、保存先と件数を返す。"""

        tasks = self.list_tasks(include_archived=include_archived)
        destination = self._resolve_export_path(output)
        final_path = _next_available_path(destination)
        rows = [
            [
                "id",
                "title",
                "project",
                "status",
                "priority",
                "description",
                "due_date",
                "tags",
                "created_at",
                "updated_at",
                "completed_at",
                "archived_at",
            ]
        ]
        rows.extend(
            [
                [
                    task.id,
                    task.title,
                    task.project,
                    task.status.value,
                    task.priority.value,
                    task.description,
                    task.due_date or "",
                    "|".join(task.tags),
                    task.created_at,
                    task.updated_at,
                    task.completed_at or "",
                    task.archived_at or "",
                ]
                for task in tasks
            ]
        )
        _write_csv_atomically(final_path, rows)
        return final_path, len(tasks)

    def _resolve_export_path(self, output: str | None) -> Path:
        if output is None:
            return self.repo_root / "exports" / f"tasks-{self._timestamp_slug()}.csv"
        # Windows/POSIXの区切り文字を統一し、どちらの形式の `../` でも外部出力を拒否する。
        candidate = Path(output.replace("\\", "/"))
        if candidate.is_absolute():
            raise ServiceError("Absolute output paths are not allowed.")
        resolved = (self.repo_root / candidate).resolve()
        if not resolved.is_relative_to(self.repo_root):
            raise ServiceError("Output path must stay inside the repository root.")
        return resolved

    def _timestamp_slug(self) -> str:
        return datetime.fromisoformat(self.now_provider()).strftime("%Y%m%d-%H%M%S")

    def _validate_due_date(self, due_date: str | None) -> None:
        if due_date is None:
            return
        try:
            datetime.strptime(due_date, self.date_format)
        except ValueError as exc:
            raise ServiceError(f"due_date must match date_format {self.date_format}: {due_date}") from exc

    def _parse_due_date(self, due_date: str) -> date:
        return datetime.strptime(due_date, self.date_format).date()

    def _is_due_soon(self, task: Task, days: int) -> bool:
        if task.archived_at is not None or task.status in DONE_LIKE_STATUSES or not task.due_date:
            return False
        due = self._parse_due_date(task.due_date)
        today = self.today_provider()
        if due < today:
            return False
        return due <= today + timedelta(days=days)

    def _is_dashboard_focus_task(self, task: Task, days: int) -> bool:
        if task.archived_at is not None or task.status in DONE_LIKE_STATUSES or not task.due_date:
            return task.status in {TaskStatus.BLOCKED, TaskStatus.REVIEW} or task.priority in {
                TaskPriority.URGENT,
                TaskPriority.HIGH,
            }
        due = self._parse_due_date(task.due_date)
        return (
            due <= self.today_provider() + timedelta(days=days)
            or task.status in {TaskStatus.BLOCKED, TaskStatus.REVIEW}
            or task.priority in {TaskPriority.URGENT, TaskPriority.HIGH}
        )

    def _dashboard_focus_sort_key(self, task: Task, days: int) -> tuple[int, int, date, str]:
        today = self.today_provider()
        due = date.max
        if task.due_date:
            due = self._parse_due_date(task.due_date)
        if task.due_date and due < today:
            rank = 0
        elif task.due_date and due == today:
            rank = 1
        elif task.due_date and due <= today + timedelta(days=days):
            rank = 2
        elif task.status == TaskStatus.BLOCKED:
            rank = 3
        elif task.status == TaskStatus.REVIEW:
            rank = 4
        elif task.priority == TaskPriority.URGENT:
            rank = 5
        elif task.priority == TaskPriority.HIGH:
            rank = 6
        else:
            rank = 7
        return (rank, PRIORITY_ORDER[task.priority], due, task.created_at)

    def _dashboard_projects(self, tasks: list[Task], due_soon_days: int) -> list[DashboardProject]:
        grouped: dict[str, list[Task]] = {}
        for task in tasks:
            grouped.setdefault(task.project, []).append(task)

        projects: list[DashboardProject] = []
        for project_name in sorted(grouped):
            group = grouped[project_name]
            active = [task for task in group if task.status not in DONE_LIKE_STATUSES]
            denominator = sum(1 for task in group if task.status != TaskStatus.CANCELLED)
            done_count = sum(1 for task in group if task.status == TaskStatus.DONE)
            projects.append(
                DashboardProject(
                    project=project_name,
                    total=len(group),
                    active=len(active),
                    todo=sum(1 for task in group if task.status in {TaskStatus.INBOX, TaskStatus.PLANNED}),
                    in_progress=sum(1 for task in group if task.status == TaskStatus.IN_PROGRESS),
                    blocked=sum(1 for task in active if task.status == TaskStatus.BLOCKED),
                    review=sum(1 for task in active if task.status == TaskStatus.REVIEW),
                    done=done_count,
                    overdue=sum(1 for task in group if self.get_due_state(task) == "期限切れ"),
                    due_today=sum(1 for task in group if self.get_due_state(task) == "今日"),
                    due_soon=sum(1 for task in active if self._is_due_soon(task, due_soon_days)),
                    urgent_high=sum(1 for task in active if task.priority in {TaskPriority.URGENT, TaskPriority.HIGH}),
                    completion_rate=round((done_count / denominator * 100) if denominator else 0.0, 1),
                )
            )
        return projects

    def _find_task_in_list(self, tasks: list[Task], task_id: str) -> Task:
        validated_task_id = Task._validate_id(task_id)
        for task in tasks:
            if task.id == validated_task_id:
                return task
        raise ServiceError(f"Task was not found: {validated_task_id}")

    def _ensure_not_archived(self, task: Task) -> None:
        if task.archived_at is not None:
            raise ServiceError("Archived tasks cannot be modified.")

    def _apply_status(self, task: Task, new_status: TaskStatus, *, allow_same: bool = False) -> None:
        if not allow_same and task.status == new_status:
            raise ServiceError(f"Task is already in status '{new_status.value}'.")
        task.status = new_status
        if new_status == TaskStatus.DONE:
            task.completed_at = self.now_provider()
        else:
            task.completed_at = None


def _task_sort_key(task: Task) -> tuple[int, date, str]:
    """優先度→期限→作成日時の順で一覧表示を安定させるソートキーを返す。"""

    due = date.max
    if task.due_date:
        try:
            due = date.fromisoformat(task.due_date)
        except ValueError:
            due = date.max
    return (PRIORITY_ORDER[task.priority], due, task.created_at)


def _next_available_path(path: Path) -> Path:
    """既存ファイルを上書きしない、未使用の連番付きパスを返す。"""

    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _write_csv_atomically(path: Path, rows: list[list[str]]) -> None:
    """CSVを一時ファイルへ完全に書いてから置換し、途中失敗による破損を防ぐ。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.tmp"
    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        raise RepositoryError(f"Could not export CSV safely: {path}") from exc
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            # CSV出力本体の成否を、一時ファイル削除エラーで上書きしない。
            pass
