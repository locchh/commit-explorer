"""Editor integration initializer.

Downloads skills from the locchh/commit-explorer GitHub repo and installs
them into the appropriate editor config directory for the current project.

Usage:
    cex --init --type claude|windsurf|cursor|copilot
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

_REPO = "locchh/commit-explorer"
_BRANCH = "master"
_API_SKILLS = f"https://api.github.com/repos/{_REPO}/contents/skills"
_RAW_BASE = f"https://raw.githubusercontent.com/{_REPO}/{_BRANCH}/skills"

_EDITOR_DIR = {
    "claude":   ".claude/skills",
    "windsurf": ".windsurf/skills",
    "cursor":   ".cursor/skills",
    "copilot":  ".copilot/skills",
}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "cex-init/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode()


def _list_skills() -> list[str]:
    data = json.loads(_get(_API_SKILLS))
    return [e["name"] for e in data if e["type"] == "dir"]


def _fetch_skill(name: str) -> str:
    return _get(f"{_RAW_BASE}/{name}/SKILL.md")


def run_init(editor: str, target: Path = Path(".")) -> None:
    print(f"Fetching skills from {_REPO} ({_BRANCH})…", file=sys.stderr)
    try:
        names = _list_skills()
    except Exception as exc:
        print(f"Error listing skills: {exc}", file=sys.stderr)
        sys.exit(1)

    if not names:
        print("No skills found in repo.", file=sys.stderr)
        return

    out_dir = target / _EDITOR_DIR[editor]

    for name in names:
        print(f"  Downloading: {name}", file=sys.stderr)
        try:
            raw = _fetch_skill(name)
        except Exception as exc:
            print(f"  Warning: could not fetch {name}: {exc}", file=sys.stderr)
            continue

        dest = out_dir / name / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        action = "Updated" if dest.exists() else "Created"
        dest.write_text(raw, encoding="utf-8")
        print(f"  {action}: {dest.relative_to(target)}")
