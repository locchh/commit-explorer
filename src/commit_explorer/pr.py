"""Pull-request metadata fetching and merge-tree parsing."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from urllib.parse import quote

from .models import ConflictFile, PRMetadata


def resolve_pr_url(url: str) -> PRMetadata:
    """Parse a GitHub PR or GitLab MR URL and fetch metadata via the provider API."""
    url = url.strip().rstrip("/")

    gh_m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if gh_m:
        return _resolve_github(gh_m.group(1), gh_m.group(2), int(gh_m.group(3)), url)

    gl_m = re.match(
        r"(https?://[^/]+)/([^/]+(?:/[^/]+)*?)(?:/-)?/merge_requests/(\d+)", url
    )
    if gl_m:
        return _resolve_gitlab(gl_m.group(1), gl_m.group(2), int(gl_m.group(3)), url)

    raise ValueError(
        f"Unsupported URL format: {url!r}\n"
        "Supported: github.com/.../pull/N  or  gitlab.com/.../merge_requests/N"
    )


def _resolve_github(owner: str, repo: str, number: int, url: str) -> PRMetadata:
    token = os.getenv("GITHUB_TOKEN", "")
    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(api_url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    merged = data.get("merged", False)
    state = "merged" if merged else data.get("state", "unknown")
    head_repo = data["head"].get("repo") or {}
    head_owner = head_repo.get("owner", {}).get("login", owner)
    head_repo_name = head_repo.get("name", repo)
    creds = f"{token}@" if token else ""
    head_clone_url = (
        f"https://{creds}github.com/"
        f"{quote(head_owner, safe='')}/{quote(head_repo_name, safe='')}.git"
    )
    return PRMetadata(
        provider="github", owner=owner, repo=repo, number=number,
        title=data.get("title", ""),
        state=state,
        author=data.get("user", {}).get("login", ""),
        base=data["base"]["ref"],
        head=data["head"]["ref"],
        url=url,
        head_clone_url=head_clone_url,
        head_owner=head_owner,
        description=data.get("body") or "",
    )


def _resolve_gitlab(host: str, path: str, number: int, url: str) -> PRMetadata:
    token = os.getenv("GITLAB_TOKEN", "")
    parts = path.split("/")
    owner, repo = "/".join(parts[:-1]), parts[-1]
    project_id = quote(path, safe="")
    api_url = f"{host}/api/v4/projects/{project_id}/merge_requests/{number}"
    headers = {"PRIVATE-TOKEN": token} if token else {}
    req = urllib.request.Request(api_url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    state = data.get("state", "unknown")
    source_ns = data.get("source_namespace", {}) or {}
    head_owner = source_ns.get("full_path", path.rsplit("/", 1)[0])
    source_http = data.get("source", {}) or {}
    head_clone_url = source_http.get("http_url_to_repo", "")
    if not head_clone_url:
        creds = f"oauth2:{token}@" if token else ""
        host_no_scheme = re.sub(r"^https?://", "", host)
        scheme = "https://" if host.startswith("https") else "http://"
        head_clone_url = (
            f"{scheme}{creds}{host_no_scheme}/"
            f"{quote(head_owner, safe='')}/{quote(path.rsplit('/', 1)[-1], safe='')}.git"
        )
    return PRMetadata(
        provider="gitlab", owner=owner, repo=repo, number=number,
        title=data.get("title", ""),
        state=state,
        author=data.get("author", {}).get("username", ""),
        base=data["target_branch"],
        head=data["source_branch"],
        url=url,
        head_clone_url=head_clone_url,
        head_owner=head_owner,
        description=data.get("description") or "",
    )


def add_fork_remote(tmpdir: str, fork_url: str, branch: str) -> None:
    """Add the 'pr-head' remote pointing at a fork and fetch the given branch."""
    subprocess.run(
        ["git", "--git-dir", tmpdir, "remote", "remove", "pr-head"],
        capture_output=True,
    )
    r = subprocess.run(
        ["git", "--git-dir", tmpdir, "remote", "add", "pr-head", fork_url],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(f"remote add failed: {r.stderr.strip()}")
    r = subprocess.run(
        ["git", "--git-dir", tmpdir, "fetch", "--filter=blob:none",
         "pr-head", branch],
        capture_output=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(f"fetch fork failed: {r.stderr.strip()}")


def parse_classic_merge_tree(output: str) -> list[ConflictFile]:
    """Parse output from classic `git merge-tree <base> <ours> <theirs>`.

    Sections look like:
        changed in both
          base  100644 <sha>  path/to/file
          our   100644 <sha>  path/to/file
          their 100644 <sha>  path/to/file
        @@@ -1,3 -1,3 +1,9 @@@
         context
        +<<<<<<< .our
        +ours
        +=======
        +theirs
        +>>>>>>> .their
    """
    conflicts: list[ConflictFile] = []
    current_file = ""
    in_diff = False
    diff_lines: list[str] = []
    has_conflict = False

    SECTION_HEADERS = (
        "changed in both", "added in both", "removed in both",
        "added in remote", "removed in remote",
        "added in local", "removed in local",
    )

    def _flush() -> None:
        nonlocal current_file, in_diff, diff_lines, has_conflict
        if current_file and has_conflict and diff_lines:
            content = []
            for dl in diff_lines:
                if dl.startswith("+"):
                    content.append(dl[1:])
                elif dl.startswith(" "):
                    content.append(dl[1:])
            conflicts.append(ConflictFile(
                filename=current_file,
                conflict_text="\n".join(content),
            ))
        current_file = ""
        in_diff = False
        diff_lines = []
        has_conflict = False

    for line in output.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(h) for h in SECTION_HEADERS):
            _flush()
        elif stripped.startswith(("base ", "our ", "their ")):
            parts = stripped.split()
            if len(parts) >= 4 and not current_file:
                current_file = parts[-1]
        elif stripped.startswith("@@@") or stripped.startswith("@@"):
            in_diff = True
            diff_lines = []
        elif in_diff:
            diff_lines.append(line)
            if stripped.startswith("+<<<<<<<") or stripped.startswith("<<<<<<< "):
                has_conflict = True

    _flush()
    return conflicts
