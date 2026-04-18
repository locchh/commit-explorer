"""Provider URL-builder tests. No network required."""

from __future__ import annotations

from commit_explorer.providers import (
    AzureDevOpsProvider,
    GitHubProvider,
    GitLabProvider,
)


class TestGitHubProvider:
    def test_name(self):
        assert GitHubProvider().name == "GitHub"

    def test_clone_url_without_token(self, clean_env):
        p = GitHubProvider()
        assert p.clone_url("octo", "repo") == "https://github.com/octo/repo.git"

    def test_clone_url_with_token(self, clean_env):
        clean_env.setenv("GITHUB_TOKEN", "ghp_abc")
        p = GitHubProvider()
        assert p.clone_url("octo", "repo") == "https://ghp_abc@github.com/octo/repo.git"

    def test_clone_url_escapes_slashes(self, clean_env):
        p = GitHubProvider()
        url = p.clone_url("owner/with/slash", "repo")
        assert "owner%2Fwith%2Fslash" in url

    def test_commit_url(self):
        p = GitHubProvider()
        assert p.commit_url("octo", "repo", "abc123") == (
            "https://github.com/octo/repo/commit/abc123"
        )


class TestGitLabProvider:
    def test_name(self):
        assert GitLabProvider().name == "GitLab"

    def test_clone_url_without_token(self, clean_env):
        p = GitLabProvider()
        assert p.clone_url("grp", "repo") == "https://gitlab.com/grp/repo.git"

    def test_clone_url_with_token(self, clean_env):
        clean_env.setenv("GITLAB_TOKEN", "glpat_xyz")
        p = GitLabProvider()
        assert p.clone_url("grp", "repo") == (
            "https://oauth2:glpat_xyz@gitlab.com/grp/repo.git"
        )

    def test_clone_url_custom_host(self, clean_env):
        clean_env.setenv("GITLAB_URL", "https://gitlab.example.com/")
        p = GitLabProvider()
        assert p.clone_url("grp", "repo") == (
            "https://gitlab.example.com/grp/repo.git"
        )

    def test_clone_url_strips_api_suffix(self, clean_env):
        clean_env.setenv("GITLAB_URL", "https://gitlab.example.com/api/v4")
        p = GitLabProvider()
        assert "api" not in p.clone_url("grp", "repo")

    def test_clone_url_http_host(self, clean_env):
        clean_env.setenv("GITLAB_URL", "http://gitlab.internal")
        clean_env.setenv("GITLAB_TOKEN", "tok")
        p = GitLabProvider()
        url = p.clone_url("grp", "repo")
        assert url.startswith("http://oauth2:tok@gitlab.internal/")

    def test_commit_url(self, clean_env):
        p = GitLabProvider()
        assert p.commit_url("grp", "repo", "sha1") == (
            "https://gitlab.com/grp/repo/-/commit/sha1"
        )

    def test_host_attr_public(self, clean_env):
        clean_env.setenv("GITLAB_URL", "https://gitlab.example.com")
        assert GitLabProvider().host == "https://gitlab.example.com"


class TestAzureDevOpsProvider:
    def test_name(self):
        assert AzureDevOpsProvider().name == "Azure DevOps"

    def test_clone_url_without_token(self, clean_env):
        clean_env.setenv("AZURE_DEVOPS_ORG", "my-org")
        p = AzureDevOpsProvider()
        assert p.clone_url("Project", "Repo") == (
            "https://dev.azure.com/my-org/Project/Repo/_git/Repo"
        )

    def test_clone_url_with_token(self, clean_env):
        clean_env.setenv("AZURE_DEVOPS_ORG", "my-org")
        clean_env.setenv("AZURE_DEVOPS_TOKEN", "pat_123")
        p = AzureDevOpsProvider()
        assert p.clone_url("Project", "Repo") == (
            "https://:pat_123@dev.azure.com/my-org/Project/Repo/_git/Repo"
        )

    def test_commit_url(self, clean_env):
        clean_env.setenv("AZURE_DEVOPS_ORG", "my-org")
        p = AzureDevOpsProvider()
        assert p.commit_url("Project", "Repo", "abc") == (
            "https://dev.azure.com/my-org/Project/_git/Repo/commit/abc"
        )
