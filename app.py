#!/usr/bin/env python3
"""Commit Explorer — Interactive TUI for exploring git repository history."""

import asyncio
import os
import re
import shutil
import sys
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import NamedTuple, Optional
from urllib.parse import quote

import webbrowser
from dotenv import load_dotenv
from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widget import Widget
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Select,
    Static,
)

load_dotenv(override=True)

# ── Types ─────────────────────────────────────────────────────────────────────

class CommitInfo(NamedTuple):
    sha: str
    short_sha: str
    message: str
    author: str
    author_email: str
    date: str  # ISO format
    parents: list[str]

class FileChange(NamedTuple):
    filename: str
    status: str  # added, modified, removed, renamed, etc.
    additions: int
    deletions: int

class CommitDetail(NamedTuple):
    info: CommitInfo
    stats: dict[str, int]
    files: list[FileChange]
    refs: list[str]  # issue refs
    linked_prs: list[dict] # simplified PR info

class RepoInfo(NamedTuple):
    description: str
    created_at: str
    default_branch: str
    language: str
    stars: int
    forks: int
    open_issues: int
    branches: Optional[int]
    total_commits: Optional[int]

# ── Providers (URL builders only) ─────────────────────────────────────────────

class GitProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def clone_url(self, owner: str, repo: str) -> str:
        """Return the git clone URL."""
        pass

    @abstractmethod
    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        """Return a browser URL for the given commit."""
        pass


class GitHubProvider(GitProvider):
    @property
    def name(self) -> str:
        return "GitHub"

    def clone_url(self, owner: str, repo: str) -> str:
        token = os.getenv("GITHUB_TOKEN", "")
        creds = f"{token}@" if token else ""
        return f"https://{creds}github.com/{quote(owner, safe='')}/{quote(repo, safe='')}.git"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"https://github.com/{owner}/{repo}/commit/{sha}"


class GitLabProvider(GitProvider):
    def __init__(self) -> None:
        base = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")
        if "/api/" in base:
            base = base.split("/api/")[0]
        self._host = base

    @property
    def name(self) -> str:
        return "GitLab"

    def clone_url(self, owner: str, repo: str) -> str:
        token = os.getenv("GITLAB_TOKEN", "")
        creds = f"oauth2:{token}@" if token else ""
        host_no_scheme = re.sub(r'^https?://', '', self._host)
        scheme = "https://" if self._host.startswith("https") else "http://"
        return f"{scheme}{creds}{host_no_scheme}/{quote(owner, safe='')}/{quote(repo, safe='')}.git"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"{self._host}/{owner}/{repo}/-/commit/{sha}"


class AzureDevOpsProvider(GitProvider):
    def __init__(self) -> None:
        self._org = os.getenv("AZURE_DEVOPS_ORG", "")

    @property
    def name(self) -> str:
        return "Azure DevOps"

    def clone_url(self, owner: str, repo: str) -> str:
        token = os.getenv("AZURE_DEVOPS_TOKEN", "")
        creds = f":{token}@" if token else ""
        return f"https://{creds}dev.azure.com/{self._org}/{quote(owner, safe='')}/{quote(repo, safe='')}/_git/{quote(repo, safe='')}"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"https://dev.azure.com/{self._org}/{owner}/_git/{repo}/commit/{sha}"


# ── Git Backend (Dulwich) ──────────────────────────────────────────────────────

class _GitBackend:
    """Bare-clone git backend using Dulwich. Stores the clone in a temp dir."""

    _PER_PAGE = 30

    def __init__(self) -> None:
        self._tmpdir: Optional[str] = None
        self._commits: list[CommitInfo] = []
        self._graph_data: list[tuple[CommitInfo, list]] = []
        self._shown: int = 0

    @property
    def all_commits(self) -> list[CommitInfo]:
        return self._commits

    @property
    def graph_data(self) -> list[tuple[CommitInfo, list]]:
        return self._graph_data

    @property
    def shown(self) -> int:
        return self._shown

    def has_more(self) -> bool:
        return self._shown < len(self._graph_data)

    def next_page(self) -> list[tuple[CommitInfo, list]]:
        end = min(self._shown + self._PER_PAGE, len(self._graph_data))
        page = self._graph_data[self._shown:end]
        self._shown = end
        return page

    async def load(self, url: str, depth: Optional[int] = None) -> None:
        self.cleanup()
        self._tmpdir = tempfile.mkdtemp(prefix="cex-")

        def _do_clone() -> None:
            import io
            from dulwich import porcelain
            porcelain.clone(
                url,
                target=self._tmpdir,
                depth=depth,
                bare=True,
                filter_spec="blob:none",  # skip file contents — commits+trees only
                errstream=io.BytesIO(),
            )

        await asyncio.to_thread(_do_clone)
        self._graph_data = await asyncio.to_thread(_build_graph_from_git, self._tmpdir)
        self._commits = [c for c, _ in self._graph_data]
        self._shown = 0

    def _extract_commits(self) -> list[CommitInfo]:
        from dulwich.repo import Repo
        from dulwich.walk import ORDER_DATE

        repo = Repo(self._tmpdir)
        heads: list[bytes] = []
        for ref, sha in repo.refs.as_dict().items():
            if ref.startswith(b"refs/heads/") or ref.startswith(b"refs/remotes/"):
                heads.append(sha)
        if not heads:
            try:
                heads = [repo.head()]
            except Exception:
                pass
        if not heads:
            return []

        commits: list[CommitInfo] = []
        seen: set[str] = set()
        for entry in repo.get_walker(include=list(set(heads)), order=ORDER_DATE):
            c = entry.commit
            sha = c.id.decode()
            if sha in seen:
                continue
            seen.add(sha)

            parents = [p.decode() for p in c.parents]
            msg = c.message.decode("utf-8", errors="replace").strip().split("\n")[0]

            author_raw = c.author.decode("utf-8", errors="replace")
            m = re.match(r"^(.*?)\s*<(.*)>$", author_raw)
            author = m.group(1).strip() if m else author_raw
            email  = m.group(2).strip() if m else ""

            dt = datetime.fromtimestamp(
                c.author_time,
                tz=timezone(timedelta(seconds=c.author_timezone)),
            )
            commits.append(CommitInfo(
                sha=sha, short_sha=sha[:7],
                message=msg, author=author, author_email=email,
                date=dt.isoformat(), parents=parents,
            ))
        return commits

    def get_detail(self, sha: str) -> "CommitDetail":
        import difflib
        from dulwich.repo import Repo
        from dulwich.diff_tree import tree_changes, CHANGE_ADD, CHANGE_DELETE, CHANGE_RENAME

        repo = Repo(self._tmpdir)
        c = repo[sha.encode()]

        parents = [p.decode() for p in c.parents]
        msg_full = c.message.decode("utf-8", errors="replace").strip()
        author_raw = c.author.decode("utf-8", errors="replace")
        m = re.match(r"^(.*?)\s*<(.*)>$", author_raw)
        author = m.group(1).strip() if m else author_raw
        email  = m.group(2).strip() if m else ""
        dt = datetime.fromtimestamp(
            c.author_time,
            tz=timezone(timedelta(seconds=c.author_timezone)),
        )
        info = CommitInfo(
            sha=sha, short_sha=sha[:7],
            message=msg_full.split("\n")[0],
            author=author, author_email=email,
            date=dt.isoformat(), parents=parents,
        )

        parent_tree = None
        if parents:
            try:
                parent_tree = repo[parents[0].encode()].tree
            except Exception:
                pass

        files: list[FileChange] = []
        total_add = total_del = 0
        try:
            for change in tree_changes(repo.object_store, parent_tree, c.tree):
                if change.type == CHANGE_ADD:
                    status   = "added"
                    filename = change.new.path.decode("utf-8", errors="replace")
                elif change.type == CHANGE_DELETE:
                    status   = "removed"
                    filename = change.old.path.decode("utf-8", errors="replace")
                elif change.type == CHANGE_RENAME:
                    status   = "renamed"
                    filename = change.new.path.decode("utf-8", errors="replace")
                else:
                    status   = "modified"
                    filename = (change.new.path or change.old.path).decode("utf-8", errors="replace")

                add = del_ = 0
                try:
                    old_data = repo.object_store[change.old.sha].data if change.old.sha else b""
                    new_data = repo.object_store[change.new.sha].data if change.new.sha else b""
                    for line in difflib.unified_diff(
                        old_data.splitlines(True), new_data.splitlines(True)
                    ):
                        if line.startswith(b"+") and not line.startswith(b"+++"):
                            add += 1
                        elif line.startswith(b"-") and not line.startswith(b"---"):
                            del_ += 1
                except Exception:
                    pass

                total_add += add
                total_del += del_
                files.append(FileChange(filename=filename, status=status,
                                        additions=add, deletions=del_))
        except Exception:
            pass

        return CommitDetail(
            info=info,
            stats={"additions": total_add, "deletions": total_del, "total": len(files)},
            files=files,
            refs=[],
            linked_prs=[],
        )

    def get_repo_info(self) -> "RepoInfo":
        from dulwich.repo import Repo
        r = Repo(self._tmpdir)
        try:
            default_branch = r.refs.get_symrefs().get(b"HEAD", b"refs/heads/main")
            default_branch = default_branch.decode().removeprefix("refs/heads/")
        except Exception:
            default_branch = "main"
        branch_count = sum(
            1 for ref in r.refs.as_dict()
            if ref.startswith(b"refs/heads/") or ref.startswith(b"refs/remotes/")
        )
        return RepoInfo(
            description="",
            created_at="",
            default_branch=default_branch,
            language="",
            stars=0,
            forks=0,
            open_issues=0,
            branches=branch_count,
            total_commits=len(self._commits),
        )

    def cleanup(self) -> None:
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
        self._commits = []
        self._graph_data = []
        self._shown = 0

# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_date(iso: str) -> str:
    try:
        iso = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16]

# ── Graph Builder ─────────────────────────────────────────────────────────────

def _build_graph_from_git(tmpdir: str) -> list[tuple[CommitInfo, list[Text]]]:
    """Run `git log --graph --color=always` on the cloned bare repo and parse
    the ANSI-coloured output into (CommitInfo, graph_lines) pairs.

    Each commit line is identified by a NUL-delimited marker injected via
    --format so we can cleanly separate graph-prefix characters from commit
    metadata without any regex fragility.
    """
    import subprocess

    # \x01 (SOH) marks commit lines; %x00 tells git to output NUL field separators.
    # Neither appears in graph characters (*, |, \, /, space).
    MARKER = "\x01"
    fmt = f"{MARKER}%H%x00%s%x00%aN%x00%aE%x00%ad%x00%P"

    proc = subprocess.run(
        [
            "git", "--git-dir", tmpdir,
            "log", "--graph", "--color=always",
            f"--format={fmt}",
            "--date=short",
            "--all",
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    output: list[tuple[CommitInfo, list[Text]]] = []
    current_commit: Optional[CommitInfo] = None
    current_lines:  list[Text] = []

    for raw in proc.stdout.splitlines():
        if MARKER in raw:
            graph_part, data = raw.split(MARKER, 1)
            fields = data.split("\x00")
            sha     = fields[0] if len(fields) > 0 else ""
            subject = fields[1] if len(fields) > 1 else ""
            author  = fields[2] if len(fields) > 2 else ""
            email   = fields[3] if len(fields) > 3 else ""
            date    = fields[4] if len(fields) > 4 else ""
            parents = fields[5].split() if len(fields) > 5 and fields[5] else []

            if not sha:
                continue

            if current_commit is not None:
                output.append((current_commit, current_lines))

            current_commit = CommitInfo(
                sha=sha, short_sha=sha[:7],
                message=subject, author=author, author_email=email,
                date=date, parents=parents,
            )
            current_lines = [Text.from_ansi(graph_part)]
        else:
            if current_commit is not None:
                current_lines.append(Text.from_ansi(raw))

    if current_commit is not None:
        output.append((current_commit, current_lines))

    return output

# ── UI Components ─────────────────────────────────────────────────────────────

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
        sha      = self.commit.short_sha
        msg_text = escape(self.commit.message.split("\n")[0].strip())
        who      = escape(self.commit.author)
        date     = fmt_date(self.commit.date)[:10]

        # Build graph cell as a single Text by joining lines with newlines
        graph_text = Text()
        for i, line in enumerate(self.graph_lines):
            if i:
                graph_text.append("\n")
            graph_text.append_text(line)
        graph_height = len(self.graph_lines)

        # Single-line info: message + sha + date on one row
        info_cell = f"[bold]{msg_text}[/bold]  [cyan]{sha}[/cyan]  [dim]{date}  {who}[/dim]"
        # Pad to match graph height (connector lines have no info)
        info_cell += "\n" * max(0, graph_height - 1)

        with Horizontal(classes="commit-row"):
            yield Label(graph_text, classes="graph-col")
            yield Label(info_cell,  classes="info-col", markup=True)

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
    ]

    def __init__(self, initial_repo: str = "", depth: Optional[int] = None) -> None:
        super().__init__()
        self._initial_repo = initial_repo
        self._owner = ""
        self._repo = ""
        self._current_sha: str = ""
        self._graph_col_width: int = 20
        self._depth = depth
        self._backend = _GitBackend()

        self.providers = {
            "github": GitHubProvider(),
            "gitlab": GitLabProvider(),
            "azure": AzureDevOpsProvider(),
        }
        self.current_provider = self.providers["github"]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="toolbar"):
            yield Select(
                [(p.name, k) for k, p in self.providers.items()],
                value="github",
                id="provider-select",
                allow_blank=False
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
                yield Button("⎋  Open in browser", id="open-btn", variant="default", disabled=True)
                with ScrollableContainer(id="right-scroll"):
                    yield Static("[dim]Select a commit to see details.[/dim]", id="detail")
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
            url = self.current_provider.commit_url(self._owner, self._repo, self._current_sha)
            webbrowser.open(url)

    @on(ListView.Selected, "#commits-list")
    def on_commit_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, CommitItem):
            self._fetch_detail(event.item.commit.sha)

    def action_reload(self) -> None:
        if self._owner:
            self._fetch_commits(replace=True)

    def action_more(self) -> None:
        self._load_more()

    _REPO_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")

    def _trigger_load(self) -> None:
        val = self.query_one("#repo-input", Input).value.strip()
        if "/" not in val:
            self.notify("Format: owner/repo (Azure: project/repo)", severity="warning")
            return

        parts = val.split("/", 1)
        owner, repo = parts[0].strip(), parts[1].strip()
        if not owner or not repo or not self._REPO_RE.match(f"{owner}/{repo}"):
            self.notify("Invalid owner/repo — use alphanumeric, hyphens, dots only", severity="warning")
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

                # Show repo info from backend
                info = self._backend.get_repo_info()
                repo_widget = self.query_one("#repo-info", Static)
                lines = [f"[bold]{escape(self._owner)}/[white]{escape(self._repo)}[/white][/bold]"]
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
                lines.append(f"[bold cyan]── Files Changed ({len(d.files)}) ────────────────────────[/bold cyan]")
                for f in d.files[:60]:
                    color = "white"
                    if f.status == "added":    color = "green"
                    elif f.status == "removed": color = "red"
                    elif f.status == "modified": color = "yellow"
                    elif f.status == "renamed":  color = "blue"
                    stats = ""
                    if f.additions or f.deletions:
                        stats = f"[dim](+{f.additions} -{f.deletions})[/dim]"
                    lines.append(f"  [{color}]{f.status[0].upper()}[/{color}] {escape(f.filename)}  {stats}")
                if len(d.files) > 60:
                    lines.append(f"  [dim]… and {len(d.files) - 60} more[/dim]")
                lines.append("")

            detail_widget.update("\n".join(lines))

        except Exception as e:
            detail_widget.update(f"[red]Error: {e}[/red]")


async def _export(owner: str, repo: str, provider_key: str, depth: Optional[int]) -> None:
    """Fetch commits via Dulwich and print the graph to stdout."""
    from rich.console import Console

    providers: dict[str, GitProvider] = {
        "github": GitHubProvider(),
        "gitlab": GitLabProvider(),
        "azure":  AzureDevOpsProvider(),
    }
    provider = providers.get(provider_key)
    if provider is None:
        print(f"Unknown provider '{provider_key}'. Choose from: {', '.join(providers)}", file=sys.stderr)
        sys.exit(1)

    backend = _GitBackend()
    try:
        console = Console(width=300, highlight=False)
        url = provider.clone_url(owner, repo)
        await backend.load(url, depth=depth)
        for commit, lines in backend.graph_data:
            date = commit.date[:10]
            node = lines[0].copy()
            node.append(f"  {commit.short_sha} ", style="cyan")
            node.append(commit.message.split("\n")[0].strip(), style="bold")
            node.append(f"  {commit.author}, {date}", style="dim")
            console.print(node)
            for cont in lines[1:]:
                console.print(cont)
    finally:
        backend.cleanup()


def main() -> None:
    """Entry point for the commit-explorer command."""
    import argparse

    parser = argparse.ArgumentParser(prog="commit-explorer")
    parser.add_argument("repo", nargs="?", default="", help="owner/repo")
    parser.add_argument("--export", action="store_true", help="Print graph to stdout and exit")
    parser.add_argument("--provider", default="github", choices=["github", "gitlab", "azure"])
    parser.add_argument("--depth", type=int, default=None, metavar="N",
                        help="Limit fetch to N commits (default: fetch all)")
    args = parser.parse_args()

    if args.export:
        if not args.repo or "/" not in args.repo:
            parser.error("--export requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_export(owner, repo, args.provider, args.depth))
    else:
        CommitExplorer(initial_repo=args.repo, depth=args.depth).run()


if __name__ == "__main__":
    main()
