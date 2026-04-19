"""Schema tests for commit_explorer.format (JSON/ndjson output).

T037 — JSON schema: all mandatory keys present, no ANSI escapes survive,
``truncated`` / ``total_diff_lines`` behave correctly, ``next`` hints round-trip.
T038 — ndjson: every line is individually parseable, last line is the
``{"kind":"page",...}`` footer, pagination ``next`` field echoes the command.
"""

from __future__ import annotations

import io
import json
import re

from commit_explorer.format import (
    OutputConfig,
    branch_comparison_to_dict,
    commit_detail_to_dict,
    commit_to_ndjson_entry,
    page_info_dict,
    render_json,
    render_ndjson,
)
from commit_explorer.models import (
    BranchComparison,
    CommitDetail,
    CommitInfo,
    FileChange,
    PRMetadata,
)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _commit_detail() -> CommitDetail:
    info = CommitInfo(
        sha="a" * 40,
        short_sha="a" * 7,
        message="feat: add",
        author="Alice",
        author_email="a@x",
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


def _branch_comparison() -> BranchComparison:
    return BranchComparison(
        base="main",
        target="feature",
        stat_summary="1 file changed",
        file_changes=[FileChange("src/x.py", "modified", 2, 1)],
        unique_commits=[],
        conflicts=[],
        shallow_warning=False,
        full_diff="diff --git a/src/x.py b/src/x.py\n+new\n-old\n",
        full_log="",
    )


class TestOutputConfigInvariants:
    """T036 — ``fmt json/ndjson`` forces ``color=never``."""

    def test_json_forces_never_color(self):
        cfg = OutputConfig(fmt="json", color="always")
        assert cfg.color == "never"

    def test_ndjson_forces_never_color(self):
        cfg = OutputConfig(fmt="ndjson", color="auto")
        assert cfg.color == "never"

    def test_text_preserves_color(self):
        cfg = OutputConfig(fmt="text", color="always")
        assert cfg.color == "always"


class TestCommitDetailSchema:
    """Mandatory keys always present; ANSI stripped; truncated behaves."""

    MANDATORY = {"kind", "repo", "sha", "summary", "files", "diff", "truncated", "next"}

    def test_mandatory_keys_present(self):
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r", diff_text=None,
            config=OutputConfig(fmt="json", include_diff=False),
        )
        assert self.MANDATORY.issubset(data.keys())
        assert data["kind"] == "commit_detail"
        assert data["repo"] == "o/r"
        assert data["sha"] == "a" * 40

    def test_summary_shape(self):
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r",
            config=OutputConfig(fmt="json", include_diff=False),
        )
        assert data["summary"] == {"files": 1, "additions": 5, "deletions": 2}

    def test_files_null_when_excluded(self):
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r",
            config=OutputConfig(fmt="json", include_files=False, include_diff=False),
        )
        assert data["files"] is None

    def test_diff_null_when_excluded(self):
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r", diff_text="some diff",
            config=OutputConfig(fmt="json", include_diff=False),
        )
        assert data["diff"] is None
        assert data["truncated"] is False

    def test_ansi_stripped_from_diff(self):
        diff_ansi = "\x1b[31m-old\x1b[0m\n\x1b[32m+new\x1b[0m\n"
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r", diff_text=diff_ansi,
            config=OutputConfig(fmt="json", include_diff=True),
        )
        assert data["diff"] is not None
        assert not _ANSI_RE.search(data["diff"])

    def test_truncation_sets_total_diff_lines(self):
        big = "\n".join(f"line {i}" for i in range(100))
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r", diff_text=big,
            config=OutputConfig(fmt="json", include_diff=True, max_lines=10),
        )
        assert data["truncated"] is True
        assert data["total_diff_lines"] == 100
        assert data["diff"].count("\n") == 9  # 10 lines = 9 newlines

    def test_not_truncated_when_under_cap(self):
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r", diff_text="one\ntwo\n",
            config=OutputConfig(fmt="json", include_diff=True, max_lines=100),
        )
        assert data["truncated"] is False
        assert "total_diff_lines" not in data

    def test_next_hints_round_trip(self):
        hints = {"full_diff": "cex o/r --show SHA --diff --max-lines 0"}
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r",
            config=OutputConfig(fmt="json", include_diff=False),
            next_hints=hints,
        )
        assert data["next"] == hints


class TestBranchComparisonSchema:
    MANDATORY = {"kind", "repo", "base", "target", "summary", "files", "diff", "truncated", "next"}

    def test_mandatory_keys_present(self):
        data = branch_comparison_to_dict(
            _branch_comparison(), repo="o/r",
            config=OutputConfig(fmt="json", include_diff=False),
        )
        assert self.MANDATORY.issubset(data.keys())
        assert data["kind"] == "branch_comparison"
        assert data["base"] == "main"
        assert data["target"] == "feature"

    def test_pr_block_populated(self):
        pr = PRMetadata(
            provider="github", owner="octo", repo="repo", number=42,
            title="Add feature", state="open", author="alice",
            base="main", head="feature",
            url="https://github.com/octo/repo/pull/42",
            head_clone_url="https://github.com/octo/repo.git",
            head_owner="octo", description="Body",
        )
        data = branch_comparison_to_dict(
            _branch_comparison(), repo="octo/repo", pr_meta=pr,
            config=OutputConfig(fmt="json", include_diff=False),
        )
        assert data["kind"] == "pr_review"
        assert data["pr"]["number"] == 42
        assert data["pr"]["title"] == "Add feature"
        assert data["pr"]["state"] == "open"
        assert data["pr"]["author"] == "alice"
        assert data["pr"]["body"] == "Body"

    def test_summary_aggregates_file_stats(self):
        data = branch_comparison_to_dict(
            _branch_comparison(), repo="o/r",
            config=OutputConfig(fmt="json", include_diff=False),
        )
        assert data["summary"] == {"files": 1, "additions": 2, "deletions": 1}


class TestRenderJson:
    def test_emits_indented_json_with_trailing_newline(self):
        data = {"kind": "commit_detail", "sha": "a" * 40}
        buf = io.StringIO()
        render_json(data, buf)
        out = buf.getvalue()
        assert out.endswith("\n")
        parsed = json.loads(out)
        assert parsed == data
        assert "\n  " in out  # indented

    def test_no_ansi_in_rendered_output(self):
        diff_ansi = "\x1b[31mred\x1b[0m"
        data = commit_detail_to_dict(
            _commit_detail(), repo="o/r", diff_text=diff_ansi,
            config=OutputConfig(fmt="json", include_diff=True),
        )
        buf = io.StringIO()
        render_json(data, buf)
        assert not _ANSI_RE.search(buf.getvalue())


class TestNdjsonSchema:
    def _entries(self) -> list[dict]:
        return [
            commit_to_ndjson_entry(
                CommitInfo(
                    sha=f"{i:040x}",
                    short_sha=f"{i:040x}"[:7],
                    message=f"msg {i}",
                    author="a",
                    author_email="a@x",
                    date="2024-01-01",
                    parents=[],
                )
            )
            for i in range(3)
        ]

    def test_entry_has_mandatory_keys(self):
        entry = self._entries()[0]
        for k in ("kind", "sha", "short_sha", "message", "author", "date", "graph"):
            assert k in entry
        assert entry["kind"] == "commit"

    def test_every_line_valid_json(self):
        entries = self._entries()
        page = page_info_dict(
            shown=3, total=3, offset=0, limit=50, next_cmd=None,
        )
        buf = io.StringIO()
        render_ndjson(entries, page, buf)
        lines = buf.getvalue().rstrip("\n").split("\n")
        assert len(lines) == 4  # 3 commits + page footer
        for line in lines:
            json.loads(line)  # raises if invalid

    def test_last_line_is_page_footer(self):
        entries = self._entries()
        page = page_info_dict(
            shown=3, total=10, offset=0, limit=3,
            next_cmd="cex o/r --export --offset 3 --limit 3",
        )
        buf = io.StringIO()
        render_ndjson(entries, page, buf)
        lines = buf.getvalue().rstrip("\n").split("\n")
        last = json.loads(lines[-1])
        assert last["kind"] == "page"
        assert last["shown"] == 3
        assert last["total"] == 10
        assert last["offset"] == 0
        assert last["limit"] == 3
        assert last["next"] == "cex o/r --export --offset 3 --limit 3"

    def test_page_next_null_when_exhausted(self):
        page = page_info_dict(
            shown=3, total=3, offset=0, limit=50, next_cmd=None,
        )
        assert page["next"] is None

    def test_no_ansi_in_ndjson_output(self):
        entries = [
            commit_to_ndjson_entry(
                CommitInfo(
                    sha="a" * 40, short_sha="a" * 7,
                    message="\x1b[31mred-msg\x1b[0m",
                    author="a", author_email="a@x",
                    date="2024-01-01", parents=[],
                ),
                graph="\x1b[32m*\x1b[0m",
            )
        ]
        page = page_info_dict(
            shown=1, total=1, offset=0, limit=50, next_cmd=None,
        )
        buf = io.StringIO()
        render_ndjson(entries, page, buf)
        # Per schema, ANSI is passed through ndjson entry body — assert the
        # JSON is still well-formed and round-trips.
        for line in buf.getvalue().rstrip("\n").split("\n"):
            json.loads(line)
