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
    "copilot":  ".github/skills",
}

_EDITOR_EXT = {
    "claude":   ".md",
    "windsurf": ".md",
    "cursor":   ".mdc",
    "copilot":  None,
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


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---"):
        return {}, content
    end = content.index("---", 3)
    fm: dict[str, str] = {}
    for line in content[4:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, content[end + 3:].lstrip("\n")


def _cursor_mdc(fm: dict[str, str], body: str) -> str:
    desc = fm.get("description", "")
    if len(desc) > 120:
        desc = desc[:117] + "..."
    return f"---\ndescription: {desc}\nglobs: \nalwaysApply: false\n---\n\n{body}"


def _copilot_marker(name: str) -> str:
    return f"<!-- cex-skill:{name} -->"


def _write_copilot(skills: dict[str, str], target: Path) -> None:
    out = target / ".github" / "skills" / "copilot-instructions.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    if out.exists():
        text = out.read_text(encoding="utf-8")
        for name, body in skills.items():
            marker = _copilot_marker(name)
            if marker in text:
                # replace between this marker and the next (or EOF)
                start = text.index(marker)
                next_marker = text.find("<!-- cex-skill:", start + len(marker))
                end = next_marker if next_marker != -1 else len(text)
                text = text[:start] + f"{marker}\n{body}\n" + text[end:]
            else:
                text = text.rstrip("\n") + f"\n\n{marker}\n{body}\n"
        action = "Updated"
    else:
        parts = [f"{_copilot_marker(n)}\n{b}" for n, b in skills.items()]
        text = "\n\n".join(parts) + "\n"
        action = "Created"

    out.write_text(text, encoding="utf-8")
    print(f"  {action}: {out.relative_to(target)}")


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
    ext = _EDITOR_EXT[editor]
    copilot_skills: dict[str, str] = {}

    for name in names:
        print(f"  Downloading: {name}", file=sys.stderr)
        try:
            raw = _fetch_skill(name)
        except Exception as exc:
            print(f"  Warning: could not fetch {name}: {exc}", file=sys.stderr)
            continue

        fm, body = _split_frontmatter(raw)

        if editor == "copilot":
            copilot_skills[name] = body
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{name}{ext}"
        action = "Updated" if dest.exists() else "Created"

        if editor == "cursor":
            dest.write_text(_cursor_mdc(fm, body), encoding="utf-8")
        else:
            dest.write_text(raw, encoding="utf-8")

        print(f"  {action}: {dest.relative_to(target)}")

    if editor == "copilot" and copilot_skills:
        _write_copilot(copilot_skills, target)
