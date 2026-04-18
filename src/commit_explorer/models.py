"""NamedTuple data classes shared across the package."""

from __future__ import annotations

from typing import NamedTuple, Optional


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
    refs: list[str]
    linked_prs: list[dict]


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


class PRMetadata(NamedTuple):
    provider: str        # "github" or "gitlab"
    owner: str
    repo: str
    number: int
    title: str
    state: str           # open / closed / merged
    author: str
    base: str
    head: str
    url: str
    head_clone_url: str
    head_owner: str
    description: str


class BranchComparison(NamedTuple):
    base: str
    target: str
    stat_summary: str
    file_changes: list[FileChange]
    unique_commits: list[CommitInfo]
    conflicts: list[ConflictFile]
    shallow_warning: bool
    full_diff: str
    full_log: str
