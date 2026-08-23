# ProjectControl Portfolio

[![CI](https://github.com/monaka-77/project-control-portfolio/actions/workflows/ci.yml/badge.svg)](https://github.com/monaka-77/project-control-portfolio/actions/workflows/ci.yml)

複数プロジェクトのタスクを、ローカル環境で安全に一元管理するための Python 製CLIツールです。

> このリポジトリは就職活動向けの公開版です。実運用のタスク、クライアント情報、個人パス、認証情報、バックアップは含めていません。サンプルデータはすべて架空です。

## このプロジェクトで示したこと

業務で使うタスク管理を想定し、単に登録・一覧表示するだけでなく、**誤操作を避けながら状況を把握しやすい設計**を目指しました。

- データを外部サービスに依存しないローカルファースト設計
- JSON更新時の一時ファイル＋置換による安全なファイル操作
- タスクの状態・優先度・日付・出力先パスの入力検証
- CLI／設定／ドメインモデル／リポジトリ／サービス／表示処理の責務分離
- 一時ディレクトリを用いた副作用のないユニットテスト
- HTMLダッシュボード、JSONバックアップ、CSVエクスポート

## 主な機能

| 分類 | 内容 |
|---|---|
| タスク管理 | 追加、詳細表示、更新、ステータス変更、完了、アーカイブ |
| 絞り込み | プロジェクト、ステータス、優先度、タグ、期限切れ、期限間近、完了状態 |
| 可視化 | プロジェクト別進捗、ターミナルダッシュボード、静的HTMLダッシュボード |
| データ保護 | 入力検証、アーカイブ確認、JSONバックアップ、リポジトリ外への出力防止 |
| 出力 | UTF-8 BOM付きCSV、ブラウザで閲覧できる単一HTMLレポート |

## 技術構成

- Python 3.13+
- Python標準ライブラリのみ
- JSON
- `unittest`
- GitHub Actions（構文検査・ユニットテスト）

外部パッケージや外部APIに依存しないため、ローカル環境で再現しやすい構成です。

## ディレクトリ構成

```text
.
├─ config/                  # アプリケーション設定
├─ data/                    # 実行時データ（Git管理対象外）
├─ examples/                # 架空のサンプルタスク
├─ src/project_control/     # アプリケーション本体
└─ tests/                   # ユニットテスト
```

## 実行方法

PowerShellでリポジトリ直下を開き、以下を実行します。

```powershell
$env:PYTHONPATH = "$PWD\src"

python -m project_control config
python -m project_control list
python -m project_control dashboard
python -m project_control dashboard-html --open
```

サンプルデータを使う場合は、先にコピーします。

```powershell
Copy-Item examples\sample_tasks.json data\tasks.json
```

## 公開デモ

架空のサンプルタスクから生成した、ブラウザで開ける[静的HTMLダッシュボード](docs/demo-dashboard.html)を公開しています。フィルタリング、プロジェクト別進捗、期限状態、簡易ガント表示を確認できます。

## テスト

```powershell
$env:PYTHONPATH = "$PWD\src"

py -3.13 -m compileall src tests
py -3.13 -m unittest discover -s tests -v
```

テストは一時ディレクトリで実行されるため、実運用の `data/tasks.json`、バックアップ、CSV出力を変更しません。

## 公開範囲について

本番運用版とはリポジトリを分離し、以下のみを公開しています。

- 汎用化したアプリケーションコード
- テストコード
- 設定例
- 架空のサンプルデータ
- 就職活動向けの説明資料

これにより、実務での設計・実装・検証の考え方を示しつつ、実データや業務情報は非公開に保っています。
