"""Dulwich-backed git operations: clone, commit walk, diff, branch compare."""

from __future__ import annotations

import asyncio
import difflib
import io
import os
import re
import shutil
import ssl
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional

import urllib3
from rich.text import Text

from .models import (
    BranchComparison,
    CommitDetail,
    CommitInfo,
    ConflictFile,
    FileChange,
    RepoInfo,
)
from .pr import parse_classic_merge_tree


class GitBackend:
    """Bare-clone git backend using Dulwich. Stores the clone in a temp dir."""

    _PER_PAGE = 30

    def __init__(self) -> None:
        self._tmpdir: Optional[str] = None
        self._commits: list[CommitInfo] = []
        self._graph_data: list[tuple[CommitInfo, list[Text]]] = []
        self._shown: int = 0

    @property
    def tmpdir(self) -> Optional[str]:
        return self._tmpdir

    @property
    def all_commits(self) -> list[CommitInfo]:
        return self._commits

    @property
    def graph_data(self) -> list[tuple[CommitInfo, list[Text]]]:
        return self._graph_data

    @property
    def shown(self) -> int:
        return self._shown

    def has_more(self) -> bool:
        return self._shown < len(self._graph_data)

    def next_page(self) -> list[tuple[CommitInfo, list[Text]]]:
        end = min(self._shown + self._PER_PAGE, len(self._graph_data))
        page = self._graph_data[self._shown:end]
        self._shown = end
        return page

    async def load(self, url: str, depth: Optional[int] = None) -> None:
        self.cleanup()
        self._tmpdir = tempfile.mkdtemp(prefix="cex-")

        def _do_clone() -> None:
            from dulwich import porcelain

            disable_ssl_verify = os.getenv("GIT_SSL_NO_VERIFY", "").lower() in (
                "1", "true", "yes"
            )

            clone_kwargs: dict = {}
            if disable_ssl_verify:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                clone_kwargs["pool_manager"] = urllib3.PoolManager(
                    cert_reqs=ssl.CERT_NONE,
                    assert_hostname=False,
                )

            porcelain.clone(
                url,
                target=self._tmpdir,
                depth=depth,
                bare=True,
                filter_spec="blob:none",
                errstream=io.BytesIO(),
                **clone_kwargs,
            )

        await asyncio.to_thread(_do_clone)
        self._graph_data = await asyncio.to_thread(build_graph, self._tmpdir)
        self._commits = [c for c, _ in self._graph_data]
        self._shown = 0

    def get_detail(self, sha: str) -> CommitDetail:
        from dulwich.repo import Repo
        from dulwich.diff_tree import (
            tree_changes, CHANGE_ADD, CHANGE_DELETE, CHANGE_RENAME,
        )

        repo = Repo(self._tmpdir)
        c = repo[sha.encode()]

        parents = [p.decode() for p in c.parents]
        msg_full = c.message.decode("utf-8", errors="replace").strip()
        author_raw = c.author.decode("utf-8", errors="replace")
        m = re.match(r"^(.*?)\s*<(.*)>$", author_raw)
        author = m.group(1).strip() if m else author_raw
        email = m.group(2).strip() if m else ""
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
                    status = "added"
                    filename = change.new.path.decode("utf-8", errors="replace")
                elif change.type == CHANGE_DELETE:
                    status = "removed"
                    filename = change.old.path.decode("utf-8", errors="replace")
                elif change.type == CHANGE_RENAME:
                    status = "renamed"
                    filename = change.new.path.decode("utf-8", errors="replace")
                else:
                    status = "modified"
                    filename = (change.new.path or change.old.path).decode(
                        "utf-8", errors="replace"
                    )

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
                files.append(FileChange(
                    filename=filename, status=status,
                    additions=add, deletions=del_,
                ))
        except Exception:
            pass

        return CommitDetail(
            info=info,
            stats={"additions": total_add, "deletions": total_del, "total": len(files)},
            files=files,
            refs=[],
            linked_prs=[],
        )

    def get_repo_info(self) -> RepoInfo:
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
        r = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "fetch", "--all", "--quiet"],
            capture_output=True,
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", errors="replace").strip())

    def compare_branches(self, base: str, target: str) -> BranchComparison:
        """Fetch remotes and compare two branches."""
        self.fetch_all()

        base_ref = self._qualify_ref(base)
        target_ref = self._qualify_ref(target)

        shallow_warning = self._is_shallow()

        file_changes = self._diff_name_status(base_ref, target_ref)
        self._lazy_fetch_blobs(base_ref, target_ref)
        stat_summary = self._diff_shortstat(base_ref, target_ref, len(file_changes))
        file_changes = self._apply_stat_counts(base_ref, target_ref, file_changes)
        unique_commits = self._log_unique(base_ref, target_ref)
        full_diff = self._diff_full(base_ref, target_ref)
        full_log = self._log_full(base_ref, target_ref)

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
            full_diff=full_diff,
            full_log=full_log,
        )

    # ---- compare_branches helpers -------------------------------------------

    @staticmethod
    def _qualify_ref(ref: str) -> str:
        if "/" in ref and not ref.startswith("refs/") and ref.split("/")[0] in ("origin", "pr-head"):
            return ref
        return f"origin/{ref}"

    def _is_shallow(self) -> bool:
        try:
            r = subprocess.run(
                ["git", "--git-dir", self._tmpdir, "rev-parse", "--is-shallow-repository"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            )
            return r.stdout.strip() == "true"
        except Exception:
            return False

    def _diff_name_status(self, base_ref: str, target_ref: str) -> list[FileChange]:
        r = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "diff",
             base_ref, target_ref, "--name-status", "--no-color", "-z"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        STATUS_MAP = {
            "A": "added", "D": "removed", "M": "modified",
            "R": "renamed", "C": "copied", "T": "modified",
            "U": "modified", "X": "modified",
        }
        tokens = [t for t in r.stdout.split("\x00") if t]
        out: list[FileChange] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if not token:
                i += 1
                continue
            code = token[0].upper()
            if code in ("R", "C") and i + 2 < len(tokens):
                fname = tokens[i + 2]
                i += 3
            elif i + 1 < len(tokens):
                fname = tokens[i + 1]
                i += 2
            else:
                i += 1
                continue
            out.append(FileChange(
                filename=fname,
                status=STATUS_MAP.get(code, "modified"),
                additions=0, deletions=0,
            ))
        return out

    def _lazy_fetch_blobs(self, base_ref: str, target_ref: str) -> None:
        def _parts(ref: str) -> tuple[str, str]:
            for prefix in ("origin/", "pr-head/"):
                if ref.startswith(prefix):
                    return prefix.rstrip("/"), ref[len(prefix):]
            return "origin", ref

        for remote, branch in {_parts(base_ref), _parts(target_ref)}:
            try:
                subprocess.run(
                    ["git", "--git-dir", self._tmpdir,
                     "-c", "fetch.promisor=true",
                     "fetch", "--filter=blob:none", remote, branch],
                    capture_output=True, timeout=60,
                )
            except Exception:
                pass

    def _diff_shortstat(self, base_ref: str, target_ref: str, n_files: int) -> str:
        r = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "diff",
             base_ref, target_ref, "--shortstat", "--no-color"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        stat_summary = r.stdout.strip()
        if not stat_summary and n_files:
            stat_summary = f"{n_files} file(s) changed"
        return stat_summary

    def _apply_stat_counts(
        self, base_ref: str, target_ref: str, file_changes: list[FileChange]
    ) -> list[FileChange]:
        r = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "diff",
             base_ref, target_ref, "--stat", "--no-color"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        stat_by_file: dict[str, tuple[int, int]] = {}
        for sline in r.stdout.splitlines():
            sline = sline.strip()
            if not sline or "|" not in sline:
                continue
            fname_s, bar = sline.split("|", 1)
            fname_s = fname_s.strip()
            bar = bar.strip()
            if not fname_s or "changed" in bar:
                continue
            stat_by_file[fname_s] = (bar.count("+"), bar.count("-"))
        return [
            FileChange(
                filename=fc.filename, status=fc.status,
                additions=stat_by_file.get(fc.filename, (0, 0))[0],
                deletions=stat_by_file.get(fc.filename, (0, 0))[1],
            )
            for fc in file_changes
        ]

    def _log_unique(self, base_ref: str, target_ref: str) -> list[CommitInfo]:
        r = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "log",
             f"{base_ref}..{target_ref}",
             "--format=%H%x00%s%x00%aN%x00%aE%x00%ad%x00%P",
             "--date=short", "--no-color"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        commits: list[CommitInfo] = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            fields = line.split("\x00")
            sha = fields[0] if fields else ""
            if not sha:
                continue
            commits.append(CommitInfo(
                sha=sha, short_sha=sha[:7],
                message=fields[1] if len(fields) > 1 else "",
                author=fields[2] if len(fields) > 2 else "",
                author_email=fields[3] if len(fields) > 3 else "",
                date=fields[4] if len(fields) > 4 else "",
                parents=fields[5].split() if len(fields) > 5 and fields[5] else [],
            ))
        return commits

    def _diff_full(self, base_ref: str, target_ref: str) -> str:
        r = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "diff",
             base_ref, target_ref, "--no-color"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return r.stdout

    def _log_full(self, base_ref: str, target_ref: str) -> str:
        r = subprocess.run(
            ["git", "--git-dir", self._tmpdir, "log",
             f"{base_ref}..{target_ref}",
             "--stat", "--no-color", "--date=iso"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return r.stdout

    # ---- conflict detection --------------------------------------------------

    def detect_conflicts(self, base: str, target: str) -> list[ConflictFile]:
        """Detect merge conflicts between two remote branches."""
        base_ref = f"origin/{base}"
        target_ref = f"origin/{target}"

        # git >= 2.38
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
                        conflicts.append(ConflictFile(
                            filename=fname, conflict_text=blob_r.stdout,
                        ))
                return conflicts
        except Exception:
            pass

        # Fallback: classic `git merge-tree`
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
            return parse_classic_merge_tree(mt_r.stdout)
        except Exception:
            return []

    def cleanup(self) -> None:
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
        self._commits = []
        self._graph_data = []
        self._shown = 0


# ── Module-level helpers ──────────────────────────────────────────────────────

def build_graph(tmpdir: str) -> list[tuple[CommitInfo, list[Text]]]:
    """Run `git log --graph --color=always` and parse into (CommitInfo, graph_lines).

    Each commit line is identified by a NUL-delimited marker injected via
    --format so graph-prefix characters are cleanly separated from metadata.
    """
    MARKER = "\x01"
    fmt = f"{MARKER}%H%x00%s%x00%aN%x00%aE%x00%ad%x00%P"

    proc = subprocess.run(
        ["git", "--git-dir", tmpdir,
         "log", "--graph", "--color=always",
         f"--format={fmt}",
         "--date=short", "--all"],
        capture_output=True, encoding="utf-8", errors="replace",
    )

    output: list[tuple[CommitInfo, list[Text]]] = []
    current_commit: Optional[CommitInfo] = None
    current_lines: list[Text] = []

    for raw in proc.stdout.splitlines():
        if MARKER in raw:
            graph_part, data = raw.split(MARKER, 1)
            fields = data.split("\x00")
            sha = fields[0] if fields else ""
            if not sha:
                continue

            if current_commit is not None:
                output.append((current_commit, current_lines))

            current_commit = CommitInfo(
                sha=sha, short_sha=sha[:7],
                message=fields[1] if len(fields) > 1 else "",
                author=fields[2] if len(fields) > 2 else "",
                author_email=fields[3] if len(fields) > 3 else "",
                date=fields[4] if len(fields) > 4 else "",
                parents=fields[5].split() if len(fields) > 5 and fields[5] else [],
            )
            current_lines = [Text.from_ansi(graph_part)]
        else:
            if current_commit is not None:
                current_lines.append(Text.from_ansi(raw))

    if current_commit is not None:
        output.append((current_commit, current_lines))

    return output


def resolve_sha(tmpdir: str, sha: str) -> Optional[str]:
    """Resolve a short or full SHA via `git rev-parse`. Returns None on failure."""
    r = subprocess.run(
        ["git", "--git-dir", tmpdir, "rev-parse", "--verify", sha],
        capture_output=True, encoding="utf-8", errors="replace", timeout=10,
    )
    full = r.stdout.strip()
    return full if r.returncode == 0 and len(full) == 40 else None
