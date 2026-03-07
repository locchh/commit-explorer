#!/usr/bin/env python3
"""Commit Explorer — Interactive TUI for exploring git repository history."""

import asyncio
import os
import re
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from typing import NamedTuple, Optional
from urllib.parse import quote

import webbrowser

import httpx
from dotenv import load_dotenv
from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical, Container
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

load_dotenv()

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

# ── Providers ─────────────────────────────────────────────────────────────────

class GitProvider(ABC):
    @abstractmethod
    async def fetch_commits(self, owner: str, repo: str, page: int) -> list[CommitInfo]:
        """Fetch a page of commits."""
        pass

    @abstractmethod
    async def fetch_detail(self, owner: str, repo: str, sha: str) -> CommitDetail:
        """Fetch detailed commit info."""
        pass

    @abstractmethod
    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        """Return a browser URL for the given commit."""
        pass

    @abstractmethod
    async def fetch_repo_info(self, owner: str, repo: str) -> RepoInfo:
        """Fetch repository metadata and statistics."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

class GitHubProvider(GitProvider):
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN", "")
        self.api_url = "https://api.github.com"

    @property
    def name(self) -> str:
        return "GitHub"

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"https://github.com/{owner}/{repo}/commit/{sha}"

    async def fetch_repo_info(self, owner: str, repo: str) -> RepoInfo:
        async with httpx.AsyncClient() as client:
            r_repo, r_branches, r_commits = await asyncio.gather(
                client.get(f"{self.api_url}/repos/{owner}/{repo}", headers=self._headers()),
                client.get(f"{self.api_url}/repos/{owner}/{repo}/branches",
                           headers=self._headers(), params={"per_page": 1}),
                client.get(f"{self.api_url}/repos/{owner}/{repo}/commits",
                           headers=self._headers(), params={"per_page": 1}),
            )
            r_repo.raise_for_status()
            d = r_repo.json()
            branches = _last_page(r_branches.headers.get("link", ""))
            total_commits = _last_page(r_commits.headers.get("link", ""))
            return RepoInfo(
                description=d.get("description") or "",
                created_at=d.get("created_at", ""),
                default_branch=d.get("default_branch", ""),
                language=d.get("language") or "",
                stars=d.get("stargazers_count", 0),
                forks=d.get("forks_count", 0),
                open_issues=d.get("open_issues_count", 0),
                branches=branches,
                total_commits=total_commits,
            )

    async def fetch_commits(self, owner: str, repo: str, page: int) -> list[CommitInfo]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/repos/{owner}/{repo}/commits",
                headers=self._headers(),
                params={"page": page, "per_page": 30},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            
            commits = []
            for item in data:
                c = item["commit"]
                author = c.get("author") or {}
                commits.append(CommitInfo(
                    sha=item["sha"],
                    short_sha=item["sha"][:7],
                    message=c.get("message", ""),
                    author=author.get("name", ""),
                    author_email=author.get("email", ""),
                    date=author.get("date", ""),
                    parents=[p["sha"] for p in item.get("parents", [])]
                ))
            return commits

    async def fetch_detail(self, owner: str, repo: str, sha: str) -> CommitDetail:
        async with httpx.AsyncClient() as client:
            tasks = [
                client.get(f"{self.api_url}/repos/{owner}/{repo}/commits/{sha}", headers=self._headers()),
                client.get(f"{self.api_url}/repos/{owner}/{repo}/commits/{sha}/pulls", headers=self._headers())
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            r_commit = responses[0]
            r_pulls = responses[1]

            if isinstance(r_commit, Exception):
                raise r_commit
            
            r_commit.raise_for_status()
            full = r_commit.json()
            
            pulls_data = []
            if not isinstance(r_pulls, Exception) and hasattr(r_pulls, 'status_code') and r_pulls.status_code == 200:
                pulls_data = r_pulls.json()

            c = full["commit"]
            author = c.get("author") or {}
            files = []
            for f in full.get("files", []):
                files.append(FileChange(
                    filename=f["filename"],
                    status=f["status"],
                    additions=f.get("additions", 0),
                    deletions=f.get("deletions", 0)
                ))

            return CommitDetail(
                info=CommitInfo(
                    sha=full["sha"],
                    short_sha=full["sha"][:7],
                    message=c.get("message", ""),
                    author=author.get("name", ""),
                    author_email=author.get("email", ""),
                    date=author.get("date", ""),
                    parents=[p["sha"] for p in full.get("parents", [])]
                ),
                stats=full.get("stats", {}),
                files=files,
                refs=list(dict.fromkeys(re.findall(r"#(\d+)", c["message"]))),
                linked_prs=[{"number": p["number"], "title": p["title"], "state": p["state"]} for p in pulls_data]
            )

class GitLabProvider(GitProvider):
    def __init__(self):
        self.token = os.getenv("GITLAB_TOKEN", "")
        base = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")
        # Accept either a bare host or a full API URL
        if base.endswith("/api/v4"):
            self.api_url = base
        else:
            self.api_url = f"{base}/api/v4"

    @property
    def name(self) -> str:
        return "GitLab"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        base = self.api_url.removesuffix("/api/v4")
        return f"{base}/{owner}/{repo}/-/commit/{sha}"

    async def fetch_repo_info(self, owner: str, repo: str) -> RepoInfo:
        project_id = quote(f"{owner}/{repo}", safe="")
        async with httpx.AsyncClient() as client:
            r_repo, r_branches = await asyncio.gather(
                client.get(f"{self.api_url}/projects/{project_id}", headers=self._headers()),
                client.get(f"{self.api_url}/projects/{project_id}/repository/branches",
                           headers=self._headers(), params={"per_page": 1}),
            )
            r_repo.raise_for_status()
            d = r_repo.json()
            branches_total = None
            if r_branches.status_code == 200:
                try:
                    branches_total = int(r_branches.headers.get("x-total", 0)) or None
                except ValueError:
                    pass
            return RepoInfo(
                description=d.get("description") or "",
                created_at=d.get("created_at", ""),
                default_branch=d.get("default_branch", ""),
                language="",
                stars=d.get("star_count", 0),
                forks=d.get("forks_count", 0),
                open_issues=d.get("open_issues_count", 0),
                branches=branches_total,
                total_commits=None,
            )

    def _headers(self) -> dict:
        h = {}
        if self.token:
            h["PRIVATE-TOKEN"] = self.token
        return h

    async def fetch_commits(self, owner: str, repo: str, page: int) -> list[CommitInfo]:
        project_id = quote(f"{owner}/{repo}", safe="")
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/projects/{project_id}/repository/commits",
                headers=self._headers(),
                params={"page": page, "per_page": 30},
                timeout=15
            )
            r.raise_for_status()
            data = r.json()
            
            commits = []
            for item in data:
                commits.append(CommitInfo(
                    sha=item["id"],
                    short_sha=item["short_id"],
                    message=item["message"],
                    author=item["author_name"],
                    author_email=item["author_email"],
                    date=item["created_at"],
                    parents=item.get("parent_ids", [])
                ))
            return commits

    async def fetch_detail(self, owner: str, repo: str, sha: str) -> CommitDetail:
        project_id = quote(f"{owner}/{repo}", safe="")
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/projects/{project_id}/repository/commits/{sha}",
                headers=self._headers()
            )
            r.raise_for_status()
            data = r.json()

            r_diff = await client.get(
                f"{self.api_url}/projects/{project_id}/repository/commits/{sha}/diff",
                headers=self._headers()
            )
            diffs = r_diff.json() if r_diff.status_code == 200 else []
            
            r_mrs = await client.get(
                f"{self.api_url}/projects/{project_id}/repository/commits/{sha}/merge_requests",
                headers=self._headers()
            )
            mrs = r_mrs.json() if r_mrs.status_code == 200 else []

            files = []
            stats = {"additions": 0, "deletions": 0, "total": 0}
            
            for d in diffs:
                status = "modified"
                if d["new_file"]: status = "added"
                elif d["deleted_file"]: status = "removed"
                elif d["renamed_file"]: status = "renamed"
                
                files.append(FileChange(
                    filename=d["new_path"],
                    status=status,
                    additions=0,
                    deletions=0
                ))

            return CommitDetail(
                info=CommitInfo(
                    sha=data["id"],
                    short_sha=data["short_id"],
                    message=data["message"],
                    author=data["author_name"],
                    author_email=data["author_email"],
                    date=data["created_at"],
                    parents=data.get("parent_ids", [])
                ),
                stats=data.get("stats", stats),
                files=files,
                refs=[],
                linked_prs=[{"number": m["iid"], "title": m["title"], "state": m["state"]} for m in mrs]
            )

class AzureDevOpsProvider(GitProvider):
    def __init__(self):
        self.token = os.getenv("AZURE_DEVOPS_TOKEN", "")
        self.org = os.getenv("AZURE_DEVOPS_ORG", "")
        
    @property
    def name(self) -> str:
        return "Azure DevOps"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"https://dev.azure.com/{self.org}/{owner}/_git/{repo}/commit/{sha}"

    async def fetch_repo_info(self, owner: str, repo: str) -> RepoInfo:
        base = f"https://dev.azure.com/{self.org}/{owner}/_apis/git/repositories/{repo}"
        async with httpx.AsyncClient() as client:
            r_repo, r_branches = await asyncio.gather(
                client.get(base, auth=self._auth(), params={"api-version": "7.1"}),
                client.get(f"https://dev.azure.com/{self.org}/{owner}/_apis/git/repositories/{repo}/refs",
                           auth=self._auth(), params={"filter": "heads", "api-version": "7.1", "$top": 1000}),
            )
            r_repo.raise_for_status()
            d = r_repo.json()
            branches = None
            if r_branches.status_code == 200:
                branches = r_branches.json().get("count")
            return RepoInfo(
                description=d.get("remoteUrl", ""),
                created_at="",
                default_branch=d.get("defaultBranch", "").removeprefix("refs/heads/"),
                language="",
                stars=0,
                forks=0,
                open_issues=0,
                branches=branches,
                total_commits=None,
            )

    def _auth(self) -> tuple[str, str]:
        return ("", self.token)

    async def fetch_commits(self, project: str, repo: str, page: int) -> list[CommitInfo]:
        if not self.org:
            raise ValueError("AZURE_DEVOPS_ORG env var is required")
            
        url = f"https://dev.azure.com/{self.org}/{project}/_apis/git/repositories/{repo}/commits"
        
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url,
                auth=self._auth(),
                params={
                    "api-version": "7.1",
                    "$top": 30,
                    "$skip": (page - 1) * 30
                },
                timeout=15
            )
            r.raise_for_status()
            data = r.json()
            
            commits = []
            for item in data["value"]:
                author = item.get("author") or {}
                commits.append(CommitInfo(
                    sha=item["commitId"],
                    short_sha=item["commitId"][:7],
                    message=item.get("comment", ""),
                    author=author.get("name", ""),
                    author_email=author.get("email", ""),
                    date=author.get("date", ""),
                    parents=item.get("parents", [])
                ))
            return commits

    async def fetch_detail(self, project: str, repo: str, sha: str) -> CommitDetail:
        url_base = f"https://dev.azure.com/{self.org}/{project}/_apis/git/repositories/{repo}/commits/{sha}"
        
        async with httpx.AsyncClient() as client:
            r = await client.get(url_base, auth=self._auth(), params={"api-version": "7.1"})
            r.raise_for_status()
            c_data = r.json()
            
            r_changes = await client.get(f"{url_base}/changes", auth=self._auth(), params={"api-version": "7.1"})
            changes_data = r_changes.json() if r_changes.status_code == 200 else {"changes": []}
            
            files = []
            stats = {"additions": 0, "deletions": 0, "total": 0}
            
            for change in changes_data.get("changes", []):
                item = change.get("item", {})
                change_type = change.get("changeType", "edit")
                
                status = "modified"
                if "add" in change_type: status = "added"
                elif "delete" in change_type: status = "removed"
                elif "rename" in change_type: status = "renamed"
                
                files.append(FileChange(
                    filename=item.get("path", ""),
                    status=status,
                    additions=0,
                    deletions=0
                ))
                
            author = c_data.get("author") or {}
            return CommitDetail(
                info=CommitInfo(
                    sha=c_data["commitId"],
                    short_sha=c_data["commitId"][:7],
                    message=c_data.get("comment", ""),
                    author=author.get("name", ""),
                    author_email=author.get("email", ""),
                    date=author.get("date", ""),
                    parents=c_data.get("parents", [])
                ),
                stats=stats,
                files=files,
                refs=[],
                linked_prs=[]
            )

# ── Helpers ───────────────────────────────────────────────────────────────────

def _last_page(link_header: str) -> Optional[int]:
    """Parse the last page number from a GitHub/GitLab Link header."""
    m = re.search(r'[?&]page=(\d+)[^>]*>;\s*rel="last"', link_header or "")
    return int(m.group(1)) if m else None

def fmt_date(iso: str) -> str:
    try:
        iso = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]

# ── Graph Visualizer ──────────────────────────────────────────────────────────

def _col(colors: list[str], i: int) -> str:
    return colors[i % len(colors)]

def _rail(colors: list[str], i: int, sym: str) -> str:
    c = _col(colors, i)
    return f"[{c}]{sym}[/{c}]"

MAX_COLS = 12  # cap visible rails; beyond this we reuse aggressively

def _alloc_slot(active: list[Optional[str]], sha: str) -> int:
    """Return index of an existing slot for sha, or allocate the nearest free one."""
    # Already tracked?
    try:
        return active.index(sha)
    except ValueError:
        pass
    # First free slot
    try:
        idx = active.index(None)
        active[idx] = sha
        return idx
    except ValueError:
        pass
    # At cap? Reuse the rightmost slot (oldest rail) — rough heuristic
    if len(active) >= MAX_COLS:
        active[-1] = sha
        return len(active) - 1
    active.append(sha)
    return len(active) - 1


def build_graph(
    commits: list[CommitInfo],
) -> list[tuple[CommitInfo, list[str]]]:
    """
    Returns (CommitInfo, graph_lines) where graph_lines is a list of
    Rich-markup strings to stack vertically — like `git log --graph`.

    Each commit produces:
      1. Node line:         ● │ │
      2. Edge line (merge): ├─╮ │   (only for merge commits)
      3. Continuation line: │ │ │   (connects to the next commit)
    """
    colors = ["red", "green", "yellow", "blue", "magenta", "cyan",
              "bright_white", "orange3", "deep_sky_blue1", "green3",
              "violet", "gold1"]

    active: list[Optional[str]] = []
    output: list[tuple[CommitInfo, list[str]]] = []

    for commit in commits:
        sha = commit.sha

        # ── Assign / find column ─────────────────────────────────────────
        try:
            col = active.index(sha)
        except ValueError:
            col = _alloc_slot(active, sha)
            active[col] = sha

        # Collapse duplicate refs (two rails converge here)
        for i in range(len(active)):
            if i != col and active[i] == sha:
                active[i] = None

        n_before = len(active)

        # ── Node line ────────────────────────────────────────────────────
        node_parts: list[str] = []
        for i in range(n_before):
            if i == col:
                c = _col(colors, i)
                node_parts.append(f"[bold {c}]●[/bold {c}] ")
            elif active[i] is not None:
                node_parts.append(_rail(colors, i, "│") + " ")
            else:
                node_parts.append("  ")
        node_line = "".join(node_parts).rstrip()

        # ── Wire parents ─────────────────────────────────────────────────
        parents = commit.parents
        active[col] = None

        parent_slots: list[int] = []
        if parents:
            active[col] = parents[0]
            parent_slots.append(col)
            for p in parents[1:]:
                slot = _alloc_slot(active, p)
                parent_slots.append(slot)

        while active and active[-1] is None:
            active.pop()

        # ── Edge line (merge commits only) ───────────────────────────────
        edge_line = ""
        if len(parents) > 1:
            extra_slots = sorted(set(parent_slots[1:]))
            span_lo = min(col, *extra_slots)
            span_hi = max(col, *extra_slots)
            width = max(n_before, len(active), span_hi + 1)

            edge_parts: list[str] = []
            for i in range(width):
                is_active = i < len(active) and active[i] is not None
                in_span = span_lo <= i <= span_hi

                if i == col:
                    edge_parts.append(_rail(colors, col, "├") + "─")
                elif i in extra_slots:
                    if i > col:
                        edge_parts.append(_rail(colors, i, "╮") + " ")
                    else:
                        edge_parts.append(_rail(colors, i, "╭") + " ")
                elif is_active and in_span:
                    edge_parts.append(_rail(colors, i, "┼") + "─")
                elif in_span:
                    edge_parts.append("──")
                elif is_active:
                    edge_parts.append(_rail(colors, i, "│") + " ")
                else:
                    edge_parts.append("  ")
            edge_line = "".join(edge_parts).rstrip()

        # ── Continuation line ────────────────────────────────────────────
        cont_parts: list[str] = []
        for i in range(len(active)):
            if active[i] is not None:
                cont_parts.append(_rail(colors, i, "│") + " ")
            else:
                cont_parts.append("  ")
        cont_line = "".join(cont_parts).rstrip()

        # ── Combine ──────────────────────────────────────────────────────
        lines = [node_line]
        if edge_line:
            lines.append(edge_line)
        if cont_line.strip():
            lines.append(cont_line)

        output.append((commit, lines))

    return output

# ── UI Components ─────────────────────────────────────────────────────────────

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
    def __init__(self, commit: CommitInfo, graph_lines: list[str]) -> None:
        super().__init__()
        self.commit = commit
        self.graph_lines = graph_lines

    def compose(self) -> ComposeResult:
        sha = self.commit.short_sha
        msg_text = self.commit.message.split("\n")[0].strip()
        if len(msg_text) > 60:
            msg_text = msg_text[:59] + "…"
        msg  = escape(msg_text)
        who  = escape(self.commit.author)
        date = fmt_date(self.commit.date)[:10]

        graph_cell = "\n".join(self.graph_lines)
        graph_height = len(self.graph_lines)

        info_cell = (
            f"[bold]{msg}[/bold]\n"
            f"[cyan]{sha}[/cyan]  [dim]{date}  {who}[/dim]"
        )
        # Pad info to match graph height
        info_height = 2
        while info_height < graph_height:
            info_cell += "\n"
            info_height += 1

        with Horizontal(classes="commit-row"):
            yield Label(graph_cell, classes="graph-col")
            yield Label(info_cell,  classes="info-col")

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
    .graph-col        { width: auto; min-width: 4; padding: 0 1 0 1; }
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

    def __init__(self, initial_repo: str = "") -> None:
        super().__init__()
        self._initial_repo = initial_repo
        self._owner = ""
        self._repo = ""
        self._page = 1
        self._commits: list[CommitInfo] = []
        self._current_sha: str = ""
        
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
            yield Splitter()
            with Vertical(id="right"):
                yield Button("⎋  Open in browser", id="open-btn", variant="default", disabled=True)
                with ScrollableContainer(id="right-scroll"):
                    yield Static("[dim]Select a commit to see details.[/dim]", id="detail")
        yield Footer()

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
        self._commits = []
        self._page = 1

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
            self._page = 1
            self._commits = []
            self._fetch_repo_info()
            self._fetch_commits(replace=True)

    def action_more(self) -> None:
        self._load_more()

    def _trigger_load(self) -> None:
        val = self.query_one("#repo-input", Input).value.strip()
        if "/" not in val:
            self.notify("Format: owner/repo (Azure: project/repo)", severity="warning")
            return
        
        parts = val.split("/", 1)
        self._owner, self._repo = parts[0], parts[1]
        self._page = 1
        self._commits = []
        self._fetch_repo_info()
        self._fetch_commits(replace=True)

    def _load_more(self) -> None:
        if self._owner:
            self._page += 1
            self._fetch_commits(replace=False)

    @work
    async def _fetch_repo_info(self) -> None:
        widget = self.query_one("#repo-info", Static)
        widget.display = False
        try:
            info = await self.current_provider.fetch_repo_info(self._owner, self._repo)

            lines: list[str] = []

            # Title + description
            title = f"[bold]{escape(self._owner)}/[white]{escape(self._repo)}[/white][/bold]"
            if info.description:
                title += f"  [dim]{escape(info.description[:80])}[/dim]"
            lines.append(title)

            # Stats row
            stats: list[str] = []
            if info.stars:
                stats.append(f"[yellow]★ {info.stars:,}[/yellow]")
            if info.forks:
                stats.append(f"[cyan]⑂ {info.forks:,}[/cyan]")
            if info.language:
                stats.append(f"[green]{escape(info.language)}[/green]")
            if info.default_branch:
                stats.append(f"default: [magenta]{escape(info.default_branch)}[/magenta]")
            if info.open_issues:
                stats.append(f"[red]{info.open_issues:,} issues[/red]")
            if stats:
                lines.append("  ".join(stats))

            # Timeline row
            meta: list[str] = []
            if info.created_at:
                meta.append(f"Created {fmt_date(info.created_at)[:10]}")
            if info.branches is not None:
                meta.append(f"{info.branches:,} branches")
            if info.total_commits is not None:
                meta.append(f"~{info.total_commits:,} commits")
            if meta:
                lines.append("[dim]" + "  ·  ".join(meta) + "[/dim]")

            widget.update("\n".join(lines))
            widget.display = True
        except Exception:
            pass  # repo info is non-critical

    @work
    async def _fetch_commits(self, replace: bool) -> None:
        spinner = self.query_one("#spinner")
        spinner.display = True
        
        try:
            new_commits = await self.current_provider.fetch_commits(
                self._owner, self._repo, self._page
            )
            
            if replace:
                self._commits = new_commits
            else:
                self._commits.extend(new_commits)
            
            lv = self.query_one("#commits-list", ListView)
            if replace:
                await lv.clear()
            
            if not new_commits and not replace:
                self.notify("No more commits.", severity="information")
                return
            
            # Simple graph recalc for new items for now
            # Note: ideally we recalculate whole graph for consistency but that might jump
            # We'll just graph the new batch independently which is a bit glitchy at page boundary
            # but safer for simple logic
            graph_data = build_graph(new_commits)

            for commit, graph_lines in graph_data:
                await lv.append(CommitItem(commit, graph_lines))

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
            d = await self.current_provider.fetch_detail(self._owner, self._repo, sha)
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
                    if f.status == "added": color = "green"
                    elif f.status == "removed": color = "red"
                    elif f.status == "modified": color = "yellow"
                    elif f.status == "renamed": color = "blue"
                    
                    stats = ""
                    if f.additions or f.deletions:
                        stats = f"[dim](+{f.additions} -{f.deletions})[/dim]"
                    
                    lines.append(f"  [{color}]{f.status[0].upper()}[/{color}] {escape(f.filename)}  {stats}")
                
                if len(d.files) > 60:
                    lines.append(f"  [dim]… and {len(d.files) - 60} more[/dim]")
                lines.append("")

            if d.linked_prs:
                lines.append("[bold cyan]── Linked Pull Requests ─────────────────────────[/bold cyan]")
                for pr in d.linked_prs:
                    state_color = "green" if pr["state"] == "open" else "magenta"
                    lines.append(f"  [{state_color}]#{pr['number']}[/{state_color}] {escape(pr['title'])}")
                lines.append("")

            detail_widget.update("\n".join(lines))

        except Exception as e:
            detail_widget.update(f"[red]Error fetching details: {e}[/red]")


def main() -> None:
    """Entry point for the commit-explorer command."""
    repo = sys.argv[1] if len(sys.argv) > 1 else ""
    CommitExplorer(initial_repo=repo).run()


if __name__ == "__main__":
    main()
