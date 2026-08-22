import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from project_control.dashboard import DashboardError, _task_rows, render_dashboard_html, save_dashboard_html
from project_control.models import Task, TaskPriority, TaskStatus
from project_control.repository import JsonTaskRepository
from project_control.service import ProjectControlService


FIXED_NOW = "2026-07-11T09:30:00+00:00"
FIXED_TODAY = date(2026, 7, 11)


class DashboardHtmlTests(unittest.TestCase):
    def _service(self, tmp: str) -> ProjectControlService:
        return ProjectControlService(
            JsonTaskRepository(Path(tmp) / "data" / "tasks.json"),
            repo_root=tmp,
            now_provider=lambda: FIXED_NOW,
            today_provider=lambda: FIXED_TODAY,
        )

    def _add(self, service: ProjectControlService, **kwargs) -> Task:
        params = {"title": "確認", "project": "SampleProject", "priority": "medium", "status": "planned"}
        params.update(kwargs)
        return service.add_task(**params)

    def _html(self, service: ProjectControlService, *, project=None, due_soon_days=3, limit=5) -> str:
        dashboard = service.get_dashboard(project=project, due_soon_days=due_soon_days, limit=limit)
        return render_dashboard_html(
            dashboard,
            generated_at=FIXED_NOW,
            project_filter=project,
            due_soon_days=due_soon_days,
            today=FIXED_TODAY,
            due_state_provider=service.get_due_state,
        )

    def test_html_generation_success_utf8_and_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="日本語タスク", due_date="2026-07-11")
            html = self._html(service)
            path = save_dashboard_html(tmp, html, "nested/report.html")

            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], "<!doctype html>")
            self.assertIn("日本語タスク", path.read_text(encoding="utf-8"))

    def test_html_contains_summary_project_tasks_due_state_and_gantt(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="期限切れ", priority="urgent", due_date="2026-07-10")
            self._add(service, title="今日", status="in_progress", due_date="2026-07-11")
            self._add(service, title="完了", status="done")

            html = self._html(service)

            self.assertIn("ProjectControl Dashboard", html)
            self.assertIn("全件数", html)
            self.assertIn("3", html)
            self.assertIn("プロジェクト別進捗", html)
            self.assertIn("対象件数", html)
            self.assertIn("タスク一覧", html)
            self.assertIn("期限切れ", html)
            self.assertIn("今日", html)
            self.assertIn("簡易ガント表示", html)
            self.assertIn("正式な工程期間ではありません", html)

    def test_generated_at_is_displayed_as_jst(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            html = self._html(service)
            generated_meta = html.split("生成日時", 1)[1].split("絞り込み対象プロジェクト", 1)[0]

            self.assertIn("2026年7月11日 18:30 JST", generated_meta)
            self.assertNotIn(FIXED_NOW, generated_meta)

    def test_invalid_generated_at_falls_back_to_escaped_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            dashboard = service.get_dashboard()
            html = render_dashboard_html(
                dashboard,
                generated_at='<bad "time">',
                project_filter=None,
                due_soon_days=3,
                today=FIXED_TODAY,
                due_state_provider=service.get_due_state,
            )

            self.assertIn("&lt;bad &quot;time&quot;&gt;", html)

    def test_naive_generated_at_falls_back_to_original_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            dashboard = service.get_dashboard()
            html = render_dashboard_html(
                dashboard,
                generated_at="2026-07-11T09:30:00",
                project_filter=None,
                due_soon_days=3,
                today=FIXED_TODAY,
                due_state_provider=service.get_due_state,
            )

            self.assertIn("2026-07-11T09:30:00", html)
            self.assertNotIn("2026年7月11日 09:30 JST", html)

    def test_task_table_shortens_uuid_and_keeps_full_id_in_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            task = self._add(service, due_date="2026-07-11")

            html = self._html(service)

            self.assertIn(f">{task.id[:8]}…</td>", html)
            self.assertIn(f'title="{task.id}"', html)
            self.assertNotIn(f"<td>{task.id}</td>", html)

    def test_task_id_title_attribute_is_escaped(self):
        task = SimpleNamespace(
            id='12345678-1234-1234-1234-123456789abc" onclick="alert(1)',
            priority=SimpleNamespace(value="high"),
            status=SimpleNamespace(value="planned"),
            project="A&B",
            due_date=None,
            title="<title>",
            tags=['"tag"'],
        )

        html = _task_rows([task], lambda _: "予定", include_id=True)

        self.assertIn('title="12345678-1234-1234-1234-123456789abc&quot; onclick=&quot;alert(1)"', html)
        self.assertIn(">12345678…</td>", html)
        self.assertIn("&lt;title&gt;", html)
        self.assertIn("&quot;tag&quot;", html)

    def test_next_tasks_table_does_not_gain_id_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="今日", due_date="2026-07-11")

            html = self._html(service)
            next_section = html.split("次に見るタスク", 1)[1].split("タスク一覧", 1)[0]

            self.assertNotIn('class="col-id"', next_section)
            self.assertNotIn('class="cell-id"', next_section)

    def test_task_table_outputs_column_classes_and_layout_css(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="確認", due_date="2026-07-11", tags=["alpha"])

            html = self._html(service)

            self.assertIn("<colgroup>", html)
            self.assertIn('class="col-title"', html)
            self.assertIn('class="cell-tags"', html)
            self.assertIn(".cell-id,", html)
            self.assertIn("white-space: nowrap;", html)
            self.assertIn(".cell-title {", html)
            self.assertIn("min-width: 16rem;", html)
            self.assertIn(".cell-tags {", html)
            self.assertIn("overflow-wrap: anywhere;", html)
            self.assertIn(".table-wrap { overflow-x: auto; }", html)
            self.assertIn("@media print", html)
            self.assertIn(".task-table { min-width: 0; }", html)

    def test_task_tables_use_mapped_visual_badges(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="期限切れ", priority="urgent", status="blocked", due_date="2026-07-10")
            self._add(service, title="今日", priority="high", status="in_progress", due_date="2026-07-11")
            self._add(service, title="レビュー", status="review", due_date="2026-07-12")

            html = self._html(service, limit=5)
            next_section = html.split("次に見るタスク", 1)[1].split("タスク一覧", 1)[0]
            task_section = html.split("タスク一覧", 1)[1].split("簡易ガント表示", 1)[0]

            for section in (next_section, task_section):
                self.assertIn('<span class="badge priority-badge priority-urgent">urgent</span>', section)
                self.assertIn('<span class="badge priority-badge priority-high">high</span>', section)
                self.assertIn('<span class="badge status-badge status-in-progress">in_progress</span>', section)
                self.assertIn('<span class="badge status-badge status-blocked">blocked</span>', section)
                self.assertIn('<span class="badge status-badge status-review">review</span>', section)
                self.assertIn('<span class="badge due-state-badge due-state-overdue">期限切れ</span>', section)
                self.assertIn('<span class="badge due-state-badge due-state-today">今日</span>', section)

    def test_unknown_badge_values_do_not_add_value_derived_classes(self):
        task = SimpleNamespace(
            id="12345678-1234-1234-1234-123456789abc",
            priority=SimpleNamespace(value="unknown priority"),
            status=SimpleNamespace(value="unknown status"),
            project="Project",
            due_date=None,
            title="Unknown values",
            tags=[],
        )

        html = _task_rows([task], lambda _: "unknown due state", include_id=False)

        self.assertIn('<span class="badge priority-badge">unknown priority</span>', html)
        self.assertIn('<span class="badge status-badge">unknown status</span>', html)
        self.assertIn('<span class="badge due-state-badge">unknown due state</span>', html)

    def test_task_table_outputs_filter_ui_only_for_task_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="今日", due_date="2026-07-11")

            html = self._html(service)
            next_section = html.split("次に見るタスク", 1)[1].split("タスク一覧", 1)[0]
            task_section = html.split("タスク一覧", 1)[1].split("簡易ガント表示", 1)[0]

            self.assertNotIn('data-dashboard-filters', next_section)
            self.assertIn('data-dashboard-filters', task_section)
            self.assertIn('for="task-filter-search"', task_section)
            self.assertIn('id="task-filter-search"', task_section)
            self.assertIn('aria-live="polite"', task_section)
            self.assertIn('data-filter-empty>条件に一致するタスクはありません。', task_section)
            self.assertIn('hidden data-filter-empty', task_section)
            self.assertIn('<button class="filter-reset" type="button" data-filter-reset>解除</button>', task_section)

    def test_task_rows_include_filter_data_attributes_only_for_task_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            active = self._add(service, title="作業中", status="in_progress", priority="high", due_date="2026-07-11")
            done = self._add(service, title="完了", status="done")
            cancelled = self._add(service, title="中止", status="cancelled")

            html = self._html(service)
            task_section = html.split("タスク一覧", 1)[1].split("簡易ガント表示", 1)[0]

            self.assertIn("data-dashboard-task-row", task_section)
            self.assertIn(f'data-project="{active.project}"', task_section)
            self.assertIn('data-status="in_progress"', task_section)
            self.assertIn('data-priority="high"', task_section)
            self.assertIn('data-due-state="今日"', task_section)
            self.assertIn(f'data-search="{active.id} 作業中 SampleProject  in_progress high 2026-07-11 今日"', task_section)
            self.assertIn(f'title="{active.id}"', task_section)
            self.assertIn(f'title="{done.id}"', task_section)
            self.assertIn(f'title="{cancelled.id}"', task_section)

            done_row = task_section.split(f'title="{done.id}"', 1)[0].rsplit("<tr", 1)[1]
            cancelled_row = task_section.split(f'title="{cancelled.id}"', 1)[0].rsplit("<tr", 1)[1]
            self.assertIn('data-completed="true"', done_row)
            self.assertIn('data-completed="false"', cancelled_row)
            self.assertNotIn("<tr hidden", task_section)

    def test_filter_select_options_are_generated_from_tasks_and_enums(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="A", project="Beta", priority="low", status="planned", due_date="2026-07-10")
            self._add(service, title="B", project="Alpha", priority="urgent", status="done")
            self._add(service, title="C", project="Beta", priority="high", status="cancelled")

            html = self._html(service)
            task_section = html.split("タスク一覧", 1)[1].split("簡易ガント表示", 1)[0]

            project_select = task_section.split('id="task-filter-project"', 1)[1].split("</select>", 1)[0]
            self.assertEqual(project_select.count('<option value="Alpha">Alpha</option>'), 1)
            self.assertEqual(project_select.count('<option value="Beta">Beta</option>'), 1)
            self.assertLess(project_select.index('value="Alpha"'), project_select.index('value="Beta"'))

            status_select = task_section.split('id="task-filter-status"', 1)[1].split("</select>", 1)[0]
            status_positions = [status_select.index(f'value="{status.value}"') for status in TaskStatus]
            self.assertEqual(status_positions, sorted(status_positions))

            priority_select = task_section.split('id="task-filter-priority"', 1)[1].split("</select>", 1)[0]
            priority_positions = [priority_select.index(f'value="{priority.value}"') for priority in TaskPriority]
            self.assertEqual(priority_positions, sorted(priority_positions))

            due_state_select = task_section.split('id="task-filter-due-state"', 1)[1].split("</select>", 1)[0]
            self.assertIn('<option value="">すべて</option>', due_state_select)
            self.assertIn('<option value="期限切れ">期限切れ</option>', due_state_select)
            self.assertIn('<option value="完了済み">完了済み</option>', due_state_select)
            self.assertIn('<option value="対象外">対象外</option>', due_state_select)

    def test_filter_data_attributes_escape_special_characters(self):
        task = SimpleNamespace(
            id='12345678-1234-1234-1234-123456789abc" onclick="alert(1)',
            priority=SimpleNamespace(value='high" data-x="1'),
            status=SimpleNamespace(value='planned" autofocus="autofocus'),
            project='A&B "Project"',
            due_date='2026-07-11" bad="1',
            title='<title> & "quote"',
            tags=['<tag>', '"quoted"'],
        )

        html = _task_rows([task], lambda _: '期限切れ" now', include_id=True)

        self.assertIn('data-dashboard-task-row', html)
        self.assertIn('data-project="A&amp;B &quot;Project&quot;"', html)
        self.assertIn('data-status="planned&quot; autofocus=&quot;autofocus"', html)
        self.assertIn('data-priority="high&quot; data-x=&quot;1"', html)
        self.assertIn('data-due-state="期限切れ&quot; now"', html)
        self.assertIn('data-completed="false"', html)
        self.assertIn('12345678-1234-1234-1234-123456789abc&quot; onclick=&quot;alert(1)', html)
        self.assertIn('&lt;title&gt; &amp; &quot;quote&quot;', html)
        self.assertIn('&lt;tag&gt;, &quot;quoted&quot;', html)
        self.assertIn('data-search="12345678-1234-1234-1234-123456789abc&quot; onclick=&quot;alert(1)', html)
        self.assertIn('&lt;title&gt; &amp; &quot;quote&quot;', html)
        self.assertIn('2026-07-11&quot; bad=&quot;1', html)

    def test_embedded_script_uses_safe_dom_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="確認", due_date="2026-07-11")

            html = self._html(service)
            script = html.split("<script>", 1)[1].split("</script>", 1)[0]

            self.assertIn("row.hidden", script)
            self.assertIn("textContent", script)
            self.assertIn("toLocaleLowerCase", script)
            self.assertIn("trim()", script)
            self.assertIn("data-dashboard-task-row", html)
            self.assertNotIn("eval", script)
            self.assertNotIn("innerHTML", script)
            self.assertNotIn("document.write", script)
            self.assertNotIn("Function(", script)
            self.assertNotIn("http://", script)
            self.assertNotIn("https://", script)

    def test_filter_css_preserves_responsive_dark_print_and_table_scroll(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="確認", due_date="2026-07-11")

            html = self._html(service)

            self.assertIn(".table-wrap { overflow-x: auto; }", html)
            self.assertIn(".task-filters {", html)
            self.assertIn("grid-template-columns: repeat(auto-fit", html)
            self.assertIn(":focus", html)
            self.assertIn("@media (prefers-color-scheme: dark)", html)
            self.assertIn("@media (max-width: 720px)", html)
            self.assertIn("@media print", html)
            self.assertIn(".task-filters,", html)
            self.assertIn(".filter-reset { display: none; }", html)

    def test_dashboard_uses_fixed_offset_jst_without_zoneinfo(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "src" / "project_control" / "dashboard.py").read_text(encoding="utf-8")

        self.assertIn("timezone(timedelta(hours=9), name=\"JST\")", source)
        self.assertNotIn("ZoneInfo", source)

    def test_project_filter_due_soon_and_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="A soon", project="A", due_date="2026-07-12")
            self._add(service, title="A week", project="A", due_date="2026-07-18")
            self._add(service, title="B soon", project="B", due_date="2026-07-12")

            html = self._html(service, project="A", due_soon_days=7, limit=1)

            self.assertIn("A soon", html)
            self.assertNotIn("B soon", html)
            self.assertIn("7日以内", html)
            next_section = html.split("次に見るタスク", 1)[1].split("タスク一覧", 1)[0]
            self.assertIn("A soon", next_section)
            self.assertNotIn("A week", next_section)

    def test_zero_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            html = self._html(service)

            self.assertIn("対象タスクはありません", html)
            self.assertIn("期限付きのアクティブタスクはありません", html)

    def test_html_special_chars_are_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(
                service,
                title="<script>alert(1)</script> & \" '",
                project="A&B",
                tags=["<script>alert(1)</script>", "\"quote\"", "'single'"],
            )

            html = self._html(service)

            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertIn("A&amp;B", html)
            self.assertIn("&quot;quote&quot;", html)
            self.assertIn("&#x27;single&#x27;", html)

    def test_rejects_absolute_and_outside_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DashboardError):
                save_dashboard_html(tmp, "html", str(Path(tmp).resolve() / "report.html"))
            with self.assertRaises(DashboardError):
                save_dashboard_html(tmp, "html", "..\\outside.html")

    def test_uses_temporary_file_and_replaces_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            target = Path(tmp) / "reports" / "dashboard.html"
            target.parent.mkdir()
            target.write_text("old", encoding="utf-8")
            real_replace = os.replace

            def capture_replace(src, dst):
                calls.append((Path(src), Path(dst)))
                real_replace(src, dst)

            with mock.patch("project_control.dashboard.os.replace", side_effect=capture_replace):
                path = save_dashboard_html(tmp, "new", "reports/dashboard.html")

            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            self.assertEqual(calls[0][1].name, target.name)
            self.assertTrue(calls[0][0].name.endswith(".tmp"))

    def test_does_not_change_tasks_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            self._add(service, title="確認")
            tasks_path = Path(tmp) / "data" / "tasks.json"
            before = tasks_path.read_text(encoding="utf-8")
            html = self._html(service)
            save_dashboard_html(tmp, html)
            after = tasks_path.read_text(encoding="utf-8")

            self.assertEqual(json.loads(before), json.loads(after))

    def test_reports_gitkeep_is_not_ignored(self):
        root = Path(__file__).resolve().parents[1]
        gitignore = (root / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("reports/*.html", gitignore)
        self.assertIn("reports/*.tmp", gitignore)
        self.assertIn("!reports/.gitkeep", gitignore)
        self.assertTrue((root / "reports" / ".gitkeep").exists())


if __name__ == "__main__":
    unittest.main()
