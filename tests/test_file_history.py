"""Tests for --export --file (file-history mode).

T021 — the commit filter is rename-aware via ``git log --follow``, the
``Next:`` hint preserves ``--file PATH``, and unknown paths produce a
stderr warning without failing the command.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
CEX = ROOT / ".venv" / "bin" / "cex"
TEST_REPO = "locchh/commit-explorer"
KNOWN_FILE = "pyproject.toml"  # present across most of this repo's history


def _run(*args: str, env=None, timeout: int = 180) -> subprocess.CompletedProcess:
    assert CEX.exists(), f"cex not installed at {CEX}; run `uv sync` first"
    return subprocess.run(
        [str(CEX), *args],
        capture_output=True, text=True, timeout=timeout, env=env,
    )


@pytest.mark.network
class TestFileHistory:
    def test_file_filter_returns_matching_commits(self, cli_env):
        r = _run(TEST_REPO, "--export", "--file", KNOWN_FILE, env=cli_env)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip(), "expected at least one commit touching the file"

    def test_file_filter_unknown_path_warns_but_succeeds(self, cli_env):
        r = _run(
            TEST_REPO, "--export", "--file",
            "path-that-never-existed-xyz-123.foo",
            env=cli_env,
        )
        assert r.returncode == 0
        assert "no commits found touching" in r.stderr.lower()

    def test_next_hint_preserves_file_flag(self, cli_env):
        r = _run(
            TEST_REPO, "--export", "--file", KNOWN_FILE,
            "--limit", "1", env=cli_env,
        )
        assert r.returncode == 0, r.stderr
        if "Next:" in r.stdout:
            assert f"--file {KNOWN_FILE}" in r.stdout
            assert "--limit 1" in r.stdout

    def test_file_filter_pagination(self, cli_env):
        first = _run(
            TEST_REPO, "--export", "--file", KNOWN_FILE,
            "--limit", "1", env=cli_env,
        )
        second = _run(
            TEST_REPO, "--export", "--file", KNOWN_FILE,
            "--limit", "1", "--offset", "1", env=cli_env,
        )
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        if first.stdout.strip() and second.stdout.strip():
            # Pages should not overlap verbatim
            first_body = first.stdout.split("\n[", 1)[0].strip()
            second_body = second.stdout.split("\n[", 1)[0].strip()
            if first_body and second_body:
                assert first_body != second_body
