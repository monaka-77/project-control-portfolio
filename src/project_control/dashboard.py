from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Callable

from .models import Task, TaskPriority, TaskStatus
from .repository import RepositoryError
from .service import DashboardData


DEFAULT_DASHBOARD_OUTPUT = Path("reports") / "dashboard.html"
GANTT_PAST_DAYS = 7
GANTT_FUTURE_DAYS = 30
JST = timezone(timedelta(hours=9), name="JST")

PRIORITY_BADGE_CLASSES = {
    "urgent": "priority-urgent",
    "high": "priority-high",
    "medium": "priority-medium",
    "low": "priority-low",
}
STATUS_BADGE_CLASSES = {
    "inbox": "status-inbox",
    "planned": "status-planned",
    "in_progress": "status-in-progress",
    "blocked": "status-blocked",
    "review": "status-review",
    "done": "status-done",
    "cancelled": "status-cancelled",
}
DUE_STATE_BADGE_CLASSES = {
    "期限切れ": "due-state-overdue",
    "今日": "due-state-today",
    "期限間近": "due-state-soon",
    "期限あり": "due-state-scheduled",
    "期限なし": "due-state-none",
    "完了済み": "due-state-completed",
    "対象外": "due-state-excluded",
}


class DashboardError(ValueError):
    """Raised when dashboard HTML generation is invalid."""


def render_dashboard_html(
    dashboard: DashboardData,
    *,
    generated_at: str,
    project_filter: str | None,
    due_soon_days: int,
    today: date,
    due_state_provider: Callable[[Task], str],
) -> str:
    target_project = project_filter if project_filter is not None else "すべて"
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="ja">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>ProjectControl Dashboard</title>",
            f"<style>{_css()}</style>",
            "</head>",
            "<body>",
            '<main class="page">',
            "<header>",
            "<h1>ProjectControl Dashboard</h1>",
            '<div class="meta-grid">',
            _meta_item("生成日時", _format_generated_at(generated_at)),
            _meta_item("絞り込み対象プロジェクト", target_project),
            _meta_item("対象タスク件数", str(len(dashboard.tasks))),
            _meta_item("期限間近", f"{due_soon_days}日以内"),
            "</div>",
            "</header>",
            _summary_cards(dashboard),
            _project_progress(dashboard),
            _next_tasks(dashboard, due_state_provider),
            _task_table(dashboard.tasks, due_state_provider),
            _gantt(dashboard.tasks, today),
            "</main>",
            f"<script>{_js()}</script>",
            "</body>",
            "</html>",
            "",
        ]
    )


def save_dashboard_html(repo_root: Path | str, html: str, output: str | None = None) -> Path:
    root = Path(repo_root).resolve()
    candidate = Path(output) if output is not None else DEFAULT_DASHBOARD_OUTPUT
    if candidate.is_absolute():
        raise DashboardError("Absolute output paths are not allowed.")
    destination = (root / candidate).resolve()
    if not destination.is_relative_to(root):
        raise DashboardError("Output path must stay inside the repository root.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.parent / f".{destination.name}.tmp"
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(html)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except OSError as exc:
        raise RepositoryError(f"Could not write dashboard HTML safely: {destination}") from exc
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
    return destination


def _summary_cards(dashboard: DashboardData) -> str:
    cards = [
        ("全件数", dashboard.total),
        ("アクティブ", dashboard.active),
        ("完了", dashboard.completed),
        ("アーカイブ", dashboard.archived),
        ("期限切れ", dashboard.overdue),
        ("今日が期限", dashboard.due_today),
        ("期限間近", dashboard.due_soon),
        ("ブロック", dashboard.blocked),
        ("レビュー", dashboard.review),
        ("urgent / high", dashboard.urgent_high),
        ("期限なしアクティブ", dashboard.no_due_active),
    ]
    return _section(
        "サマリー",
        '<div class="cards">'
        + "".join(f'<article class="card"><span>{_h(label)}</span><strong>{value}</strong></article>' for label, value in cards)
        + "</div>",
    )


def _project_progress(dashboard: DashboardData) -> str:
    if not dashboard.projects:
        body = '<p class="empty">対象の進捗データはありません。</p>'
    else:
        rows = []
        for entry in dashboard.projects:
            rows.append(
                "<tr>"
                f"<th>{_h(entry.project)}</th>"
                f"<td>{entry.total}</td>"
                f"<td>{entry.todo}</td>"
                f"<td>{entry.in_progress}</td>"
                f"<td>{entry.blocked}</td>"
                f"<td>{entry.review}</td>"
                f"<td>{entry.done}</td>"
                f"<td>{entry.overdue}</td>"
                f'<td><span class="progress-label">{entry.completion_rate:.1f}%</span>'
                f'<span class="progress"><span style="width: {entry.completion_rate:.1f}%"></span></span></td>'
                "</tr>"
            )
        body = (
            '<div class="table-wrap"><table><thead><tr>'
            "<th>プロジェクト名</th><th>対象件数</th><th>未着手</th><th>進行中</th><th>ブロック</th>"
            "<th>レビュー</th><th>完了</th><th>期限切れ</th><th>完了率</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )
    return _section("プロジェクト別進捗", body)


def _next_tasks(dashboard: DashboardData, due_state_provider: Callable[[Task], str]) -> str:
    return _section("次に見るタスク", _task_rows(dashboard.next_tasks, due_state_provider, include_id=False))


def _task_table(tasks: list[Task], due_state_provider: Callable[[Task], str]) -> str:
    return _section(
        "タスク一覧",
        _task_filters(tasks, due_state_provider) + _task_rows(tasks, due_state_provider, include_id=True),
    )


def _task_rows(tasks: list[Task], due_state_provider: Callable[[Task], str], *, include_id: bool) -> str:
    if not tasks:
        return '<p class="empty">対象タスクはありません。</p>'
    id_col = '<col class="col-id">' if include_id else ""
    id_header = '<th class="col-id" scope="col">ID</th>' if include_id else ""
    rows = []
    for task in tasks:
        due_state = due_state_provider(task)
        id_cell = f'<td class="cell-id" title="{_h(task.id)}">{_h(_short_id(task.id))}</td>' if include_id else ""
        row_attrs = ""
        if include_id:
            row_attrs = (
                " data-dashboard-task-row"
                f' data-project="{_h(task.project)}"'
                f' data-status="{_h(task.status.value)}"'
                f' data-priority="{_h(task.priority.value)}"'
                f' data-due-state="{_h(due_state)}"'
                f' data-completed="{_h("true" if task.status == TaskStatus.DONE else "false")}"'
                f' data-search="{_h(_task_search_text(task, due_state))}"'
            )
        rows.append(
            f"<tr{row_attrs}>"
            f"{id_cell}"
            f'<td class="cell-priority">{_badge(task.priority.value, "priority-badge", PRIORITY_BADGE_CLASSES)}</td>'
            f'<td class="cell-status">{_badge(task.status.value, "status-badge", STATUS_BADGE_CLASSES)}</td>'
            f'<td class="cell-project">{_h(task.project)}</td>'
            f'<td class="cell-due">{_h(task.due_date or "-")}</td>'
            f'<td class="cell-title">{_h(task.title)}</td>'
            f'<td class="cell-tags">{_h(", ".join(task.tags) if task.tags else "-")}</td>'
            f'<td class="cell-due-state">{_badge(due_state, "due-state-badge", DUE_STATE_BADGE_CLASSES)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="task-table">'
        f"<colgroup>{id_col}"
        '<col class="col-priority"><col class="col-status"><col class="col-project"><col class="col-due">'
        '<col class="col-title"><col class="col-tags"><col class="col-due-state"></colgroup>'
        "<thead><tr>"
        f'{id_header}<th class="col-priority" scope="col">優先度</th><th class="col-status" scope="col">ステータス</th>'
        '<th class="col-project" scope="col">プロジェクト</th><th class="col-due" scope="col">期限</th>'
        '<th class="col-title" scope="col">タイトル</th><th class="col-tags" scope="col">タグ</th>'
        '<th class="col-due-state" scope="col">期限状態</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _badge(value: str, badge_class: str, class_mapping: dict[str, str]) -> str:
    classes = " ".join(("badge", badge_class, class_mapping.get(value, ""))).strip()
    return f'<span class="{classes}">{_h(value)}</span>'


def _task_filters(tasks: list[Task], due_state_provider: Callable[[Task], str]) -> str:
    return (
        '<form class="task-filters" data-dashboard-filters>'
        '<div class="filter-field filter-field-wide">'
        '<label for="task-filter-search">フリーワード</label>'
        '<input id="task-filter-search" name="search" type="search" autocomplete="off" data-filter-search>'
        "</div>"
        + _select_filter(
            "task-filter-project",
            "project",
            "プロジェクト",
            sorted({task.project for task in tasks}),
            "data-filter-project",
        )
        + _select_filter(
            "task-filter-status",
            "status",
            "ステータス",
            [status.value for status in TaskStatus],
            "data-filter-status",
        )
        + _select_filter(
            "task-filter-priority",
            "priority",
            "優先度",
            [priority.value for priority in TaskPriority],
            "data-filter-priority",
        )
        + _select_filter(
            "task-filter-due-state",
            "due_state",
            "期限状態",
            _ordered_due_states({due_state_provider(task) for task in tasks}),
            "data-filter-due-state",
        )
        + '<label class="filter-check" for="task-filter-completed">'
        '<input id="task-filter-completed" name="show_completed" type="checkbox" data-filter-completed>'
        "<span>完了済みを表示</span>"
        "</label>"
        '<button class="filter-reset" type="button" data-filter-reset>解除</button>'
        '<p class="filter-count" aria-live="polite" data-filter-count>'
        f"表示件数: {len(tasks)} / {len(tasks)}"
        "</p>"
        '<p class="filter-empty" hidden data-filter-empty>条件に一致するタスクはありません。</p>'
        "</form>"
    )


def _select_filter(field_id: str, name: str, label: str, values: list[str], data_attr: str) -> str:
    options = ['<option value="">すべて</option>']
    options.extend(f'<option value="{_h(value)}">{_h(value)}</option>' for value in values)
    return (
        '<div class="filter-field">'
        f'<label for="{_h(field_id)}">{_h(label)}</label>'
        f'<select id="{_h(field_id)}" name="{_h(name)}" {data_attr}>'
        + "".join(options)
        + "</select>"
        "</div>"
    )


def _ordered_due_states(values: set[str]) -> list[str]:
    preferred = ["期限切れ", "今日が期限", "今日", "期限間近", "予定", "期限なし", "完了済み", "対象外"]
    ordered = [value for value in preferred if value in values]
    ordered.extend(sorted(values - set(preferred)))
    return ordered


def _task_search_text(task: Task, due_state: str) -> str:
    return " ".join(
        [
            task.id,
            task.title,
            task.project,
            " ".join(task.tags),
            task.status.value,
            task.priority.value,
            task.due_date or "",
            due_state,
        ]
    )


def _gantt(tasks: list[Task], today: date) -> str:
    active_due_tasks = [
        task
        for task in tasks
        if task.status not in {TaskStatus.DONE, TaskStatus.CANCELLED} and task.due_date is not None
    ]
    if not active_due_tasks:
        body = '<p class="empty">期限付きのアクティブタスクはありません。</p>'
    else:
        start = today - timedelta(days=GANTT_PAST_DAYS)
        end = today + timedelta(days=GANTT_FUTURE_DAYS)
        total_days = (end - start).days + 1
        rows = []
        for task in active_due_tasks:
            due = _parse_date(task.due_date)
            created = _parse_datetime_date(task.created_at) or due
            bar_start = min(max(created, start), end)
            bar_end = min(max(due, start), end)
            if bar_start > bar_end:
                bar_start = bar_end
            left = ((bar_start - start).days / total_days) * 100
            width = max((((bar_end - bar_start).days + 1) / total_days) * 100, 2.5)
            range_label = _range_label(due, start, end)
            rows.append(
                '<div class="gantt-row">'
                f'<div class="gantt-label">{_h(task.project)} / {_h(task.title)}<br><span>{_h(task.due_date or "-")} {_h(range_label)}</span></div>'
                '<div class="gantt-track">'
                f'<span class="gantt-bar" style="left: {left:.2f}%; width: {width:.2f}%"></span>'
                f'<span class="gantt-due" style="left: {min(max(((due - start).days / total_days) * 100, 0), 100):.2f}%"></span>'
                "</div>"
                "</div>"
            )
        body = (
            '<p class="note">簡易表示です。開始日を持たないため、created_at から due_date までを参考表示しており、正式な工程期間ではありません。</p>'
            f'<div class="gantt-scale"><span>{_h(start.isoformat())}</span><span>今日 {_h(today.isoformat())}</span><span>{_h(end.isoformat())}</span></div>'
            '<div class="gantt">'
            + "".join(rows)
            + "</div>"
        )
    return _section("簡易ガント表示", body)


def _section(title: str, body: str) -> str:
    return f'<section><h2>{_h(title)}</h2>{body}</section>'


def _meta_item(label: str, value: str) -> str:
    return f'<div><span>{_h(label)}</span><strong>{_h(value)}</strong></div>'


def _format_generated_at(value: str) -> str:
    try:
        generated = datetime.fromisoformat(value)
    except ValueError:
        return value
    if generated.tzinfo is None:
        return value
    generated = generated.astimezone(JST)
    return f"{generated.year}年{generated.month}月{generated.day}日 {generated:%H:%M} JST"


def _short_id(value: str) -> str:
    return f"{value[:8]}…"


def _h(value: object) -> str:
    return escape(str(value), quote=True)


def _parse_date(value: str | None) -> date:
    if value is None:
        return date.max
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.max


def _parse_datetime_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _range_label(due: date, start: date, end: date) -> str:
    if due < start:
        return "範囲外: 過去"
    if due > end:
        return "範囲外: 未来"
    return "範囲内"


def _js() -> str:
    return """
(function () {
  var filters = document.querySelector("[data-dashboard-filters]");
  if (!filters) {
    return;
  }
  var rows = Array.prototype.slice.call(document.querySelectorAll("[data-dashboard-task-row]"));
  if (!rows.length) {
    return;
  }

  var search = filters.querySelector("[data-filter-search]");
  var project = filters.querySelector("[data-filter-project]");
  var status = filters.querySelector("[data-filter-status]");
  var priority = filters.querySelector("[data-filter-priority]");
  var dueState = filters.querySelector("[data-filter-due-state]");
  var completed = filters.querySelector("[data-filter-completed]");
  var reset = filters.querySelector("[data-filter-reset]");
  var count = filters.querySelector("[data-filter-count]");
  var empty = filters.querySelector("[data-filter-empty]");
  if (!search || !project || !status || !priority || !dueState || !completed || !reset || !count || !empty) {
    return;
  }

  function normalized(value) {
    return String(value || "").trim().toLocaleLowerCase();
  }

  function matches(row, query, selectedProject, selectedStatus, selectedPriority, selectedDueState, showCompleted) {
    if (!showCompleted && row.dataset.completed === "true") {
      return false;
    }
    if (selectedProject && row.dataset.project !== selectedProject) {
      return false;
    }
    if (selectedStatus && row.dataset.status !== selectedStatus) {
      return false;
    }
    if (selectedPriority && row.dataset.priority !== selectedPriority) {
      return false;
    }
    if (selectedDueState && row.dataset.dueState !== selectedDueState) {
      return false;
    }
    if (query && normalized(row.dataset.search).indexOf(query) === -1) {
      return false;
    }
    return true;
  }

  function applyFilters() {
    var query = normalized(search.value);
    var selectedProject = project.value;
    var selectedStatus = status.value;
    var selectedPriority = priority.value;
    var selectedDueState = dueState.value;
    var showCompleted = completed.checked;
    var visible = 0;

    rows.forEach(function (row) {
      var visibleRow = matches(row, query, selectedProject, selectedStatus, selectedPriority, selectedDueState, showCompleted);
      row.hidden = !visibleRow;
      if (visibleRow) {
        visible += 1;
      }
    });

    count.textContent = "表示件数: " + visible + " / " + rows.length;
    empty.hidden = visible !== 0;
  }

  [search, project, status, priority, dueState, completed].forEach(function (control) {
    control.addEventListener(control === search ? "input" : "change", applyFilters);
  });

  reset.addEventListener("click", function () {
    search.value = "";
    project.value = "";
    status.value = "";
    priority.value = "";
    dueState.value = "";
    completed.checked = false;
    applyFilters();
  });

  applyFilters();
}());
""".strip()


def _css() -> str:
    return """
:root {
  color-scheme: light dark;
  --bg: #f7f7f4;
  --fg: #202124;
  --muted: #5f6368;
  --panel: #ffffff;
  --line: #d6d9d6;
  --accent: #176f63;
  --warn: #a64b00;
  --danger: #b3261e;
  --review: #7651a8;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #181a1b;
    --fg: #f1f3f4;
    --muted: #bdc1c6;
    --panel: #222527;
    --line: #3c4043;
    --accent: #69c5b8;
    --warn: #ffb36c;
    --danger: #ff8a80;
    --review: #c7a7f2;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
}
.page { max-width: 1180px; margin: 0 auto; padding: 24px; }
header, section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 16px;
}
h1, h2 { margin: 0 0 14px; line-height: 1.2; }
.meta-grid, .cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}
.meta-grid div, .card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}
.meta-grid span, .card span, .note, .empty, .gantt-label span { color: var(--muted); font-size: 0.88rem; }
.meta-grid strong, .card strong { display: block; font-size: 1.35rem; margin-top: 4px; overflow-wrap: anywhere; }
.table-wrap { overflow-x: auto; }
.task-filters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  align-items: end;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.filter-field {
  display: grid;
  gap: 4px;
}
.filter-field-wide {
  grid-column: span 2;
}
.filter-field label,
.filter-check {
  color: var(--muted);
  font-size: 0.88rem;
}
.filter-field input,
.filter-field select,
.filter-reset {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  background: var(--panel);
  color: var(--fg);
  font: inherit;
}
.filter-field input:focus,
.filter-field select:focus,
.filter-check input:focus-visible,
.filter-reset:focus {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.filter-check {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 42px;
}
.filter-check input {
  width: 1.1rem;
  height: 1.1rem;
  accent-color: var(--accent);
}
.filter-reset {
  cursor: pointer;
}
.filter-count,
.filter-empty {
  margin: 0;
  align-self: center;
  color: var(--muted);
}
.filter-empty {
  grid-column: 1 / -1;
  color: var(--danger);
}
table { width: 100%; border-collapse: collapse; min-width: 760px; }
.task-table { min-width: 980px; }
th, td { border-bottom: 1px solid var(--line); padding: 9px; text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: 0.86rem; white-space: nowrap; }
thead th { background: var(--panel); }
.col-id { width: 7.5rem; }
.col-priority { width: 6rem; }
.col-status { width: 7.5rem; }
.col-project { width: 9rem; }
.col-due { width: 7rem; }
.col-title { width: 32%; }
.col-tags { width: 18%; }
.col-due-state { width: 7rem; }
.cell-id,
.cell-priority,
.cell-status,
.cell-project,
.cell-due,
.cell-due-state {
  white-space: nowrap;
}
.cell-id { font-variant-numeric: tabular-nums; }
.cell-title {
  min-width: 16rem;
  overflow-wrap: anywhere;
}
.cell-tags {
  max-width: 16rem;
  overflow-wrap: anywhere;
}
.badge {
  display: inline-block;
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.82rem;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
}
.priority-urgent,
.status-blocked,
.due-state-overdue {
  color: var(--danger);
  background: rgba(179, 38, 30, 0.10);
}
.priority-high,
.due-state-today,
.due-state-soon {
  color: var(--warn);
  background: rgba(166, 75, 0, 0.10);
}
.priority-medium,
.status-planned,
.status-in-progress,
.status-done,
.due-state-scheduled,
.due-state-completed {
  color: var(--accent);
  background: rgba(23, 111, 99, 0.10);
}
.status-review {
  color: var(--review);
  background: rgba(118, 81, 168, 0.10);
}
.priority-low,
.status-inbox,
.status-cancelled,
.due-state-none,
.due-state-excluded {
  color: var(--muted);
  background: rgba(95, 99, 104, 0.10);
}
@media (prefers-color-scheme: dark) {
  .priority-urgent,
  .status-blocked,
  .due-state-overdue { background: rgba(255, 138, 128, 0.14); }
  .priority-high,
  .due-state-today,
  .due-state-soon { background: rgba(255, 179, 108, 0.14); }
  .priority-medium,
  .status-planned,
  .status-in-progress,
  .status-done,
  .due-state-scheduled,
  .due-state-completed { background: rgba(105, 197, 184, 0.14); }
  .status-review { background: rgba(199, 167, 242, 0.14); }
  .priority-low,
  .status-inbox,
  .status-cancelled,
  .due-state-none,
  .due-state-excluded { background: rgba(189, 193, 198, 0.12); }
}
.progress {
  display: block;
  height: 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  overflow: hidden;
  margin-top: 4px;
}
.progress span { display: block; height: 100%; background: var(--accent); }
.progress-label { font-variant-numeric: tabular-nums; }
.gantt-scale {
  display: flex;
  justify-content: space-between;
  color: var(--muted);
  font-size: 0.86rem;
  margin: 12px 0 8px;
}
.gantt-row {
  display: grid;
  grid-template-columns: minmax(180px, 280px) 1fr;
  gap: 10px;
  align-items: center;
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
}
.gantt-track {
  position: relative;
  min-height: 22px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.gantt-bar {
  position: absolute;
  top: 5px;
  height: 10px;
  background: var(--accent);
  border-radius: 999px;
}
.gantt-due {
  position: absolute;
  top: 1px;
  bottom: 1px;
  border-left: 2px solid var(--danger);
}
@media (max-width: 720px) {
  .page { padding: 12px; }
  .filter-field-wide { grid-column: 1 / -1; }
  .gantt-row { grid-template-columns: 1fr; }
  table { min-width: 680px; }
  .task-table { min-width: 860px; }
}
@media print {
  body { background: #fff; color: #000; }
  header, section { break-inside: avoid; border-color: #999; }
  .page { max-width: none; padding: 0; }
  .task-filters,
  .filter-count,
  .filter-empty,
  .filter-reset { display: none; }
  .table-wrap { overflow: visible; }
  .task-table { min-width: 0; }
}
""".strip()
