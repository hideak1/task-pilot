<p align="center">
  <strong>Task Pilot</strong><br>
  複数の Claude Code セッションを統括するターミナルダッシュボード
</p>

<p align="center">
  <a href="./README.md">English</a> |
  <a href="./README.zh-CN.md">中文</a> |
  <a href="./README.ja.md">日本語</a>
</p>

---

## Task Pilot とは？

Task Pilot は、ターミナルを離れることなく複数の Claude Code セッションを起動・切り替えできるコントロールパネルです。**tmux** の上に構築されており、`task-pilot` という専用 tmux セッションの中に、左ペイン（pilot の Textual UI）と右ペイン（現在表示中の Claude Code セッション）を持ちます。pilot から起動したそれ以外のすべての Claude Code セッションは、隠された `_bg_<uuid>` ウィンドウ内で、プロセスが通常どおり動作し続けます。

左パネルで別のセッションを選ぶと、pilot は **2 ステップ swap-pane プロトコル**を実行します。ステップ 1 で現在表示中のセッションのペインをその `_bg_*` ホームウィンドウに戻し、ステップ 2 で選択したセッションのペインを右側へ入れ替えます。切り替え中にセッションが kill されたり、切断されたり、再起動されたりすることはありません。

**スコープ（E1）：** pilot が管理するのは、*pilot 内部から作成したセッション*のみです。別のターミナルで起動したセッションは意図的にスコープ外です。

**なぜ書き直したか？** v0.1 は Claude Code hooks + scanner + AI サマライザに依存しており、内側のループでトークンを消費し、しかも Claude と実際に対話するためにはターミナルを切り替える必要がありました。tmux モデルはこの両方を解決します — ホットパスで API 呼び出しゼロ、右ペインは実物の Claude Code TUI で直接入力できます。

## 機能

- **tmux ベースのオーケストレーション** — hooks なし、API 呼び出しなし、トークンコストゼロ
- **リアルタイム更新** — 2 秒ごとに `~/.claude/projects/*.jsonl` から直接読み取り
- **ライブトークンカウント** — 各 transcript を tail で読み、assistant メッセージの `input_tokens + output_tokens` を集計
- **ステータス検出** — `initializing` / `working` / `idle` / `unknown`、すべてローカル transcript の活動から算出
- **セッションごとのコンテキスト** — 各行に作業ディレクトリ（`~` 省略）と git ブランチを表示
- **2 ステップ swap-pane 切替** — 瞬時に視覚的に入れ替え、プロセスは再起動しない
- **マウス + キーボードナビゲーション** — 行クリック、Claude 内でのスクロール、vim 風キーのいずれも対応
- **コマンドバー（`:q`）** — vim 風の終了コマンドで、管理下の全セッションをクリーンに片付け
- **クラッシュ耐性** — pilot は watchdog ラッパーの下で動作、起動時に tmux と照合して孤児ウィンドウを引き取る

## クイックスタート

```bash
uv venv && uv pip install -e .
task-pilot ui      # tmux セッションをブートストラップまたはアタッチ
```

`task-pilot ui` は冪等です：
- `task-pilot` tmux セッションが存在しなければ、2 ペインレイアウトでブートストラップし、左ペインで pilot を起動します。
- 既に存在すれば、`task-pilot ui` はそのセッションにアタッチします。
- *別の* tmux セッション内から実行した場合、pilot は静かに誤動作する代わりに実行可能なガイダンスを表示します。

## キーバインド

| キー               | アクション                                                         |
|--------------------|--------------------------------------------------------------------|
| `j` / `k` / `↑` / `↓` | 左パネルで選択を移動                                           |
| `Enter`            | 選択したセッションへ切替（2 ステップ swap-pane）、右ペインにフォーカス |
| `Tab`              | 左パネルと右ペインの間でフォーカスを切替                           |
| `n`                | 新規セッション — 最近ディレクトリと Tab 補完つきダイアログを開く   |
| `x`                | 選択セッションを閉じる（確認あり）                                 |
| `r`                | 強制更新（git ブランチと transcript パスも再解決）                 |
| `/`                | タイトルや cwd の部分一致で行をフィルタ                            |
| `:`                | コマンドバーを開く                                                 |
| `:q` + `Enter`     | pilot を終了し、管理下の全 Claude Code プロセスを kill             |

単独の `q` 終了キーは意図的に用意していません。`:q` は誤入力しづらいため、確認ダイアログは不要です。

## アーキテクチャ

```
┌─── tmux セッション: task-pilot ─────────────────────┐
│                                                    │
│  ウィンドウ: main                                  │
│  ┌──────────────────┬──────────────────────────┐  │
│  │                  │                          │  │
│  │  pilot (Textual) │  Claude Code セッション   │  │
│  │  左リスト        │  （現在選択中）            │  │
│  │                  │                          │  │
│  └──────────────────┴──────────────────────────┘  │
│                                                    │
│  ウィンドウ: _bg_<uuid1>  → セッション A のペイン │
│  ウィンドウ: _bg_<uuid2>  → セッション B のペイン │
│  ウィンドウ: _bg_<uuid3>  → セッション C のペイン │
│                                                    │
└────────────────────────────────────────────────────┘
```

- 専用 tmux セッションは `task-pilot` ひとつ。
- `main` ウィンドウは常に 2 ペイン構成：左は pilot、右は現在表示中の Claude Code セッション。
- それ以外のセッションは自分の `_bg_<uuid>` ウィンドウに存在し、表示はされないものの Claude Code プロセスは動作し続けます。
- セッション切替時、pilot は 2 ステップ `swap-pane` を実行します。ステップ 1 で現在のペインを `_bg_*` ホームに戻し、ステップ 2 で対象ペインを `main.1` に入れ替えます。
- 起動時、pilot は tmux と状態を照合します。tmux ウィンドウが失われた DB 行は削除、DB 行のない `_bg_*` ウィンドウは引き取ります。

## プラットフォームサポート

| プラットフォーム                          | ステータス        |
|------------------------------------------|-------------------|
| macOS（iTerm2、Terminal.app、Kitty など）| サポート          |
| Linux（tmux が動く任意のターミナル）     | サポート          |
| Windows 上の WSL2                        | サポート          |
| SSH 経由のリモート Ubuntu                | 推奨              |
| VS Code Remote-SSH 統合ターミナル        | サポート          |
| Windows ネイティブ（PowerShell、CMD、Git Bash）| 非対応 — WSL2 を使用 |

## 必要要件

- Python 3.11+
- tmux 3.0+
- `PATH` 上の Claude Code CLI（`claude`）
- `psutil` Python パッケージ
- UTF-8 と 256 色に対応したターミナル（行区切りやステータスアイコンのために Nerd Font 推奨）

## 開発

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest tests/ -v   # 125+ テスト
```

## 技術スタック

- [Python 3.11+](https://www.python.org/)
- [Textual](https://textual.textualize.io/) — 左パネルの TUI フレームワーク
- SQLite — セッションの永続状態（`sessions` と `pilot_state` テーブル）
- [tmux](https://github.com/tmux/tmux) 3.0+ — セッションオーケストレーションとペイン入替
- [psutil](https://github.com/giampaolo/psutil) — クロスプラットフォームなプロセス検査で Claude Code transcript を特定
- [Click](https://click.palletsprojects.com/) — CLI エントリポイント
