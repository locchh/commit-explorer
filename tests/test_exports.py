"""Tests for the write_export and write_commit_export file writers."""

from __future__ import annotations

import io
import pathlib

import pytest

from commit_explorer.export import write_commit_export, write_export
from commit_explorer.models import (
    BranchComparison,
    CommitDetail,
    CommitInfo,
    ConflictFile,
    FileChange,
    PRMetadata,
)


def _make_branch_comparison(**overrides) -> BranchComparison:
    defaults = dict(
        base="main",
        target="feature",
        stat_summary="1 file changed, 2 insertions(+), 1 deletion(-)",
        file_changes=[
            FileChange(filename="src/app.py", status="modified",
                       additions=2, deletions=1),
        ],
        unique_commits=[
            CommitInfo(
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
    return BranchComparison(**defaults)


class TestWriteExport:
    def test_writes_file_and_returns_path(self, tmp_path):
        result = _make_branch_comparison()
        path = write_export(result, out_dir=str(tmp_path))
        assert pathlib.Path(path).exists()
        assert pathlib.Path(path).parent == tmp_path
        assert pathlib.Path(path).name.startswith("compare-main-feature-")
        assert pathlib.Path(path).suffix == ".txt"

    def test_contents_include_all_sections(self, tmp_path):
        result = _make_branch_comparison()
        path = write_export(result, out_dir=str(tmp_path))
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
        path = write_export(result, out_dir=str(tmp_path))
        assert "WARNING" in pathlib.Path(path).read_text(encoding="utf-8")

    def test_conflicts_rendered(self, tmp_path):
        conflict = ConflictFile(
            filename="src/conflict.py",
            conflict_text="<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>>\n",
        )
        result = _make_branch_comparison(conflicts=[conflict])
        text = pathlib.Path(
            write_export(result, out_dir=str(tmp_path))
        ).read_text(encoding="utf-8")
        assert "src/conflict.py" in text
        assert "<<<<<<<" in text

    def test_with_pr_metadata_filename(self, tmp_path):
        result = _make_branch_comparison()
        pr = PRMetadata(
            provider="github", owner="octo", repo="repo", number=42,
            title="Add feature", state="open", author="alice",
            base="main", head="feature", url="https://github.com/octo/repo/pull/42",
            head_clone_url="https://github.com/octo/repo.git",
            head_owner="octo", description="Body text here",
        )
        path = write_export(result, pr_meta=pr, out_dir=str(tmp_path))
        assert pathlib.Path(path).name.startswith("compare-octo-repo-pr42-")
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert "Add feature" in text
        assert "Body text here" in text
        assert "pull/42" in text


class TestWriteCommitExport:
    @pytest.fixture
    def detail(self) -> CommitDetail:
        info = CommitInfo(
            sha="c" * 40,
            short_sha="c" * 7,
            message="feat: add feature",
            author="Alice",
            author_email="a@example.com",
            date="2024-01-15T10:00:00",
            parents=["b" * 40],
        )
        return CommitDetail(
            info=info,
            stats={"additions": 5, "deletions": 2, "total": 1},
            files=[FileChange("src/x.py", "modified", 5, 2)],
            refs=[],
            linked_prs=[],
        )

    def test_filename_format(self, detail, cloned_backend, tmp_path):
        path = write_commit_export(detail, cloned_backend.tmpdir, str(tmp_path))
        name = pathlib.Path(path).name
        assert name.startswith("20240115_")
        assert "feat-add-feature" in name
        assert name.endswith(".txt")

    def test_initial_commit_has_placeholder(self, cloned_backend, tmp_path):
        info = CommitInfo(
            sha="d" * 40, short_sha="d" * 7,
            message="initial", author="A", author_email="a@x",
            date="2024-01-01T00:00:00", parents=[],
        )
        detail = CommitDetail(
            info=info,
            stats={"additions": 0, "deletions": 0, "total": 0},
            files=[], refs=[], linked_prs=[],
        )
        path = write_commit_export(detail, cloned_backend.tmpdir, str(tmp_path))
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert "No diff available (initial commit)." in text

    @pytest.mark.network
    def test_real_commit_export(self, cloned_backend, known_shas, tmp_path):
        detail = cloned_backend.get_detail(known_shas["non_merge"])
        path = write_commit_export(detail, cloned_backend.tmpdir, str(tmp_path))
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert detail.info.sha in text
        assert "FULL DIFF" in text
        assert "DIFF SUMMARY" in text


class TestStreamMode:
    """T012 — stream= writes to IO object and returns None; out_dir still returns path."""

    def test_write_export_stream_returns_none(self, tmp_path):
        result = _make_branch_comparison()
        buf = io.StringIO()
        r = write_export(result, stream=buf)
        assert r is None
        text = buf.getvalue()
        assert "DIFF SUMMARY" in text
        assert "src/app.py" in text
        # No files created
        assert list(tmp_path.iterdir()) == []

    def test_write_export_rejects_both_destinations(self, tmp_path):
        result = _make_branch_comparison()
        with pytest.raises(ValueError):
            write_export(result, out_dir=str(tmp_path), stream=io.StringIO())

    def test_write_export_rejects_neither_destination(self):
        result = _make_branch_comparison()
        with pytest.raises(ValueError):
            write_export(result)

    def test_write_export_out_dir_still_returns_path(self, tmp_path):
        result = _make_branch_comparison()
        path = write_export(result, out_dir=str(tmp_path))
        assert path is not None
        assert pathlib.Path(path).exists()

    def test_write_commit_export_stream_returns_none(self, tmp_path, cloned_backend):
        info = CommitInfo(
            sha="e" * 40, short_sha="e" * 7,
            message="stream test", author="A", author_email="a@x",
            date="2024-02-01T00:00:00", parents=[],
        )
        detail = CommitDetail(
            info=info,
            stats={"additions": 0, "deletions": 0, "total": 0},
            files=[], refs=[], linked_prs=[],
        )
        buf = io.StringIO()
        r = write_commit_export(detail, cloned_backend.tmpdir, stream=buf)
        assert r is None
        assert "Commit:    " + info.sha in buf.getvalue()

    def test_write_commit_export_rejects_both_destinations(self, cloned_backend, tmp_path):
        info = CommitInfo(
            sha="f" * 40, short_sha="f" * 7,
            message="x", author="A", author_email="a@x",
            date="2024-02-01T00:00:00", parents=[],
        )
        detail = CommitDetail(
            info=info, stats={"additions": 0, "deletions": 0, "total": 0},
            files=[], refs=[], linked_prs=[],
        )
        with pytest.raises(ValueError):
            write_commit_export(
                detail, cloned_backend.tmpdir,
                out_dir=str(tmp_path), stream=io.StringIO(),
            )


class TestSectionControl:
    """T029 — include_files / include_diff / file_filter selectively strip output."""

    def test_include_diff_false_omits_full_diff(self):
        result = _make_branch_comparison()
        buf = io.StringIO()
        write_export(result, stream=buf, include_diff=False)
        out = buf.getvalue()
        assert "FULL DIFF" not in out
        assert "CONFLICTS" not in out
        # metadata + file list still present
        assert "DIFF SUMMARY" in out
        assert "CHANGED FILES" in out

    def test_include_files_false_omits_file_list(self):
        result = _make_branch_comparison()
        buf = io.StringIO()
        write_export(result, stream=buf, include_files=False)
        out = buf.getvalue()
        assert "CHANGED FILES" not in out
        assert "COMMIT LOG" not in out
        # FULL DIFF still present (include_diff defaults True)
        assert "FULL DIFF" in out

    def test_summary_shape_both_false(self):
        result = _make_branch_comparison()
        buf = io.StringIO()
        write_export(result, stream=buf, include_files=False, include_diff=False)
        out = buf.getvalue()
        assert "FULL DIFF" not in out
        assert "CHANGED FILES" not in out
        assert "CONFLICTS" not in out
        assert "DIFF SUMMARY" in out  # stat summary always present

    def test_file_filter_restricts_full_diff(self):
        result = _make_branch_comparison(
            full_diff=(
                "diff --git a/src/app.py b/src/app.py\n+app change\n"
                "diff --git a/src/other.py b/src/other.py\n+other change\n"
            ),
        )
        buf = io.StringIO()
        write_export(result, stream=buf, file_filter=["src/app.py"])
        out = buf.getvalue()
        assert "app change" in out
        assert "other change" not in out

    def test_commit_export_include_diff_false(self, cloned_backend):
        info = CommitInfo(
            sha="a" * 40, short_sha="a" * 7,
            message="no-diff test", author="A", author_email="a@x",
            date="2024-01-01T00:00:00", parents=["b" * 40],
        )
        detail = CommitDetail(
            info=info, stats={"additions": 0, "deletions": 0, "total": 0},
            files=[FileChange("x.py", "modified", 0, 0)],
            refs=[], linked_prs=[],
        )
        buf = io.StringIO()
        write_commit_export(detail, cloned_backend.tmpdir, stream=buf, include_diff=False)
        out = buf.getvalue()
        assert "FULL DIFF" not in out
        assert "CHANGED FILES" in out
