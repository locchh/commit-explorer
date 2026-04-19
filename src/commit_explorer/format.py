"""JSON / ndjson renderers for agent-friendly output.

The schema is the public contract for every ``--format json|ndjson`` call
— mandatory keys are always present (they may be ``null``), key names are
``snake_case``, and ANSI codes never appear in output.

This module also owns :class:`OutputConfig`, the command-wide rendering
config assembled in ``cli.main`` and passed to every handler. Handlers
choose whether to render text (via :mod:`commit_explorer.export`) or
JSON/ndjson (via this module) based on ``config.fmt``.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import IO, Any, Optional

from .models import BranchComparison, CommitDetail, CommitInfo, PRMetadata


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI colour escapes from ``text``."""
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# OutputConfig
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class OutputConfig:
    """Rendering options shared across every command handler.

    Assembled once in :func:`commit_explorer.cli.main` from parsed argv.
    Handlers read the fields they care about and pass relevant subsets to
    the writers.

    Invariants (enforced in :meth:`__post_init__`):

    * ``stream`` and ``out_dir`` are mutually exclusive at use time — if
      ``out_dir`` is set the writers treat ``stream`` as ignored.
    * When ``fmt`` is ``"json"`` or ``"ndjson"`` the ``color`` field is
      forced to ``"never"`` — structured output never carries ANSI codes.
    """

    # Destination
    stream: Optional[IO[str]] = None
    out_dir: Optional[str] = None

    # Section control
    include_diff: bool = True
    include_files: bool = True
    file_filter: list[str] = dataclasses.field(default_factory=list)

    # Size caps
    max_lines: int = 0
    max_bytes: int = 0

    # Pagination
    limit: int = 50
    offset: int = 0

    # Format & colour
    fmt: str = "text"
    color: str = "auto"

    # File-content mode
    cat: bool = False

    def __post_init__(self) -> None:
        if self.fmt in ("json", "ndjson"):
            self.color = "never"


# ---------------------------------------------------------------------------
# Schema builders
# ---------------------------------------------------------------------------


def _file_change_dict(fc) -> dict[str, Any]:
    return {
        "path": fc.filename,
        "status": fc.status,
        "additions": fc.additions,
        "deletions": fc.deletions,
    }


def _clip_diff(diff_text: str, max_lines: int) -> tuple[str, bool, int]:
    """Return ``(clipped, truncated, total_lines)``."""
    clean = _strip_ansi(diff_text)
    lines = clean.splitlines()
    total = len(lines)
    if max_lines and total > max_lines:
        return "\n".join(lines[:max_lines]), True, total
    return clean, False, total


def commit_detail_to_dict(
    detail: CommitDetail,
    *,
    repo: str,
    diff_text: Optional[str] = None,
    config: Optional[OutputConfig] = None,
    next_hints: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Build the :class:`CommitDetail` JSON schema."""
    cfg = config or OutputConfig()
    info = detail.info

    diff: Optional[str] = None
    truncated = False
    total_diff_lines: Optional[int] = None
    if cfg.include_diff and diff_text:
        effective = diff_text
        if cfg.file_filter:
            from .export import _filter_diff_by_paths
            effective = _filter_diff_by_paths(effective, cfg.file_filter)
        diff, truncated, total_diff_lines = _clip_diff(effective, cfg.max_lines)

    out: dict[str, Any] = {
        "kind": "commit_detail",
        "repo": repo,
        "sha": info.sha,
        "summary": {
            "files": detail.stats.get("total", len(detail.files)),
            "additions": detail.stats.get("additions", 0),
            "deletions": detail.stats.get("deletions", 0),
        },
        "files": (
            [_file_change_dict(fc) for fc in detail.files]
            if cfg.include_files else None
        ),
        "diff": diff,
        "truncated": truncated,
    }
    if truncated and total_diff_lines is not None:
        out["total_diff_lines"] = total_diff_lines
    out["next"] = next_hints
    return out


def branch_comparison_to_dict(
    result: BranchComparison,
    *,
    repo: str,
    pr_meta: Optional[PRMetadata] = None,
    config: Optional[OutputConfig] = None,
    next_hints: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Build the :class:`BranchComparison` / PR-review JSON schema."""
    cfg = config or OutputConfig()

    diff: Optional[str] = None
    truncated = False
    total_diff_lines: Optional[int] = None
    if cfg.include_diff and result.full_diff:
        effective = result.full_diff
        if cfg.file_filter:
            from .export import _filter_diff_by_paths
            effective = _filter_diff_by_paths(effective, cfg.file_filter)
        diff, truncated, total_diff_lines = _clip_diff(effective, cfg.max_lines)

    out: dict[str, Any] = {
        "kind": "pr_review" if pr_meta else "branch_comparison",
        "repo": repo,
        "base": result.base,
        "target": result.target,
    }
    if pr_meta:
        out["pr"] = {
            "number": pr_meta.number,
            "title": pr_meta.title,
            "state": pr_meta.state,
            "author": pr_meta.author,
            "body": pr_meta.description,
        }
    out["summary"] = {
        "files": len(result.file_changes),
        "additions": sum(fc.additions for fc in result.file_changes),
        "deletions": sum(fc.deletions for fc in result.file_changes),
    }
    out["files"] = (
        [_file_change_dict(fc) for fc in result.file_changes]
        if cfg.include_files else None
    )
    out["diff"] = diff
    out["truncated"] = truncated
    if truncated and total_diff_lines is not None:
        out["total_diff_lines"] = total_diff_lines
    out["next"] = next_hints
    return out


def commit_to_ndjson_entry(info: CommitInfo, graph: str = "") -> dict[str, Any]:
    """Build the light per-commit ndjson line for ``--export`` / ``--range``."""
    return {
        "kind": "commit",
        "sha": info.sha,
        "short_sha": info.short_sha,
        "message": info.message,
        "author": info.author,
        "date": info.date,
        "graph": graph,
    }


def page_info_dict(
    *,
    shown: int,
    total: int,
    offset: int,
    limit: int,
    next_cmd: Optional[str],
) -> dict[str, Any]:
    return {
        "kind": "page",
        "shown": shown,
        "total": total,
        "offset": offset,
        "limit": limit,
        "next": next_cmd,
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_json(data: dict[str, Any], stream: IO[str]) -> None:
    """Serialise ``data`` as indented JSON to ``stream``, trailing newline."""
    json.dump(data, stream, indent=2)
    stream.write("\n")


def render_ndjson(
    entries: list[dict[str, Any]],
    page: dict[str, Any],
    stream: IO[str],
) -> None:
    """Write one JSON object per line for each entry, then the page footer."""
    for entry in entries:
        stream.write(json.dumps(entry))
        stream.write("\n")
    stream.write(json.dumps(page))
    stream.write("\n")
