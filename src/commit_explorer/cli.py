"""Command-line entry point for commit-explorer."""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from .backend import GitBackend, resolve_sha
from .export import write_commit_export, write_export
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


async def _pr_review(url: str, provider_key: str, depth: Optional[int], out_dir: str) -> None:
    """Resolve a PR/MR URL, clone the repo, compare branches, write export."""
    print(f"Resolving PR/MR: {url}", file=sys.stderr)
    try:
        pr = await asyncio.to_thread(resolve_pr_url, url)
    except Exception as e:
        print(f"Error resolving PR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  #{pr.number}: {pr.title}", file=sys.stderr)
    print(f"  {pr.author}  |  {pr.state}", file=sys.stderr)
    print(f"  base: {pr.base}  →  head: {pr.head}", file=sys.stderr)

    providers = get_providers()
    inferred = pr.provider if pr.provider in providers else provider_key
    provider = providers[inferred]

    backend = GitBackend()
    try:
        clone_url = provider.clone_url(pr.owner, pr.repo)
        print(f"Cloning {pr.owner}/{pr.repo}…", file=sys.stderr)
        await backend.load(clone_url, depth=depth)

        is_cross_fork = pr.head_owner.lower() != pr.owner.lower()
        head_ref = pr.head
        if is_cross_fork and pr.head_clone_url:
            print(f"Adding fork remote: {pr.head_owner}/{pr.repo}…", file=sys.stderr)
            await asyncio.to_thread(
                add_fork_remote, backend.tmpdir, pr.head_clone_url, pr.head
            )
            head_ref = f"pr-head/{pr.head}"

        print(f"Comparing origin/{pr.base} → {head_ref}…", file=sys.stderr)
        result = await asyncio.to_thread(backend.compare_branches, pr.base, head_ref)
        path = write_export(result, pr_meta=pr, out_dir=out_dir)
        print(f"\n#{pr.number}: {pr.title}  [{pr.state}]  by {pr.author}")
        print(f"{result.stat_summary or 'No differences.'}")
        if result.file_changes:
            print(f"\n{len(result.file_changes)} file(s) changed:")
            for fc in result.file_changes:
                print(f"  {fc.status[0].upper()} {fc.filename}  (+{fc.additions} -{fc.deletions})")
        print(f"\n{len(result.unique_commits)} unique commit(s) in origin/{pr.head}")
        if result.conflicts:
            print(
                f"\n⚠ {len(result.conflicts)} conflict(s): "
                f"{', '.join(cf.filename for cf in result.conflicts)}"
            )
        else:
            print("\n✓ Clean merge — no conflicts")
        print(f"\nExported to {path}")
    finally:
        backend.cleanup()


async def _compare(
    owner: str, repo: str, provider_key: str,
    depth: Optional[int], base: str, target: str, out_dir: str,
) -> None:
    """Clone repo, compare two branches, write export file, print summary."""
    provider = _provider(provider_key)

    backend = GitBackend()
    try:
        url = provider.clone_url(owner, repo)
        print(f"Cloning {owner}/{repo}…", file=sys.stderr)
        await backend.load(url, depth=depth)
        print(f"Comparing origin/{base} → origin/{target}…", file=sys.stderr)
        result = await asyncio.to_thread(backend.compare_branches, base, target)
        path = write_export(result, out_dir=out_dir)
        print(f"\n{result.stat_summary or 'No differences.'}")
        if result.file_changes:
            print(f"\n{len(result.file_changes)} file(s) changed:")
            for fc in result.file_changes:
                print(f"  {fc.status[0].upper()} {fc.filename}  (+{fc.additions} -{fc.deletions})")
        print(f"\n{len(result.unique_commits)} unique commit(s) in origin/{target}")
        if result.conflicts:
            print(
                f"\n⚠ {len(result.conflicts)} conflict(s): "
                f"{', '.join(cf.filename for cf in result.conflicts)}"
            )
        else:
            print("\n✓ Clean merge — no conflicts")
        print(f"\nExported to {path}")
    finally:
        backend.cleanup()


async def _export(
    owner: str, repo: str, provider_key: str,
    depth: Optional[int], out_dir: Optional[str],
) -> None:
    """Render the commit graph via git log --graph.

    Prints coloured output to stdout, or writes plain-text when out_dir is given.
    """
    provider = _provider(provider_key)

    backend = GitBackend()
    try:
        url = provider.clone_url(owner, repo)
        await backend.load(url, depth=depth)

        log_args = [
            "git", "--git-dir", backend.tmpdir,
            "log", "--graph", "--all",
        ]

        if out_dir is not None:
            r = await asyncio.to_thread(
                subprocess.run, log_args + ["--no-color"],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"{owner.replace('/', '-')}-{repo}-graph-{ts}.txt"
            path = os.path.join(out_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(r.stdout)
            print(path)
        else:
            await asyncio.to_thread(
                subprocess.run, log_args + ["--color=always"],
            )
    finally:
        backend.cleanup()


async def _show(
    owner: str, repo: str, provider_key: str,
    sha: str, depth: Optional[int], out_dir: str,
) -> None:
    """Clone repo, resolve SHA, export full commit details to a .txt file."""
    provider = _provider(provider_key)

    backend = GitBackend()
    try:
        url = provider.clone_url(owner, repo)
        print(f"Cloning {owner}/{repo}…", file=sys.stderr)
        await backend.load(url, depth=depth)

        full_sha = resolve_sha(backend.tmpdir, sha)
        if not full_sha:
            print(f"Error: SHA '{sha}' not found in {owner}/{repo}.", file=sys.stderr)
            sys.exit(1)

        print(f"Exporting commit {full_sha[:7]}…", file=sys.stderr)
        detail = await asyncio.to_thread(backend.get_detail, full_sha)
        path = write_commit_export(detail, backend.tmpdir, out_dir)
        print(path)
    finally:
        backend.cleanup()


async def _range(
    owner: str, repo: str, provider_key: str,
    range_shas: list[str], depth: Optional[int], out_dir: str,
) -> None:
    """Clone repo, walk a commit range, export one .txt file per commit."""
    from dulwich.repo import Repo
    from dulwich.walk import ORDER_DATE

    provider = _provider(provider_key)

    backend = GitBackend()
    try:
        url = provider.clone_url(owner, repo)
        print(f"Cloning {owner}/{repo}…", file=sys.stderr)
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

        for n, entry in enumerate(entries, 1):
            sha = entry.commit.id.decode()
            print(f"Exporting {n}/{total}…", file=sys.stderr)
            detail = await asyncio.to_thread(backend.get_detail, sha)
            path = write_commit_export(detail, backend.tmpdir, out_dir)
            print(path)
    finally:
        backend.cleanup()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commit-explorer")
    parser.add_argument("repo", nargs="?", default="", help="owner/repo")
    parser.add_argument(
        "--export", action="store_true",
        help="Print graph to stdout and exit",
    )
    parser.add_argument(
        "--pr", metavar="URL",
        help="GitHub PR or GitLab MR URL to review; resolves base/head automatically",
    )
    parser.add_argument(
        "--compare", nargs=2, metavar=("BASE", "TARGET"),
        help="Compare two branches and write a detailed report to .txt",
    )
    parser.add_argument(
        "--show", metavar="SHA",
        help="Export full details of a single commit to a .txt file",
    )
    parser.add_argument(
        "--range", nargs="+", metavar="SHA",
        help="Export a commit range: --range BASE TARGET or --range TARGET --depth N",
    )
    parser.add_argument(
        "--out", metavar="PATH", default=None,
        help="Output folder for exported .txt files (default: /tmp, created if missing)",
    )
    parser.add_argument(
        "--provider", default="github", choices=["github", "gitlab", "azure"],
    )
    parser.add_argument(
        "--depth", type=int, default=None, metavar="N",
        help="Limit fetch to N commits (default: fetch all)",
    )
    return parser


def main() -> None:
    """Entry point for the commit-explorer CLI."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.range and len(args.range) > 2:
        parser.error(
            "--range accepts 1 or 2 SHAs: --range TARGET --depth N  or  --range BASE TARGET"
        )

    # Output dir rules:
    #   --export with no --out → stdout (out_dir=None)
    #   other file-writing modes with no --out → /tmp
    #   any mode with explicit --out → that path (created if missing)
    is_file_mode = bool(args.pr or args.show or args.range or args.compare)
    if args.out is not None:
        out_dir: Optional[str] = args.out
        if args.export or is_file_mode:
            os.makedirs(out_dir, exist_ok=True)
    elif is_file_mode:
        out_dir = "/tmp"
    else:
        out_dir = None

    if args.pr:
        asyncio.run(_pr_review(args.pr, args.provider, args.depth, out_dir))
    elif args.show:
        if not args.repo or "/" not in args.repo:
            parser.error("--show requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_show(owner, repo, args.provider, args.show, args.depth, out_dir))
    elif args.range:
        if not args.repo or "/" not in args.repo:
            parser.error("--range requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_range(owner, repo, args.provider, args.range, args.depth, out_dir))
    elif args.compare:
        if not args.repo or "/" not in args.repo:
            parser.error("--compare requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_compare(
            owner, repo, args.provider, args.depth,
            args.compare[0], args.compare[1], out_dir,
        ))
    elif args.export:
        if not args.repo or "/" not in args.repo:
            parser.error("--export requires repo in owner/repo format")
        owner, repo = args.repo.split("/", 1)
        asyncio.run(_export(owner, repo, args.provider, args.depth, out_dir))
    else:
        from .ui.app import CommitExplorer
        CommitExplorer(initial_repo=args.repo, depth=args.depth).run()


if __name__ == "__main__":
    main()
