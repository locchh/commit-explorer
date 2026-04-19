---
name: repo-archaeology
description: Answer questions about the history of a *remote* git repository (GitHub / GitLab / Azure DevOps) — when a file was introduced, how it evolved, what changed between branches, what's in a PR, or what a commit range contains. Uses the `cex` CLI (this project's own tool) which lazy-clones the repo, streams to stdout with `Next:` pagination hints, and speaks JSON/ndjson for clean parsing. NOT for the local working tree — use `git log` directly for that.
---

# Repo Archaeology (via `cex`)

`cex` is this project's CLI for answering history questions about *remote*
repos without fully cloning them. It shallow-clones with `filter=blob:none`
(no file contents until asked), and every command defaults to stdout with
pagination hints — so you can start cheap, follow `Next:` hints, and climb
up only when a task needs more.

## When to reach for `cex`

Use `cex` when the answer requires **remote git history** the user does
not already have locally:

- "When was file X added to `owner/repo`?"
- "How has `path/to/module.py` evolved in `torvalds/linux`?"
- "What changed between `main` and `release/2.3` in `owner/repo`?"
- "Review PR #123 before merging."
- "What's in the last 20 commits of `owner/repo`?"
- "Walk me through how `owner/repo` is structured today (reproduce it)."

**Do NOT use `cex` when**:
- The repo is already cloned locally (`git log`, `git blame`, `git show`
  are faster and don't re-clone).
- The user only cares about the *current* state of a file (read it).
- The user wants the GitHub UI URL (build it — don't clone).

## Core rule: progressive disclosure

Every `cex` handler climbs a ladder. Start cheap. Only step up when the
previous rung didn't answer the question.

| Rung | Flag | Output size |
|---|---|---|
| 1 | `--summary` | metadata + stat line (≤ 20 lines) |
| 2 | *(default)* | file list, no diff |
| 3 | `--file PATH` | diff for one file |
| 4 | `--diff` | full diff capped at 500 lines |
| 5 | `--diff --max-lines 0` | uncapped full diff |

If the user asks a focused question ("did Alice touch auth.py in PR #42?"),
skip straight to rung 3 with `--file src/auth.py`. Never dump the full
diff as a first step — it floods the context and often includes content
you don't need.

## Pagination is load-bearing

`--export` and `--range` default to 50 commits per call with a footer like:

```
[50 of 2,431 commits shown]
Next: cex owner/repo --export --offset 50 --limit 50
```

When the user wants "more history," **run the `Next:` command verbatim**
— don't re-fetch from the top. If the user wants a specific slice,
compute `--offset` / `--limit` yourself rather than paging blindly.

## Structured output for parsing

When you need to parse `cex` output (pick a SHA, count commits, extract a
file list) **use `--format json` or `--format ndjson`** — never regex the
text mode. JSON mode keeps every mandatory key present (may be `null`),
strips ANSI, and exposes `next` hints as a map.

```bash
# Pick the newest commit SHA that touched a file
cex owner/repo --export --file src/auth.py --format ndjson --limit 1 \
  | head -1 | jq -r .sha

# Extract file list from a PR with no diff bytes
cex --pr https://github.com/o/r/pull/42 --format json | jq '.files[].path'

# Walk the last 20 commits as JSON objects
cex owner/repo --export --limit 20 --format ndjson
```

## Recipe book

### "When was file X first added?"

`git log --diff-filter=A --follow` on the clone. `cex` doesn't expose this
directly, but file-history mode gives you every commit that touched the
path — the **last line** of the ndjson output (oldest commit) is the add:

```bash
cex owner/repo --export --file path/to/file.py --format ndjson --limit 0
# → pipe to `tail -2 | head -1 | jq .` for the introducing commit
```

### "How has file X evolved over time?"

```bash
cex owner/repo --export --file path/to/file.py --limit 20
# → one-line-per-commit log (text); paginate with the Next: hint
```

For a proper per-commit diff of that file:

```bash
cex owner/repo --export --file path/to/file.py --format ndjson --limit 20 \
  | jq -r .sha \
  | while read sha; do
      cex owner/repo --show "$sha" --file path/to/file.py --diff
      echo '---'
    done
```

### "What changed between two branches?"

Climb the ladder. Start at rung 1:

```bash
cex owner/repo --compare main release/2.3 --summary       # stats only
cex owner/repo --compare main release/2.3                 # + file list
cex owner/repo --compare main release/2.3 --file src/x.py # one file's diff
cex owner/repo --compare main release/2.3 --diff          # full diff (capped)
```

### "Review this PR before I merge it"

```bash
cex --pr https://github.com/o/r/pull/42 --summary           # ~20 lines
cex --pr https://github.com/o/r/pull/42                     # + file list
cex --pr https://github.com/o/r/pull/42 --file src/auth.py  # one file's diff
cex --pr https://github.com/o/r/pull/42 --diff              # full diff
```

The provider (github / gitlab) is inferred from the URL — no `--provider`
needed. Cross-fork PRs work automatically.

### "What's in the last N commits?"

```bash
cex owner/repo --export --limit N                           # graph view
cex owner/repo --export --limit N --format ndjson           # structured
```

### "Give me the full context of one commit"

```bash
cex owner/repo --show <SHA>                      # metadata + file list
cex owner/repo --show <SHA> --diff               # + diff (capped 500 lines)
cex owner/repo --show <SHA> --format json        # parseable
```

SHAs can be short (7+ chars) or full.

### "Walk me through a commit range"

```bash
# All commits between base..target
cex owner/repo --range <base-sha> <target-sha> --summary
cex owner/repo --range <base-sha> <target-sha> --limit 10

# Last N commits from a starting SHA
cex owner/repo --range <target-sha> --depth N --summary
```

Range mode emits one entry per commit separated by `---` in text mode, or
one JSON object per commit in ndjson mode.

### "How would I reproduce this repo's setup from scratch?"

Walk the root-adjacent commits — the earliest ones usually set up tooling:

```bash
# Jump to the very first page of history (oldest last)
cex owner/repo --export --format ndjson --limit 0 | tail -20

# Read the add-introducing commit for tooling files
for f in pyproject.toml package.json Dockerfile Makefile README.md; do
  sha=$(cex owner/repo --export --file "$f" --format ndjson --limit 0 \
          | tail -2 | head -1 | jq -r .sha)
  [ -n "$sha" ] && cex owner/repo --show "$sha" --file "$f" --diff
done
```

## Depth and network budget

`--depth N` limits the **clone** (network cost), independent of `--limit`
(how much of that clone is displayed). If the user says "explore the last
200 commits of torvalds/linux", pair `--depth 200 --limit 50` — the
clone stays cheap, pagination walks through what was fetched.

Without `--depth`, the full history is cloned. That's fine for small
repos; prefer `--depth` for multi-GB ones.

## Providers & auth

`cex` auto-detects the provider from `owner/repo` syntax with `--provider`
as a fallback (`github` default, `gitlab`, `azure`). Tokens live in `.env`:

| Provider | `--provider` | Env var |
|---|---|---|
| GitHub | `github` | `GITHUB_TOKEN` |
| GitLab | `gitlab` | `GITLAB_TOKEN` (+ `GITLAB_URL` for self-hosted) |
| Azure DevOps | `azure` | `AZURE_DEVOPS_TOKEN` + `AZURE_DEVOPS_ORG` |

## Routing & size control — pocket reference

| Flag | Effect |
|---|---|
| *(no `--out`)* | Stream to stdout (default, agent-friendly) |
| `--out PATH` | Write `.txt` file(s) under PATH; prints resolved path |
| `--max-lines N` | Cap stdout at N lines (500 default when `--diff`) |
| `--max-bytes N` | Cap stdout at N bytes |
| `--limit N` / `--offset M` | Paginate `--export` / `--range` |
| `--format json` | Single-object schema with `next` hints |
| `--format ndjson` | One object per commit + `{"kind":"page",…}` footer |
| `--color never` | Strip ANSI (forced in JSON modes) |

## Common pitfalls

- **Don't regex `--format text`** — use `--format json` / `ndjson`.
- **Don't dump `--diff` as a first step** — always try rungs 1–3 first.
- **Don't re-fetch page 1** when the user wants "more" — run the `Next:`
  command verbatim.
- **Don't use `cex` for the local working tree** — `git log` / `git blame`
  are faster and don't re-clone.
- **Don't escalate `--max-lines 0`** unless the user explicitly asked for
  the full uncapped diff — the cap exists to protect context.
