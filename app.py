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
from textual.screen import Screen
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

class ConflictFile(NamedTuple):
    filename: str
    conflict_text: str  # raw text containing <<<<<<< / ======= / >>>>>>> markers

class BranchComparison(NamedTuple):
    base: str
    target: str
    stat_summary: str         # shortstat line
    file_changes: list        # list[FileChange]
    unique_commits: list      # list[CommitInfo]
    conflicts: list           # list[ConflictFile]
    shallow_warning: bool

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
            import os
            import urllib3
            import ssl
            from dulwich import porcelain
            
            # Check if SSL verification should be disabled
            disable_ssl_verify = os.getenv("GIT_SSL_NO_VERIFY", "").lower() in ("1", "true", "yes")
            
            # Setup clone kwargs
            clone_kwargs = {}
            if disable_ssl_verify:
                # Disable warnings about unverified requests
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                
                # Create a custom pool manager that doesn't verify certificates
                # and pass it through to the GitClient
                pool_manager = urllib3.PoolManager(
                    cert_reqs=ssl.CERT_NONE,
                    assert_hostname=False
                )
                clone_kwargs['pool_manager'] = pool_manager
                
            porcelain.clone(
                url,
                target=self._tmpdir,
                depth=depth,
                bare=True,
                filter_spec="blob:none",  # skip file contents — commits+trees only
                errstream=io.BytesIO(),
                **clone_kwargs
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

    def fetch_all(self) -> None:
        """Fetch all remote refs into the existing bare clone."""
        import subprocess
        r = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "fetch", "--all", "--quiet"],
            capture_output=True,
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", errors="replace").strip())

    def compare_branches(self, base: str, target: str) -> "BranchComparison":
        """Fetch remotes and compare two branches. Returns a BranchComparison."""
        import subprocess

        self.fetch_all()

        base_ref = f"origin/{base}"
        target_ref = f"origin/{target}"

        # Shallow clone detection
        shallow_warning = False
        try:
            r = subprocess.run(
                ["git", "--git-dir", self._tmpdir, "rev-parse", "--is-shallow-repository"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            )
            if r.stdout.strip() == "true":
                shallow_warning = True
        except Exception:
            pass

        # Shortstat summary
        r_short = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "diff",
             base_ref, target_ref, "--shortstat", "--no-color"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        stat_summary = r_short.stdout.strip()

        # Per-file stat
        r_stat = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "diff",
             base_ref, target_ref, "--stat", "--no-color"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        file_changes: list[FileChange] = []
        for line in r_stat.stdout.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            fname, bar = line.split("|", 1)
            fname = fname.strip()
            bar = bar.strip()
            # Skip the summary line ("3 files changed …")
            if not fname or "changed" in bar:
                continue
            add = bar.count("+")
            del_ = bar.count("-")
            if add > 0 and del_ == 0:
                status = "added"
            elif del_ > 0 and add == 0:
                status = "removed"
            else:
                status = "modified"
            file_changes.append(FileChange(filename=fname, status=status,
                                           additions=add, deletions=del_))

        # Unique commits in target not in base
        r_log = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "log",
             f"{base_ref}..{target_ref}",
             "--format=%H%x00%s%x00%aN%x00%aE%x00%ad%x00%P",
             "--date=short", "--no-color"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        unique_commits: list[CommitInfo] = []
        for line in r_log.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            fields = line.split("\x00")
            sha = fields[0] if len(fields) > 0 else ""
            if not sha:
                continue
            unique_commits.append(CommitInfo(
                sha=sha, short_sha=sha[:7],
                message=fields[1] if len(fields) > 1 else "",
                author=fields[2] if len(fields) > 2 else "",
                author_email=fields[3] if len(fields) > 3 else "",
                date=fields[4] if len(fields) > 4 else "",
                parents=fields[5].split() if len(fields) > 5 and fields[5] else [],
            ))

        # Conflict detection (shallow repos may lack merge-base)
        conflicts: list[ConflictFile] = []
        if not shallow_warning:
            conflicts = self.detect_conflicts(base, target)

        return BranchComparison(
            base=base, target=target,
            stat_summary=stat_summary,
            file_changes=file_changes,
            unique_commits=unique_commits,
            conflicts=conflicts,
            shallow_warning=shallow_warning,
        )

    def detect_conflicts(self, base: str, target: str) -> "list[ConflictFile]":
        """Detect merge conflicts between two remote branches."""
        import subprocess

        base_ref = f"origin/{base}"
        target_ref = f"origin/{target}"

        # Try git merge-tree --write-tree (git >= 2.38)
        try:
            r = subprocess.run(
                ["git", "--git-dir", self._tmpdir, "-c", "core.bare=true",
                 "merge-tree", "--write-tree", "--no-messages", "--name-only",
                 base_ref, target_ref],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            if r.returncode == 0:
                return []
            if r.returncode == 1:
                # First line = merged tree SHA, rest = conflicted filenames
                lines = r.stdout.strip().splitlines()
                if not lines:
                    return []
                tree_sha = lines[0].strip()
                conflict_filenames = [l.strip() for l in lines[1:] if l.strip()]
                conflicts: list[ConflictFile] = []
                for fname in conflict_filenames:
                    blob_r = subprocess.run(
                        ["git", "--git-dir", self._tmpdir, "cat-file", "blob",
                         f"{tree_sha}:{fname}"],
                        capture_output=True, encoding="utf-8", errors="replace", timeout=10,
                    )
                    if blob_r.returncode == 0:
                        conflicts.append(ConflictFile(filename=fname,
                                                      conflict_text=blob_r.stdout))
                return conflicts
        except Exception:
            pass

        # Fallback: classic git merge-tree
        try:
            mb_r = subprocess.run(
                ["git", "--git-dir", self._tmpdir, "merge-base", base_ref, target_ref],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            if mb_r.returncode != 0:
                return []
            merge_base = mb_r.stdout.strip()
            if not merge_base:
                return []

            mt_r = subprocess.run(
                ["git", "--git-dir", self._tmpdir, "merge-tree",
                 merge_base, base_ref, target_ref],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            return _parse_classic_merge_tree(mt_r.stdout)
        except Exception:
            return []

    def cleanup(self) -> None:
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
        self._commits = []
        self._graph_data = []
        self._shown = 0

# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_classic_merge_tree(output: str) -> "list[ConflictFile]":
    """Parse output from classic `git merge-tree <base> <ours> <theirs>`.

    Sections look like:
        changed in both
          base  100644 <sha>  path/to/file
          our   100644 <sha>  path/to/file
          their 100644 <sha>  path/to/file
        @@@ -1,3 -1,3 +1,9 @@@
         context
        +<<<<<<< .our
        +ours
        +=======
        +theirs
        +>>>>>>> .their
    """
    conflicts: list[ConflictFile] = []
    current_file = ""
    in_diff = False
    diff_lines: list[str] = []
    has_conflict = False

    SECTION_HEADERS = (
        "changed in both", "added in both", "removed in both",
        "added in remote", "removed in remote",
        "added in local", "removed in local",
    )

    def _flush() -> None:
        nonlocal current_file, in_diff, diff_lines, has_conflict
        if current_file and has_conflict and diff_lines:
            content = []
            for dl in diff_lines:
                if dl.startswith("+"):
                    content.append(dl[1:])
                elif dl.startswith(" "):
                    content.append(dl[1:])
            conflicts.append(ConflictFile(
                filename=current_file,
                conflict_text="\n".join(content),
            ))
        current_file = ""
        in_diff = False
        diff_lines = []
        has_conflict = False

    for line in output.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(h) for h in SECTION_HEADERS):
            _flush()
        elif stripped.startswith("base ") or stripped.startswith("our ") or stripped.startswith("their "):
            # "  base  100644 sha  path/to/file" — last token is filename
            parts = stripped.split()
            if len(parts) >= 4 and not current_file:
                current_file = parts[-1]
        elif stripped.startswith("@@@") or stripped.startswith("@@"):
            in_diff = True
            diff_lines = []
        elif in_diff:
            diff_lines.append(line)
            if stripped.startswith("+<<<<<<<") or stripped.startswith("<<<<<<< "):
                has_conflict = True

    _flush()
    return conflicts


def _write_export(result: "BranchComparison") -> str:
    """Write a BranchComparison to a .txt file in the CWD. Returns the file path."""
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    base_safe = result.base.replace("/", "-")
    target_safe = result.target.replace("/", "-")
    filename = f"compare-{base_safe}-{target_safe}-{date_str}.txt"

    lines = [
        f"Compare: origin/{result.base} \u2192 origin/{result.target}",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if result.shallow_warning:
        lines.append("\u26a0 Shallow clone \u2014 commit log and conflict results may be incomplete")
    lines.append("")

    lines.append("\u2500\u2500 Diff Summary " + "\u2500" * 40)
    lines.append(result.stat_summary if result.stat_summary else "No differences.")
    lines.append("")

    lines.append(f"\u2500\u2500 Changed Files ({len(result.file_changes)}) " + "\u2500" * 36)
    for fc in result.file_changes:
        lines.append(f"  {fc.status[0].upper()} {fc.filename}  (+{fc.additions} -{fc.deletions})")
    if not result.file_changes:
        lines.append("  No file changes.")
    lines.append("")

    lines.append(f"\u2500\u2500 Commits ({len(result.unique_commits)}) " + "\u2500" * 40)
    for c in result.unique_commits:
        lines.append(f"  {c.short_sha}  {c.message}  {c.author}  {c.date}")
    if not result.unique_commits:
        lines.append("  No unique commits.")
    lines.append("")

    lines.append("\u2500\u2500 Conflicts " + "\u2500" * 43)
    if not result.conflicts:
        lines.append("Clean merge \u2014 no conflicts detected")
    else:
        for cf in result.conflicts:
            lines.append(f"File: {cf.filename}")
            lines.append(cf.conflict_text)
            lines.append("")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return filename


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

class CompareScreen(Screen):
    """Modal screen for comparing two remote branches."""

    BINDINGS = [Binding("escape", "dismiss", "Back")]

    CSS = """
    CompareScreen {
        background: $surface;
    }
    #compare-toolbar {
        height: 5;
        padding: 1;
        background: $panel;
        layout: horizontal;
    }
    #base-input    { width: 1fr; margin-right: 1; }
    #target-input  { width: 1fr; margin-right: 1; }
    #compare-btn   { width: 12; }
    #export-btn    { width: 12; margin-left: 1; }
    #compare-spinner { height: 3; display: none; }
    #compare-scroll  { height: 1fr; padding: 1 2; }
    """

    def __init__(self, backend: "_GitBackend") -> None:
        super().__init__()
        self._backend = backend
        self._last_result: Optional[BranchComparison] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="compare-toolbar"):
            yield Input(placeholder="Base branch (e.g. main)", id="base-input")
            yield Input(placeholder="Target branch (e.g. feature/foo)", id="target-input")
            yield Button("Compare", id="compare-btn", variant="primary")
            yield Button("Export", id="export-btn", disabled=True)
        yield LoadingIndicator(id="compare-spinner")
        with ScrollableContainer(id="compare-scroll"):
            yield Static("[dim]Enter branch names and press Compare.[/dim]",
                         id="compare-results")
        yield Footer()

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
                path = _write_export(self._last_result)
                self.notify(f"Exported to {path}")
            except Exception as e:
                self.notify(f"Export failed: {e}", severity="error")

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

        lines.append(
            f"[bold]Compare: [cyan]origin/{escape(result.base)}[/cyan]"
            f" \u2192 [cyan]origin/{escape(result.target)}[/cyan][/bold]"
        )
        lines.append("")

        lines.append("[bold cyan]\u2500\u2500 Diff Summary \u2500\u2500\u2500\u2500\u2500"
                     "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                     "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                     "\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/bold cyan]")
        lines.append(escape(result.stat_summary) if result.stat_summary else "[dim]No differences.[/dim]")
        lines.append("")

        lines.append(
            f"[bold cyan]\u2500\u2500 Changed Files ({len(result.file_changes)}) "
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500[/bold cyan]"
        )
        if result.file_changes:
            for fc in result.file_changes:
                color = {"added": "green", "removed": "red"}.get(fc.status, "yellow")
                stats = f"[dim](+{fc.additions} -{fc.deletions})[/dim]"
                lines.append(f"  [{color}]{fc.status[0].upper()}[/{color}] "
                              f"{escape(fc.filename)}  {stats}")
        else:
            lines.append("[dim]No file changes.[/dim]")
        lines.append("")

        lines.append(
            f"[bold cyan]\u2500\u2500 Commits ({len(result.unique_commits)}) "
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/bold cyan]"
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

        lines.append(
            "[bold cyan]\u2500\u2500 Conflicts \u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/bold cyan]"
        )
        if not result.conflicts:
            lines.append("[green]\u2713 Clean merge \u2014 no conflicts detected[/green]")
        else:
            for cf in result.conflicts:
                lines.append(f"[bold red]File: {escape(cf.filename)}[/bold red]")
                lines.append(escape(cf.conflict_text))
                lines.append("")

        return "\n".join(lines)


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

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "compare":
            return bool(self._owner)
        return True

    def action_compare(self) -> None:
        if self._owner:
            self.push_screen(CompareScreen(self._backend))

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
