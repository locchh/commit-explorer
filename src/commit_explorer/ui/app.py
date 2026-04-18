"""Root Textual application: CommitExplorer."""

from __future__ import annotations

import asyncio
import re
import webbrowser
from typing import Optional

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import (
    Button, Footer, Header, Input, ListView, LoadingIndicator, Select, Static,
)

from ..backend import GitBackend
from ..providers import get_providers
from ..utils import fmt_date
from .compare import CompareScreen
from .widgets import CommitItem, GraphSplitter, Splitter


class CommitExplorer(App):
    TITLE = "Commit Explorer"
    CSS = """
    #toolbar {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        background: $panel;
    }
    #provider-select { width: 20; margin-right: 1; }
    #repo-input { width: 1fr; margin-right: 1; }
    #load-btn   { width: 8; }

    #main { height: 1fr; layout: horizontal; }

    #left {
        width: 50%;
    }
    #repo-info {
        height: auto;
        padding: 1 2;
        background: $panel;
        border-bottom: solid $primary-darken-2;
        display: none;
    }
    #spinner     { height: 3; display: none; }
    #commits-list { height: 1fr; }
    #more-btn    { height: 3; dock: bottom; }

    CommitItem        { padding: 0 0; height: auto; }
    CommitItem:hover  { background: $boost; }
    .commit-row       { height: auto; }
    .graph-col        { width: auto; min-width: 2; padding: 0 1 0 0; }
    .info-col         { width: 1fr; padding: 0 1; }

    #right        { width: 1fr; }
    #open-btn     { margin: 1 2 0 2; width: auto; }
    #right-scroll { height: 1fr; padding: 1 2; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("n", "more", "Next page"),
        Binding("c", "compare", "Compare"),
    ]

    _REPO_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")

    def __init__(self, initial_repo: str = "", depth: Optional[int] = None) -> None:
        super().__init__()
        self._initial_repo = initial_repo
        self._owner = ""
        self._repo = ""
        self._current_sha: str = ""
        self._graph_col_width: int = 20
        self._depth = depth
        self._backend = GitBackend()
        self.providers = get_providers()
        self.current_provider = self.providers["github"]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="toolbar"):
            yield Select(
                [(p.name, k) for k, p in self.providers.items()],
                value="github",
                id="provider-select",
                allow_blank=False,
            )
            yield Input(
                placeholder="owner/repo (e.g. paperclipai/paperclip)",
                id="repo-input",
            )
            yield Button("Load", id="load-btn", variant="primary")

        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("", id="repo-info")
                yield LoadingIndicator(id="spinner")
                yield ListView(id="commits-list")
                yield Button("Load more  ↓", id="more-btn")
                yield GraphSplitter()
            yield Splitter()
            with Vertical(id="right"):
                yield Button(
                    "⎋  Open in browser", id="open-btn",
                    variant="default", disabled=True,
                )
                with ScrollableContainer(id="right-scroll"):
                    yield Static(
                        "[dim]Select a commit to see details.[/dim]", id="detail",
                    )
        yield Footer()

    def _set_graph_col_width(self, width: int) -> None:
        self._graph_col_width = width

    def on_mount(self) -> None:
        self.query_one("#spinner").display = False
        if self._initial_repo:
            self.query_one("#repo-input", Input).value = self._initial_repo
            self._trigger_load()

    @on(Select.Changed, "#provider-select")
    def on_provider_changed(self, event: Select.Changed) -> None:
        self.current_provider = self.providers[str(event.value)]
        self.query_one("#commits-list", ListView).clear()
        self.query_one("#repo-info", Static).display = False

    @on(Input.Submitted, "#repo-input")
    def on_input_submitted(self) -> None:
        self._trigger_load()

    @on(Button.Pressed, "#load-btn")
    def on_load_pressed(self) -> None:
        self._trigger_load()

    @on(Button.Pressed, "#more-btn")
    def on_more_pressed(self) -> None:
        self._load_more()

    @on(Button.Pressed, "#open-btn")
    def on_open_pressed(self) -> None:
        if self._current_sha and self._owner:
            url = self.current_provider.commit_url(
                self._owner, self._repo, self._current_sha
            )
            webbrowser.open(url)

    @on(ListView.Selected, "#commits-list")
    def on_commit_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, CommitItem):
            self._fetch_detail(event.item.commit.sha)

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "compare":
            return bool(self._owner)
        return True

    def action_compare(self) -> None:
        if self._owner:
            self.push_screen(CompareScreen(
                self._backend,
                owner=self._owner,
                repo=self._repo,
                provider=self.current_provider,
            ))

    def action_reload(self) -> None:
        if self._owner:
            self._fetch_commits(replace=True)

    def action_more(self) -> None:
        self._load_more()

    def _trigger_load(self) -> None:
        val = self.query_one("#repo-input", Input).value.strip()
        if "/" not in val:
            self.notify("Format: owner/repo (Azure: project/repo)", severity="warning")
            return

        parts = val.split("/", 1)
        owner, repo = parts[0].strip(), parts[1].strip()
        if not owner or not repo or not self._REPO_RE.match(f"{owner}/{repo}"):
            self.notify(
                "Invalid owner/repo — use alphanumeric, hyphens, dots only",
                severity="warning",
            )
            return

        self._owner, self._repo = owner, repo
        self._fetch_commits(replace=True)

    def _load_more(self) -> None:
        if self._owner and self._backend.has_more():
            self._fetch_commits(replace=False)

    @work
    async def _fetch_commits(self, replace: bool) -> None:
        spinner = self.query_one("#spinner")
        spinner.display = True
        more_btn = self.query_one("#more-btn", Button)
        more_btn.display = False

        try:
            if replace:
                url = self.current_provider.clone_url(self._owner, self._repo)
                await self._backend.load(url, depth=self._depth)

                info = self._backend.get_repo_info()
                repo_widget = self.query_one("#repo-info", Static)
                lines = [
                    f"[bold]{escape(self._owner)}/[white]{escape(self._repo)}[/white][/bold]"
                ]
                meta = []
                if info.default_branch:
                    meta.append(f"default: [magenta]{escape(info.default_branch)}[/magenta]")
                if info.branches is not None:
                    meta.append(f"{info.branches:,} branches")
                if info.total_commits is not None:
                    label = f"~{info.total_commits:,} commits"
                    if self._depth:
                        label += f" (depth {self._depth})"
                    meta.append(label)
                if meta:
                    lines.append("[dim]" + "  ·  ".join(meta) + "[/dim]")
                repo_widget.update("\n".join(lines))
                repo_widget.display = True

                lv = self.query_one("#commits-list", ListView)
                await lv.clear()

            page = self._backend.next_page()
            if not page:
                self.notify("No commits found.", severity="information")
                return

            lv = self.query_one("#commits-list", ListView)
            for commit, graph_lines in page:
                await lv.append(CommitItem(commit, graph_lines))

            more_btn.display = self._backend.has_more()

        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
        finally:
            spinner.display = False

    @work
    async def _fetch_detail(self, sha: str) -> None:
        self._current_sha = sha
        self.query_one("#open-btn", Button).disabled = True
        detail_widget = self.query_one("#detail", Static)
        detail_widget.update("[dim]Loading details…[/dim]")

        try:
            d = await asyncio.to_thread(self._backend.get_detail, sha)
            self.query_one("#open-btn", Button).disabled = False

            lines = [
                f"[bold yellow]SHA[/bold yellow]     {d.info.sha}",
                f"[bold yellow]Author[/bold yellow]  {d.info.author} <{d.info.author_email}>",
                f"[bold yellow]Date[/bold yellow]    {fmt_date(d.info.date)}",
                f"[bold yellow]Parents[/bold yellow] {', '.join(d.info.parents)}",
            ]

            if d.stats:
                lines.append(
                    f"[bold yellow]Stats[/bold yellow]   "
                    f"[green]+{d.stats.get('additions', 0)}[/green]  "
                    f"[red]-{d.stats.get('deletions', 0)}[/red]  "
                    f"[dim]({d.stats.get('total', 0)} changes)[/dim]"
                )

            lines.extend([
                "",
                "[bold cyan]── Message ──────────────────────────────────────[/bold cyan]",
                escape(d.info.message),
                "",
            ])

            if d.files:
                lines.append(
                    f"[bold cyan]── Files Changed ({len(d.files)}) ────────────────────────[/bold cyan]"
                )
                for f in d.files[:60]:
                    color = "white"
                    if f.status == "added":
                        color = "green"
                    elif f.status == "removed":
                        color = "red"
                    elif f.status == "modified":
                        color = "yellow"
                    elif f.status == "renamed":
                        color = "blue"
                    stats = ""
                    if f.additions or f.deletions:
                        stats = f"[dim](+{f.additions} -{f.deletions})[/dim]"
                    lines.append(
                        f"  [{color}]{f.status[0].upper()}[/{color}] "
                        f"{escape(f.filename)}  {stats}"
                    )
                if len(d.files) > 60:
                    lines.append(f"  [dim]… and {len(d.files) - 60} more[/dim]")
                lines.append("")

            detail_widget.update("\n".join(lines))

        except Exception as e:
            detail_widget.update(f"[red]Error: {e}[/red]")
