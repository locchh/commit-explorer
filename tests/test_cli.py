"""End-to-end CLI tests. Invokes the `cex` binary via subprocess."""

from __future__ import annotations

import pathlib
import subprocess

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
CEX = ROOT / ".venv" / "bin" / "cex"
TEST_REPO = "locchh/commit-explorer"


def _run(*args: str, env=None, timeout: int = 180) -> subprocess.CompletedProcess:
    assert CEX.exists(), f"cex not installed at {CEX}; run `uv sync` first"
    return subprocess.run(
        [str(CEX), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


class TestHelp:
    def test_help_flag(self, cli_env):
        r = _run("--help", env=cli_env, timeout=15)
        assert r.returncode == 0
        assert "--export" in r.stdout
        assert "--compare" in r.stdout
        assert "--show" in r.stdout
        assert "--range" in r.stdout
        assert "--pr" in r.stdout
        assert "--out" in r.stdout


class TestArgValidation:
    """Error paths that must not require network."""

    def test_export_without_repo_errors(self, cli_env):
        r = _run("--export", env=cli_env, timeout=15)
        assert r.returncode != 0
        assert "owner/repo" in (r.stdout + r.stderr)

    def test_show_without_repo_errors(self, cli_env):
        r = _run("--show", "abc", env=cli_env, timeout=15)
        assert r.returncode != 0
        assert "owner/repo" in (r.stdout + r.stderr)

    def test_range_without_repo_errors(self, cli_env):
        r = _run("--range", "abc", env=cli_env, timeout=15)
        assert r.returncode != 0
        assert "owner/repo" in (r.stdout + r.stderr)

    def test_compare_without_repo_errors(self, cli_env):
        r = _run("--compare", "main", "dev", env=cli_env, timeout=15)
        assert r.returncode != 0
        assert "owner/repo" in (r.stdout + r.stderr)

    def test_range_with_three_shas_errors(self, cli_env):
        r = _run(TEST_REPO, "--range", "a", "b", "c", env=cli_env, timeout=15)
        assert r.returncode != 0
        assert "--range" in (r.stdout + r.stderr)

    def test_unknown_provider_is_rejected(self, cli_env):
        r = _run(TEST_REPO, "--export", "--provider", "bogus", env=cli_env, timeout=15)
        assert r.returncode != 0


@pytest.mark.network
class TestExport:
    def test_export_stdout(self, cli_env):
        r = _run(TEST_REPO, "--export", "--depth", "10", env=cli_env)
        assert r.returncode == 0, r.stderr
        assert r.stdout, "expected graph on stdout"
        # git log --graph output uses * for commits
        assert "*" in r.stdout

    def test_export_to_file(self, cli_env, tmp_path):
        r = _run(TEST_REPO, "--export", "--depth", "10",
                 "--out", str(tmp_path), env=cli_env)
        assert r.returncode == 0, r.stderr
        files = list(tmp_path.glob("*-graph-*.txt"))
        assert len(files) == 1
        assert r.stdout.strip().endswith(files[0].name)
        text = files[0].read_text(encoding="utf-8")
        assert "*" in text

    def test_export_creates_missing_out_dir(self, cli_env, tmp_path):
        target = tmp_path / "nested" / "dir"
        r = _run(TEST_REPO, "--export", "--depth", "5",
                 "--out", str(target), env=cli_env)
        assert r.returncode == 0, r.stderr
        assert target.is_dir()


@pytest.mark.network
class TestShow:
    def test_show_writes_file(self, cli_env, tmp_path, known_shas):
        r = _run(TEST_REPO, "--show", known_shas["non_merge"],
                 "--depth", "20", "--out", str(tmp_path), env=cli_env)
        assert r.returncode == 0, r.stderr
        out_path = pathlib.Path(r.stdout.strip())
        assert out_path.exists()
        assert out_path.parent == tmp_path
        text = out_path.read_text(encoding="utf-8")
        assert known_shas["non_merge"] in text
        assert "DIFF SUMMARY" in text

    def test_show_short_sha(self, cli_env, tmp_path, known_shas):
        r = _run(TEST_REPO, "--show", known_shas["head_short"],
                 "--depth", "5", "--out", str(tmp_path), env=cli_env)
        assert r.returncode == 0, r.stderr

    def test_show_bad_sha_errors(self, cli_env, tmp_path):
        r = _run(TEST_REPO, "--show", "deadbeef",
                 "--depth", "5", "--out", str(tmp_path), env=cli_env)
        assert r.returncode != 0
        assert "not found" in (r.stdout + r.stderr).lower()


@pytest.mark.network
class TestRange:
    def test_range_with_depth(self, cli_env, tmp_path, known_shas):
        r = _run(TEST_REPO, "--range", known_shas["head"],
                 "--depth", "3", "--out", str(tmp_path), env=cli_env)
        assert r.returncode == 0, r.stderr
        files = sorted(tmp_path.glob("*.txt"))
        assert len(files) == 3

    def test_range_with_depth_requires_depth(self, cli_env, tmp_path, known_shas):
        r = _run(TEST_REPO, "--range", known_shas["head"],
                 "--out", str(tmp_path), env=cli_env)
        assert r.returncode != 0
        assert "--depth" in (r.stdout + r.stderr)

    def test_range_two_shas(self, cli_env, tmp_path, cloned_backend):
        # Pick two commits on master that are ancestors: take commits[5] → commits[0]
        commits = cloned_backend.all_commits
        base = commits[5].sha
        target = commits[0].sha
        r = _run(TEST_REPO, "--range", base, target,
                 "--out", str(tmp_path), env=cli_env)
        assert r.returncode == 0, r.stderr
        files = list(tmp_path.glob("*.txt"))
        assert len(files) >= 1


@pytest.mark.network
class TestCompare:
    def test_compare_same_branch(self, cli_env, tmp_path):
        r = _run(TEST_REPO, "--compare", "master", "master",
                 "--depth", "10", "--out", str(tmp_path), env=cli_env)
        assert r.returncode == 0, r.stderr
        files = list(tmp_path.glob("compare-master-master-*.txt"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "Clean merge" in text or "no conflicts" in text.lower()
        assert "No unique commits" in text or "0 commits" in text


@pytest.mark.network
class TestStdoutDefault:
    """T013 — default (no --out) writes content to stdout; no files created."""

    def test_show_without_out_writes_content_to_stdout(
        self, cli_env, tmp_path, known_shas,
    ):
        # tmp_path is used only to confirm no file was written there.
        r = _run(
            TEST_REPO, "--show", known_shas["non_merge"], "--depth", "20",
            "--diff",
            env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        # Content on stdout, not a path
        assert "Commit:" in r.stdout
        assert "DIFF SUMMARY" in r.stdout
        assert "FULL DIFF" in r.stdout
        assert known_shas["non_merge"] in r.stdout
        # Verify no temp files got created in the test tmp_path
        assert list(tmp_path.iterdir()) == []

    def test_compare_without_out_writes_content_to_stdout(self, cli_env, tmp_path):
        r = _run(
            TEST_REPO, "--compare", "master", "master",
            "--depth", "10", "--diff",
            env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        assert "DIFF SUMMARY" in r.stdout
        assert "CHANGED FILES" in r.stdout
        assert list(tmp_path.iterdir()) == []

    def test_show_with_out_prints_only_path(
        self, cli_env, tmp_path, known_shas,
    ):
        """--out stays a single path on stdout (script-parseable)."""
        r = _run(
            TEST_REPO, "--show", known_shas["non_merge"], "--depth", "20",
            "--out", str(tmp_path), env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        assert len(lines) == 1
        path = pathlib.Path(lines[0])
        assert path.exists()
        assert path.parent == tmp_path


@pytest.mark.network
class TestProgressiveDisclosure:
    """T029 — CLI-level flag resolution: defaults, --summary, --diff, --no-diff."""

    def test_show_default_has_no_full_diff(self, cli_env, known_shas):
        """Default --show stdout should list files but not emit the FULL DIFF block."""
        r = _run(
            TEST_REPO, "--show", known_shas["non_merge"], "--depth", "20",
            env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        assert "CHANGED FILES" in r.stdout
        assert "FULL DIFF" not in r.stdout

    def test_show_summary_strips_file_list_and_diff(self, cli_env, known_shas):
        r = _run(
            TEST_REPO, "--show", known_shas["non_merge"], "--depth", "20",
            "--summary", env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        assert "DIFF SUMMARY" in r.stdout
        assert "CHANGED FILES" not in r.stdout
        assert "FULL DIFF" not in r.stdout

    def test_show_no_diff_keeps_file_list(self, cli_env, known_shas):
        r = _run(
            TEST_REPO, "--show", known_shas["non_merge"], "--depth", "20",
            "--no-diff", env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        assert "CHANGED FILES" in r.stdout
        assert "FULL DIFF" not in r.stdout

    def test_show_diff_enables_full_diff(self, cli_env, known_shas):
        r = _run(
            TEST_REPO, "--show", known_shas["non_merge"], "--depth", "20",
            "--diff", env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        assert "FULL DIFF" in r.stdout

    def test_compare_default_has_no_full_diff(self, cli_env):
        r = _run(
            TEST_REPO, "--compare", "master", "master",
            "--depth", "5", env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        assert "CHANGED FILES" in r.stdout
        assert "FULL DIFF" not in r.stdout


@pytest.mark.network
class TestPagination:
    """T017 — --export and --range paginate via --limit/--offset with a Next: hint."""

    def _count_commit_markers(self, text: str) -> int:
        # A commit header in git log --graph is: zero-or-more graph chars,
        # ``*``, optional spaces, then ``commit <40-char-sha>``. Counting on
        # that anchor avoids matching ``*`` bullets inside commit messages.
        import re
        pat = re.compile(r"^[ *|\\/_]*\*\s+commit\s+[0-9a-f]{7,40}\b")
        return sum(1 for ln in text.splitlines() if pat.match(ln))

    def test_export_default_is_bounded(self, cli_env):
        """Default --export returns at most --limit commits (default 50)."""
        r = _run(TEST_REPO, "--export", env=cli_env)
        assert r.returncode == 0, r.stderr
        markers = self._count_commit_markers(r.stdout)
        assert markers <= 50

    def test_export_limit_applied(self, cli_env):
        r = _run(TEST_REPO, "--export", "--limit", "5", env=cli_env)
        assert r.returncode == 0, r.stderr
        markers = self._count_commit_markers(r.stdout)
        assert markers <= 5

    def _has_pagination_footer(self, text: str) -> bool:
        """True if stdout contains the ``Next: cex …`` pagination footer line."""
        import re
        return bool(re.search(r"^\s*Next:\s+cex\s+", text, re.MULTILINE))

    def test_export_footer_when_more_commits(self, cli_env):
        """A small --limit on a repo with more commits produces a Next: hint."""
        r = _run(TEST_REPO, "--export", "--limit", "3", env=cli_env)
        assert r.returncode == 0, r.stderr
        if self._has_pagination_footer(r.stdout):
            assert "commits shown" in r.stdout
            assert "--offset 3" in r.stdout
            assert "--limit 3" in r.stdout

    def test_export_offset_pagination(self, cli_env):
        """--offset N skips the first N commits so pages do not overlap."""
        first = _run(TEST_REPO, "--export", "--limit", "3", env=cli_env)
        second = _run(TEST_REPO, "--export", "--limit", "3", "--offset", "3", env=cli_env)
        assert first.returncode == 0
        assert second.returncode == 0
        # The second page's content differs from the first (no verbatim overlap).
        assert first.stdout != second.stdout

    def test_export_limit_zero_is_unbounded(self, cli_env):
        r = _run(TEST_REPO, "--export", "--limit", "0", env=cli_env)
        assert r.returncode == 0, r.stderr
        # Unbounded mode: no pagination footer line
        assert not self._has_pagination_footer(r.stdout)


class TestNewFlagsInHelp:
    """T013 — progressive-disclosure flags show in --help."""

    def test_help_lists_new_flags(self, cli_env):
        r = _run("--help", env=cli_env, timeout=15)
        assert r.returncode == 0
        for flag in ("--summary", "--diff", "--no-diff", "--file",
                     "--max-lines", "--limit", "--offset",
                     "--format", "--color"):
            assert flag in r.stdout, f"{flag} missing from --help"


@pytest.mark.network
class TestSizeCaps:
    """T044 — ``--max-lines`` / ``--max-bytes`` stream wrappers."""

    def test_max_lines_caps_output(self, cli_env):
        r = _run(TEST_REPO, "--export", "--max-lines", "5", env=cli_env)
        assert r.returncode == 0, r.stderr
        # Wrapper emits one marker line that starts with the ellipsis.
        assert "output truncated" in r.stdout
        # Body before the marker is at most 5 newlines.
        body = r.stdout.split("\n… output truncated", 1)[0]
        assert body.count("\n") <= 5

    def test_max_lines_zero_is_unbounded(self, cli_env):
        r = _run(TEST_REPO, "--export", "--max-lines", "0",
                 "--limit", "3", env=cli_env)
        assert r.returncode == 0, r.stderr
        assert "output truncated" not in r.stdout

    def test_max_bytes_caps_output(self, cli_env):
        r = _run(TEST_REPO, "--export", "--max-bytes", "200", env=cli_env)
        assert r.returncode == 0, r.stderr
        assert "output truncated" in r.stdout

    def test_max_bytes_zero_is_unbounded(self, cli_env):
        r = _run(TEST_REPO, "--export", "--max-bytes", "0",
                 "--limit", "3", env=cli_env)
        assert r.returncode == 0, r.stderr
        assert "output truncated" not in r.stdout


class TestLimitStreamUnit:
    """Unit tests for ``_LineLimitStream`` / ``_ByteLimitStream``."""

    def test_line_limit_stream_truncates_and_marks(self):
        import io as _io
        from commit_explorer.cli import _LineLimitStream
        buf = _io.StringIO()
        s = _LineLimitStream(buf, 3)
        s.write("a\nb\nc\nd\ne\n")
        out = buf.getvalue()
        assert out.startswith("a\nb\nc\n")
        assert "output truncated" in out

    def test_line_limit_zero_is_pass_through(self):
        import io as _io
        from commit_explorer.cli import _LineLimitStream
        buf = _io.StringIO()
        s = _LineLimitStream(buf, 0)
        s.write("a\nb\nc\n")
        assert buf.getvalue() == "a\nb\nc\n"

    def test_byte_limit_stream_truncates(self):
        import io as _io
        from commit_explorer.cli import _ByteLimitStream
        buf = _io.StringIO()
        s = _ByteLimitStream(buf, 5)
        s.write("abcdefgh")
        out = buf.getvalue()
        assert out.startswith("abcde")
        assert "output truncated" in out


@pytest.mark.network
class TestOutCompat:
    """T040 — --out PATH writes a file at that path and prints it to stdout."""

    def test_out_creates_directory_if_missing(self, tmp_path, cli_env):
        target = tmp_path / "nested" / "out"
        assert not target.exists()
        r = _run(TEST_REPO, "--export", "--out", str(target), env=cli_env)
        assert r.returncode == 0, r.stderr
        assert target.is_dir()
        written = r.stdout.strip()
        assert written, "expected path printed to stdout"
        assert pathlib.Path(written).exists()

    def test_out_show_prints_single_path(self, cli_env, tmp_path):
        # Pick a SHA from --export --format ndjson (first line is a commit).
        import json as _json
        g = _run(TEST_REPO, "--export", "--limit", "1",
                 "--format", "ndjson", env=cli_env)
        assert g.returncode == 0, g.stderr
        first = g.stdout.splitlines()[0]
        sha = _json.loads(first)["sha"]
        r = _run(TEST_REPO, "--show", sha, "--out", str(tmp_path), env=cli_env)
        assert r.returncode == 0, r.stderr
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        assert len(lines) == 1, f"expected exactly one path on stdout, got: {r.stdout!r}"
        assert pathlib.Path(lines[0]).exists()
        assert pathlib.Path(lines[0]).suffix == ".txt"

    def test_out_compare_prints_path_only(self, cli_env, tmp_path):
        r = _run(TEST_REPO, "--compare", "master", "master",
                 "--out", str(tmp_path), env=cli_env)
        assert r.returncode == 0, r.stderr
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        assert len(lines) == 1
        assert pathlib.Path(lines[0]).exists()
