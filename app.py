#!/usr/bin/env python3
"""Commit Explorer — Interactive TUI for exploring git repository history."""

import asyncio
import heapq
import os
import re
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum, auto
from typing import NamedTuple, Optional
from urllib.parse import quote

import webbrowser

import httpx
from dotenv import load_dotenv
from rich.markup import escape
from rich.style import Style
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

    @abstractmethod
    async def fetch_branches(self, owner: str, repo: str, limit: int = 10) -> list[str]:
        """Fetch branch names, sorted by most recently updated, capped at limit."""
        pass

    async def fetch_all_commits(
        self, owner: str, repo: str, count: int = 100
    ) -> list[CommitInfo]:
        """Fetch commits from multiple branches, deduplicate, and sort by date descending."""
        branches = await self.fetch_branches(owner, repo, limit=10)
        if not branches:
            # Fallback: just fetch from default branch
            return await self.fetch_commits(owner, repo, page=1)

        per_branch = max(20, count // len(branches))
        seen: dict[str, CommitInfo] = {}

        tasks = [
            self._fetch_branch_commits(owner, repo, branch, per_branch)
            for branch in branches
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        failed_branches = []
        for branch, result in zip(branches, results):
            if isinstance(result, Exception):
                failed_branches.append(branch)
                continue
            for commit in result:
                if commit.sha not in seen:
                    seen[commit.sha] = commit

        if failed_branches and not seen:
            raise RuntimeError(f"All branch fetches failed (e.g. {failed_branches[0]}: {results[branches.index(failed_branches[0])]})")

        # Sort by date descending (newest first)
        all_commits = sorted(
            seen.values(),
            key=lambda c: c.date,
            reverse=True,
        )
        return all_commits[:count]

    async def _fetch_branch_commits(
        self, owner: str, repo: str, branch: str, per_page: int
    ) -> list[CommitInfo]:
        """Override in subclasses to fetch commits for a specific branch."""
        return await self.fetch_commits(owner, repo, page=1)

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
        return f"https://github.com/{quote(owner, safe='')}/{quote(repo, safe='')}/commit/{quote(sha, safe='')}"

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

    async def fetch_branches(self, owner: str, repo: str, limit: int = 10) -> list[str]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/repos/{owner}/{repo}/branches",
                headers=self._headers(),
                params={"per_page": limit, "sort": "updated", "direction": "desc"},
                timeout=15,
            )
            r.raise_for_status()
            return [b.get("name", "") for b in r.json() if isinstance(b, dict) and b.get("name")]

    async def _fetch_branch_commits(
        self, owner: str, repo: str, branch: str, per_page: int
    ) -> list[CommitInfo]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/repos/{owner}/{repo}/commits",
                headers=self._headers(),
                params={"sha": branch, "per_page": per_page},
                timeout=15,
            )
            r.raise_for_status()
            return self._parse_commits(r.json())

    async def fetch_commits(self, owner: str, repo: str, page: int) -> list[CommitInfo]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/repos/{owner}/{repo}/commits",
                headers=self._headers(),
                params={"page": page, "per_page": 100},
                timeout=15,
            )
            r.raise_for_status()
            return self._parse_commits(r.json())

    def _parse_commits(self, data: list[dict]) -> list[CommitInfo]:
        commits = []
        for item in data:
            try:
                c = item.get("commit") or {}
                author = c.get("author") or {}
                commits.append(CommitInfo(
                    sha=item.get("sha", ""),
                    short_sha=item.get("sha", "")[:7],
                    message=c.get("message", ""),
                    author=author.get("name", ""),
                    author_email=author.get("email", ""),
                    date=author.get("date", ""),
                    parents=[p.get("sha", "") for p in item.get("parents", []) if isinstance(p, dict)]
                ))
            except (KeyError, TypeError, AttributeError):
                continue
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
                try:
                    pulls_data = r_pulls.json()
                except (ValueError, TypeError):
                    pulls_data = []

            c = full.get("commit") or {}
            author = c.get("author") or {}
            files = []
            for f in full.get("files", []):
                files.append(FileChange(
                    filename=f.get("filename", ""),
                    status=f.get("status", "modified"),
                    additions=f.get("additions", 0),
                    deletions=f.get("deletions", 0)
                ))

            return CommitDetail(
                info=CommitInfo(
                    sha=full.get("sha", ""),
                    short_sha=full.get("sha", "")[:7],
                    message=c.get("message", ""),
                    author=author.get("name", ""),
                    author_email=author.get("email", ""),
                    date=author.get("date", ""),
                    parents=[p.get("sha", "") for p in full.get("parents", []) if isinstance(p, dict)]
                ),
                stats=full.get("stats", {}),
                files=files,
                refs=list(dict.fromkeys(re.findall(r"#(\d+)", c.get("message", "")))),
                linked_prs=[{"number": p.get("number", 0), "title": p.get("title", ""), "state": p.get("state", "")} for p in pulls_data if isinstance(p, dict)]
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
        return f"{base}/{quote(owner, safe='')}/{quote(repo, safe='')}/-/commit/{quote(sha, safe='')}"

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

    async def fetch_branches(self, owner: str, repo: str, limit: int = 10) -> list[str]:
        project_id = quote(f"{owner}/{repo}", safe="")
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/projects/{project_id}/repository/branches",
                headers=self._headers(),
                params={"per_page": limit, "order_by": "updated", "sort": "desc"},
                timeout=15,
            )
            r.raise_for_status()
            return [b.get("name", "") for b in r.json() if isinstance(b, dict) and b.get("name")]

    async def _fetch_branch_commits(
        self, owner: str, repo: str, branch: str, per_page: int
    ) -> list[CommitInfo]:
        project_id = quote(f"{owner}/{repo}", safe="")
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/projects/{project_id}/repository/commits",
                headers=self._headers(),
                params={"ref_name": branch, "per_page": per_page},
                timeout=15,
            )
            r.raise_for_status()
            return self._parse_commits(r.json())

    async def fetch_commits(self, owner: str, repo: str, page: int) -> list[CommitInfo]:
        project_id = quote(f"{owner}/{repo}", safe="")
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.api_url}/projects/{project_id}/repository/commits",
                headers=self._headers(),
                params={"page": page, "per_page": 100},
                timeout=15
            )
            r.raise_for_status()
            return self._parse_commits(r.json())

    def _parse_commits(self, data: list[dict]) -> list[CommitInfo]:
        commits = []
        for item in data:
            try:
                commits.append(CommitInfo(
                    sha=item.get("id", ""),
                    short_sha=item.get("short_id", ""),
                    message=item.get("message", ""),
                    author=item.get("author_name", ""),
                    author_email=item.get("author_email", ""),
                    date=item.get("created_at", ""),
                    parents=item.get("parent_ids", [])
                ))
            except (KeyError, TypeError, AttributeError):
                continue
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
            try:
                diffs = r_diff.json() if r_diff.status_code == 200 else []
            except (ValueError, TypeError):
                diffs = []

            r_mrs = await client.get(
                f"{self.api_url}/projects/{project_id}/repository/commits/{sha}/merge_requests",
                headers=self._headers()
            )
            try:
                mrs = r_mrs.json() if r_mrs.status_code == 200 else []
            except (ValueError, TypeError):
                mrs = []

            files = []
            stats = {"additions": 0, "deletions": 0, "total": 0}
            
            for d in diffs:
                status = "modified"
                if d.get("new_file", False): status = "added"
                elif d.get("deleted_file", False): status = "removed"
                elif d.get("renamed_file", False): status = "renamed"

                files.append(FileChange(
                    filename=d.get("new_path", ""),
                    status=status,
                    additions=0,
                    deletions=0
                ))

            return CommitDetail(
                info=CommitInfo(
                    sha=data.get("id", ""),
                    short_sha=data.get("short_id", ""),
                    message=data.get("message", ""),
                    author=data.get("author_name", ""),
                    author_email=data.get("author_email", ""),
                    date=data.get("created_at", ""),
                    parents=data.get("parent_ids", [])
                ),
                stats=data.get("stats", stats),
                files=files,
                refs=[],
                linked_prs=[{"number": m.get("iid", 0), "title": m.get("title", ""), "state": m.get("state", "")} for m in mrs if isinstance(m, dict)]
            )

class AzureDevOpsProvider(GitProvider):
    def __init__(self):
        self.token = os.getenv("AZURE_DEVOPS_TOKEN", "")
        self.org = os.getenv("AZURE_DEVOPS_ORG", "")
        
    @property
    def name(self) -> str:
        return "Azure DevOps"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"https://dev.azure.com/{quote(self.org, safe='')}/{quote(owner, safe='')}/_git/{quote(repo, safe='')}/commit/{quote(sha, safe='')}"

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

    async def fetch_branches(self, owner: str, repo: str, limit: int = 10) -> list[str]:
        if not self.org:
            return []
        url = f"https://dev.azure.com/{self.org}/{owner}/_apis/git/repositories/{repo}/refs"
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url,
                auth=self._auth(),
                params={"filter": "heads", "api-version": "7.1", "$top": limit},
                timeout=15,
            )
            r.raise_for_status()
            refs = r.json().get("value", [])
            return [ref.get("name", "").removeprefix("refs/heads/") for ref in refs if isinstance(ref, dict) and ref.get("name")]

    async def _fetch_branch_commits(
        self, owner: str, repo: str, branch: str, per_page: int
    ) -> list[CommitInfo]:
        if not self.org:
            raise ValueError("AZURE_DEVOPS_ORG env var is required")
        url = f"https://dev.azure.com/{self.org}/{owner}/_apis/git/repositories/{repo}/commits"
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url,
                auth=self._auth(),
                params={
                    "api-version": "7.1",
                    "searchCriteria.itemVersion.version": branch,
                    "$top": per_page,
                },
                timeout=15,
            )
            r.raise_for_status()
            return self._parse_commits(r.json().get("value", []))

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
                    "$top": 100,
                    "$skip": (page - 1) * 100
                },
                timeout=15
            )
            r.raise_for_status()
            return self._parse_commits(r.json().get("value", []))

    def _parse_commits(self, data: list[dict]) -> list[CommitInfo]:
        commits = []
        for item in data:
            try:
                author = item.get("author") or {}
                commits.append(CommitInfo(
                    sha=item.get("commitId", ""),
                    short_sha=item.get("commitId", "")[:7],
                    message=item.get("comment", ""),
                    author=author.get("name", ""),
                    author_email=author.get("email", ""),
                    date=author.get("date", ""),
                    parents=item.get("parents", [])
                ))
            except (KeyError, TypeError, AttributeError):
                continue
        return commits

    async def fetch_detail(self, project: str, repo: str, sha: str) -> CommitDetail:
        url_base = f"https://dev.azure.com/{self.org}/{project}/_apis/git/repositories/{repo}/commits/{sha}"
        
        async with httpx.AsyncClient() as client:
            r = await client.get(url_base, auth=self._auth(), params={"api-version": "7.1"})
            r.raise_for_status()
            c_data = r.json()
            
            r_changes = await client.get(f"{url_base}/changes", auth=self._auth(), params={"api-version": "7.1"})
            try:
                changes_data = r_changes.json() if r_changes.status_code == 200 else {"changes": []}
            except (ValueError, TypeError):
                changes_data = {"changes": []}
            
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
                    sha=c_data.get("commitId", ""),
                    short_sha=c_data.get("commitId", "")[:7],
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
    except (ValueError, TypeError):
        return iso[:16]

# ── Graph Visualizer ──────────────────────────────────────────────────────────
#
# Faithful Python port of git's graph.c state machine.
# Renders exactly like `git log --graph --color`:
#   * | \  /  _  .  -   (same ASCII characters, same 2-chars-per-column layout)
#
# States (mirrors enum graph_state in graph.c):
#   PADDING     – vertical padding between commits
#   PRE_COMMIT  – expansion rows before an octopus merge (3+ parents)
#   COMMIT      – the commit node line itself  → returns this line to caller
#   POST_MERGE  – the |\ line drawn immediately after a merge commit
#   COLLAPSING  – one or more / lines that slide rails leftward after a branch closes

class _GS(Enum):
    PADDING    = auto()
    PRE_COMMIT = auto()
    COMMIT     = auto()
    POST_MERGE = auto()
    COLLAPSING = auto()

# ANSI color names cycled across lanes — used as Rich Style colors.
_LANE_COLORS = [
    "red", "green", "yellow", "blue", "magenta", "cyan",
    "bright_red", "bright_green", "bright_yellow", "bright_blue",
    "bright_magenta", "bright_cyan", "white", "bright_white",
    "dark_orange", "hot_pink",
]

def _ch(t: Text, color_idx: int, char: str) -> None:
    """Append a single styled character to a Rich Text object."""
    c = _LANE_COLORS[color_idx % len(_LANE_COLORS)]
    t.append(char, style=Style(color=c))


def _topo_sort(commits: list[CommitInfo]) -> list[CommitInfo]:
    """Topological sort matching git's revision walk order.

    Emits children before parents, newest-date first.  For merge commits,
    non-first parents (feature branch tips) are queued immediately after
    the merge using the merge's date as priority key — this keeps them
    visually adjacent to the merge row, matching git log --graph output.
    """
    by_sha = {c.sha: c for c in commits}

    # pending_children[sha] = number of in-window children not yet emitted
    pending: dict[str, int] = {c.sha: 0 for c in commits}
    for c in commits:
        for p in c.parents:
            if p in pending:
                pending[p] += 1

    def _neg(iso: str) -> str:
        return "".join(chr(126 - ord(ch)) if ch.isdigit() else ch for ch in iso)

    seq = 0
    # heap entries: (tier, neg_date, seq, sha)
    # tier 0 = non-first parent chain (feature branch — drain immediately)
    # tier 1 = first parent / mainline
    queue: list[tuple[int, str, int, str]] = []

    for c in commits:
        if pending[c.sha] == 0:
            heapq.heappush(queue, (1, _neg(c.date), seq, c.sha))
            seq += 1

    result: list[CommitInfo] = []
    emitted: set[str] = set()
    in_queue: set[str] = {c.sha for c in commits if pending[c.sha] == 0}

    while queue:
        tier, nd, _, sha = heapq.heappop(queue)
        if sha in emitted:
            continue
        emitted.add(sha)
        c = by_sha[sha]
        result.append(c)

        for idx, p in enumerate(c.parents):
            if p not in by_sha or p in emitted:
                continue
            pending[p] -= 1
            if pending[p] == 0 and p not in in_queue:
                in_queue.add(p)
                if idx > 0:
                    # Non-first parent starts a feature-branch chain (tier 0)
                    ptier = 0
                    pdate = nd
                elif tier == 0:
                    # Continuing a feature-branch chain — stay tier 0
                    ptier = 0
                    pdate = _neg(by_sha[p].date)
                else:
                    # Mainline first parent
                    ptier = 1
                    pdate = _neg(by_sha[p].date)
                heapq.heappush(queue, (ptier, pdate, seq, p))
                seq += 1

    for c in commits:
        if c.sha not in emitted:
            result.append(c)

    return result


class _Column:
    """One active branch lane — mirrors struct column in graph.c."""
    __slots__ = ("sha", "color")

    def __init__(self, sha: str, color: int) -> None:
        self.sha   = sha
        self.color = color


class _Graph:
    """
    Stateful renderer that mirrors struct git_graph.

    Call graph_update(commit) for each commit in topological order,
    then drain graph_next_line() until graph_is_commit_finished() is True.
    graph_next_line() returns (line_str, is_commit_line).
    """

    def __init__(self) -> None:
        self.commit: Optional[CommitInfo] = None
        self.num_parents:       int = 0
        self.width:             int = 0
        self.expansion_row:     int = 0
        self.state:             _GS = _GS.PADDING
        self.prev_state:        _GS = _GS.PADDING
        self.commit_index:      int = 0
        self.prev_commit_index: int = 0
        self.merge_layout:      int = 0   # 0 = left-skewed, 1 = right-skewed
        self.edges_added:       int = 0
        self.prev_edges_added:  int = 0
        self.default_color:     int = 0   # next color to hand out

        self.columns:     list[_Column] = []   # current columns
        self.new_columns: list[_Column] = []   # columns for next commit
        # mapping[i] = target column index for screen position i, or -1
        self.mapping:     list[int] = []
        self.old_mapping: list[int] = []
        # SHAs of all commits in the render window — parents outside this
        # set are ignored so they don't create permanent orphan lanes.
        self.known_shas: set[str] = set()

    # ── public API ────────────────────────────────────────────────────────

    def graph_update(self, commit: CommitInfo) -> None:
        self.commit = commit
        self.prev_commit_index = self.commit_index

        # Count only in-window parents — unknown parents are ignored
        self.num_parents = sum(1 for p in commit.parents if p in self.known_shas)

        self._update_columns()
        self.expansion_row = 0

        if self.state != _GS.PADDING:
            self.state = _GS.PADDING   # skip ellipsis – not needed for API use
        if self._needs_pre_commit_line():
            self.state = _GS.PRE_COMMIT
        else:
            self.state = _GS.COMMIT

    def graph_is_commit_finished(self) -> bool:
        return self.state == _GS.PADDING

    def graph_next_line(self) -> tuple[Text, bool]:
        """Return (Text line, is_commit_line)."""
        is_commit = False
        t = Text()

        if self.state == _GS.PADDING:
            self._output_padding(t)
        elif self.state == _GS.PRE_COMMIT:
            self._output_pre_commit(t)
        elif self.state == _GS.COMMIT:
            self._output_commit(t)
            is_commit = True
        elif self.state == _GS.POST_MERGE:
            self._output_post_merge(t)
        elif self.state == _GS.COLLAPSING:
            self._output_collapsing(t)

        self._pad_horizontally(t)
        t.rstrip()
        return t, is_commit

    # ── internal helpers ──────────────────────────────────────────────────

    def _update_state(self, new: _GS) -> None:
        self.prev_state = self.state
        self.state = new

    def _next_color(self) -> int:
        c = self.default_color
        self.default_color = (self.default_color + 1) % len(_LANE_COLORS)
        return c

    def _find_commit_color(self, sha: str) -> int:
        for col in self.columns:
            if col.sha == sha:
                return col.color
        return self._next_color()

    def _find_new_column_by_sha(self, sha: str) -> int:
        for i, col in enumerate(self.new_columns):
            if col.sha == sha:
                return i
        return -1

    def _insert_into_new_columns(self, sha: str, idx: int) -> None:
        """Mirror graph_insert_into_new_columns from graph.c."""
        i = self._find_new_column_by_sha(sha)

        if i < 0:
            i = len(self.new_columns)
            self.new_columns.append(_Column(sha, self._find_commit_color(sha)))

        if self.num_parents > 1 and idx > -1 and self.merge_layout == -1:
            # First parent of a merge: choose layout
            dist  = idx - i
            shift = (2 * dist - 3) if dist > 1 else 1
            self.merge_layout  = 0 if dist > 0 else 1
            self.edges_added   = self.num_parents + self.merge_layout - 2
            mapping_idx        = self.width + (self.merge_layout - 1) * shift
            self.width        += 2 * self.merge_layout
        elif self.edges_added > 0 and i == self.mapping[self.width - 2]:
            # Last column fuses with the merge – tighten the join
            mapping_idx      = self.width - 2
            self.edges_added = -1
        else:
            mapping_idx  = self.width
            self.width  += 2

        # Grow mapping if needed
        while len(self.mapping) <= mapping_idx:
            self.mapping.append(-1)
        self.mapping[mapping_idx] = i

    def _update_columns(self) -> None:
        """Mirror graph_update_columns from graph.c."""
        assert self.commit is not None

        # Swap columns ↔ new_columns
        self.columns, self.new_columns = self.new_columns, self.columns
        num_cols = len(self.columns)
        self.new_columns.clear()

        max_new = num_cols + self.num_parents
        map_size = 2 * max_new
        self.old_mapping = self.mapping[:]
        self.mapping = [-1] * map_size

        self.width             = 0
        self.prev_edges_added  = self.edges_added
        self.edges_added       = 0

        seen_this          = False
        is_commit_in_cols  = True

        for i in range(num_cols + 1):
            if i == num_cols:
                if seen_this:
                    break
                is_commit_in_cols = False
                col_sha = self.commit.sha
            else:
                col_sha = self.columns[i].sha

            if col_sha == self.commit.sha:
                seen_this         = True
                self.commit_index = i
                self.merge_layout = -1

                for p in self.commit.parents:
                    if p not in self.known_shas:
                        continue   # skip unknown parents — no orphan lane
                    if self.num_parents > 1 or not is_commit_in_cols:
                        self._next_color()
                    self._insert_into_new_columns(p, i)

                if self.num_parents == 0:
                    self.width += 2
            else:
                self._insert_into_new_columns(col_sha, -1)

        # Shrink mapping to minimum necessary size
        while len(self.mapping) > 1 and self.mapping[-1] < 0:
            self.mapping.pop()

    def _num_dashed_parents(self) -> int:
        return self.num_parents + self.merge_layout - 3

    def _num_expansion_rows(self) -> int:
        return self._num_dashed_parents() * 2

    def _needs_pre_commit_line(self) -> bool:
        return (self.num_parents >= 3
                and self.commit_index < len(self.columns) - 1
                and self.expansion_row < self._num_expansion_rows())

    def _pad_horizontally(self, t: Text) -> None:
        """Pad to self.width screen columns (2 per logical column)."""
        cur = len(t.plain)
        if cur < self.width:
            t.append(" " * (self.width - cur))

    # ── line renderers ────────────────────────────────────────────────────

    def _output_padding(self, t: Text) -> None:
        for col in self.new_columns:
            _ch(t, col.color, "|")
            t.append(" ")

    def _output_pre_commit(self, t: Text) -> None:
        assert self.commit is not None
        seen = False
        for i, col in enumerate(self.columns):
            if col.sha == self.commit.sha:
                seen = True
                _ch(t, col.color, "|")
                t.append(" " * self.expansion_row)
            elif seen and self.expansion_row == 0:
                if (self.prev_state == _GS.POST_MERGE
                        and self.prev_commit_index < i):
                    _ch(t, col.color, "\\")
                else:
                    _ch(t, col.color, "|")
            elif seen:
                _ch(t, col.color, "\\")
            else:
                _ch(t, col.color, "|")
            t.append(" ")

        self.expansion_row += 1
        if not self._needs_pre_commit_line():
            self._update_state(_GS.COMMIT)

    def _output_commit(self, t: Text) -> None:
        assert self.commit is not None
        seen = False
        num_cols = len(self.columns)

        for i in range(num_cols + 1):
            if i == num_cols:
                if seen:
                    break
                col_sha   = self.commit.sha
                col_color = self._find_commit_color(self.commit.sha)
            else:
                col_sha   = self.columns[i].sha
                col_color = self.columns[i].color

            if col_sha == self.commit.sha:
                seen = True
                _ch(t, col_color, "*")
                if self.num_parents > 2:
                    self._draw_octopus_merge(t)
            elif seen and self.edges_added > 1:
                _ch(t, col_color, "\\")
            elif seen and self.edges_added == 1:
                if (self.prev_state == _GS.POST_MERGE
                        and self.prev_edges_added > 0
                        and self.prev_commit_index < i):
                    _ch(t, col_color, "\\")
                else:
                    _ch(t, col_color, "|")
            elif (self.prev_state == _GS.COLLAPSING
                  and i < len(self.old_mapping) // 2
                  and self.old_mapping[2 * i + 1] == i
                  and 2 * i < len(self.mapping)
                  and self.mapping[2 * i] < i):
                _ch(t, col_color, "/")
            else:
                _ch(t, col_color, "|")
            t.append(" ")

        if self.num_parents > 1:
            self._update_state(_GS.POST_MERGE)
        elif self._is_mapping_correct():
            self._update_state(_GS.PADDING)
        else:
            self._update_state(_GS.COLLAPSING)

    def _draw_octopus_merge(self, t: Text) -> None:
        dashed = self._num_dashed_parents()
        for i in range(dashed):
            mi = (self.commit_index + i + 2) * 2
            if mi < len(self.mapping) and self.mapping[mi] >= 0:
                col = self.new_columns[self.mapping[mi]]
                _ch(t, col.color, "-")
                _ch(t, col.color, "." if i == dashed - 1 else "-")

    def _output_post_merge(self, t: Text) -> None:
        assert self.commit is not None
        merge_chars = ["/", "|", "\\"]
        seen        = False
        num_cols    = len(self.columns)

        first_parent_sha = self.commit.parents[0] if self.commit.parents else None
        parent_col_color: Optional[int] = None

        for i in range(num_cols + 1):
            if i == num_cols:
                if seen:
                    break
                col_sha   = self.commit.sha
                col_color = self._find_commit_color(self.commit.sha)
            else:
                col_sha   = self.columns[i].sha
                col_color = self.columns[i].color

            if col_sha == self.commit.sha:
                seen     = True
                idx      = self.merge_layout
                parents  = list(self.commit.parents)
                for j, p_sha in enumerate(parents):
                    pc = self._find_new_column_by_sha(p_sha)
                    if pc < 0:
                        continue
                    p_color = self.new_columns[pc].color
                    _ch(t, p_color, merge_chars[idx])
                    if idx == 2:
                        if self.edges_added > 0 or j < len(parents) - 1:
                            t.append(" ")
                    else:
                        idx += 1
                if self.edges_added == 0:
                    t.append(" ")
            elif seen:
                if self.edges_added > 0:
                    _ch(t, col_color, "\\")
                else:
                    _ch(t, col_color, "|")
                t.append(" ")
            else:
                _ch(t, col_color, "|")
                if (self.merge_layout != 0 or i != self.commit_index - 1):
                    if parent_col_color is not None:
                        _ch(t, parent_col_color, "_")
                    else:
                        t.append(" ")

            if first_parent_sha is not None and i < num_cols:
                if self.columns[i].sha == first_parent_sha:
                    parent_col_color = self.columns[i].color

        if self._is_mapping_correct():
            self._update_state(_GS.PADDING)
        else:
            self._update_state(_GS.COLLAPSING)

    def _output_collapsing(self, t: Text) -> None:
        """Mirror graph_output_collapsing_line from graph.c."""
        self.mapping, self.old_mapping = self.old_mapping, self.mapping

        map_size = len(self.old_mapping)
        self.mapping = [-1] * map_size

        used_horizontal        = False
        horizontal_edge        = -1
        horizontal_edge_target = -1

        for i in range(map_size):
            target = self.old_mapping[i]
            if target < 0:
                continue

            if target * 2 == i:
                self.mapping[i] = target
            elif i > 0 and self.mapping[i - 1] < 0:
                self.mapping[i - 1] = target
                if horizontal_edge == -1:
                    horizontal_edge        = i
                    horizontal_edge_target = target
                    j = (target * 2) + 3
                    while j < i - 2:
                        self.mapping[j] = target
                        j += 2
            elif i > 0 and self.mapping[i - 1] == target:
                pass
            else:
                if i >= 2:
                    self.mapping[i - 2] = target
                if horizontal_edge == -1:
                    horizontal_edge_target = target
                    horizontal_edge        = i - 1
                    j = (target * 2) + 3
                    while j < i - 2:
                        self.mapping[j] = target
                        j += 2

        self.old_mapping = self.mapping[:]

        while len(self.mapping) > 1 and self.mapping[-1] < 0:
            self.mapping.pop()
        map_size = len(self.mapping)

        for i in range(map_size):
            target = self.mapping[i]
            if target < 0:
                t.append(" ")
            elif target * 2 == i:
                col = self.new_columns[target]
                _ch(t, col.color, "|")
            elif (target == horizontal_edge_target
                  and i != horizontal_edge - 1):
                if i != (target * 2) + 3:
                    self.mapping[i] = -1
                used_horizontal = True
                col = self.new_columns[target]
                _ch(t, col.color, "_")
            else:
                if used_horizontal and i < horizontal_edge:
                    self.mapping[i] = -1
                col = self.new_columns[target]
                _ch(t, col.color, "/")

        if self._is_mapping_correct():
            self._update_state(_GS.PADDING)

    def _is_mapping_correct(self) -> bool:
        for i, target in enumerate(self.mapping):
            if target < 0:
                continue
            if target != i // 2:
                return False
        return True


def build_graph(
    commits: list[CommitInfo],
) -> list[tuple[CommitInfo, list[Text]]]:
    """
    Returns list of (CommitInfo, graph_lines) where graph_lines is a list
    of Rich Text objects — one per screen row — rendered exactly like
    `git log --graph --color`.

    Uses the same state machine as git's graph.c:
      PADDING → PRE_COMMIT → COMMIT → POST_MERGE → COLLAPSING → PADDING
    Characters: * | \\ / _ . -  (ASCII only, 2 screen columns per lane)
    """
    commits = _topo_sort(commits)
    g       = _Graph()
    g.known_shas = {c.sha for c in commits}

    # Pass 1: flat stream of (Text, commit_or_None)
    flat: list[tuple[Text, Optional[CommitInfo]]] = []

    for commit in commits:
        g.graph_update(commit)
        while not g.graph_is_commit_finished():
            line, is_commit = g.graph_next_line()
            flat.append((line, commit if is_commit else None))

    # Pass 2: group lines — commit node line + trailing connector lines
    # all belong to the same CommitItem.
    output: list[tuple[CommitInfo, list[Text]]] = []
    current_commit: Optional[CommitInfo] = None
    current_lines:  list[Text] = []

    for line, commit in flat:
        if commit is not None:
            if current_commit is not None:
                output.append((current_commit, current_lines))
            current_commit = commit
            current_lines  = [line]
        else:
            if current_commit is not None:
                current_lines.append(line)

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

        # Info cell as markup string
        info_cell = (
            f"[bold]{msg_text}[/bold]\n"
            f"[cyan]{sha}[/cyan]  [dim]{date}  {who}[/dim]"
        )
        # Pad info to match graph height
        info_height = 2
        while info_height < graph_height:
            info_cell += "\n"
            info_height += 1

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

    def __init__(self, initial_repo: str = "") -> None:
        super().__init__()
        self._initial_repo = initial_repo
        self._owner = ""
        self._repo = ""
        self._page = 1
        self._commits: list[CommitInfo] = []
        self._current_sha: str = ""
        self._graph_col_width: int = 20

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
        except Exception as e:
            self.notify(f"Could not load repo info: {e}", severity="warning")

    @work
    async def _fetch_commits(self, replace: bool) -> None:
        spinner = self.query_one("#spinner")
        spinner.display = True
        
        try:
            if replace:
                # First load: fetch from all branches for a proper multi-branch graph
                new_commits = await self.current_provider.fetch_all_commits(
                    self._owner, self._repo, count=100
                )
                self._commits = new_commits
            else:
                # "Load more": append additional commits from default branch
                new_commits = await self.current_provider.fetch_commits(
                    self._owner, self._repo, self._page
                )
                if not new_commits:
                    self.notify("No more commits.", severity="information")
                    return
                # Deduplicate against existing commits
                seen = {c.sha for c in self._commits}
                for c in new_commits:
                    if c.sha not in seen:
                        self._commits.append(c)
                        seen.add(c.sha)
            
            lv = self.query_one("#commits-list", ListView)
            await lv.clear()

            # Rebuild full graph from all accumulated commits for consistency
            graph_data = build_graph(self._commits)

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
