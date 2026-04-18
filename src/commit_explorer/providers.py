"""Git hosting providers — URL builders for clone and commit browser links."""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from urllib.parse import quote


class GitProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def clone_url(self, owner: str, repo: str) -> str: ...

    @abstractmethod
    def commit_url(self, owner: str, repo: str, sha: str) -> str: ...


class GitHubProvider(GitProvider):
    @property
    def name(self) -> str:
        return "GitHub"

    def clone_url(self, owner: str, repo: str) -> str:
        token = os.getenv("GITHUB_TOKEN", "")
        creds = f"{token}@" if token else ""
        return f"https://{creds}github.com/{quote(owner, safe='')}/{quote(repo, safe='')}.git"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"https://github.com/{owner}/{repo}/commit/{sha}"


class GitLabProvider(GitProvider):
    def __init__(self) -> None:
        base = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")
        if "/api/" in base:
            base = base.split("/api/")[0]
        self.host = base

    @property
    def name(self) -> str:
        return "GitLab"

    def clone_url(self, owner: str, repo: str) -> str:
        token = os.getenv("GITLAB_TOKEN", "")
        creds = f"oauth2:{token}@" if token else ""
        host_no_scheme = re.sub(r"^https?://", "", self.host)
        scheme = "https://" if self.host.startswith("https") else "http://"
        return f"{scheme}{creds}{host_no_scheme}/{quote(owner, safe='')}/{quote(repo, safe='')}.git"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"{self.host}/{owner}/{repo}/-/commit/{sha}"


class AzureDevOpsProvider(GitProvider):
    def __init__(self) -> None:
        self._org = os.getenv("AZURE_DEVOPS_ORG", "")

    @property
    def name(self) -> str:
        return "Azure DevOps"

    def clone_url(self, owner: str, repo: str) -> str:
        token = os.getenv("AZURE_DEVOPS_TOKEN", "")
        creds = f":{token}@" if token else ""
        return f"https://{creds}dev.azure.com/{self._org}/{quote(owner, safe='')}/{quote(repo, safe='')}/_git/{quote(repo, safe='')}"

    def commit_url(self, owner: str, repo: str, sha: str) -> str:
        return f"https://dev.azure.com/{self._org}/{owner}/_git/{repo}/commit/{sha}"


def get_providers() -> dict[str, GitProvider]:
    """Return a fresh registry of provider instances keyed by CLI name."""
    return {
        "github": GitHubProvider(),
        "gitlab": GitLabProvider(),
        "azure": AzureDevOpsProvider(),
    }
