import csv
import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from project_control.models import Task
from project_control.repository import JsonTaskRepository, RepositoryError
from project_control.service import ProjectControlService, ServiceError


FIXED_NOW = "2026-07-11T09:30:00+00:00"
FIXED_TODAY = date(2026, 7, 11)


class RepositoryTests(unittest.TestCase):
    def test_missing_file_loads_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonTaskRepository(Path(tmp) / "tasks.json")
            self.assertEqual(repo.load(), [])

    def test_save_and_reload_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonTaskRepository(Path(tmp) / "tasks.json")
            task = Task(title="確認", project="SampleProject")
            repo.save([task])
            self.assertEqual(repo.load()[0].to_dict(), task.to_dict())

    def test_japanese_text_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonTaskRepository(Path(tmp) / "tasks.json")
            task = Task(title="日本語タスク", project="多言語ローカライズ", description="説明")
            repo.save([task])
            restored = repo.load()[0]
            self.assertEqual(restored.title, "日本語タスク")
            self.assertEqual(restored.project, "多言語ローカライズ")

    def test_invalid_json_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            path.write_text("{broken", encoding="utf-8")
            repo = JsonTaskRepository(path)
            with self.assertRaises(RepositoryError):
                repo.load()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_json_root_must_be_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            path.write_text("{}", encoding="utf-8")
            repo = JsonTaskRepository(path)
            with self.assertRaises(RepositoryError):
                repo.load()

    def test_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            task = Task(title="確認", project="SampleProject")
            path.write_text(json.dumps([task.to_dict(), task.to_dict()]), encoding="utf-8")
            repo = JsonTaskRepository(path)
            with self.assertRaises(RepositoryError):
                repo.load()

    def test_save_uses_temporary_file_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            repo = JsonTaskRepository(path)
            task = Task(title="確認", project="SampleProject")
            calls = []
            real_replace = os.replace

            def capture_replace(src, dst):
                calls.append((Path(src), Path(dst)))
                real_replace(src, dst)

            with mock.patch("project_control.repository.os.replace", side_effect=capture_replace):
                repo.save([task])

            self.assertEqual(calls[0][1], path)
            self.assertEqual(calls[0][0].parent, path.parent)
            self.assertTrue(calls[0][0].name.endswith(".tmp"))

    def test_find_by_id_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonTaskRepository(Path(tmp) / "tasks.json")
            task = Task(title="確認", project="SampleProject")
            repo.save([task])
            self.assertEqual(repo.find_by_id(task.id).id, task.id)

    def test_find_by_id_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonTaskRepository(Path(tmp) / "tasks.json")
            self.assertIsNone(repo.find_by_id("8d39a481-68d8-4508-9336-9a51cf1e96d4"))

    def test_save_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonTaskRepository(Path(tmp) / "tasks.json")
            task = Task(title="確認", project="SampleProject")
            with self.assertRaises(RepositoryError):
                repo.save([task, Task.from_dict(task.to_dict())])

    def test_save_rejects_non_task_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonTaskRepository(Path(tmp) / "tasks.json")
            with self.assertRaises(RepositoryError):
                repo.save([Task(title="確認", project="SampleProject"), "not-task"])

    def test_backup_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "tasks.json"
            repo = JsonTaskRepository(source)
            repo.save([Task(title="確認", project="SampleProject")])
            backup_path, count = repo.create_backup(Path(tmp) / "backups" / "tasks-20260711-093000.json")
            self.assertTrue(backup_path.exists())
            self.assertEqual(count, 1)

    def test_backup_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "tasks.json"
            repo = JsonTaskRepository(source)
            repo.save([Task(title="確認", project="SampleProject")])
            target = Path(tmp) / "backups" / "tasks-20260711-093000.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("[]", encoding="utf-8")
            backup_path, _ = repo.create_backup(target)
            self.assertEqual(backup_path.name, "tasks-20260711-093000-1.json")

    def test_backup_fails_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "tasks.json"
            source.write_text("{broken", encoding="utf-8")
            repo = JsonTaskRepository(source)
            with self.assertRaises(RepositoryError):
                repo.create_backup(Path(tmp) / "backups" / "tasks-20260711-093000.json")


class ServiceTests(unittest.TestCase):
    def _service(self, tmp):
        return ProjectControlService(
            JsonTaskRepository(Path(tmp) / "tasks.json"),
            repo_root=tmp,
            now_provider=lambda: FIXED_NOW,
            today_provider=lambda: FIXED_TODAY,
        )

    def _add(self, service: ProjectControlService, **kwargs) -> Task:
        params = {"title": "確認", "project": "SampleProject", "priority": "medium", "status": "planned"}
        params.update(kwargs)
        return service.add_task(**params)

    def test_priority_sorting(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="low", priority="low", status="inbox")
            self._add(service, title="urgent", priority="urgent", status="inbox")
            self._add(service, title="high", priority="high", status="inbox")
            self.assertEqual([task.title for task in service.list_tasks()], ["urgent", "high", "low"])

    def test_missing_due_date_sorts_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="no due", priority="high", status="inbox")
            self._add(service, title="due", priority="high", status="inbox", due_date="2026-07-20")
            self.assertEqual([task.title for task in service.list_tasks()], ["due", "no due"])

    def test_filters_are_and_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="match", priority="high", status="planned", tags=["SEO"])
            self._add(service, title="other", priority="low", status="planned", tags=["SEO"])
            tasks = service.list_tasks(project="SampleProject", status="planned", priority="high", tag="SEO")
            self.assertEqual([task.title for task in tasks], ["match"])

    def test_summary_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="a", priority="high", status="planned")
            self._add(service, title="b", project="ContentWorkflow", priority="medium", status="done")
            summary = service.summary()
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["by_project"], {"ContentWorkflow": 1, "SampleProject": 1})
            self.assertEqual(summary["by_status"]["planned"], 1)
            self.assertEqual(summary["by_priority"]["high"], 1)
            self.assertEqual(summary["completed"], 1)

    def test_update_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            updated = service.update_task(task.id, title="新タイトル")
            self.assertEqual(updated.title, "新タイトル")

    def test_update_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            updated = service.update_task(task.id, project="ContentWorkflow")
            self.assertEqual(updated.project, "ContentWorkflow")

    def test_update_status_sets_completed_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            updated = service.update_task(task.id, status="done")
            self.assertEqual(updated.status.value, "done")
            self.assertEqual(updated.completed_at, FIXED_NOW)

    def test_update_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            updated = service.update_task(task.id, priority="urgent")
            self.assertEqual(updated.priority.value, "urgent")

    def test_update_description_to_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, description="説明")
            updated = service.update_task(task.id, description="")
            self.assertEqual(updated.description, "")

    def test_update_due_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            updated = service.update_task(task.id, due_date="2026-07-20")
            self.assertEqual(updated.due_date, "2026-07-20")

    def test_clear_due_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, due_date="2026-07-20")
            updated = service.update_task(task.id, clear_due_date=True)
            self.assertIsNone(updated.due_date)

    def test_replace_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, tags=["SEO"])
            updated = service.update_task(task.id, tags=["PSI", "Docs"])
            self.assertEqual(updated.tags, ["PSI", "Docs"])

    def test_clear_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, tags=["SEO"])
            updated = service.update_task(task.id, clear_tags=True)
            self.assertEqual(updated.tags, [])

    def test_update_rejects_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            with self.assertRaises(ServiceError):
                service.update_task(task.id)

    def test_update_rejects_archived_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            service.archive_task(task.id)
            with self.assertRaises(ServiceError):
                service.update_task(task.id, title="変更")

    def test_update_rejects_missing_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            with self.assertRaises(ServiceError):
                service.update_task("8d39a481-68d8-4508-9336-9a51cf1e96d4", title="変更")

    def test_update_preserves_id_and_created_at_and_updates_updated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            created_at = task.created_at
            updated = service.update_task(task.id, title="変更")
            self.assertEqual(updated.id, task.id)
            self.assertEqual(updated.created_at, created_at)
            self.assertEqual(updated.updated_at, FIXED_NOW)

    def test_change_status_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            changed, old_status = service.change_status(task.id, "in_progress")
            self.assertEqual(old_status.value, "planned")
            self.assertEqual(changed.status.value, "in_progress")

    def test_change_status_rejects_same_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            with self.assertRaises(ServiceError):
                service.change_status(task.id, "planned")

    def test_change_status_done_sets_completed_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            changed, _ = service.change_status(task.id, "done")
            self.assertEqual(changed.completed_at, FIXED_NOW)

    def test_change_status_from_done_clears_completed_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, status="done")
            changed, _ = service.change_status(task.id, "review")
            self.assertIsNone(changed.completed_at)

    def test_complete_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            completed = service.complete_task(task.id)
            self.assertEqual(completed.status.value, "done")
            self.assertEqual(completed.completed_at, FIXED_NOW)

    def test_complete_rejects_second_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, status="done")
            with self.assertRaises(ServiceError):
                service.complete_task(task.id)

    def test_complete_rejects_archived_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            service.archive_task(task.id)
            with self.assertRaises(ServiceError):
                service.complete_task(task.id)

    def test_complete_rejects_missing_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            with self.assertRaises(ServiceError):
                service.complete_task("8d39a481-68d8-4508-9336-9a51cf1e96d4")

    def test_archive_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            archived = service.archive_task(task.id)
            self.assertEqual(archived.archived_at, FIXED_NOW)

    def test_archive_keeps_task_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            service.archive_task(task.id)
            loaded = service.repository.load()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, task.id)

    def test_archive_rejects_second_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            service.archive_task(task.id)
            with self.assertRaises(ServiceError):
                service.archive_task(task.id)

    def test_archived_tasks_are_hidden_from_default_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            service.archive_task(task.id)
            self.assertEqual(service.list_tasks(), [])

    def test_include_archived_shows_archived_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            service.archive_task(task.id)
            self.assertEqual([item.id for item in service.list_tasks(include_archived=True)], [task.id])

    def test_archive_list_shows_archived_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service)
            service.archive_task(task.id)
            self.assertEqual([item.id for item in service.list_archived_tasks()], [task.id])

    def test_due_state_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self._add(self._service(tmp))
            self.assertEqual(self._service(tmp).get_due_state(task), "期限なし")

    def test_due_state_overdue(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, due_date="2026-07-10")
            self.assertEqual(service.get_due_state(task), "期限切れ")

    def test_due_state_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, due_date="2026-07-11")
            self.assertEqual(service.get_due_state(task), "今日")

    def test_due_state_due_soon(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, due_date="2026-07-13")
            self.assertEqual(service.get_due_state(task), "期限間近")

    def test_due_state_scheduled(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, due_date="2026-07-20")
            self.assertEqual(service.get_due_state(task), "予定")

    def test_due_state_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, status="done")
            self.assertEqual(service.get_due_state(task), "完了済み")

    def test_due_state_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, status="cancelled")
            self.assertEqual(service.get_due_state(task), "対象外")

    def test_overdue_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="over", due_date="2026-07-10")
            self._add(service, title="future", due_date="2026-07-20")
            self.assertEqual([task.title for task in service.list_tasks(overdue=True)], ["over"])

    def test_due_soon_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="soon", due_date="2026-07-13")
            self._add(service, title="later", due_date="2026-07-20")
            self.assertEqual([task.title for task in service.list_tasks(due_soon_days=3)], ["soon"])

    def test_due_soon_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="boundary", due_date="2026-07-14")
            self.assertEqual([task.title for task in service.list_tasks(due_soon_days=3)], ["boundary"])

    def test_done_task_is_not_overdue(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="done", due_date="2026-07-10", status="done")
            self.assertEqual(service.list_tasks(overdue=True), [])

    def test_archived_task_is_not_overdue(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, title="archived", due_date="2026-07-10")
            service.archive_task(task.id)
            self.assertEqual(service.list_tasks(overdue=True), [])

    def test_progress_by_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="todo", project="A", status="planned")
            self._add(service, title="doing", project="A", status="in_progress")
            entries = service.get_progress(project="A")
            self.assertEqual(entries[0].project, "A")
            self.assertEqual(entries[0].total, 2)

    def test_progress_excludes_cancelled_from_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, project="A", status="done")
            self._add(service, project="A", status="cancelled")
            entry = service.get_progress(project="A")[0]
            self.assertEqual(entry.completion_rate, 100.0)

    def test_progress_zero_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, project="A", status="cancelled")
            entry = service.get_progress(project="A")[0]
            self.assertEqual(entry.completion_rate, 0.0)

    def test_progress_counts_overdue(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, project="A", due_date="2026-07-10")
            entry = service.get_progress(project="A")[0]
            self.assertEqual(entry.overdue, 1)

    def test_progress_excludes_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, project="A")
            service.archive_task(task.id)
            self.assertEqual(service.get_progress(project="A"), [])

    def test_dashboard_counts_focus_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="over", priority="urgent", due_date="2026-07-10")
            self._add(service, title="today", priority="high", due_date="2026-07-11")
            self._add(service, title="soon", due_date="2026-07-13")
            self._add(service, title="blocked", status="blocked")
            self._add(service, title="review", status="review")
            self._add(service, title="done", status="done")
            archived = self._add(service, title="archived")
            service.archive_task(archived.id)

            dashboard = service.get_dashboard()

            self.assertEqual(dashboard.total, 7)
            self.assertEqual(dashboard.active, 5)
            self.assertEqual(dashboard.completed, 1)
            self.assertEqual(dashboard.archived, 1)
            self.assertEqual(dashboard.overdue, 1)
            self.assertEqual(dashboard.due_today, 1)
            self.assertEqual(dashboard.due_soon, 2)
            self.assertEqual(dashboard.blocked, 1)
            self.assertEqual(dashboard.review, 1)
            self.assertEqual(dashboard.urgent_high, 2)
            self.assertEqual(dashboard.no_due_active, 2)
            self.assertEqual([task.title for task in dashboard.next_tasks], ["over", "today", "soon", "blocked", "review"])

    def test_dashboard_project_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="a", project="A", due_date="2026-07-10")
            self._add(service, title="b", project="B", due_date="2026-07-10")

            dashboard = service.get_dashboard(project="A")

            self.assertEqual(dashboard.total, 1)
            self.assertEqual([entry.project for entry in dashboard.projects], ["A"])
            self.assertEqual([task.title for task in dashboard.next_tasks], ["a"])

    def test_dashboard_due_window_and_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="soon", due_date="2026-07-12")
            self._add(service, title="week", due_date="2026-07-18")

            dashboard = service.get_dashboard(due_soon_days=7, limit=1)

            self.assertEqual(dashboard.due_soon, 2)
            self.assertEqual([task.title for task in dashboard.next_tasks], ["soon"])

    def test_dashboard_rejects_negative_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            with self.assertRaises(ServiceError):
                service.get_dashboard(due_soon_days=-1)
            with self.assertRaises(ServiceError):
                service.get_dashboard(limit=-1)

    def test_create_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="日本語")
            path, count = service.create_backup()
            self.assertTrue(path.exists())
            self.assertEqual(count, 1)

    def test_create_backup_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="確認")
            source_before = service.repository.path.read_text(encoding="utf-8")
            service.create_backup()
            source_after = service.repository.path.read_text(encoding="utf-8")
            self.assertEqual(source_before, source_after)

    def test_create_backup_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service)
            path, _ = service.create_backup()
            self.assertTrue(path.parent.exists())

    def test_create_backup_uses_atomic_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service)
            calls = []
            real_replace = os.replace

            def capture_replace(src, dst):
                calls.append((Path(src), Path(dst)))
                real_replace(src, dst)

            with mock.patch("project_control.repository.os.replace", side_effect=capture_replace):
                service.create_backup()
            self.assertTrue(calls)

    def test_backup_requires_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            with self.assertRaises(RepositoryError):
                service.create_backup()

    def test_export_csv_utf8_bom_and_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="日本語", tags=["SEO", "PSI"])
            path, count = service.export_csv()
            self.assertEqual(count, 1)
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
            self.assertEqual(
                rows[0],
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
                ],
            )
            self.assertEqual(rows[1][1], "日本語")
            self.assertEqual(rows[1][7], "SEO|PSI")

    def test_export_csv_excludes_archived_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, title="archived")
            service.archive_task(task.id)
            path, count = service.export_csv()
            rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
            self.assertEqual(count, 0)
            self.assertEqual(len(rows), 1)

    def test_export_csv_include_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, title="archived")
            service.archive_task(task.id)
            path, count = service.export_csv(include_archived=True)
            rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
            self.assertEqual(count, 1)
            self.assertEqual(rows[1][1], "archived")

    def test_export_csv_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service)
            with self.assertRaises(ServiceError):
                service.export_csv(output=str(Path(tmp).resolve()))

    def test_export_csv_rejects_path_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service)
            with self.assertRaises(ServiceError):
                service.export_csv(output="..\\outside.csv")

    def test_export_csv_avoids_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service)
            output = Path("exports") / "tasks-fixed.csv"
            first_path, _ = service.export_csv(output=str(output))
            second_path, _ = service.export_csv(output=str(output))
            self.assertNotEqual(first_path, second_path)

    def test_export_csv_uses_atomic_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service)
            calls = []
            real_replace = os.replace

            def capture_replace(src, dst):
                calls.append((Path(src), Path(dst)))
                real_replace(src, dst)

            with mock.patch("project_control.service.os.replace", side_effect=capture_replace):
                service.export_csv()
            self.assertTrue(calls)


if __name__ == "__main__":
    unittest.main()
