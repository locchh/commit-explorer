"""Shared pytest fixtures for the commit-explorer test suite.

Tests are built against the public repo `locchh/commit-explorer`.
Network-dependent tests share one session-scoped bare clone to keep
runtime reasonable.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import pytest

# Make the project root importable so tests can `import app`.
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

TEST_REPO_OWNER = "locchh"
TEST_REPO_NAME = "commit-explorer"
TEST_REPO = f"{TEST_REPO_OWNER}/{TEST_REPO_NAME}"


@pytest.fixture(scope="session")
def cloned_backend() -> "app._GitBackend":
    """A single _GitBackend cloned once per test session."""
    backend = app._GitBackend()
    provider = app.GitHubProvider()
    url = provider.clone_url(TEST_REPO_OWNER, TEST_REPO_NAME)
    try:
        asyncio.run(backend.load(url, depth=None))
    except Exception as exc:
        backend.cleanup()
        pytest.skip(f"Unable to clone {TEST_REPO}: {exc}")
    yield backend
    backend.cleanup()


@pytest.fixture(scope="session")
def session_tmp_dir(tmp_path_factory) -> pathlib.Path:
    return tmp_path_factory.mktemp("cex-session")


@pytest.fixture(scope="session")
def known_shas(cloned_backend) -> dict[str, str]:
    """Real SHAs from the test repo, usable across tests."""
    commits = cloned_backend.all_commits
    assert commits, "test repo has no commits"
    merge_commit = next((c for c in commits if len(c.parents) >= 2), None)
    non_merge = next((c for c in commits if len(c.parents) == 1), None)
    root = commits[-1]
    return {
        "head": commits[0].sha,
        "head_short": commits[0].short_sha,
        "root": root.sha,
        "merge": merge_commit.sha if merge_commit else commits[0].sha,
        "non_merge": non_merge.sha if non_merge else commits[0].sha,
    }


@pytest.fixture
def clean_env(monkeypatch):
    """Strip provider tokens so URL-builder tests see the unauth path."""
    for var in (
        "GITHUB_TOKEN",
        "GITLAB_TOKEN",
        "GITLAB_URL",
        "AZURE_DEVOPS_TOKEN",
        "AZURE_DEVOPS_ORG",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
def cli_env():
    """Environment for subprocess CLI invocations."""
    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    return env
