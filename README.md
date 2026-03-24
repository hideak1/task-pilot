<p align="center">
  <strong>Task Pilot</strong><br>
  Terminal UI task manager for Claude Code sessions
</p>

<p align="center">
  <a href="#english">English</a> |
  <a href="#中文">中文</a> |
  <a href="#日本語">日本語</a>
</p>

---

<a id="english"></a>

## English

### What is Task Pilot?

Task Pilot is a terminal dashboard that tracks your Claude Code sessions, surfaces action items that need your attention, and lets you resume sessions — acting as a dispatcher panel for multi-session workflows.

**The core idea:** You are the CPU (decision-maker), Claude Code is I/O (code executor). When you juggle multiple sessions, you lose context. Task Pilot solves this by giving you a single pane of glass.

### Features

- **Real-time tracking** — Claude Code hooks automatically capture session events (start, heartbeat, stop, end)
- **Session scanner** — Discovers existing sessions from `~/.claude/` on startup
- **Three-section dashboard** — Tasks grouped by: Action Required / Working / Done
- **Detail view** — Summary, action steps checklist, timeline for each task
- **Session resume** — Press `c` to resume any session in a new terminal
- **Search** — Press `/` to filter tasks by title
- **Auto-refresh** — Dashboard updates every 5 seconds
- **Responsive** — Adapts to terminal width

### Quick Start

```bash
# Install with uv
uv pip install -e .

# Install Claude Code hooks (one-time setup)
task-pilot install-hooks

# Launch the dashboard
task-pilot ui
```

### Architecture

```
SQLite DB  <──  Hooks (real-time)  <──  Claude Code sessions
    |       <──  Scanner (backfill) <──  ~/.claude/ files
    v
  Textual TUI ── List View ── Detail View
```

| Layer | Description |
|-------|-------------|
| `models.py` | Dataclasses: Task, Session, ActionItem, TimelineEvent |
| `db.py` | SQLite CRUD with schema auto-migration |
| `hooks.py` | Claude Code hook installer + event handlers |
| `scanner.py` | Reads `~/.claude/` to discover sessions |
| `summarizer.py` | Transcript parsing + summary generation |
| `cli.py` | Click CLI entry point |
| `app.py` | Textual app shell |
| `screens/` | List screen + Detail screen |
| `widgets/` | HeaderBar, TaskRow, ActionSteps, Timeline |

### Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Open task detail |
| `Esc` | Go back / close search |
| `c` | Resume session |
| `d` | Mark task done |
| `r` | Refresh |
| `/` | Search |
| `n` | New task |
| `q` | Quit |

### Development

```bash
# Setup
uv venv && uv pip install -e ".[dev]"

# Run tests (102 tests)
uv run pytest tests/ -v

# Run the app
uv run task-pilot ui
```

### Tech Stack

- Python 3.11+
- [Textual](https://textual.textualize.io/) — TUI framework
- [Rich](https://rich.readthedocs.io/) — Terminal rendering
- [Click](https://click.palletsprojects.com/) — CLI
- SQLite3 — Local storage

---

<a id="中文"></a>

## 中文

### Task Pilot 是什么？

Task Pilot 是一个终端仪表盘，用于追踪你的 Claude Code 会话、展示需要你处理的操作项，并支持恢复会话 —— 相当于多会话工作流的调度面板。

**核心理念：** 你是 CPU（决策者），Claude Code 是 I/O（代码执行者）。当你同时操控多个会话时，很容易丢失上下文。Task Pilot 为你提供一个统一视图。

### 功能特性

- **实时追踪** — Claude Code hooks 自动捕获会话事件（启动、心跳、中断、结束）
- **会话扫描** — 启动时自动从 `~/.claude/` 发现已有会话
- **三栏仪表盘** — 任务按状态分组：需要操作 / 运行中 / 已完成
- **详情视图** — 摘要、操作步骤清单、时间线
- **恢复会话** — 按 `c` 在新终端中恢复任意会话
- **搜索** — 按 `/` 按标题筛选任务
- **自动刷新** — 每 5 秒更新仪表盘
- **响应式** — 自适应终端宽度

### 快速开始

```bash
# 用 uv 安装
uv pip install -e .

# 安装 Claude Code hooks（仅需一次）
task-pilot install-hooks

# 启动仪表盘
task-pilot ui
```

### 架构

```
SQLite 数据库  <──  Hooks（实时写入）  <──  Claude Code 会话
      |         <──  Scanner（回填）   <──  ~/.claude/ 文件
      v
   Textual TUI ── 列表视图 ── 详情视图
```

| 层级 | 说明 |
|------|------|
| `models.py` | 数据类：Task、Session、ActionItem、TimelineEvent |
| `db.py` | SQLite CRUD，自动建表 |
| `hooks.py` | Claude Code hook 安装器 + 事件处理器 |
| `scanner.py` | 读取 `~/.claude/` 发现会话 |
| `summarizer.py` | 解析会话记录 + 生成摘要 |
| `cli.py` | Click CLI 入口 |
| `app.py` | Textual 应用外壳 |
| `screens/` | 列表页 + 详情页 |
| `widgets/` | 头部栏、任务行、操作步骤、时间线 |

### 快捷键

| 按键 | 功能 |
|------|------|
| `Enter` | 打开任务详情 |
| `Esc` | 返回 / 关闭搜索 |
| `c` | 恢复会话 |
| `d` | 标记完成 |
| `r` | 刷新 |
| `/` | 搜索 |
| `n` | 新建任务 |
| `q` | 退出 |

### 开发

```bash
# 环境搭建
uv venv && uv pip install -e ".[dev]"

# 运行测试（102 个测试用例）
uv run pytest tests/ -v

# 运行应用
uv run task-pilot ui
```

---

<a id="日本語"></a>

## 日本語

### Task Pilot とは？

Task Pilot は Claude Code セッションを追跡し、対応が必要なアクションアイテムを表示し、セッションの再開を可能にするターミナルダッシュボードです。マルチセッションワークフローのディスパッチャーパネルとして機能します。

**コアコンセプト：** あなたは CPU（意思決定者）、Claude Code は I/O（コード実行者）。複数セッションを同時に扱うとコンテキストを見失います。Task Pilot が統一ビューを提供します。

### 機能

- **リアルタイム追跡** — Claude Code hooks がセッションイベント（開始・ハートビート・停止・終了）を自動キャプチャ
- **セッションスキャン** — 起動時に `~/.claude/` から既存セッションを自動検出
- **3セクションダッシュボード** — タスクをステータス別に表示：対応必要 / 実行中 / 完了
- **詳細ビュー** — サマリー、アクションステップチェックリスト、タイムライン
- **セッション再開** — `c` キーで新しいターミナルにセッションを再開
- **検索** — `/` キーでタイトルフィルタリング
- **自動更新** — 5秒ごとにダッシュボードを更新
- **レスポンシブ** — ターミナル幅に自動適応

### クイックスタート

```bash
# uv でインストール
uv pip install -e .

# Claude Code hooks をインストール（初回のみ）
task-pilot install-hooks

# ダッシュボードを起動
task-pilot ui
```

### アーキテクチャ

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

### キーバインド

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

### 開発

```bash
# セットアップ
uv venv && uv pip install -e ".[dev]"

# テスト実行（102テスト）
uv run pytest tests/ -v

# アプリ実行
uv run task-pilot ui
```

### 技術スタック

- Python 3.11+
- [Textual](https://textual.textualize.io/) — TUI フレームワーク
- [Rich](https://rich.readthedocs.io/) — ターミナルレンダリング
- [Click](https://click.palletsprojects.com/) — CLI
- SQLite3 — ローカルストレージ
