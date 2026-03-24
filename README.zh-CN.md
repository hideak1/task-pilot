<p align="center">
  <strong>Task Pilot</strong><br>
  Claude Code 会话的终端任务管理面板
</p>

<p align="center">
  <a href="./README.md">English</a> |
  <a href="./README.zh-CN.md">中文</a> |
  <a href="./README.ja.md">日本語</a>
</p>

---

## Task Pilot 是什么？

Task Pilot 是一个终端仪表盘，用于追踪你的 Claude Code 会话、展示需要你处理的操作项，并支持恢复会话 —— 相当于多会话工作流的调度面板。

**核心理念：** 你是 CPU（决策者），Claude Code 是 I/O（代码执行者）。当你同时操控多个会话时，很容易丢失上下文。Task Pilot 为你提供一个统一视图。

## 功能特性

- **实时追踪** — Claude Code hooks 自动捕获会话事件（启动、心跳、中断、结束）
- **会话扫描** — 启动时自动从 `~/.claude/` 发现已有会话
- **三栏仪表盘** — 任务按状态分组：需要操作 / 运行中 / 已完成
- **详情视图** — 摘要、操作步骤清单、时间线
- **恢复会话** — 按 `c` 在新终端中恢复任意会话
- **搜索** — 按 `/` 按标题筛选任务
- **自动刷新** — 每 5 秒更新仪表盘
- **响应式** — 自适应终端宽度

## 快速开始

```bash
# 用 uv 安装
uv pip install -e .

# 安装 Claude Code hooks（仅需一次）
task-pilot install-hooks

# 启动仪表盘
task-pilot ui
```

## 架构

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

## 快捷键

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

## 开发

```bash
# 环境搭建
uv venv && uv pip install -e ".[dev]"

# 运行测试（102 个测试用例）
uv run pytest tests/ -v

# 运行应用
uv run task-pilot ui
```

## 技术栈

- Python 3.11+
- [Textual](https://textual.textualize.io/) — TUI 框架
- [Rich](https://rich.readthedocs.io/) — 终端渲染
- [Click](https://click.palletsprojects.com/) — CLI
- SQLite3 — 本地存储
