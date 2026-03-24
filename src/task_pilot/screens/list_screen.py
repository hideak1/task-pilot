from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widget import Widget
from textual.widgets import Input, Static

from task_pilot.db import Database
from task_pilot.models import Task
from task_pilot.widgets.header_bar import HeaderBar
from task_pilot.widgets.task_row import TaskRow


class ListScreen(Widget):
    """Main list view with 3 sections: action_required, working, done."""

    DEFAULT_CSS = """
    ListScreen {
        height: 1fr;
        width: 1fr;
    }
    ListScreen #search-bar {
        height: 3;
        background: #181b22;
        border-bottom: solid #181b22;
        padding: 0 2;
        display: none;
    }
    ListScreen #search-bar.visible {
        display: block;
    }
    ListScreen #search-input {
        background: #111318;
        color: #e2e4e9;
        border: solid #74c0fc;
    }
    ListScreen .section-label {
        height: 1;
        padding: 0 2;
        text-style: bold;
        margin-top: 1;
    }
    ListScreen .section-label-action {
        color: #ff6b6b;
    }
    ListScreen .section-label-working {
        color: #69db7c;
    }
    ListScreen .section-label-done {
        color: #555869;
    }
    ListScreen .empty-hint {
        color: #555869;
        padding: 1 4;
        text-style: italic;
    }
    """

    BINDINGS = [
        ("slash", "toggle_search", "Search"),
        ("escape", "close_search", "Close Search"),
        ("n", "new_task", "New Task"),
    ]

    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db
        self._search_query = ""

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="search-bar"):
            yield Input(placeholder="Search tasks...", id="search-input")
        with ScrollableContainer(id="task-list"):
            yield Static("Loading...", id="loading-hint")

    def on_mount(self) -> None:
        self.refresh_tasks()
        self.set_interval(5, self.refresh_tasks)

    def refresh_tasks(self) -> None:
        all_tasks = self._db.list_tasks()

        if self._search_query:
            q = self._search_query.lower()
            all_tasks = [t for t in all_tasks if q in t.title.lower()]

        action_tasks = [t for t in all_tasks if t.status == "action_required"]
        working_tasks = [t for t in all_tasks if t.status == "working"]
        done_tasks = [t for t in all_tasks if t.status == "done"]
        pending_tasks = [t for t in all_tasks if t.status == "pending"]

        # Update header stats
        try:
            header = self.query_one(HeaderBar)
            header.update_counts(
                action=len(action_tasks),
                working=len(working_tasks),
                done=len(done_tasks),
            )
        except Exception:
            pass

        container = self.query_one("#task-list", ScrollableContainer)
        container.remove_children()

        if action_tasks:
            container.mount(
                Static(f"  需要你操作 ({len(action_tasks)})", classes="section-label section-label-action")
            )
            for task in action_tasks:
                container.mount(TaskRow(task))

        if working_tasks:
            container.mount(
                Static(f"  Claude 工作中 ({len(working_tasks)})", classes="section-label section-label-working")
            )
            for task in working_tasks:
                container.mount(TaskRow(task))

        if pending_tasks:
            container.mount(
                Static(f"  等待中 ({len(pending_tasks)})", classes="section-label section-label-working")
            )
            for task in pending_tasks:
                container.mount(TaskRow(task))

        if done_tasks:
            container.mount(
                Static(f"  已完成 ({len(done_tasks)})", classes="section-label section-label-done")
            )
            for task in done_tasks:
                container.mount(TaskRow(task))

        if not all_tasks:
            container.mount(
                Static("No tasks yet. Run 'task-pilot scan' or start a Claude Code session.", classes="empty-hint")
            )

    def action_toggle_search(self) -> None:
        search_bar = self.query_one("#search-bar")
        search_bar.toggle_class("visible")
        if search_bar.has_class("visible"):
            self.query_one("#search-input", Input).focus()

    def action_close_search(self) -> None:
        search_bar = self.query_one("#search-bar")
        search_bar.remove_class("visible")
        self._search_query = ""
        self.refresh_tasks()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._search_query = event.value
            self.refresh_tasks()

    def on_task_row_selected(self, event: TaskRow.Selected) -> None:
        from task_pilot.screens.detail_screen import DetailScreen

        self.app.push_screen(DetailScreen(self._db, event.task_id))
