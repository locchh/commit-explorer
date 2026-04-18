"""Branch/PR comparison modal screen."""

from __future__ import annotations

import asyncio
from typing import Optional

from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button, Footer, Header, Input, LoadingIndicator, Static,
)

from ..backend import GitBackend
from ..export import write_export
from ..models import BranchComparison, PRMetadata
from ..pr import add_fork_remote, resolve_pr_url
from ..providers import GitHubProvider, GitLabProvider, GitProvider


class CompareScreen(Screen):
    """Modal screen for comparing two remote branches."""

    BINDINGS = [Binding("escape", "dismiss", "Back")]

    CSS = """
    CompareScreen {
        background: $surface;
    }
    #compare-toolbar {
        height: 8;
        padding: 1;
        background: $panel;
        layout: vertical;
    }
    #pr-row        { layout: horizontal; height: 3; }
    #branch-row    { layout: horizontal; height: 3; }
    #pr-input      { width: 1fr; margin-right: 1; }
    #pr-btn        { width: 14; }
    #base-input    { width: 1fr; margin-right: 1; }
    #target-input  { width: 1fr; margin-right: 1; }
    #compare-btn   { width: 12; }
    #export-btn    { width: 12; margin-left: 1; }
    #compare-spinner { height: 3; display: none; }
    #compare-scroll  { height: 1fr; padding: 1 2; }
    """

    def __init__(
        self,
        backend: GitBackend,
        owner: str = "",
        repo: str = "",
        provider: Optional[GitProvider] = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._owner = owner
        self._repo = repo
        self._provider = provider
        self._last_result: Optional[BranchComparison] = None
        self._last_pr: Optional[PRMetadata] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="compare-toolbar"):
            with Horizontal(id="pr-row"):
                yield Input(placeholder="PR/MR number (e.g. 123)", id="pr-input")
                yield Button("Fill branches", id="pr-btn")
            with Horizontal(id="branch-row"):
                yield Input(placeholder="Base branch (e.g. main)", id="base-input")
                yield Input(placeholder="Target branch (e.g. feature/foo)", id="target-input")
                yield Button("Compare", id="compare-btn", variant="primary")
                yield Button("Export", id="export-btn", disabled=True)
        yield LoadingIndicator(id="compare-spinner")
        with ScrollableContainer(id="compare-scroll"):
            yield Static(
                "[dim]Enter branch names or a PR/MR URL and press Compare.[/dim]",
                id="compare-results",
            )
        yield Footer()

    @on(Input.Submitted, "#pr-input")
    @on(Button.Pressed, "#pr-btn")
    def on_pr_submitted(self) -> None:
        self._run_pr_resolve()

    @on(Input.Submitted, "#base-input")
    @on(Input.Submitted, "#target-input")
    def on_input_submitted(self) -> None:
        self._run_comparison()

    @on(Button.Pressed, "#compare-btn")
    def on_compare_pressed(self) -> None:
        self._run_comparison()

    @on(Button.Pressed, "#export-btn")
    def on_export_pressed(self) -> None:
        if self._last_result is not None:
            try:
                path = write_export(self._last_result, pr_meta=self._last_pr)
                self.notify(f"Exported to {path}")
            except Exception as e:
                self.notify(f"Export failed: {e}", severity="error")

    def _build_pr_url(self, number: str) -> str:
        if not self._owner or not self._repo or not self._provider:
            raise ValueError("No repo loaded — cannot resolve PR number.")
        if isinstance(self._provider, GitHubProvider):
            return f"https://github.com/{self._owner}/{self._repo}/pull/{number}"
        if isinstance(self._provider, GitLabProvider):
            return f"{self._provider.host}/{self._owner}/{self._repo}/-/merge_requests/{number}"
        raise ValueError("PR number shortcut only supported for GitHub and GitLab.")

    @work
    async def _run_pr_resolve(self) -> None:
        raw = self.query_one("#pr-input", Input).value.strip()
        if not raw:
            self.notify("Enter a PR/MR number.", severity="warning")
            return
        try:
            url = self._build_pr_url(raw) if raw.isdigit() else raw
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        spinner = self.query_one("#compare-spinner")
        spinner.display = True
        try:
            pr = await asyncio.to_thread(resolve_pr_url, url)
            self._last_pr = pr
            is_cross_fork = pr.head_owner.lower() != pr.owner.lower()
            head_ref = pr.head
            if is_cross_fork and pr.head_clone_url:
                await asyncio.to_thread(
                    add_fork_remote, self._backend.tmpdir, pr.head_clone_url, pr.head
                )
                head_ref = f"pr-head/{pr.head}"
            self.query_one("#base-input", Input).value = pr.base
            self.query_one("#target-input", Input).value = head_ref
            self.notify(f"#{pr.number}: {pr.title[:60]}  [{pr.state}]")
            self._run_comparison()
        except Exception as e:
            self.notify(f"PR resolve failed: {e}", severity="error")
        finally:
            spinner.display = False

    @work
    async def _run_comparison(self) -> None:
        base = self.query_one("#base-input", Input).value.strip()
        target = self.query_one("#target-input", Input).value.strip()

        if not base or not target:
            self.notify("Enter both branch names.", severity="warning")
            return

        spinner = self.query_one("#compare-spinner")
        spinner.display = True
        results = self.query_one("#compare-results", Static)
        results.update("[dim]Comparing…[/dim]")
        self.query_one("#export-btn", Button).disabled = True

        try:
            result = await asyncio.to_thread(
                self._backend.compare_branches, base, target
            )
            self._last_result = result
            self.query_one("#export-btn", Button).disabled = False
            results.update(self._render_comparison(result))
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
            results.update(f"[red]Error: {escape(str(e))}[/red]")
        finally:
            spinner.display = False

    def _render_comparison(self, result: BranchComparison) -> str:
        lines: list[str] = []

        if result.shallow_warning:
            lines.append(
                "[bold yellow]\u26a0 Shallow clone \u2014 "
                "commit log and conflict results may be incomplete[/bold yellow]"
            )
            lines.append("")

        if self._last_pr:
            pr = self._last_pr
            lines.append(
                f"[bold]PR [cyan]#{pr.number}[/cyan]: {escape(pr.title)}[/bold]  "
                f"[dim]{escape(pr.author)}  |  {pr.state}[/dim]"
            )
            if pr.description.strip():
                lines.append("")
                for dl in pr.description.strip().splitlines()[:20]:
                    lines.append(f"  [dim]{escape(dl)}[/dim]")
                if pr.description.strip().count("\n") >= 20:
                    lines.append("  [dim]\u2026 (see export for full description)[/dim]")
            lines.append("")

        lines.append(
            f"[bold]Compare: [cyan]origin/{escape(result.base)}[/cyan]"
            f" \u2192 [cyan]origin/{escape(result.target)}[/cyan][/bold]"
        )
        lines.append("")

        bar = "\u2500" * 30
        lines.append(f"[bold cyan]\u2500\u2500 Diff Summary {bar}[/bold cyan]")
        lines.append(
            escape(result.stat_summary)
            if result.stat_summary
            else "[dim]No differences.[/dim]"
        )
        lines.append("")

        lines.append(
            f"[bold cyan]\u2500\u2500 Changed Files ({len(result.file_changes)}) {bar}[/bold cyan]"
        )
        if result.file_changes:
            for fc in result.file_changes:
                color = {"added": "green", "removed": "red"}.get(fc.status, "yellow")
                stats = f"[dim](+{fc.additions} -{fc.deletions})[/dim]"
                lines.append(
                    f"  [{color}]{fc.status[0].upper()}[/{color}] "
                    f"{escape(fc.filename)}  {stats}"
                )
        else:
            lines.append("[dim]No file changes.[/dim]")
        lines.append("")

        lines.append(
            f"[bold cyan]\u2500\u2500 Commits ({len(result.unique_commits)}) {bar}[/bold cyan]"
        )
        if result.unique_commits:
            for c in result.unique_commits:
                lines.append(
                    f"  [cyan]{c.short_sha}[/cyan]  {escape(c.message)}"
                    f"  [dim]{escape(c.author)}  {c.date}[/dim]"
                )
        else:
            lines.append("[dim]No unique commits.[/dim]")
        lines.append("")

        lines.append(f"[bold cyan]\u2500\u2500 Conflicts {bar}[/bold cyan]")
        if not result.conflicts:
            lines.append("[green]\u2713 Clean merge \u2014 no conflicts detected[/green]")
        else:
            lines.append(
                f"[bold red]\u26a0 {len(result.conflicts)} conflicting file(s) "
                "\u2014 see export for full details[/bold red]"
            )
            for cf in result.conflicts:
                lines.append(f"  [red]\u2717[/red] {escape(cf.filename)}")

        return "\n".join(lines)
