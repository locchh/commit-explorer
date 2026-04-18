"""Pure-function helper tests. No network required."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

import app


class TestFmtDate:
    def test_iso_with_z(self):
        assert app.fmt_date("2024-01-15T12:34:56Z") == "2024-01-15 12:34"

    def test_iso_with_offset(self):
        assert app.fmt_date("2024-01-15T12:34:56+00:00") == "2024-01-15 12:34"

    def test_iso_date_only(self):
        # fromisoformat accepts "YYYY-MM-DD"
        assert app.fmt_date("2024-01-15") == "2024-01-15 00:00"

    def test_unparseable_falls_back_to_prefix(self):
        assert app.fmt_date("not a date") == "not a date"[:16]

    def test_empty(self):
        assert app.fmt_date("") == ""


class TestSlugify:
    def test_basic(self):
        assert app._slugify("Hello World") == "hello-world"

    def test_punctuation_runs(self):
        assert app._slugify("feat: add CLI export!!!") == "feat-add-cli-export"

    def test_unicode_stripped(self):
        assert app._slugify("café — résumé") == "caf-r-sum"

    def test_max_length_40(self):
        long = "a" * 80
        assert len(app._slugify(long)) == 40

    def test_leading_trailing_dashes_stripped(self):
        assert app._slugify("---hi---") == "hi"

    def test_empty(self):
        assert app._slugify("") == ""


class TestParseClassicMergeTree:
    def test_no_conflicts_returns_empty(self):
        assert app._parse_classic_merge_tree("") == []

    def test_detects_conflict_block(self):
        sample = (
            "changed in both\n"
            "  base  100644 aaaaaaa  path/to/file\n"
            "  our   100644 bbbbbbb  path/to/file\n"
            "  their 100644 ccccccc  path/to/file\n"
            "@@@ -1,3 -1,3 +1,9 @@@\n"
            " context line\n"
            "+<<<<<<< .our\n"
            "+ours content\n"
            "+=======\n"
            "+theirs content\n"
            "+>>>>>>> .their\n"
        )
        conflicts = app._parse_classic_merge_tree(sample)
        assert len(conflicts) == 1
        assert conflicts[0].filename == "path/to/file"
        assert "<<<<<<<" in conflicts[0].conflict_text
        assert "ours content" in conflicts[0].conflict_text
        assert "theirs content" in conflicts[0].conflict_text

    def test_ignores_non_conflict_sections(self):
        sample = (
            "changed in both\n"
            "  base  100644 a  some/file\n"
            "  our   100644 b  some/file\n"
            "  their 100644 c  some/file\n"
            "@@@ -1 -1 +1 @@@\n"
            " harmless\n"
        )
        assert app._parse_classic_merge_tree(sample) == []


def _fake_urlopen(response_bytes: bytes):
    """Build a context-manager mock of urllib.request.urlopen."""
    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

        def read(self_inner):
            return response_bytes

    def _factory(req, timeout=None):  # noqa: ARG001
        return _Resp()

    return _factory


class TestResolvePrUrl:
    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            app._resolve_pr_url("https://example.com/not/a/pr")

    def test_github_pr_parsed(self, clean_env):
        payload = {
            "title": "Fix bug",
            "state": "open",
            "merged": False,
            "user": {"login": "octo"},
            "base": {"ref": "main"},
            "head": {
                "ref": "feature-x",
                "repo": {"name": "repo", "owner": {"login": "forker"}},
            },
            "body": "PR description",
        }
        fake = _fake_urlopen(json.dumps(payload).encode())
        with patch("urllib.request.urlopen", fake):
            meta = app._resolve_pr_url("https://github.com/octo/repo/pull/42")
        assert meta.provider == "github"
        assert meta.owner == "octo"
        assert meta.repo == "repo"
        assert meta.number == 42
        assert meta.title == "Fix bug"
        assert meta.state == "open"
        assert meta.author == "octo"
        assert meta.base == "main"
        assert meta.head == "feature-x"
        assert meta.head_owner == "forker"
        assert meta.description == "PR description"
        assert "forker/repo.git" in meta.head_clone_url

    def test_github_pr_merged_state(self, clean_env):
        payload = {
            "title": "t",
            "state": "closed",
            "merged": True,
            "user": {"login": "u"},
            "base": {"ref": "main"},
            "head": {"ref": "f", "repo": {"name": "r", "owner": {"login": "o"}}},
        }
        fake = _fake_urlopen(json.dumps(payload).encode())
        with patch("urllib.request.urlopen", fake):
            meta = app._resolve_pr_url("https://github.com/o/r/pull/1")
        assert meta.state == "merged"

    def test_gitlab_mr_parsed(self, clean_env):
        payload = {
            "title": "MR title",
            "state": "opened",
            "author": {"username": "alice"},
            "target_branch": "main",
            "source_branch": "feat",
            "source_namespace": {"full_path": "alice"},
            "source": {"http_url_to_repo": "https://gitlab.com/alice/proj.git"},
            "description": "Does thing",
        }
        fake = _fake_urlopen(json.dumps(payload).encode())
        with patch("urllib.request.urlopen", fake):
            meta = app._resolve_pr_url(
                "https://gitlab.com/grp/proj/-/merge_requests/7"
            )
        assert meta.provider == "gitlab"
        assert meta.repo == "proj"
        assert meta.number == 7
        assert meta.author == "alice"
        assert meta.base == "main"
        assert meta.head == "feat"
        assert meta.description == "Does thing"
        assert meta.head_clone_url == "https://gitlab.com/alice/proj.git"
