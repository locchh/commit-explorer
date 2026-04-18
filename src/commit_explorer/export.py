"""Text-file exporters for branch comparisons and single-commit details."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from typing import Optional

from .models import BranchComparison, CommitDetail, PRMetadata


_SEP = "=" * 72
_sub = "-" * 72


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40]


def write_export(
    result: BranchComparison,
    pr_meta: Optional[PRMetadata] = None,
    out_dir: str = ".",
) -> str:
    """Write a BranchComparison to a detailed .txt file. Returns the file path."""
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

    lines.append("FULL DIFF")
    lines.append(_sub)
    lines.append(result.full_diff.rstrip() if result.full_diff.strip() else "No differences.")
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

    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def write_commit_export(detail: CommitDetail, tmpdir: str, out_dir: str) -> str:
    """Write full commit details to a .txt file. Returns the file path."""
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

    lines.append("FULL DIFF")
    lines.append(_sub)
    if not info.parents:
        lines.append("No diff available (initial commit).")
    else:
        # Transient -c flags make git treat this as a partial clone and lazy-fetch
        # missing blobs from origin without writing to the repo config.
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
        diff_text = r.stdout.strip()
        lines.append(diff_text if diff_text else "No diff output.")
    lines.append("")

    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
