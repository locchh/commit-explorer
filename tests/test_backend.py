"""GitBackend integration tests against locchh/commit-explorer."""

from __future__ import annotations

import asyncio
import os

import pytest
from rich.text import Text

from commit_explorer.backend import GitBackend, build_graph, resolve_sha
from commit_explorer.models import BranchComparison, CommitDetail, CommitInfo
from commit_explorer.providers import GitHubProvider


pytestmark = pytest.mark.network


class TestLoadAndPagination:
    def test_commits_loaded(self, cloned_backend):
        assert len(cloned_backend.all_commits) > 0
        for c in cloned_backend.all_commits[:5]:
            assert len(c.sha) == 40
            assert c.short_sha == c.sha[:7]

    def test_graph_data_parallel_to_commits(self, cloned_backend):
        graph = cloned_backend.graph_data
        assert len(graph) == len(cloned_backend.all_commits)
        commit, lines = graph[0]
        assert isinstance(commit, CommitInfo)
        assert lines and all(isinstance(line, Text) for line in lines)

    def test_pagination(self):
        """Uses its own backend to exercise stateful pagination."""
        backend = GitBackend()
        try:
            url = GitHubProvider().clone_url("locchh", "commit-explorer")
            asyncio.run(backend.load(url, depth=None))
        except Exception as exc:
            backend.cleanup()
            pytest.skip(f"clone failed: {exc}")

        try:
            assert backend.shown == 0
            first = backend.next_page()
            assert len(first) == min(backend._PER_PAGE, len(backend.graph_data))
            assert backend.shown == len(first)

            total_pages = [first]
            while backend.has_more():
                total_pages.append(backend.next_page())
            flat = [c for page in total_pages for c, _ in page]
            assert len(flat) == len(backend.graph_data)
            assert backend.has_more() is False
        finally:
            backend.cleanup()


class TestGetDetail:
    def test_returns_commit_detail(self, cloned_backend, known_shas):
        detail = cloned_backend.get_detail(known_shas["non_merge"])
        assert isinstance(detail, CommitDetail)
        assert detail.info.sha == known_shas["non_merge"]
        assert isinstance(detail.files, list)
        assert set(detail.stats.keys()) == {"additions", "deletions", "total"}
        assert detail.stats["total"] == len(detail.files)

    def test_non_merge_commit_has_file_changes(self, cloned_backend, known_shas):
        detail = cloned_backend.get_detail(known_shas["non_merge"])
        assert len(detail.files) >= 1
        valid_statuses = {"added", "modified", "removed", "renamed"}
        for fc in detail.files:
            assert fc.status in valid_statuses


class TestRepoInfo:
    def test_default_branch_is_master(self, cloned_backend):
        info = cloned_backend.get_repo_info()
        assert info.default_branch == "master"
        assert info.total_commits == len(cloned_backend.all_commits)
        assert info.branches is not None and info.branches >= 1


class TestResolveSha:
    def test_full_sha(self, cloned_backend, known_shas):
        resolved = resolve_sha(cloned_backend.tmpdir, known_shas["head"])
        assert resolved == known_shas["head"]

    def test_short_sha(self, cloned_backend, known_shas):
        resolved = resolve_sha(cloned_backend.tmpdir, known_shas["head_short"])
        assert resolved == known_shas["head"]

    def test_unknown_sha_returns_none(self, cloned_backend):
        assert resolve_sha(cloned_backend.tmpdir, "deadbeef") is None


class TestCompareBranches:
    def test_self_comparison_yields_no_changes(self, cloned_backend):
        result = cloned_backend.compare_branches("master", "master")
        assert isinstance(result, BranchComparison)
        assert result.base == "master"
        assert result.target == "master"
        assert result.file_changes == []
        assert result.unique_commits == []
        assert result.conflicts == []


class TestDetectConflicts:
    def test_self_compare_no_conflicts(self, cloned_backend):
        assert cloned_backend.detect_conflicts("master", "master") == []


class TestBuildGraph:
    def test_returns_commit_tuples(self, cloned_backend):
        graph = build_graph(cloned_backend.tmpdir)
        assert graph
        info, lines = graph[0]
        assert isinstance(info, CommitInfo)
        assert all(isinstance(line, Text) for line in lines)


class TestCleanup:
    def test_cleanup_clears_state(self):
        backend = GitBackend()
        try:
            url = GitHubProvider().clone_url("locchh", "commit-explorer")
            asyncio.run(backend.load(url, depth=5))
        except Exception as exc:
            backend.cleanup()
            pytest.skip(f"clone failed: {exc}")

        tmp = backend.tmpdir
        assert tmp is not None
        backend.cleanup()

        assert backend.tmpdir is None
        assert backend.all_commits == []
        assert backend.graph_data == []
        assert backend.shown == 0
        assert not os.path.exists(tmp)
