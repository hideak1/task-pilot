<p align="center">
  <strong>Task Pilot</strong><br>
  Claude Code セッション用ターミナルタスク管理ダッシュボード
</p>

<p align="center">
  <a href="./README.md">English</a> |
  <a href="./README.zh-CN.md">中文</a> |
  <a href="./README.ja.md">日本語</a>
</p>

---

## Task Pilot とは？

Task Pilot は Claude Code セッションを追跡し、対応が必要なアクションアイテムを表示し、セッションの再開を可能にするターミナルダッシュボードです。マルチセッションワークフローのディスパッチャーパネルとして機能します。

**コアコンセプト：** あなたは CPU（意思決定者）、Claude Code は I/O（コード実行者）。複数セッションを同時に扱うとコンテキストを見失います。Task Pilot が統一ビューを提供します。

## 機能

- **リアルタイム追跡** — Claude Code hooks がセッションイベント（開始・ハートビート・停止・終了）を自動キャプチャ
- **セッションスキャン** — 起動時に `~/.claude/` から既存セッションを自動検出
- **3セクションダッシュボード** — タスクをステータス別に表示：対応必要 / 実行中 / 完了
- **詳細ビュー** — サマリー、アクションステップチェックリスト、タイムライン
- **セッション再開** — `c` キーで新しいターミナルにセッションを再開
- **検索** — `/` キーでタイトルフィルタリング
- **自動更新** — 5秒ごとにダッシュボードを更新
- **レスポンシブ** — ターミナル幅に自動適応

## クイックスタート

```bash
# uv でインストール
uv pip install -e .

# Claude Code hooks をインストール（初回のみ）
task-pilot install-hooks

# ダッシュボードを起動
task-pilot ui
```

## アーキテクチャ

```
SQLite DB  <──  Hooks（リアルタイム） <──  Claude Code セッション
    |       <──  Scanner（バックフィル）<──  ~/.claude/ ファイル
    v
  Textual TUI ── リストビュー ── 詳細ビュー
```

| レイヤー | 説明 |
|----------|------|
| `models.py` | データクラス：Task、Session、ActionItem、TimelineEvent |
| `db.py` | SQLite CRUD、自動スキーマ作成 |
| `hooks.py` | Claude Code hook インストーラー + イベントハンドラー |
| `scanner.py` | `~/.claude/` を読み取りセッションを検出 |
| `summarizer.py` | トランスクリプト解析 + サマリー生成 |
| `cli.py` | Click CLI エントリーポイント |
| `app.py` | Textual アプリシェル |
| `screens/` | リスト画面 + 詳細画面 |
| `widgets/` | ヘッダーバー、タスク行、アクションステップ、タイムライン |

## キーバインド

| キー | アクション |
|------|-----------|
| `Enter` | タスク詳細を開く |
| `Esc` | 戻る / 検索を閉じる |
| `c` | セッション再開 |
| `d` | 完了にする |
| `r` | 更新 |
| `/` | 検索 |
| `n` | 新規タスク |
| `q` | 終了 |

## 開発

```bash
# セットアップ
uv venv && uv pip install -e ".[dev]"

# テスト実行（102テスト）
uv run pytest tests/ -v

# アプリ実行
uv run task-pilot ui
```

## 技術スタック

- Python 3.11+
- [Textual](https://textual.textualize.io/) — TUI フレームワーク
- [Rich](https://rich.readthedocs.io/) — ターミナルレンダリング
- [Click](https://click.palletsprojects.com/) — CLI
- SQLite3 — ローカルストレージ
