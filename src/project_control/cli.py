from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .config import ConfigError, ProjectConfig, load_config
from .dashboard import DashboardError, render_dashboard_html, save_dashboard_html
from .models import Task, TaskPriority, TaskStatus
from .repository import JsonTaskRepository, RepositoryError
from .service import ProjectControlService, ServiceError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="project_control", description="ProjectControl のタスク管理 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("config", help="設定内容を表示します")

    add_parser = subparsers.add_parser("add", help="タスクを追加します")
    add_parser.add_argument("--title", required=True, help="タスクタイトル")
    add_parser.add_argument("--project", required=True, help="プロジェクト名")
    add_parser.add_argument("--priority", choices=_priority_values(), help="優先度")
    add_parser.add_argument("--status", choices=_status_values(), help="ステータス")
    add_parser.add_argument("--description", default="", help="説明")
    add_parser.add_argument("--due-date", help="期限日")
    add_parser.add_argument("--tag", action="append", default=[], help="タグ。複数指定可")

    list_parser = subparsers.add_parser("list", help="タスクを一覧表示します")
    _add_task_filters(list_parser)
    list_parser.add_argument("--include-archived", action="store_true", help="アーカイブ済みも含めます")
    due_group = list_parser.add_mutually_exclusive_group()
    due_group.add_argument("--overdue", action="store_true", help="期限切れのみ表示します")
    due_group.add_argument("--due-soon", type=int, help="今日から指定日数以内の期限を表示します")
    state_group = list_parser.add_mutually_exclusive_group()
    state_group.add_argument("--completed", action="store_true", help="完了済みのみ表示します")
    state_group.add_argument("--active", action="store_true", help="アクティブなタスクのみ表示します")

    show_parser = subparsers.add_parser("show", help="タスク詳細を表示します")
    show_parser.add_argument("task_id", help="対象タスクID")

    update_parser = subparsers.add_parser("update", help="タスクを更新します")
    update_parser.add_argument("task_id", help="対象タスクID")
    update_parser.add_argument("--title", help="新しいタイトル")
    update_parser.add_argument("--project", help="新しいプロジェクト")
    update_parser.add_argument("--status", choices=_status_values(), help="新しいステータス")
    update_parser.add_argument("--priority", choices=_priority_values(), help="新しい優先度")
    update_parser.add_argument("--description", help="新しい説明。空文字も指定可能です")
    due_update_group = update_parser.add_mutually_exclusive_group()
    due_update_group.add_argument("--due-date", help="新しい期限日")
    due_update_group.add_argument("--clear-due-date", action="store_true", help="期限日を削除します")
    tag_update_group = update_parser.add_mutually_exclusive_group()
    tag_update_group.add_argument("--tag", action="append", help="タグを置換します。複数指定可")
    tag_update_group.add_argument("--clear-tags", action="store_true", help="タグをすべて削除します")

    status_parser = subparsers.add_parser("status", help="タスクのステータスを変更します")
    status_parser.add_argument("task_id", help="対象タスクID")
    status_parser.add_argument("new_status", choices=_status_values(), help="新しいステータス")

    complete_parser = subparsers.add_parser("complete", help="タスクを完了にします")
    complete_parser.add_argument("task_id", help="対象タスクID")

    archive_parser = subparsers.add_parser("archive", help="タスクをアーカイブします")
    archive_parser.add_argument("task_id", help="対象タスクID")
    archive_parser.add_argument("--yes", action="store_true", help="確認なしでアーカイブします")

    archive_list_parser = subparsers.add_parser("archive-list", help="アーカイブ済みタスクを一覧表示します")
    _add_task_filters(archive_list_parser)

    progress_parser = subparsers.add_parser("progress", help="プロジェクト別の進捗を表示します")
    progress_parser.add_argument("--project", help="対象プロジェクトを完全一致で絞り込みます")

    dashboard_parser = subparsers.add_parser("dashboard", help="作業状況のダッシュボードを表示します")
    dashboard_parser.add_argument("--project", help="対象プロジェクトを完全一致で絞り込みます")
    dashboard_parser.add_argument("--due-soon", type=int, default=3, help="期限間近として扱う日数")
    dashboard_parser.add_argument("--limit", type=int, default=5, help="次に見るタスクの最大件数")

    dashboard_html_parser = subparsers.add_parser("dashboard-html", help="静的 HTML ダッシュボードを生成します")
    dashboard_html_parser.add_argument("--output", help="出力先の相対パス")
    dashboard_html_parser.add_argument("--project", help="対象プロジェクトを完全一致で絞り込みます")
    dashboard_html_parser.add_argument("--due-soon", type=int, default=3, help="期限間近として扱う日数")
    dashboard_html_parser.add_argument("--limit", type=int, default=5, help="次に見るタスクの最大件数")
    dashboard_html_parser.add_argument("--open", action="store_true", help="生成後に既定ブラウザで開きます")

    subparsers.add_parser("summary", help="タスクを集計します")
    subparsers.add_parser("backup", help="tasks.json のバックアップを作成します")

    export_parser = subparsers.add_parser("export-csv", help="CSV を出力します")
    export_parser.add_argument("--output", help="出力先の相対パス")
    export_parser.add_argument("--include-archived", action="store_true", help="アーカイブ済みも含めます")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        config = load_config(Path.cwd())
        service = ProjectControlService(
            JsonTaskRepository(config.data_file),
            repo_root=Path.cwd(),
            date_format=config.date_format,
        )
        if args.command == "config":
            _print_config(config)
        elif args.command == "add":
            _handle_add(args, config, service)
        elif args.command == "list":
            _handle_list(args, service)
        elif args.command == "show":
            _handle_show(args, service)
        elif args.command == "update":
            _handle_update(args, service)
        elif args.command == "status":
            _handle_status(args, service)
        elif args.command == "complete":
            _handle_complete(args, service)
        elif args.command == "archive":
            return _handle_archive(args, service)
        elif args.command == "archive-list":
            _handle_archive_list(args, service)
        elif args.command == "progress":
            _handle_progress(args, service)
        elif args.command == "dashboard":
            _handle_dashboard(args, service)
        elif args.command == "dashboard-html":
            _handle_dashboard_html(args, service)
        elif args.command == "summary":
            _handle_summary(service)
        elif args.command == "backup":
            _handle_backup(service)
        elif args.command == "export-csv":
            _handle_export_csv(args, service)
        return 0
    except KeyboardInterrupt:
        print("中断しました。", file=sys.stderr)
        return 1
    except (ConfigError, DashboardError, RepositoryError, ServiceError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _priority_values() -> list[str]:
    return [item.value for item in TaskPriority]


def _status_values() -> list[str]:
    return [item.value for item in TaskStatus]


def _add_task_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", help="プロジェクト名")
    parser.add_argument("--status", choices=_status_values(), help="ステータス")
    parser.add_argument("--priority", choices=_priority_values(), help="優先度")
    parser.add_argument("--tag", help="タグ")


def _print_config(config: ProjectConfig) -> None:
    print("設定ファイル:", config.config_file)
    print("データ保存先:", config.data_file)
    print("既定ステータス:", config.default_status.value)
    print("既定優先度:", config.default_priority.value)
    print("日付形式:", config.date_format)


def _handle_add(args: argparse.Namespace, config: ProjectConfig, service: ProjectControlService) -> None:
    task = service.add_task(
        title=args.title,
        project=args.project,
        status=args.status or config.default_status,
        priority=args.priority or config.default_priority,
        description=args.description,
        due_date=args.due_date,
        tags=args.tag,
    )
    print("タスクを追加しました。")
    _print_task_brief(task)


def _handle_list(args: argparse.Namespace, service: ProjectControlService) -> None:
    tasks = service.list_tasks(
        project=args.project,
        status=args.status,
        priority=args.priority,
        tag=args.tag,
        include_archived=args.include_archived,
        overdue=args.overdue,
        due_soon_days=args.due_soon,
        completed=args.completed,
        active=args.active,
    )
    if not tasks:
        print("タスクはありません。")
        return
    headers = ["ID", "優先度", "ステータス", "プロジェクト", "期限", "タイトル", "タグ"]
    if args.include_archived:
        headers.append("アーカイブ")
    rows = [headers]
    for task in tasks:
        row = [
            task.id,
            task.priority.value,
            task.status.value,
            task.project,
            task.due_date or "-",
            task.title,
            ", ".join(task.tags) if task.tags else "-",
        ]
        if args.include_archived:
            row.append("済" if task.archived_at else "-")
        rows.append(row)
    _print_table(rows)


def _handle_show(args: argparse.Namespace, service: ProjectControlService) -> None:
    task = service.get_task(args.task_id)
    print("ID:", task.id)
    print("タイトル:", task.title)
    print("プロジェクト:", task.project)
    print("ステータス:", task.status.value)
    print("優先度:", task.priority.value)
    print("説明:", task.description if task.description != "" else "(空)")
    print("期限:", task.due_date or "-")
    print("タグ:", ", ".join(task.tags) if task.tags else "-")
    print("作成日時:", task.created_at)
    print("更新日時:", task.updated_at)
    print("完了日時:", task.completed_at or "-")
    print("アーカイブ日時:", task.archived_at or "-")
    print("期限状態:", service.get_due_state(task))


def _handle_update(args: argparse.Namespace, service: ProjectControlService) -> None:
    task = service.update_task(
        args.task_id,
        title=args.title,
        project=args.project,
        status=args.status,
        priority=args.priority,
        description=args.description,
        due_date=args.due_date,
        clear_due_date=args.clear_due_date,
        tags=args.tag,
        clear_tags=args.clear_tags,
    )
    print("タスクを更新しました。")
    _print_task_brief(task)


def _handle_status(args: argparse.Namespace, service: ProjectControlService) -> None:
    task, old_status = service.change_status(args.task_id, args.new_status)
    print("ステータスを変更しました。")
    print("ID:", task.id)
    print("タイトル:", task.title)
    print("変更前:", old_status.value)
    print("変更後:", task.status.value)


def _handle_complete(args: argparse.Namespace, service: ProjectControlService) -> None:
    task = service.complete_task(args.task_id)
    print("タスクを完了しました。")
    print("ID:", task.id)
    print("タイトル:", task.title)
    print("完了日時:", task.completed_at or "-")


def _handle_archive(args: argparse.Namespace, service: ProjectControlService) -> int:
    if not args.yes and not _confirm_archive():
        print("アーカイブを中止しました。")
        return 0
    task = service.archive_task(args.task_id)
    print("タスクをアーカイブしました。")
    print("ID:", task.id)
    print("タイトル:", task.title)
    print("アーカイブ日時:", task.archived_at or "-")
    return 0


def _confirm_archive() -> bool:
    answer = input("このタスクをアーカイブしますか？ [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _handle_archive_list(args: argparse.Namespace, service: ProjectControlService) -> None:
    tasks = service.list_archived_tasks(
        project=args.project,
        status=args.status,
        priority=args.priority,
        tag=args.tag,
    )
    if not tasks:
        print("アーカイブ済みタスクはありません。")
        return
    rows = [["ID", "優先度", "ステータス", "プロジェクト", "期限", "タイトル", "タグ", "アーカイブ日時"]]
    rows.extend(
        [
            [
                task.id,
                task.priority.value,
                task.status.value,
                task.project,
                task.due_date or "-",
                task.title,
                ", ".join(task.tags) if task.tags else "-",
                task.archived_at or "-",
            ]
            for task in tasks
        ]
    )
    _print_table(rows)


def _handle_progress(args: argparse.Namespace, service: ProjectControlService) -> None:
    entries = service.get_progress(project=args.project)
    if not entries:
        print("対象の進捗データはありません。")
        return
    rows = [["プロジェクト", "全件数", "未着手", "進行中", "ブロック", "レビュー", "完了", "期限切れ", "完了率"]]
    rows.extend(
        [
            [
                entry.project,
                str(entry.total),
                str(entry.todo),
                str(entry.in_progress),
                str(entry.blocked),
                str(entry.review),
                str(entry.done),
                str(entry.overdue),
                f"{entry.completion_rate:.1f}%",
            ]
            for entry in entries
        ]
    )
    _print_table(rows)


def _handle_dashboard(args: argparse.Namespace, service: ProjectControlService) -> None:
    dashboard = service.get_dashboard(project=args.project, due_soon_days=args.due_soon, limit=args.limit)
    title = "ダッシュボード" if args.project is None else f"ダッシュボード: {args.project}"
    print(title)
    print("全件数:", dashboard.total)
    print("アクティブ件数:", dashboard.active)
    print("完了件数:", dashboard.completed)
    print("アーカイブ件数:", dashboard.archived)
    print("期限切れ件数:", dashboard.overdue)
    print("今日が期限:", dashboard.due_today)
    print("期限間近件数:", dashboard.due_soon)
    print("ブロック件数:", dashboard.blocked)
    print("レビュー件数:", dashboard.review)
    print("高優先度件数:", dashboard.urgent_high)
    print("期限なしアクティブ件数:", dashboard.no_due_active)

    print("\nプロジェクト別:")
    if not dashboard.projects:
        print("  なし")
    else:
        rows = [["プロジェクト", "アクティブ", "完了", "期限切れ", "今日", "期限間近", "ブロック", "高優先度", "完了率"]]
        rows.extend(
            [
                [
                    entry.project,
                    str(entry.active),
                    str(entry.done),
                    str(entry.overdue),
                    str(entry.due_today),
                    str(entry.due_soon),
                    str(entry.blocked),
                    str(entry.urgent_high),
                    f"{entry.completion_rate:.1f}%",
                ]
                for entry in dashboard.projects
            ]
        )
        _print_table(rows)

    print("\n次に見るタスク:")
    if not dashboard.next_tasks:
        print("  なし")
    else:
        rows = [["ID", "優先度", "ステータス", "プロジェクト", "期限", "期限状態", "タイトル"]]
        rows.extend(
            [
                [
                    task.id,
                    task.priority.value,
                    task.status.value,
                    task.project,
                    task.due_date or "-",
                    service.get_due_state(task),
                    task.title,
                ]
                for task in dashboard.next_tasks
            ]
        )
        _print_table(rows)


def _handle_dashboard_html(args: argparse.Namespace, service: ProjectControlService) -> None:
    dashboard = service.get_dashboard(project=args.project, due_soon_days=args.due_soon, limit=args.limit)
    html = render_dashboard_html(
        dashboard,
        generated_at=service.now_provider(),
        project_filter=args.project,
        due_soon_days=args.due_soon,
        today=service.today_provider(),
        due_state_provider=service.get_due_state,
    )
    path = save_dashboard_html(service.repo_root, html, args.output)
    print("HTML ダッシュボードを生成しました。")
    print("保存先:", path)
    print("件数:", len(dashboard.tasks))
    if args.open:
        webbrowser.open(path.as_uri())


def _handle_summary(service: ProjectControlService) -> None:
    summary = service.summary()
    print("全件数:", summary["total"])
    print("アクティブ件数:", summary["active"])
    print("完了件数:", summary["completed"])
    print("アーカイブ件数:", summary["archived"])
    print("期限切れ件数:", summary["overdue"])
    print("期限間近件数:", summary["due_soon"])
    _print_counts("プロジェクト別", summary["by_project"])
    _print_counts("ステータス別", summary["by_status"])
    _print_counts("優先度別", summary["by_priority"])


def _handle_backup(service: ProjectControlService) -> None:
    path, count = service.create_backup()
    print("バックアップを作成しました。")
    print("保存先:", path)
    print("件数:", count)


def _handle_export_csv(args: argparse.Namespace, service: ProjectControlService) -> None:
    path, count = service.export_csv(output=args.output, include_archived=args.include_archived)
    print("CSV を出力しました。")
    print("保存先:", path)
    print("件数:", count)


def _print_task_brief(task: Task) -> None:
    print("ID:", task.id)
    print("タイトル:", task.title)
    print("プロジェクト:", task.project)
    print("状態:", task.status.value)
    print("優先度:", task.priority.value)
    print("期限:", task.due_date or "-")


def _print_counts(title: str, counts: dict[str, int]) -> None:
    print(f"\n{title}:")
    if not counts:
        print("  なし")
        return
    for key, value in counts.items():
        print(f"  {key}: {value}")


def _print_table(rows: list[list[str]]) -> None:
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row_index, row in enumerate(rows):
        line = "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        print(line)
        if row_index == 0:
            print("  ".join("-" * width for width in widths))
