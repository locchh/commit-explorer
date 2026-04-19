"""Text-file exporters for branch comparisons and single-commit details.

Callers choose destination with either ``out_dir`` (write a generated filename
into that directory and return the path) or ``stream`` (write directly to the
given text stream and return ``None``). Exactly one of the two must be set.

Section-control knobs (``include_files``, ``include_diff``, ``file_filter``)
let the CLI emit metadata-only or diff-free responses without allocating
extra text. ``file_filter`` clips the FULL DIFF block to hunks whose
``diff --git a/PATH`` header matches any supplied path.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from typing import IO, Iterable, Optional

from .models import BranchComparison, CommitDetail, PRMetadata


_SEP = "=" * 72
_sub = "-" * 72


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40]


def get_commit_diff_text(info: "CommitInfo", tmpdir: str) -> str:  # noqa: F821
    """Return the raw diff text for a single commit.

    Uses ``git show`` via the partial-clone lazy-fetch tricks so file blobs
    are pulled on demand. Returns an empty string for the root commit (no
    parent). This helper is shared by :func:`write_commit_export` (text
    output) and :mod:`commit_explorer.format` (JSON output).
    """
    if not info.parents:
        return ""
    r = subprocess.run(
        ["git",
         "-c", "remote.origin.promisor=true",
         "-c", "remote.origin.partialclonefilter=blob:none",
         "-c", "core.repositoryformatversion=1",
         "-c", "extensions.partialclone=origin",
         "--git-dir", tmpdir,
         "show", info.sha, "--no-color", "-p", "--format="],
        capture_output=True, encoding="utf-8", errors="replace", timeout=120,
    )
    return r.stdout.strip()


def _filter_diff_by_paths(diff_text: str, paths: Iterable[str]) -> str:
    """Return only the hunks of ``diff_text`` whose file header matches ``paths``.

    A hunk starts at ``diff --git a/<path> b/<path>`` and runs until the next
    ``diff --git`` line or end-of-text.
    """
    wanted = set(paths)
    if not wanted:
        return diff_text
    out: list[str] = []
    keep = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            # "diff --git a/<path> b/<path>" — pull the path from the "a/" token
            toks = line.split(" ")
            keep = False
            if len(toks) >= 3 and toks[2].startswith("a/"):
                keep = toks[2][2:] in wanted
        if keep:
            out.append(line)
    return "\n".join(out)


def write_export(
    result: BranchComparison,
    pr_meta: Optional[PRMetadata] = None,
    out_dir: Optional[str] = None,
    stream: Optional[IO[str]] = None,
    *,
    include_files: bool = True,
    include_diff: bool = True,
    file_filter: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Render a BranchComparison as text.

    When ``out_dir`` is given, a dated filename is written into it and the
    path is returned. When ``stream`` is given, text is written to it and
    ``None`` is returned. Exactly one of the two must be set.

    ``include_files`` / ``include_diff`` toggle whether the CHANGED FILES /
    FULL DIFF sections are emitted. ``file_filter`` (if non-empty) restricts
    the FULL DIFF block to hunks touching the listed paths.
    """
    if (out_dir is None) == (stream is None):
        raise ValueError("write_export: pass exactly one of out_dir or stream")

    now = datetime.now()
    date_str = now.strftime("%Y%m%d-%H%M%S")
    if pr_meta:
        owner_safe = pr_meta.owner.replace("/", "-")
        repo_safe = pr_meta.repo.replace("/", "-")
        filename = f"compare-{owner_safe}-{repo_safe}-pr{pr_meta.number}-{date_str}.txt"
    else:
        base_safe = result.base.replace("/", "-")
        target_safe = result.target.replace("/", "-")
        filename = f"compare-{base_safe}-{target_safe}-{date_str}.txt"

    lines = [_SEP]
    if pr_meta:
        lines += [
            f"PR/MR Review: {pr_meta.url}",
            f"Title:        {pr_meta.title}",
            f"Author:       {pr_meta.author}  |  State: {pr_meta.state}",
        ]
        if pr_meta.description.strip():
            lines.append("")
            lines.append("Description:")
            for dl in pr_meta.description.strip().splitlines():
                lines.append(f"  {dl}")
    lines += [
        f"Compare: origin/{result.base} \u2192 origin/{result.target}",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if result.shallow_warning:
        lines.append(
            "WARNING: Shallow clone \u2014 commit log and conflict results may be incomplete"
        )
    lines += ["", _SEP, ""]

    lines.append("DIFF SUMMARY")
    lines.append(_sub)
    lines.append(result.stat_summary if result.stat_summary else "No differences.")
    lines.append("")

    if include_files:
        lines.append(f"CHANGED FILES ({len(result.file_changes)})")
        lines.append(_sub)
        if result.file_changes:
            col_w = max(len(fc.filename) for fc in result.file_changes) + 2
            for fc in result.file_changes:
                lines.append(
                    f"  {fc.status.upper():<10}  {fc.filename:<{col_w}}  +{fc.additions}  -{fc.deletions}"
                )
        else:
            lines.append("  No file changes.")
        lines.append("")

        lines.append(
            f"COMMIT LOG ({len(result.unique_commits)} commits in "
            f"origin/{result.target} not in origin/{result.base})"
        )
        lines.append(_sub)
        if result.full_log.strip():
            lines.append(result.full_log.rstrip())
        elif result.unique_commits:
            for c in result.unique_commits:
                lines.append(f"commit {c.sha}")
                lines.append(f"Author: {c.author} <{c.author_email}>")
                lines.append(f"Date:   {c.date}")
                lines.append("")
                lines.append(f"    {c.message}")
                lines.append("")
        else:
            lines.append("  No unique commits.")
        lines.append("")

    if include_diff:
        lines.append("FULL DIFF")
        lines.append(_sub)
        diff_text = result.full_diff
        if file_filter:
            diff_text = _filter_diff_by_paths(diff_text, file_filter)
        lines.append(diff_text.rstrip() if diff_text.strip() else "No differences.")
        lines.append("")

        lines.append("CONFLICTS")
        lines.append(_sub)
        if not result.conflicts:
            lines.append("Clean merge \u2014 no conflicts detected")
        else:
            for cf in result.conflicts:
                lines.append(f"File: {cf.filename}")
                lines.append(_sub)
                lines.append(cf.conflict_text.rstrip())
                lines.append("")
        lines.append("")

    text = "\n".join(lines)
    if stream is not None:
        stream.write(text)
        return None
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def write_commit_export(
    detail: CommitDetail,
    tmpdir: str,
    out_dir: Optional[str] = None,
    stream: Optional[IO[str]] = None,
    *,
    include_files: bool = True,
    include_diff: bool = True,
    file_filter: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Render full commit details as text.

    Same dual-destination contract as ``write_export``: either write into
    ``out_dir`` under a dated filename (returning the path) or emit into
    ``stream`` (returning ``None``). Section control and ``file_filter``
    apply the same way as ``write_export``.
    """
    if (out_dir is None) == (stream is None):
        raise ValueError("write_commit_export: pass exactly one of out_dir or stream")

    info = detail.info
    date_compact = info.date[:10].replace("-", "")
    filename = f"{date_compact}_{info.short_sha}_{_slugify(info.message)}.txt"

    lines = [
        _SEP,
        f"Commit:    {info.sha}",
        f"Author:    {info.author} <{info.author_email}>",
        f"Date:      {info.date}",
        f"Message:   {info.message}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "", _SEP, "",
    ]

    lines.append("DIFF SUMMARY")
    lines.append(_sub)
    if detail.files:
        lines.append(
            f"{detail.stats['total']} file(s) changed, "
            f"+{detail.stats['additions']} insertions, "
            f"-{detail.stats['deletions']} deletions"
        )
    else:
        lines.append("No differences.")
    lines.append("")

    if include_files:
        lines.append(f"CHANGED FILES ({len(detail.files)})")
        lines.append(_sub)
        if detail.files:
            col_w = max(len(fc.filename) for fc in detail.files) + 2
            for fc in detail.files:
                lines.append(
                    f"  {fc.status.upper():<10}  {fc.filename:<{col_w}}  +{fc.additions}  -{fc.deletions}"
                )
        else:
            lines.append("  No file changes.")
        lines.append("")

    if include_diff:
        lines.append("FULL DIFF")
        lines.append(_sub)
        if not info.parents:
            lines.append("No diff available (initial commit).")
        else:
            diff_text = get_commit_diff_text(info, tmpdir)
            if file_filter:
                diff_text = _filter_diff_by_paths(diff_text, file_filter)
            lines.append(diff_text if diff_text else "No diff output.")
        lines.append("")

    text = "\n".join(lines)
    if stream is not None:
        stream.write(text)
        return None
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
