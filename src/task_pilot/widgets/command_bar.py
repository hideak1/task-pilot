from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input


class CommandBar(ModalScreen[str | None]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    CommandBar {
        align: center bottom;
    }
    CommandBar #cmd {
        width: 100%;
        background: #181b22;
        color: #e2e4e9;
    }
    """

    def compose(self) -> ComposeResult:
        yield Input(placeholder=":", id="cmd")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)
