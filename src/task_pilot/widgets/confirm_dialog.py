from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        ("y", "yes", "Yes"),
        ("n,escape", "no", "No"),
    ]

    DEFAULT_CSS = """
    ConfirmDialog { align: center middle; }
    ConfirmDialog #box {
        background: #181b22;
        border: solid #ff6b6b;
        padding: 1 2;
        width: 60;
        height: 8;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(self.message)
            yield Label("[y] Yes   [n] No")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
