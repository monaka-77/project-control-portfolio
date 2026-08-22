# ProjectControl Portfolio

**Pythonで構築した、ローカルファーストのタスク管理CLI**

> このリポジトリは、ProjectControlの公開ポートフォリオ版です。  
> 公開対象はソースコード、テスト、架空のサンプルデータのみです。実運用のタスク、クライアント情報、個人環境のパス、認証情報、運用データは含めていません。

## 概要

ProjectControlは、複数プロジェクトの作業を安全かつ追跡可能な形で管理するためのPython CLIアプリケーションです。

タスクの作成・更新・ステータス変更・完了・アーカイブ・絞り込み・進捗集計に加え、JSONバックアップ、CSV出力、静的HTMLダッシュボードの生成に対応しています。

## 設計上の特徴

- **Local-first**: タスクデータはローカルのJSONファイルに保存し、外部APIや追加パッケージを必須としません。
- **安全なファイル操作**: JSON書き込みでは一時ファイルやアトミックな置換を適宜利用します。
- **Validation**: ステータス、優先度、日付、リポジトリ相対の出力パスを検証します。
- **責務の分離**: CLI、ドメインモデル、設定、リポジトリ、サービス、ダッシュボード描画を分離しています。
- **Testability**: テストでは一時ディレクトリと分離されたサンプルデータを使用し、実運用データへ影響しない構成にしています。

## 主な機能

- タスクの作成・表示・更新・完了・アーカイブ
- プロジェクト、ステータス、優先度、タグ、期限超過、期限間近、完了状態による絞り込み
- プロジェクト単位の進捗・タスク集計
- ターミナルダッシュボードと自己完結型の静的HTMLダッシュボード
- JSONバックアップとUTF-8 BOM付きCSV出力
- 設定ファイルの検証
- Python標準ライブラリのみで動作

## 技術スタック

- Python 3.13+
- Python standard library
- JSON
- `unittest`
- Git / GitHub

## ローカルでの実行

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m project_control config
python -m project_control list
python -m project_control dashboard
python -m project_control dashboard-html --open
```

## テストの実行

```powershell
$env:PYTHONPATH = "$PWD\src"
py -3.13 -m compileall src tests
py -3.13 -m unittest discover -s tests -v
```

## サンプルデータ

公開版には、`examples/sample_tasks.json` に架空のサンプルデータを含めています。ローカルで試す場合は、`data/tasks.json` へコピーしてください。

```powershell
Copy-Item examples\sample_tasks.json data\tasks.json
```

## リポジトリ構成

```text
.
├─ config/                  # アプリケーション設定
├─ examples/                # 架空のサンプルデータ
├─ src/project_control/     # アプリケーション本体
└─ tests/                   # 単体テスト
```

## ポートフォリオとしての公開範囲

このリポジトリでは、アプリケーション設計、入力検証、安全なファイル操作、CLI実装、静的レポート生成、単体テストを確認できます。

実際のタスクデータや事業情報を含む非公開の運用リポジトリとは分離し、ポートフォリオとして公開して問題のないコードと架空データのみを掲載しています。
