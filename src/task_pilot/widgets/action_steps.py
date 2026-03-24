from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from task_pilot.models import ActionItem


class ActionStepRow(Widget, can_focus=True):
    """A single action step with toggle support."""

    class Toggled(Message):
        def __init__(self, item_id: int) -> None:
            self.item_id = item_id
            super().__init__()

    DEFAULT_CSS = """
    ActionStepRow {
        height: 2;
        padding: 0 1;
        layout: horizontal;
    }
    ActionStepRow .step-number {
        width: 4;
        min-width: 4;
        color: #ffd43b;
        text-style: bold;
        padding: 0 0;
    }
    ActionStepRow .step-text {
        width: 1fr;
        color: #e2e4e9;
    }
    ActionStepRow .step-done .step-text {
        color: #555869;
        text-style: strike;
    }
    ActionStepRow .step-check {
        width: 4;
        min-width: 4;
    }
    """

    def __init__(self, item: ActionItem, index: int) -> None:
        super().__init__()
        self.item = item
        self.index = index

    def compose(self) -> ComposeResult:
        check = "[#69db7c]✓[/]" if self.item.is_done else "[#555869]○[/]"
        yield Static(check, classes="step-check")
        num = f"{self.index + 1}."
        yield Static(num, classes="step-number")
        text_style = f"[#555869 strike]{self.item.description}[/]" if self.item.is_done else self.item.description
        cmd_hint = f"\n   [#555869]$ {self.item.command}[/]" if self.item.command and not self.item.is_done else ""
        yield Static(text_style + cmd_hint, classes="step-text")

    def on_click(self) -> None:
        self.post_message(self.Toggled(self.item.id))

    def key_space(self) -> None:
        self.post_message(self.Toggled(self.item.id))


class ActionSteps(Widget):
    """Action steps checklist card."""

    DEFAULT_CSS = """
    ActionSteps {
        background: #111318;
        border: solid #181b22;
        margin: 1 2;
        padding: 1 1;
    }
    ActionSteps .card-title {
        color: #ffd43b;
        text-style: bold;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, items: list[ActionItem]) -> None:
        super().__init__()
        self.items = items

    def compose(self) -> ComposeResult:
        done = sum(1 for i in self.items if i.is_done)
        total = len(self.items)
        yield Static(f"操作步骤 ({done}/{total})", classes="card-title")
        for idx, item in enumerate(self.items):
            yield ActionStepRow(item, idx)
