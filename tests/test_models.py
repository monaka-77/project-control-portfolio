import unittest
from uuid import UUID

from project_control.models import Task, TaskModelError, TaskPriority, TaskStatus


class TaskModelTests(unittest.TestCase):
    def test_task_creation(self):
        task = Task(title="確認", project="SampleProject", status="planned", priority="high")
        self.assertEqual(task.title, "確認")
        self.assertEqual(task.status, TaskStatus.PLANNED)
        self.assertEqual(task.priority, TaskPriority.HIGH)

    def test_uuid_is_generated(self):
        task = Task(title="確認", project="SampleProject")
        self.assertEqual(str(UUID(task.id)), task.id)

    def test_title_empty_is_rejected(self):
        with self.assertRaises(TaskModelError):
            Task(title="", project="SampleProject")

    def test_title_whitespace_is_rejected(self):
        with self.assertRaises(TaskModelError):
            Task(title="   ", project="SampleProject")

    def test_project_empty_is_rejected(self):
        with self.assertRaises(TaskModelError):
            Task(title="確認", project="")

    def test_project_whitespace_is_rejected(self):
        with self.assertRaises(TaskModelError):
            Task(title="確認", project="   ")

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(TaskModelError):
            Task(title="確認", project="SampleProject", status="unknown")

    def test_invalid_priority_is_rejected(self):
        with self.assertRaises(TaskModelError):
            Task(title="確認", project="SampleProject", priority="later")

    def test_json_round_trip(self):
        task = Task(title="確認", project="SampleProject", tags=["SEO", "PSI"], due_date=None)
        restored = Task.from_dict(task.to_dict())
        self.assertEqual(restored.to_dict(), task.to_dict())

    def test_tags_are_restored(self):
        task = Task(title="確認", project="SampleProject", tags=["SEO"])
        restored = Task.from_dict(task.to_dict())
        self.assertEqual(restored.tags, ["SEO"])

    def test_due_date_can_be_unspecified(self):
        task = Task(title="確認", project="SampleProject")
        self.assertIsNone(task.due_date)

    def test_missing_archived_at_defaults_to_none(self):
        task = Task.from_dict(
            {
                "id": "8d39a481-68d8-4508-9336-9a51cf1e96d4",
                "title": "確認",
                "project": "SampleProject",
                "status": "planned",
                "priority": "medium",
                "created_at": "2026-07-11T09:00:00+00:00",
                "updated_at": "2026-07-11T09:00:00+00:00",
            }
        )
        self.assertIsNone(task.archived_at)

    def test_missing_completed_at_defaults_to_none(self):
        task = Task.from_dict(
            {
                "id": "8d39a481-68d8-4508-9336-9a51cf1e96d4",
                "title": "確認",
                "project": "SampleProject",
                "status": "planned",
                "priority": "medium",
                "created_at": "2026-07-11T09:00:00+00:00",
                "updated_at": "2026-07-11T09:00:00+00:00",
            }
        )
        self.assertIsNone(task.completed_at)

    def test_archived_at_must_be_iso8601(self):
        with self.assertRaises(TaskModelError):
            Task(title="確認", project="SampleProject", archived_at="2026/07/11")

    def test_completed_at_must_be_iso8601(self):
        with self.assertRaises(TaskModelError):
            Task(title="確認", project="SampleProject", completed_at="2026/07/11")

    def test_to_dict_includes_new_fields(self):
        task = Task(
            title="確認",
            project="SampleProject",
            completed_at="2026-07-11T09:00:00+00:00",
            archived_at="2026-07-11T10:00:00+00:00",
        )
        data = task.to_dict()
        self.assertIn("completed_at", data)
        self.assertIn("archived_at", data)

    def test_round_trip_preserves_new_fields(self):
        task = Task(
            title="確認",
            project="SampleProject",
            completed_at="2026-07-11T09:00:00+00:00",
            archived_at="2026-07-11T10:00:00+00:00",
        )
        restored = Task.from_dict(task.to_dict())
        self.assertEqual(restored.completed_at, "2026-07-11T09:00:00+00:00")
        self.assertEqual(restored.archived_at, "2026-07-11T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
