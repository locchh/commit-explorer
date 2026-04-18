"""Tests for the _write_export and _write_commit_export file writers."""

from __future__ import annotations

import pathlib

import pytest

import app


def _make_branch_comparison(**overrides) -> app.BranchComparison:
    defaults = dict(
        base="main",
        target="feature",
        stat_summary="1 file changed, 2 insertions(+), 1 deletion(-)",
        file_changes=[
            app.FileChange(filename="src/app.py", status="modified",
                           additions=2, deletions=1),
        ],
        unique_commits=[
            app.CommitInfo(
                sha="a" * 40,
                short_sha="a" * 7,
                message="Feature commit",
                author="Alice",
                author_email="a@example.com",
                date="2024-01-15",
                parents=["b" * 40],
            ),
        ],
        conflicts=[],
        shallow_warning=False,
        full_diff="diff --git a/src/app.py b/src/app.py\n+added line\n-removed line\n",
        full_log="commit aaaaaaaaaa\nAuthor: Alice\n\n    Feature commit\n",
    )
    defaults.update(overrides)
    return app.BranchComparison(**defaults)


class TestWriteExport:
    def test_writes_file_and_returns_path(self, tmp_path):
        result = _make_branch_comparison()
        path = app._write_export(result, out_dir=str(tmp_path))
        assert pathlib.Path(path).exists()
        assert pathlib.Path(path).parent == tmp_path
        assert pathlib.Path(path).name.startswith("compare-main-feature-")
        assert pathlib.Path(path).suffix == ".txt"

    def test_contents_include_all_sections(self, tmp_path):
        result = _make_branch_comparison()
        path = app._write_export(result, out_dir=str(tmp_path))
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert "DIFF SUMMARY" in text
        assert "CHANGED FILES" in text
        assert "COMMIT LOG" in text
        assert "FULL DIFF" in text
        assert "CONFLICTS" in text
        assert "Clean merge" in text
        assert "src/app.py" in text
        assert "Feature commit" in text

    def test_shallow_warning_included(self, tmp_path):
        result = _make_branch_comparison(shallow_warning=True)
        path = app._write_export(result, out_dir=str(tmp_path))
        assert "WARNING" in pathlib.Path(path).read_text(encoding="utf-8")

    def test_conflicts_rendered(self, tmp_path):
        conflict = app.ConflictFile(
            filename="src/conflict.py",
            conflict_text="<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>>\n",
        )
        result = _make_branch_comparison(conflicts=[conflict])
        text = pathlib.Path(
            app._write_export(result, out_dir=str(tmp_path))
        ).read_text(encoding="utf-8")
        assert "src/conflict.py" in text
        assert "<<<<<<<" in text

    def test_with_pr_metadata_filename(self, tmp_path):
        result = _make_branch_comparison()
        pr = app.PRMetadata(
            provider="github", owner="octo", repo="repo", number=42,
            title="Add feature", state="open", author="alice",
            base="main", head="feature", url="https://github.com/octo/repo/pull/42",
            head_clone_url="https://github.com/octo/repo.git",
            head_owner="octo", description="Body text here",
        )
        path = app._write_export(result, pr_meta=pr, out_dir=str(tmp_path))
        assert pathlib.Path(path).name.startswith("compare-octo-repo-pr42-")
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert "Add feature" in text
        assert "Body text here" in text
        assert "pull/42" in text


class TestWriteCommitExport:
    @pytest.fixture
    def detail(self) -> app.CommitDetail:
        info = app.CommitInfo(
            sha="c" * 40,
            short_sha="c" * 7,
            message="feat: add feature",
            author="Alice",
            author_email="a@example.com",
            date="2024-01-15T10:00:00",
            parents=["b" * 40],
        )
        return app.CommitDetail(
            info=info,
            stats={"additions": 5, "deletions": 2, "total": 1},
            files=[app.FileChange("src/x.py", "modified", 5, 2)],
            refs=[],
            linked_prs=[],
        )

    def test_filename_format(self, detail, cloned_backend, tmp_path):
        path = app._write_commit_export(detail, cloned_backend._tmpdir, str(tmp_path))
        name = pathlib.Path(path).name
        # date_compact _ short_sha _ slug .txt
        assert name.startswith("20240115_")
        assert "feat-add-feature" in name
        assert name.endswith(".txt")

    def test_initial_commit_has_placeholder(self, cloned_backend, tmp_path):
        info = app.CommitInfo(
            sha="d" * 40, short_sha="d" * 7,
            message="initial", author="A", author_email="a@x",
            date="2024-01-01T00:00:00", parents=[],
        )
        detail = app.CommitDetail(info=info, stats={"additions": 0, "deletions": 0, "total": 0},
                                  files=[], refs=[], linked_prs=[])
        path = app._write_commit_export(detail, cloned_backend._tmpdir, str(tmp_path))
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert "No diff available (initial commit)." in text

    @pytest.mark.network
    def test_real_commit_export(self, cloned_backend, known_shas, tmp_path):
        detail = cloned_backend.get_detail(known_shas["non_merge"])
        path = app._write_commit_export(detail, cloned_backend._tmpdir, str(tmp_path))
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert detail.info.sha in text
        assert "FULL DIFF" in text
        assert "DIFF SUMMARY" in text
