from typing import Callable
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input


class SearchBar(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    DEFAULT_CSS = """
    SearchBar { align: center bottom; }
    SearchBar #q {
        width: 100%;
        background: #181b22;
        border: solid #74c0fc;
    }
    """

    def __init__(self, on_change: Callable[[str], None], on_close: Callable[[], None]) -> None:
        super().__init__()
        self._on_change = on_change
        self._on_close = on_close

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search...", id="q")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._on_change(event.value)

    def action_close(self) -> None:
        self._on_close()
        self.dismiss(None)
