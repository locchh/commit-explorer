"""_GitBackend integration tests against locchh/commit-explorer."""

from __future__ import annotations

import pytest
from rich.text import Text

import app


pytestmark = pytest.mark.network


class TestLoadAndPagination:
    def test_commits_loaded(self, cloned_backend):
        assert len(cloned_backend.all_commits) > 0
        # Every commit has a 40-char sha.
        for c in cloned_backend.all_commits[:5]:
            assert len(c.sha) == 40
            assert c.short_sha == c.sha[:7]

    def test_graph_data_parallel_to_commits(self, cloned_backend):
        graph = cloned_backend.graph_data
        assert len(graph) == len(cloned_backend.all_commits)
        commit, lines = graph[0]
        assert isinstance(commit, app.CommitInfo)
        assert lines and all(isinstance(line, Text) for line in lines)

    def test_pagination(self):
        """Uses its own backend to exercise stateful pagination."""
        backend = app._GitBackend()
        try:
            import asyncio

            url = app.GitHubProvider().clone_url("locchh", "commit-explorer")
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
        assert isinstance(detail, app.CommitDetail)
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
        resolved = app._resolve_sha(cloned_backend._tmpdir, known_shas["head"])
        assert resolved == known_shas["head"]

    def test_short_sha(self, cloned_backend, known_shas):
        resolved = app._resolve_sha(cloned_backend._tmpdir, known_shas["head_short"])
        assert resolved == known_shas["head"]

    def test_unknown_sha_returns_none(self, cloned_backend):
        assert app._resolve_sha(cloned_backend._tmpdir, "deadbeef") is None


class TestCompareBranches:
    def test_self_comparison_yields_no_changes(self, cloned_backend):
        result = cloned_backend.compare_branches("master", "master")
        assert isinstance(result, app.BranchComparison)
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
        graph = app._build_graph_from_git(cloned_backend._tmpdir)
        assert graph
        info, lines = graph[0]
        assert isinstance(info, app.CommitInfo)
        assert all(isinstance(line, Text) for line in lines)


class TestCleanup:
    def test_cleanup_clears_state(self):
        backend = app._GitBackend()
        import asyncio

        try:
            url = app.GitHubProvider().clone_url("locchh", "commit-explorer")
            asyncio.run(backend.load(url, depth=5))
        except Exception as exc:
            backend.cleanup()
            pytest.skip(f"clone failed: {exc}")

        tmp = backend._tmpdir
        assert tmp is not None
        backend.cleanup()
        import os

        assert backend._tmpdir is None
        assert backend.all_commits == []
        assert backend.graph_data == []
        assert backend.shown == 0
        assert not os.path.exists(tmp)
