import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_control.cli import main
from project_control.models import Task


class CliTests(unittest.TestCase):
    def _repo_root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "src").mkdir(exist_ok=True)
        (root / "config").mkdir(exist_ok=True)
        (root / "data").mkdir(exist_ok=True)
        (root / "backups").mkdir(exist_ok=True)
        (root / "exports").mkdir(exist_ok=True)
        (root / "config" / "project-control.json").write_text(
            json.dumps(
                {
                    "data_file": "data/tasks.json",
                    "default_status": "inbox",
                    "default_priority": "medium",
                    "date_format": "%Y-%m-%d",
                }
            ),
            encoding="utf-8",
        )
        return root

    def _write_tasks(self, root: Path, tasks: list[Task]) -> None:
        (root / "data" / "tasks.json").write_text(
            json.dumps([task.to_dict() for task in tasks], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _run(self, root: Path, argv: list[str], *, user_input: str | None = None) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        patches = [
            mock.patch("project_control.cli.Path.cwd", return_value=root),
            mock.patch("sys.stdout", stdout),
            mock.patch("sys.stderr", stderr),
        ]
        if user_input is not None:
            patches.append(mock.patch("builtins.input", return_value=user_input))
        with patches[0], patches[1], patches[2]:
            if user_input is None:
                code = main(argv)
            else:
                with patches[3]:
                    code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_show_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject")
            self._write_tasks(root, [task])
            code, stdout, stderr = self._run(root, ["show", task.id])
            self.assertEqual(code, 0)
            self.assertIn("タイトル: 確認", stdout)
            self.assertEqual(stderr, "")

    def test_update_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject")
            self._write_tasks(root, [task])
            code, stdout, _ = self._run(root, ["update", task.id, "--title", "変更後"])
            self.assertEqual(code, 0)
            self.assertIn("変更後", stdout)

    def test_status_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject", status="planned")
            self._write_tasks(root, [task])
            code, stdout, _ = self._run(root, ["status", task.id, "in_progress"])
            self.assertEqual(code, 0)
            self.assertIn("変更後: in_progress", stdout)

    def test_complete_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject", status="planned")
            self._write_tasks(root, [task])
            code, stdout, _ = self._run(root, ["complete", task.id])
            self.assertEqual(code, 0)
            self.assertIn("タスクを完了しました。", stdout)

    def test_archive_yes_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject")
            self._write_tasks(root, [task])
            code, stdout, _ = self._run(root, ["archive", task.id, "--yes"])
            self.assertEqual(code, 0)
            self.assertIn("アーカイブ日時:", stdout)

    def test_archive_cancel_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject")
            self._write_tasks(root, [task])
            code, stdout, stderr = self._run(root, ["archive", task.id], user_input="n")
            self.assertEqual(code, 0)
            self.assertIn("アーカイブを中止しました。", stdout)
            self.assertEqual(stderr, "")

    def test_archive_list_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject", archived_at="2026-07-11T09:00:00+00:00")
            self._write_tasks(root, [task])
            code, stdout, _ = self._run(root, ["archive-list"])
            self.assertEqual(code, 0)
            self.assertIn("アーカイブ日時", stdout)

    def test_progress_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            tasks = [Task(title="a", project="SampleProject", status="planned"), Task(title="b", project="SampleProject", status="done")]
            self._write_tasks(root, tasks)
            code, stdout, _ = self._run(root, ["progress"])
            self.assertEqual(code, 0)
            self.assertIn("完了率", stdout)

    def test_dashboard_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            tasks = [
                Task(title="期限切れ", project="SampleProject", priority="high", due_date="2026-07-10"),
                Task(title="完了", project="SampleProject", status="done"),
            ]
            self._write_tasks(root, tasks)
            code, stdout, _ = self._run(root, ["dashboard"])
            self.assertEqual(code, 0)
            self.assertIn("ダッシュボード", stdout)
            self.assertIn("期限切れ件数:", stdout)
            self.assertIn("次に見るタスク", stdout)
            self.assertIn("期限切れ", stdout)

    def test_dashboard_html_command_without_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject", due_date="2026-07-11")
            self._write_tasks(root, [task])
            with mock.patch("project_control.cli.webbrowser.open") as browser_open:
                code, stdout, stderr = self._run(root, ["dashboard-html"])

            self.assertEqual(code, 0)
            self.assertIn("HTML ダッシュボードを生成しました。", stdout)
            self.assertEqual(stderr, "")
            self.assertTrue((root / "reports" / "dashboard.html").exists())
            browser_open.assert_not_called()

    def test_dashboard_html_command_with_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject", due_date="2026-07-11")
            self._write_tasks(root, [task])
            with mock.patch("project_control.cli.webbrowser.open") as browser_open:
                code, _, _ = self._run(root, ["dashboard-html", "--open"])

            self.assertEqual(code, 0)
            browser_open.assert_called_once()

    def test_backup_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject")
            self._write_tasks(root, [task])
            code, stdout, _ = self._run(root, ["backup"])
            self.assertEqual(code, 0)
            self.assertIn("バックアップを作成しました。", stdout)

    def test_export_csv_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            task = Task(title="確認", project="SampleProject")
            self._write_tasks(root, [task])
            code, stdout, _ = self._run(root, ["export-csv"])
            self.assertEqual(code, 0)
            self.assertIn("CSV を出力しました。", stdout)

    def test_invalid_id_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            code, _, stderr = self._run(root, ["show", "bad-id"])
            self.assertEqual(code, 1)
            self.assertIn("エラー:", stderr)

    def test_missing_id_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo_root(tmp)
            code, _, stderr = self._run(root, ["show", "8d39a481-68d8-4508-9336-9a51cf1e96d4"])
            self.assertEqual(code, 1)
            self.assertIn("Task was not found", stderr)


if __name__ == "__main__":
    unittest.main()
