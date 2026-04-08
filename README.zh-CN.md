<p align="center">
  <strong>Task Pilot</strong><br>
  用于编排多个 Claude Code 会话的终端仪表盘
</p>

<p align="center">
  <a href="./README.md">English</a> |
  <a href="./README.zh-CN.md">中文</a> |
  <a href="./README.ja.md">日本語</a>
</p>

---

## Task Pilot 是什么？

Task Pilot 是一个终端控制面板，让你无需离开终端就能同时运行并切换多个 Claude Code 会话。它基于 **tmux** 构建：一个名为 `task-pilot` 的专用 tmux 会话内，左侧窗格运行 pilot 的 Textual UI，右侧窗格是当前可见的 Claude Code 会话。你在 pilot 中启动的其他每一个 Claude Code 会话都存活在隐藏的 `_bg_<uuid>` 窗口中，进程持续正常运行。

当你在左侧列表中选中另一个会话时，pilot 使用**两步 swap-pane 协议**：第一步把当前可见会话的窗格送回它自己的 `_bg_*` 老家窗口，第二步再把目标会话的窗格交换进右侧主窗格。切换期间没有任何会话会被杀死、断开或重启。

**范围（E1）：** pilot 只管理*你从 pilot 内部创建*的会话；在其他终端启动的会话有意不在此范围之内。

**为什么要重写？** v0.1 依赖 Claude Code hooks + scanner + AI 摘要器。那套方案在内循环里烧 token，而且你仍然要切终端才能真正和 Claude 交互。tmux 模型同时解决了这两个问题：热路径上零 API 调用，右侧窗格就是一个真正的 Claude Code TUI，你可以直接在里面打字。

## 功能特性

- **基于 tmux 的编排** — 无 hooks，无 API 调用，零 token 开销
- **实时刷新** — 每 2 秒刷新，直接读取 `~/.claude/projects/*.jsonl`
- **实时 token 计数** — tail 读取每个 transcript，累加 assistant 消息的 `input_tokens + output_tokens`
- **状态检测** — `initializing` / `working` / `idle` / `unknown`，完全来源于本地 transcript 活动
- **每会话上下文** — 每行显示工作目录（`~` 缩写）和 git 分支
- **两步 swap-pane 切换** — 瞬时视觉切换，进程不重启
- **鼠标 + 键盘导航** — 可以点击行、在 Claude 内部滚动，或使用 vim 风格按键
- **命令栏（`:q`）** — vim 风格退出，干净地收尾所有被管理的会话
- **抗崩溃** — pilot 在 watchdog 包装下运行；启动时与 tmux 对账，自动收养孤儿窗口

## 快速开始

```bash
uv venv && uv pip install -e .
task-pilot ui      # 引导创建或连接到 tmux 会话
```

`task-pilot ui` 是幂等的：
- 如果 `task-pilot` tmux 会话不存在，会引导创建双窗格布局，并在左侧启动 pilot。
- 如果已存在，`task-pilot ui` 会直接 attach 上去。
- 如果你在*另一个* tmux 会话内运行它，pilot 会打印可操作的指引，而不是默默出错。

## 快捷键

| 按键               | 功能                                                               |
|--------------------|--------------------------------------------------------------------|
| `j` / `k` / `↑` / `↓` | 在左侧面板移动选中                                             |
| `Enter`            | 切换到选中会话（两步 swap-pane）并把焦点移到右侧                   |
| `Tab`              | 在左侧面板与右侧窗格之间切换焦点                                   |
| `n`                | 新建会话 — 打开对话框，带最近目录与 Tab 补全                       |
| `x`                | 关闭选中会话（带确认）                                             |
| `r`                | 强制刷新（同时重新解析 git 分支与 transcript 路径）                |
| `/`                | 按标题或 cwd 子串过滤行                                            |
| `:`                | 打开命令栏                                                         |
| `:q` + `Enter`     | 退出 pilot，并杀死所有被管理的 Claude Code 进程                    |

有意不提供裸 `q` 退出键 —— `:q` 足够难以误触，因此不需要确认框。

## 架构

```
┌─── tmux 会话: task-pilot ──────────────────────────┐
│                                                    │
│  窗口: main                                        │
│  ┌──────────────────┬──────────────────────────┐  │
│  │                  │                          │  │
│  │  pilot (Textual) │  Claude Code 会话         │  │
│  │  左侧列表        │  （当前选中）              │  │
│  │                  │                          │  │
│  └──────────────────┴──────────────────────────┘  │
│                                                    │
│  窗口: _bg_<uuid1>  →  会话 A 的窗格（隐藏）       │
│  窗口: _bg_<uuid2>  →  会话 B 的窗格（隐藏）       │
│  窗口: _bg_<uuid3>  →  会话 C 的窗格（隐藏）       │
│                                                    │
└────────────────────────────────────────────────────┘
```

- 一个专用 tmux 会话：`task-pilot`。
- `main` 窗口始终持有两个窗格：左侧 pilot，右侧当前可见的 Claude Code 会话。
- 其他每个 Claude Code 会话存活在自己的 `_bg_<uuid>` 窗口里，这些窗口从不展示给用户，但其中的 Claude Code 进程一直在跑。
- 切换会话时，pilot 执行两步 `swap-pane`：第一步把当前窗格送回它的 `_bg_*` 老家窗口；第二步把目标窗格交换进 `main.1`。
- 启动时 pilot 与 tmux 对账：DB 中没有对应 tmux 窗口的行会被删除；tmux 中没有对应 DB 行的 `_bg_*` 窗口会被收养。

## 平台支持

| 平台                                     | 状态              |
|------------------------------------------|-------------------|
| macOS（iTerm2、Terminal.app、Kitty 等）  | 支持              |
| Linux（任何带 tmux 的终端）              | 支持              |
| Windows 上的 WSL2                        | 支持              |
| 通过 SSH 远程 Ubuntu                     | 推荐              |
| VS Code Remote-SSH 集成终端              | 支持              |
| 原生 Windows（PowerShell、CMD、Git Bash）| 不支持 —— 请使用 WSL2 |

## 运行要求

- Python 3.11+
- tmux 3.0+
- `PATH` 中有 Claude Code CLI（`claude`）
- `psutil` Python 包
- 支持 UTF-8 和 256 色的终端（推荐使用 Nerd Font 以正确渲染分隔线与状态图标）

## 开发

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest tests/ -v   # 125+ 测试
```

## 技术栈

- [Python 3.11+](https://www.python.org/)
- [Textual](https://textual.textualize.io/) — 左侧面板的 TUI 框架
- SQLite — 持久化会话状态（`sessions` 和 `pilot_state` 表）
- [tmux](https://github.com/tmux/tmux) 3.0+ — 会话编排与窗格交换
- [psutil](https://github.com/giampaolo/psutil) — 跨平台进程检查，用于定位 Claude Code transcript
- [Click](https://click.palletsprojects.com/) — CLI 入口
