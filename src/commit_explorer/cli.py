"""Command-line entry point for commit-explorer.

Output routing contract
-----------------------

Every command defaults to **stdout**. When ``--out PATH`` is given, the
handler writes one or more files into ``PATH`` (creating it if missing) and
prints the resolved path(s) to stdout — nothing else. Progress chatter
("Cloning…", PR summary, etc.) always goes to stderr so ``stdout`` is safe
for agent piping and shell parsing.

Progressive-disclosure flags (``--summary`` / ``--diff`` / ``--no-diff`` /
``--file`` / ``--max-lines`` / ``--max-bytes`` / ``--limit`` / ``--offset``
/ ``--format`` / ``--color``) are assembled into :class:`OutputConfig` in
``main`` and passed to every handler.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime
from typing import IO, Optional

from dotenv import load_dotenv

from .backend import GitBackend, resolve_sha
from .export import get_commit_diff_text, write_commit_export, write_export
from .format import (
    OutputConfig,
    branch_comparison_to_dict,
    commit_detail_to_dict,
    commit_to_ndjson_entry,
    page_info_dict,
    render_json,
    render_ndjson,
)
from .pr import add_fork_remote, resolve_pr_url
from .providers import GitProvider, get_providers

load_dotenv(override=True)


def _provider(key: str) -> GitProvider:
    providers = get_providers()
    p = providers.get(key)
    if p is None:
        print(
            f"Unknown provider '{key}'. Choose from: {', '.join(providers)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return p


def _resolve_stream(config: OutputConfig) -> IO[str]:
    """Pick the stream a handler should write to when ``out_dir`` is unset."""
    return config.stream if config.stream is not None else sys.stdout


class _LineLimitStream:
    """Wrap a text stream; silently truncate output after ``max_lines`` newlines.

    When the limit is hit a single marker (``\\n… output truncated …``) is
    appended once; subsequent ``write`` calls are absorbed as no-ops. A
    ``max_lines`` of ``0`` disables wrapping entirely (pass-through).
    """

    def __init__(self, inner: IO[str], max_lines: int) -> None:
        self._inner = inner
        self._max = max_lines
        self._count = 0
        self._done = False

    def write(self, data: str) -> int:
        if self._done:
            return len(data)
        if self._max <= 0:
            return self._inner.write(data)
        newlines = data.count("\n")
        if self._count + newlines <= self._max:
            self._count += newlines
            return self._inner.write(data)
        need = self._max - self._count
        pos = 0
        for _ in range(need):
            idx = data.find("\n", pos)
            if idx == -1:
                pos = len(data)
                break
            pos = idx + 1
        if pos > 0:
            self._inner.write(data[:pos])
        self._inner.write(
            f"\n… output truncated at {self._max} lines. "
            f"Re-run with --max-lines 0 for full output.\n"
        )
        self._count = self._max
        self._done = True
        return len(data)

    def flush(self) -> None:
        self._inner.flush()

    def isatty(self) -> bool:
        fn = getattr(self._inner, "isatty", None)
        return fn() if callable(fn) else False

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class _ByteLimitStream:
    """Wrap a text stream; truncate output after ``max_bytes`` UTF-8 bytes."""

    def __init__(self, inner: IO[str], max_bytes: int) -> None:
        self._inner = inner
        self._max = max_bytes
        self._count = 0
        self._done = False

    def write(self, data: str) -> int:
        if self._done:
            return len(data)
        if self._max <= 0:
            return self._inner.write(data)
        encoded = data.encode("utf-8")
        if self._count + len(encoded) <= self._max:
            self._count += len(encoded)
            return self._inner.write(data)
        remaining = self._max - self._count
        if remaining > 0:
            clipped = encoded[:remaining].decode("utf-8", errors="ignore")
            self._inner.write(clipped)
        self._inner.write(
            f"\n… output truncated at {self._max} bytes. "
            f"Re-run with --max-bytes 0 for full output.\n"
        )
        self._count = self._max
        self._done = True
        return len(data)

    def flush(self) -> None:
        self._inner.flush()

    def isatty(self) -> bool:
        fn = getattr(self._inner, "isatty", None)
        return fn() if callable(fn) else False

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def _resolve_color_flag(color: str) -> str:
    """Map ``--color`` to the ``git log`` flag string."""
    if color == "never":
        return "--no-color"
    if color == "always":
        return "--color=always"
    # auto
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return "--color=always"
    return "--no-color"


def _fmt_page_footer(
    *,
    shown: int,
    total: int,
    offset: int,
    limit: int,
    base_cmd: str,
    extra_flags: Optional[list[str]] = None,
) -> str:
    """Build the ``[N of M commits shown]\\nNext: …`` footer.

    Returns an empty string when there is no next page (``limit == 0`` or the
    full range has been shown). The returned text has leading and trailing
    newlines so it can be appended directly after paginated output.
    """
    if limit <= 0:
        return ""
    if offset + shown >= total:
        return ""
    next_offset = offset + shown
    flags = list(extra_flags or [])
    flags += [f"--offset {next_offset}", f"--limit {limit}"]
    next_cmd = f"{base_cmd} {' '.join(flags)}"
    return f"\n[{shown} of {total:,} commits shown]\nNext: {next_cmd}\n"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _pr_review(url: str, provider_key: str, depth: Optional[int], config: OutputConfig) -> None:
    """Resolve a PR/MR URL, clone the repo, compare branches, emit the report."""
    print(f"Resolving PR/MR: {url}", file=sys.stderr)
    try:
        pr = await asyncio.to_thread(resolve_pr_url, url)
    except Exception as e:
        print(f"Error resolving PR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  #{pr.number}: {pr.title}", file=sys.stderr)
    print(f"  {pr.author}  |  {pr.state}", file=sys.stderr)
    print(f"  base: {pr.base}  \u2192  head: {pr.head}", file=sys.stderr)

    providers = get_providers()
    inferred = pr.provider if pr.provider in providers else provider_key
    provider = providers[inferred]

    backend = GitBackend()
    try:
        clone_url = provider.clone_url(pr.owner, pr.repo)
        print(f"Cloning {pr.owner}/{pr.repo}\u2026", file=sys.stderr)
        await backend.load(clone_url, depth=depth)

        is_cross_fork = pr.head_owner.lower() != pr.owner.lower()
        head_ref = pr.head
        if is_cross_fork and pr.head_clone_url:
            print(f"Adding fork remote: {pr.head_owner}/{pr.repo}\u2026", file=sys.stderr)
            await asyncio.to_thread(
                add_fork_remote, backend.tmpdir, pr.head_clone_url, pr.head
            )
            head_ref = f"pr-head/{pr.head}"

        print(f"Comparing origin/{pr.base} \u2192 {head_ref}\u2026", file=sys.stderr)
        result = await asyncio.to_thread(backend.compare_branches, pr.base, head_ref)

        if config.fmt in ("json", "ndjson"):
            data = branch_comparison_to_dict(
                result, repo=f"{pr.owner}/{pr.repo}", pr_meta=pr, config=config,
                next_hints={
                    "full_diff": f"cex --pr {url} --diff --max-lines 0",
                    "single_file": f"cex --pr {url} --file <path>",
                },
            )
            _emit_json(data, config, out_stem=f"compare-{pr.owner}-{pr.repo}-pr{pr.number}")
            return

        if config.out_dir is not None:
            path = write_export(
                result,
                pr_meta=pr,
                out_dir=config.out_dir,
                include_files=config.include_files,
                include_diff=config.include_diff,
                file_filter=config.file_filter,
            )
            print(path)
        else:
            write_export(
                result,
                pr_meta=pr,
                stream=_resolve_stream(config),
                include_files=config.include_files,
                include_diff=config.include_diff,
                file_filter=config.file_filter,
            )
    finally:
        backend.cleanup()


async def _compare(
    owner: str,
    repo: str,
    provider_key: str,
    depth: Optional[int],
    base: str,
    target: str,
    config: OutputConfig,
) -> None:
    """Clone repo, compare two branches, emit the report."""
    provider = _provider(provider_key)

    backend = GitBackend()
    try:
        url = provider.clone_url(owner, repo)
        print(f"Cloning {owner}/{repo}\u2026", file=sys.stderr)
        await backend.load(url, depth=depth)
        print(f"Comparing origin/{base} \u2192 origin/{target}\u2026", file=sys.stderr)
        result = await asyncio.to_thread(backend.compare_branches, base, target)

        if config.fmt in ("json", "ndjson"):
            data = branch_comparison_to_dict(
                result, repo=f"{owner}/{repo}", config=config,
                next_hints={
                    "full_diff": f"cex {owner}/{repo} --compare {base} {target} --diff --max-lines 0",
                    "single_file": f"cex {owner}/{repo} --compare {base} {target} --file <path>",
                },
            )
            base_safe = base.replace("/", "-")
            target_safe = target.replace("/", "-")
            _emit_json(data, config, out_stem=f"compare-{base_safe}-{target_safe}")
            return

        if config.out_dir is not None:
            path = write_export(
                result,
                out_dir=config.out_dir,
                include_files=config.include_files,
                include_diff=config.include_diff,
                file_filter=config.file_filter,
            )
            print(path)
        else:
            write_export(
                result,
                stream=_resolve_stream(config),
                include_files=config.include_files,
                include_diff=config.include_diff,
                file_filter=config.file_filter,
            )
    finally:
        backend.cleanup()


def _count_commits(git_dir: str) -> int:
    """Return ``git rev-list --all --count`` for this clone."""
    r = subprocess.run(
        ["git", "--git-dir", git_dir, "rev-list", "--all", "--count"],
        capture_output=True, text=True, errors="replace",
    )
    try:
        return int((r.stdout or "0").strip())
    except ValueError:
        return 0


def _emit_json(data: dict, config: OutputConfig, *, out_stem: str) -> None:
    """Render ``data`` as JSON to stdout or to ``{out_dir}/{stem}-{ts}.json``.

    When ``config.out_dir`` is set the JSON is written to that file and the
    resolved path is printed to stdout — composes ``--out`` with
    ``--format json`` as the contract requires.
    """
    if config.out_dir is not None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{out_stem}-{ts}.json"
        path = os.path.join(config.out_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            render_json(data, f)
        print(path)
    else:
        render_json(data, _resolve_stream(config))


def _emit_ndjson(
    entries: list[dict],
    page: dict,
    config: OutputConfig,
    *,
    out_stem: str,
) -> None:
    """Render ndjson entries + page footer to stdout or a ``.ndjson`` file."""
    if config.out_dir is not None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{out_stem}-{ts}.ndjson"
        path = os.path.join(config.out_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            render_ndjson(entries, page, f)
        print(path)
    else:
        render_ndjson(entries, page, _resolve_stream(config))


def _file_history_shas(git_dir: str, paths: list[str]) -> list[str]:
    """Return SHAs that touched any of ``paths`` (rename-aware, newest first).

    Runs ``git log --follow --format=%H -- PATH`` per path and unions the
    results. Paths that match no commits produce a warning on stderr.
    Within the union, SHAs are ordered by first appearance so the newest
    commit across all paths comes first.
    """
    seen: dict[str, None] = {}
    for path in paths:
        r = subprocess.run(
            ["git", "--git-dir", git_dir, "log", "--follow", "--format=%H", "--", path],
            capture_output=True, text=True, errors="replace",
        )
        shas = [s for s in r.stdout.splitlines() if s]
        if not shas:
            print(f"Warning: no commits found touching '{path}'", file=sys.stderr)
        for s in shas:
            seen.setdefault(s, None)
    return list(seen.keys())


async def _export(
    owner: str,
    repo: str,
    provider_key: str,
    depth: Optional[int],
    config: OutputConfig,
) -> None:
    """Render the commit graph via ``git log --graph``.

    Writes to stdout by default; to a file when ``config.out_dir`` is set.
    Default page size is ``config.limit`` (50). A ``Next:`` hint is emitted
    whenever more commits remain.

    When ``config.file_filter`` is non-empty the graph view is replaced with
    a flat one-line-per-commit listing restricted to commits that touched
    any of the listed paths (rename-aware via ``git log --follow``).
    """
    provider = _provider(provider_key)

    backend = GitBackend()
    try:
        url = provider.clone_url(owner, repo)
        await backend.load(url, depth=depth)

        # ----- JSON / ndjson mode ----------------------------------------
        if config.fmt in ("json", "ndjson"):
            commits = backend.all_commits
            if config.file_filter:
                wanted = set(await asyncio.to_thread(
                    _file_history_shas, backend.tmpdir, list(config.file_filter)
                ))
                commits = [c for c in commits if c.sha in wanted]

            total = len(commits)
            offset = max(0, config.offset)
            page = (
                commits[offset: offset + config.limit]
                if config.limit > 0 else commits[offset:]
            )
            shown = len(page)

            extra_flags: list[str] = []
            for p in config.file_filter:
                extra_flags += ["--file", p]
            next_cmd: Optional[str] = None
            if config.limit > 0 and offset + shown < total:
                flags = " ".join(
                    extra_flags + [
                        f"--offset {offset + shown}",
                        f"--limit {config.limit}",
                    ]
                )
                next_cmd = f"cex {owner}/{repo} --export {flags}"

            entries = [commit_to_ndjson_entry(c) for c in page]
            page_footer = page_info_dict(
                shown=shown, total=total,
                offset=offset, limit=config.limit,
                next_cmd=next_cmd,
            )
            stem_tag = "file-history" if config.file_filter else "graph"
            _emit_ndjson(entries, page_footer, config,
                         out_stem=f"{owner.replace('/', '-')}-{repo}-{stem_tag}")
            return

        # ----- File-history mode -----------------------------------------
        if config.file_filter:
            filtered_shas = await asyncio.to_thread(
                _file_history_shas, backend.tmpdir, list(config.file_filter)
            )
            total = len(filtered_shas)
            offset = max(0, config.offset)
            if config.limit > 0:
                page_shas = filtered_shas[offset: offset + config.limit]
            else:
                page_shas = filtered_shas[offset:]
            shown = len(page_shas)

            # Render one-line entries using `git log --no-walk` so we get
            # the metadata exactly in the page order.
            if page_shas:
                log_cmd = [
                    "git", "--git-dir", backend.tmpdir,
                    "log", "--no-walk",
                    "--format=%h  %ad  %an  %s",
                    "--date=short",
                ] + page_shas
                r = await asyncio.to_thread(
                    subprocess.run, log_cmd,
                    capture_output=True, encoding="utf-8", errors="replace",
                )
                body = r.stdout
            else:
                body = ""

            extra_flags = []
            for p in config.file_filter:
                extra_flags += ["--file", p]

            if config.out_dir is not None:
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                filename = f"{owner.replace('/', '-')}-{repo}-file-history-{ts}.txt"
                path = os.path.join(config.out_dir, filename)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(body)
                print(path)
                return

            stream = _resolve_stream(config)
            stream.write(body)
            footer = _fmt_page_footer(
                shown=shown, total=total,
                offset=offset, limit=config.limit,
                base_cmd=f"cex {owner}/{repo} --export",
                extra_flags=extra_flags,
            )
            if footer:
                stream.write(footer)
            return

        # ----- Full-graph mode -------------------------------------------
        log_args = [
            "git", "--git-dir", backend.tmpdir,
            "log", "--graph", "--all",
        ]
        if config.limit > 0:
            log_args.append(f"--max-count={config.limit}")
        if config.offset > 0:
            log_args.append(f"--skip={config.offset}")

        if config.out_dir is not None:
            r = await asyncio.to_thread(
                subprocess.run, log_args + ["--no-color"],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"{owner.replace('/', '-')}-{repo}-graph-{ts}.txt"
            path = os.path.join(config.out_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(r.stdout)
            print(path)
            return

        color_flag = _resolve_color_flag(config.color)
        r = await asyncio.to_thread(
            subprocess.run, log_args + [color_flag],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        stream = _resolve_stream(config)
        stream.write(r.stdout)

        total = _count_commits(backend.tmpdir)
        shown_max = config.limit if config.limit > 0 else total
        shown = max(0, min(shown_max, total - config.offset))
        footer = _fmt_page_footer(
            shown=shown, total=total,
            offset=config.offset, limit=config.limit,
            base_cmd=f"cex {owner}/{repo} --export",
        )
        if footer:
            stream.write(footer)
    finally:
        backend.cleanup()


async def _show(
    owner: str,
    repo: str,
    provider_key: str,
    sha: str,
    depth: Optional[int],
    config: OutputConfig,
) -> None:
    """Clone repo, resolve SHA, emit full commit details."""
    provider = _provider(provider_key)

    backend = GitBackend()
    try:
        url = provider.clone_url(owner, repo)
        print(f"Cloning {owner}/{repo}\u2026", file=sys.stderr)
        await backend.load(url, depth=depth)

        full_sha = resolve_sha(backend.tmpdir, sha)
        if not full_sha:
            print(f"Error: SHA '{sha}' not found in {owner}/{repo}.", file=sys.stderr)
            sys.exit(1)

        print(f"Exporting commit {full_sha[:7]}\u2026", file=sys.stderr)
        detail = await asyncio.to_thread(backend.get_detail, full_sha)

        if config.fmt in ("json", "ndjson"):
            diff_text: Optional[str] = None
            if config.include_diff:
                diff_text = await asyncio.to_thread(
                    get_commit_diff_text, detail.info, backend.tmpdir
                )
            data = commit_detail_to_dict(
                detail, repo=f"{owner}/{repo}",
                diff_text=diff_text, config=config,
                next_hints={
                    "full_diff": f"cex {owner}/{repo} --show {full_sha} --diff --max-lines 0",
                    "single_file": f"cex {owner}/{repo} --show {full_sha} --file <path>",
                },
            )
            date_compact = detail.info.date[:10].replace("-", "")
            _emit_json(data, config, out_stem=f"{date_compact}_{detail.info.short_sha}")
            return

        if config.out_dir is not None:
            path = write_commit_export(
                detail,
                backend.tmpdir,
                out_dir=config.out_dir,
                include_files=config.include_files,
                include_diff=config.include_diff,
                file_filter=config.file_filter,
            )
            print(path)
        else:
            write_commit_export(
                detail,
                backend.tmpdir,
                stream=_resolve_stream(config),
                include_files=config.include_files,
                include_diff=config.include_diff,
                file_filter=config.file_filter,
            )
    finally:
        backend.cleanup()


async def _range(
    owner: str,
    repo: str,
    provider_key: str,
    range_shas: list[str],
    depth: Optional[int],
    config: OutputConfig,
) -> None:
    """Walk a commit range and emit per-commit details.

    File mode writes one ``.txt`` per commit and prints each path.
    Stream mode writes all entries to the stream with a ``---`` separator.
    """
    from dulwich.repo import Repo
    from dulwich.walk import ORDER_DATE

    provider = _provider(provider_key)

    backend = GitBackend()
    try:
        url = provider.clone_url(owner, repo)
        print(f"Cloning {owner}/{repo}\u2026", file=sys.stderr)
        await backend.load(url, depth=depth)

        r = Repo(backend.tmpdir)

        def _resolve(s: str) -> bytes:
            full = resolve_sha(backend.tmpdir, s)
            if not full:
                print(f"Error: SHA '{s}' not found in {owner}/{repo}.", file=sys.stderr)
                sys.exit(1)
            return full.encode()

        if len(range_shas) == 2:
            base_bytes = _resolve(range_shas[0])
            target_bytes = _resolve(range_shas[1])
            entries = list(
                r.get_walker(include=[target_bytes], exclude=[base_bytes], order=ORDER_DATE)
            )
            if not entries:
                print(
                    f"Error: no commits found between '{range_shas[0]}' and '{range_shas[1]}'. "
                    "SHAs may have no ancestor relationship or range is empty.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            target_bytes = _resolve(range_shas[0])
            if depth is None:
                print("Error: --range with a single SHA requires --depth N.", file=sys.stderr)
                sys.exit(1)
            entries = list(r.get_walker(include=[target_bytes], max_entries=depth, order=ORDER_DATE))

        entries = list(reversed(entries))
        total = len(entries)

        offset = max(0, config.offset)
        if config.limit > 0:
            sliced = entries[offset: offset + config.limit]
        else:
            sliced = entries[offset:]
        shown = len(sliced)

        # ----- JSON / ndjson mode ----------------------------------------
        if config.fmt in ("json", "ndjson"):
            base_range = " ".join(range_shas)
            next_cmd: Optional[str] = None
            if config.limit > 0 and offset + shown < total:
                next_cmd = (
                    f"cex {owner}/{repo} --range {base_range} "
                    f"--offset {offset + shown} --limit {config.limit}"
                )
            ndjson_entries: list[dict] = []
            for entry in sliced:
                sha = entry.commit.id.decode()
                detail = await asyncio.to_thread(backend.get_detail, sha)
                ndjson_entries.append(commit_to_ndjson_entry(detail.info))
            page_footer = page_info_dict(
                shown=shown, total=total,
                offset=offset, limit=config.limit,
                next_cmd=next_cmd,
            )
            _emit_ndjson(
                ndjson_entries, page_footer, config,
                out_stem=f"{owner.replace('/', '-')}-{repo}-range",
            )
            return

        stream = _resolve_stream(config) if config.out_dir is None else None

        for n, entry in enumerate(sliced, 1):
            sha = entry.commit.id.decode()
            print(f"Exporting {n}/{shown}\u2026", file=sys.stderr)
            detail = await asyncio.to_thread(backend.get_detail, sha)
            if config.out_dir is not None:
                path = write_commit_export(
                    detail,
                    backend.tmpdir,
                    out_dir=config.out_dir,
                    include_files=config.include_files,
                    include_diff=config.include_diff,
                    file_filter=config.file_filter,
                )
                print(path)
            else:
                if n > 1:
                    stream.write("\n---\n")
                write_commit_export(
                    detail,
                    backend.tmpdir,
                    stream=stream,
                    include_files=config.include_files,
                    include_diff=config.include_diff,
                    file_filter=config.file_filter,
                )

        # Pagination footer (stream mode only).
        if stream is not None:
            base_range = " ".join(range_shas)
            footer = _fmt_page_footer(
                shown=shown, total=total,
                offset=offset, limit=config.limit,
                base_cmd=f"cex {owner}/{repo} --range {base_range}",
            )
            if footer:
                stream.write(footer)
    finally:
        backend.cleanup()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commit-explorer")
    parser.add_argument("repo", nargs="?", default="", help="owner/repo")
    parser.add_argument(
        "--export", action="store_true",
        help="Print commit graph (bounded to --limit; default 50)",
    )
    parser.add_argument(
        "--pr", metavar="URL",
        help="GitHub PR or GitLab MR URL to review; resolves base/head automatically",
    )
    parser.add_argument(
        "--compare", nargs=2, metavar=("BASE", "TARGET"),
        help="Compare two branches and emit a detailed report",
    )
    parser.add_argument(
        "--show", metavar="SHA",
        help="Emit full details of a single commit",
    )
    parser.add_argument(
        "--range", nargs="+", metavar="SHA",
        help="Emit a commit range: --range BASE TARGET or --range TARGET --depth N",
    )
    parser.add_argument(
        "--out", metavar="PATH", default=None,
        help="Output folder for .txt files (default: stdout; directory created if missing)",
    )
    parser.add_argument(
        "--provider", default="github", choices=["github", "gitlab", "azure"],
    )
    parser.add_argument(
        "--depth", type=int, default=None, metavar="N",
        help="Limit clone to N commits (network optimisation, independent of --limit)",
    )

    # Progressive-disclosure flags
    parser.add_argument(
        "--summary", action="store_true",
        help="Metadata + stat line only; suppresses file list and diff",
    )
    parser.add_argument(
        "--diff", action="store_true",
        help="Include full diff; implies --max-lines 500 unless --max-lines set",
    )
    parser.add_argument(
        "--no-diff", action="store_true",
        help="Explicitly suppress diff (wins over --diff if both present)",
    )
    parser.add_argument(
        "--file", action="append", metavar="PATH", default=[],
        help=(
            "On show/compare/pr/range: diff for this file only (implies --diff). "
            "On export: filter commit list to commits touching PATH (rename-aware). "
            "Repeatable."
        ),
    )

    # Size caps
    parser.add_argument(
        "--max-lines", type=int, default=None, metavar="N",
        help="Truncate stdout at N lines; 0 = unbounded. Default: 500 when --diff else 0",
    )
    parser.add_argument(
        "--max-bytes", type=int, default=0, metavar="N",
        help="Truncate stdout at N bytes; 0 = unbounded",
    )

    # Pagination
    parser.add_argument(
        "--limit", type=int, default=50, metavar="N",
        help="Max commits per --export/--range response; 0 = unbounded",
    )
    parser.add_argument(
        "--offset", type=int, default=0, metavar="M",
        help="Skip first M commits (paginate)",
    )

    # Format & colour
    parser.add_argument(
        "--format", dest="fmt", default="text",
        choices=["text", "json", "ndjson"],
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--color", default="auto",
        choices=["auto", "always", "never"],
        help="Colour mode (default: auto; forced never in json/ndjson)",
    )

    # Editor integration
    parser.add_argument(
        "--init", action="store_true",
        help="Download skills into the current project for the chosen editor",
    )
    parser.add_argument(
        "--type", dest="editor_type", default=None,
        choices=["claude", "windsurf", "cursor", "copilot"],
        help="Editor target for --init (claude | windsurf | cursor | copilot)",
    )
    return parser


def _build_output_config(args: argparse.Namespace) -> OutputConfig:
    """Assemble :class:`OutputConfig` from parsed argv.

    Section-flag priority (Phase 5 / T024) is resolved here so handlers
    receive a canonical view.
    """
    # Destination
    out_dir: Optional[str] = args.out
    stream: Optional[IO[str]] = None if out_dir is not None else sys.stdout

    # Size-cap stream wrapping (text / ndjson mode only; JSON mode does its
    # own in-content truncation via ``_clip_diff``).
    wrap_stream = stream is not None and args.fmt != "json"
    if wrap_stream and args.max_bytes and args.max_bytes > 0:
        stream = _ByteLimitStream(stream, args.max_bytes)

    # Section control — priority order: summary > no-diff > diff > file > default
    if args.summary:
        include_diff = False
        include_files = False
    elif args.no_diff:
        include_diff = False
        include_files = True
    elif args.diff:
        include_diff = True
        include_files = True
    elif args.file:
        # --file on show/compare/pr/range implies --diff (for those paths).
        # On --export, file_filter is a commit-selection filter; we still
        # leave include_diff=False because export doesn't emit per-file
        # diffs anyway.
        include_diff = not args.export
        include_files = True
    else:
        # Default: stdout = file list only (no diff);
        #         --out = full content (preserves old file-mode behaviour).
        include_diff = out_dir is not None
        include_files = True

    # Size caps — --diff implies 500 unless user set --max-lines explicitly
    if args.max_lines is not None:
        max_lines = args.max_lines
    elif include_diff and out_dir is None:
        # Only clip stdout; file output stays full.
        max_lines = 500
    else:
        max_lines = 0

    # Wrap the stream for line-cap truncation. In text mode ``max_lines`` is
    # applied at the stream level; in JSON mode the diff is clipped in-content
    # so we skip wrapping there to avoid double truncation.
    if wrap_stream and max_lines > 0:
        stream = _LineLimitStream(stream, max_lines)

    return OutputConfig(
        stream=stream,
        out_dir=out_dir,
        include_diff=include_diff,
        include_files=include_files,
        file_filter=list(args.file),
        max_lines=max_lines,
        max_bytes=args.max_bytes,
        limit=args.limit,
        offset=args.offset,
        fmt=args.fmt,
        color=args.color,
    )


def main() -> None:
    """Entry point for the commit-explorer CLI."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.init:
        if not args.editor_type:
            parser.error("--init requires --type (claude | windsurf | cursor | copilot)")
        from .init import run_init
        run_init(args.editor_type)
        return

    if args.range and len(args.range) > 2:
        parser.error(
            "--range accepts 1 or 2 SHAs: --range TARGET --depth N  or  --range BASE TARGET"
        )

    # Validate format choice early (argparse handles this but double-check)
    if args.fmt not in ("text", "json", "ndjson"):
        parser.error(f"--format: invalid value {args.fmt!r}")

    # Auto-create --out directory
    if args.out is not None:
        os.makedirs(args.out, exist_ok=True)

    config = _build_output_config(args)

    if args.pr:
        asyncio.run(_pr_review(args.pr, args.provider, args.depth, config))
    elif args.show:
        if not args.repo or "/" not in args.repo:
            parser.error("--show requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_show(owner, repo, args.provider, args.show, args.depth, config))
    elif args.range:
        if not args.repo or "/" not in args.repo:
            parser.error("--range requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_range(owner, repo, args.provider, args.range, args.depth, config))
    elif args.compare:
        if not args.repo or "/" not in args.repo:
            parser.error("--compare requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_compare(
            owner, repo, args.provider, args.depth,
            args.compare[0], args.compare[1], config,
        ))
    elif args.export or (
        args.repo
        and "/" in args.repo
        and (
            args.summary or args.diff or args.no_diff or args.file
            or args.fmt != "text"
            or args.limit != 50 or args.offset != 0 or args.depth is not None
        )
    ):
        if not args.repo or "/" not in args.repo:
            parser.error("--export requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_export(owner, repo, args.provider, args.depth, config))
    else:
        from .ui.app import CommitExplorer
        CommitExplorer(initial_repo=args.repo, depth=args.depth).run()


if __name__ == "__main__":
    main()
