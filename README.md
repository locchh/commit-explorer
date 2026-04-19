# Commit Explorer (CEX)

A terminal UI and agent-friendly CLI for exploring remote git repository history. Clones via the git protocol (no REST API calls) with `filter=blob:none` — fast even for large repos.

```
┌─ Toolbar ──────────────────────────────────────────────────────┐
│ [Provider ▾]  [owner/repo                    ]  [Load]         │
├─ Commit list (resizable) ──────┬──┬─ Detail ───────────────────┤
│ * feat: add login  abc1234 …   │  │ [Open in browser]          │
│ * fix: null check  def5678 …   │  │ SHA     abc1234...         │
│ ├─╮ Merge branch 'feat'        │  │ Author  Jane Doe           │
│ [Load more ↓]                  │  │ M src/foo.py               │
└────────────────────────────────┴──┴────────────────────────────┘
```

## Install

```bash
# Run without installing
uvx --from git+https://github.com/locchh/commit-explorer cex owner/repo

# Install as a tool
uv tool install git+https://github.com/locchh/commit-explorer

# Run with specific branch
uv --from git+https://github.com/locchh/commit-explorer@<branch-name> cex owner/repo
```

```bash
# Bypass SSL for corporate proxies
GIT_SSL_NO_VERIFY=1 uvx --from git+https://github.com/locchh/commit-explorer cex owner/repo
```

## Quick examples

```bash
cex owner/repo                                        # interactive TUI
cex owner/repo --export                               # commit graph → stdout
cex owner/repo --show SHA --summary                   # single commit, stats only
cex owner/repo --compare main feature/foo --diff      # branch diff
cex --pr https://github.com/owner/repo/pull/123       # PR review
cex --init --type claude                              # install skills for Claude Code
```

See [`docs/CLI.md`](docs/CLI.md) for the full reference.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- `git` (system install)

## Related

- [Dulwich](https://www.dulwich.io/) — pure-Python git implementation
- [Textual](https://textual.textualize.io/) — TUI framework
- [Rich](https://github.com/Textualize/rich) — text formatting

## License

MIT
