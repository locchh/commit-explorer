"""Small reusable Textual widgets: commit row, splitters."""

from __future__ import annotations

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label, ListItem

from ..models import CommitInfo
from ..utils import fmt_date


class GraphSplitter(Widget):
    """Horizontal drag bar at the bottom of the left panel to resize the graph column."""

    DEFAULT_CSS = """
    GraphSplitter {
        height: 1;
        background: $primary-darken-2;
        color: $text-muted;
        content-align: center middle;
    }
    GraphSplitter:hover {
        background: $accent;
        color: $text;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_width = 8

    def render(self) -> str:
        w = getattr(self.app, "_graph_col_width", 8)
        return f"◁  graph: {w}  ▷"

    def on_mouse_down(self, event) -> None:
        self._dragging = True
        self._drag_start_x = event.screen_x
        self._drag_start_width = getattr(self.app, "_graph_col_width", 8)
        self.capture_mouse()
        event.stop()

    def on_mouse_up(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.release_mouse()
            event.stop()

    def on_mouse_move(self, event) -> None:
        if self._dragging:
            delta = event.screen_x - self._drag_start_x
            new_width = max(4, min(60, self._drag_start_width + delta))
            self.app._set_graph_col_width(new_width)
            self.refresh()
            event.stop()


class Splitter(Widget):
    """Draggable vertical splitter between two panels."""

    DEFAULT_CSS = """
    Splitter {
        width: 1;
        height: 100%;
        background: $primary-darken-2;
    }
    Splitter:hover {
        background: $accent;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._dragging = False

    def render(self) -> str:
        return ""

    def on_mouse_down(self, event) -> None:
        self._dragging = True
        self.capture_mouse()
        event.stop()

    def on_mouse_up(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.release_mouse()
            event.stop()

    def on_mouse_move(self, event) -> None:
        if self._dragging:
            main = self.app.query_one("#main")
            total = main.size.width
            if total > 0:
                rel_x = event.screen_x - main.region.x
                pct = max(15, min(85, int((rel_x / total) * 100)))
                self.app.query_one("#left").styles.width = f"{pct}%"
            event.stop()


class CommitItem(ListItem):
    def __init__(self, commit: CommitInfo, graph_lines: list[Text]) -> None:
        super().__init__()
        self.commit = commit
        self.graph_lines = graph_lines

    def compose(self) -> ComposeResult:
        sha = self.commit.short_sha
        msg_text = escape(self.commit.message.split("\n")[0].strip())
        who = escape(self.commit.author)
        date = fmt_date(self.commit.date)[:10]

        graph_text = Text()
        for i, line in enumerate(self.graph_lines):
            if i:
                graph_text.append("\n")
            graph_text.append_text(line)
        graph_height = len(self.graph_lines)

        info_cell = f"[bold]{msg_text}[/bold]  [cyan]{sha}[/cyan]  [dim]{date}  {who}[/dim]"
        info_cell += "\n" * max(0, graph_height - 1)

        with Horizontal(classes="commit-row"):
            yield Label(graph_text, classes="graph-col")
            yield Label(info_cell, classes="info-col", markup=True)
