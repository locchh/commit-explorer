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
