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
- **自動スキャン** — 起動時に `~/.claude/` から既存セッションを自動検出、手動スキャン不要
- **AI サマリー** — [Codex CLI](https://github.com/openai/codex) でアクティブセッションのタイトルとサマリーを生成。履歴セッションは最初のユーザーメッセージを使用（コストゼロ）
- **3セクションダッシュボード** — タスクをステータス別に表示：対応必要 / 実行中 / 完了
- **詳細ビュー** — サマリー、アクションステップチェックリスト、タイムライン
- **セッション再開** — `c` キーで新しいターミナルにセッションを再開
- **検索** — `/` キーでタイトルフィルタリング
- **自動更新** — 5秒ごとにダッシュボードを更新
- **ハートビートスロットル** — セッションごとに30秒に1回のみDB書き込み
- **レスポンシブ** — ターミナル幅に自動適応

## クイックスタート

```bash
# インストール
uv venv && uv pip install -e .

# Claude Code hooks をインストール（初回のみ）
uv run task-pilot install-hooks

# 起動（自動スキャン）
uv run task-pilot ui
```

AI によるタイトル・サマリー生成には [Codex CLI](https://github.com/openai/codex) が必要です。未インストールの場合、最初のユーザーメッセージにフォールバックします。

## アーキテクチャ

```
SQLite DB  <──  Hooks（リアルタイム）   <──  Claude Code セッション
    |       <──  Scanner（自動スキャン）<──  ~/.claude/ ファイル
    |       <──  Codex CLI（サマリー） <──  OpenAI（オプション）
    v
  Textual TUI ── リストビュー ── 詳細ビュー
```

### サマリー戦略

| シナリオ | タイトル | サマリー | コスト |
|----------|---------|---------|--------|
| 履歴セッション（終了済み） | 最初のユーザーメッセージ（~60文字） | 同左 | 0 |
| アクティブセッション（新規検出） | Codex AI -> フォールバック | Codex AI -> フォールバック | OpenAI トークン |
| セッション終了（hook） | 生成済み | 生成済み | 0 |

### モジュール

| レイヤー | 説明 |
|----------|------|
| `summarizer.py` | Codex CLI AI サマリー、ヒューリスティックフォールバック |
| `db.py` | SQLite CRUD、自動スキーマ作成 |
| `hooks.py` | Claude Code hook インストーラー + スロットル付きイベントハンドラー |
| `scanner.py` | `~/.claude/` を読み取りセッションを検出 |
| `cli.py` | Click CLI エントリーポイント |
| `app.py` | Textual アプリシェル、起動時自動スキャン |
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

# テスト実行（106テスト）
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
- [Codex CLI](https://github.com/openai/codex) — AI サマリー（オプション）
