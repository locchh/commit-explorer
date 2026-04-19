# Feature Specification: Agent-Friendly CLI (Progressive Disclosure)

**Feature Branch**: `20260418-212347-agent-friendly-cli`  
**Created**: 2026-04-18  
**Status**: Draft  
**Input**: User description: "Make cex agent-friendly: progressive disclosure, stdout-default, pagination, file-history, JSON format"

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Agent Explores a Large Repo Without Context Overflow (Priority: P1)

An AI agent (e.g. Claude Code) is asked to summarise recent activity in a repository that may have hundreds of thousands of commits (e.g. the Linux kernel). The agent needs to start small, decide what is interesting, and drill down — without a single command filling its entire context window.

**Why this priority**: This is the core motivation for the feature. If a default invocation against a large repo is safe, every other use case is too.

**Independent Test**: Run `cex owner/repo --export` against a large repo and verify the output does not exceed 55 lines. Confirm a `Next:` hint appears pointing to the next page.

**Acceptance Scenarios**:

1. **Given** a repo with 1,000,000+ commits, **When** the agent runs `cex owner/repo --export`, **Then** stdout contains at most 50 commit entries plus a `[N of M commits shown]` footer and a `Next:` command.
2. **Given** a page was returned, **When** the agent runs the `Next:` command verbatim, **Then** the next 50 entries are returned with an updated footer.
3. **Given** the agent wants the full graph, **When** it runs `cex owner/repo --export --limit 0`, **Then** all commits are returned with no artificial cap.
4. **Given** a TTY is not attached (pipe or agent context), **When** any command runs, **Then** no ANSI colour codes appear in output.

---

### User Story 2 — Agent Traces the History of a Specific File (Priority: P1)

An AI agent needs to understand how a particular source file has changed over time — which commits touched it, what changed in each, and how the file evolved between two releases.

**Why this priority**: Without file-scoped history, the agent must ingest the entire commit graph and filter client-side — prohibitively expensive for large repos.

**Independent Test**: Run `cex owner/repo --export --file src/backend.py` and confirm only commits that modified `src/backend.py` are returned, paginated the same way as the full graph.

**Acceptance Scenarios**:

1. **Given** a file path, **When** the agent runs `cex owner/repo --export --file path/to/file`, **Then** stdout lists only commits that touched that path (renames followed), paginated at 50.
2. **Given** a specific commit SHA from the file history, **When** the agent runs `cex owner/repo --show SHA --file path/to/file`, **Then** stdout contains only the diff for that file in that commit.
3. **Given** two refs, **When** the agent runs `cex owner/repo --compare BASE TARGET --file path/to/file`, **Then** only that file's cumulative diff is shown.

---

### User Story 3 — Agent Reviews a PR Diff Progressively (Priority: P2)

An AI agent is asked to review a pull request. It starts with the cheapest useful view and drills down only into interesting parts.

**Why this priority**: PR review is a primary agent workflow. The current tool writes to a temp file and dumps everything; this makes progressive review practical.

**Independent Test**: Run `cex --pr URL --summary` and confirm output is under 20 lines. Run default and confirm file list but no diff. Add `--file path` and confirm only that file's diff appears.

**Acceptance Scenarios**:

1. **Given** a PR URL, **When** the agent runs `cex --pr URL --summary`, **Then** stdout contains PR metadata (title, state, author, base, head, body) and stat summary — no file list, no diff.
2. **Given** a PR URL, **When** the agent runs `cex --pr URL` (default), **Then** stdout contains PR metadata, stat summary, and changed-file list with per-file stats — no diff.
3. **Given** a PR URL and a file path, **When** the agent runs `cex --pr URL --file path/to/x`, **Then** stdout contains the default view plus the diff for that one file only.
4. **Given** a PR URL, **When** the agent runs `cex --pr URL --diff`, **Then** the full diff is included, capped at 500 lines, with a truncation marker and `Next:` command if truncated.

---

### User Story 4 — Agent Parses Output Programmatically (Priority: P2)

An AI agent needs to parse `cex` output reliably — extracting file paths, addition counts, commit SHAs, and pagination hints — without writing brittle regexes against human-readable text.

**Why this priority**: Structured output is what separates a tool an agent can *use* from one it can only *read*.

**Independent Test**: Run `cex owner/repo --show SHA --format json` and verify the output is valid JSON with keys `kind`, `sha`, `summary`, `files`, `diff`, `truncated`, `next`.

**Acceptance Scenarios**:

1. **Given** `--format json`, **When** any single-object command (`show`, `compare`, `pr`) runs, **Then** stdout is a single valid JSON object with schema-stable keys.
2. **Given** `--format ndjson`, **When** a list-shaped command (`export`, `range`) runs, **Then** stdout is one JSON object per line, followed by a final page-footer object `{"kind":"page","shown":N,"total":M,"next":"..."}`.
3. **Given** output was truncated, **When** `--format json` is used, **Then** the JSON object contains `"truncated": true`, `"total_diff_lines": N`, and a `"next"` field with the exact command to retrieve more.
4. **Given** `--format json` or `--format ndjson`, **When** the command runs in any environment, **Then** the output contains no ANSI colour codes.

---

### User Story 5 — Shell Scripts Retain File-Output Behaviour (Priority: P3)

Existing shell scripts that capture the output path from a temp file must continue to work by passing `--out PATH`.

**Why this priority**: Breaking existing scripts needlessly hurts adoption. `--out` is a one-flag migration path.

**Independent Test**: Run `cex owner/repo --show SHA --out /tmp/test.txt` and confirm the file is created and its path is printed to stdout.

**Acceptance Scenarios**:

1. **Given** `--out PATH` is provided, **When** any command runs, **Then** output is written to PATH and the resolved file path is printed to stdout.
2. **Given** `--out PATH` where parent directories do not exist, **When** the command runs, **Then** directories are created and the file is written.

---

### Edge Cases

- What happens when `--export` is run against a repo with 0 commits?
- What happens when `--file PATH` is given but PATH was never modified in any commit?
- What happens when `--show SHA` is called for an initial (parentless) commit and `--diff` is requested?
- What happens when `--limit` exceeds the total commit count?
- What happens when `--format json` and `--out PATH` are both given?
- How does rename-following behave when a file was renamed multiple times?
- What happens when `--max-lines 0` is combined with a diff that is millions of lines?

---

## Requirements *(mandatory)*

### Functional Requirements

**Stdout & output routing**

- **FR-001**: The tool MUST write command output to stdout by default, with no file side-effects, when `--out` is not provided.
- **FR-002**: When `--out PATH` is provided, the tool MUST write output to PATH (creating parent directories as needed) and print the resolved file path to stdout.

**Progressive disclosure defaults**

- **FR-003**: `--show`, `--compare`, and `--pr` MUST default to outputting metadata and the changed-file list with per-file stats; they MUST NOT include a diff unless `--diff` or `--file` is specified.
- **FR-004**: `--export` MUST default to at most 50 commits, with a `[N of M commits shown]` footer and a `Next:` hint on the final line.
- **FR-005**: `--range` MUST default to per-commit metadata and file list only (no diffs), paginated at 50 entries.

**Progressive-disclosure flags**

- **FR-006**: `--summary` MUST reduce output to metadata and stat line only, suppressing file list, diff, and commit log, for all commands.
- **FR-007**: `--diff` MUST add the full diff section to `show`, `compare`, and `pr`. When used without `--max-lines`, it MUST implicitly cap output at 500 lines.
- **FR-008**: `--file PATH` on `show`, `compare`, `pr`, and `range` MUST include the diff for that specific file only (repeatable for multiple files); it implies `--diff` for those files.
- **FR-009**: `--file PATH` on `export` MUST filter the commit list to only commits that touched PATH, following renames across the repository history.
- **FR-010**: `--no-diff` MUST explicitly suppress the diff section.
- **FR-011**: `--max-lines N` MUST truncate stdout to N lines and append a truncation marker with the exact command to retrieve full output. `N=0` means no cap.
- **FR-012**: `--max-bytes N` MUST truncate stdout at N bytes with the same marker. `N=0` means no cap.

**Pagination**

- **FR-013**: `--limit N` MUST control the maximum number of commits returned by `export` and `range`. Default is 50. `N=0` means unbounded.
- **FR-014**: `--offset M` MUST skip the first M commits in `export` and `range` results.
- **FR-015**: Every paginated response MUST include a footer stating commits shown vs. total and the exact `cex … --offset N` command to fetch the next page.

**Structured output**

- **FR-016**: `--format json` MUST produce a single valid JSON object per run with schema-stable keys: `kind`, `repo`, `sha`/`base`/`target`, `summary`, `files`, `diff`, `truncated`, `next`.
- **FR-017**: `--format ndjson` MUST produce one JSON object per commit/entry, followed by a final `{"kind":"page", ...}` object with pagination metadata.
- **FR-018**: JSON and ndjson output MUST never contain ANSI colour codes regardless of TTY state.
- **FR-019**: `--format text` MUST produce human-readable output identical in structure to the current format (default).

**Colour**

- **FR-020**: `--color auto` (default) MUST emit colour when stdout is a TTY and `NO_COLOR` is not set; otherwise plain text.
- **FR-021**: `--color always` MUST emit colour regardless of TTY. `--color never` MUST always suppress colour.

### Key Entities

- **Commit**: identified by SHA; has message, author, date, parents, and a set of file changes.
- **FileChange**: a path, change status (added/modified/removed/renamed), addition count, deletion count.
- **Page**: a bounded slice of a commit list; carries `shown`, `total`, and the `next` command hint.
- **DiffSection**: the raw unified-diff text for one or more files; may be truncated with a marker.
- **PR/MR Metadata**: title, state, author, base ref, head ref, body text, repository coordinates.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running any `cex` command with default flags against a repository with 1,000,000+ commits produces output bounded to under 60 lines.
- **SC-002**: An agent can obtain PR metadata, file list, a single-file diff, and a specific commit's full diff in 4 or fewer `cex` invocations, each producing under 600 lines.
- **SC-003**: `--format json` output passes JSON schema validation on every run with no missing mandatory keys.
- **SC-004**: The `Next:` hint command, when run verbatim, returns the correct subsequent page with no repeated or missing entries.
- **SC-005**: All 73 existing tests continue to pass after each implementation phase lands.
- **SC-006**: New tests covering stdout mode, progressive-disclosure flags, pagination correctness, JSON schema stability, and file-history filtering achieve ≥ 90% coverage of new code paths.
- **SC-007**: `--export --file PATH` against a repo with renames returns only commits that touched PATH under any of its historical names.

---

## Assumptions

- The primary consumer of the new behaviour is an AI agent running in a non-TTY context; human-interactive use remains supported but is not the optimisation target.
- "Follows renames" for `--export --file PATH` means the same behaviour as `git log --follow`; edge cases where git cannot determine rename lineage result in a warning line and partial results, not an error exit.
- `--range` default pagination at 50 entries may still produce large output for wide ranges; this will be reviewed after phase 2 (see open question in PROMPT.md).
- `--out PATH` and `--format json` are orthogonal and combinable: JSON output goes to the file, resolved path goes to stdout.
- The existing `--depth` flag (clone depth) is unchanged; `--limit`/`--offset` are view-layer controls applied after cloning.
- Backwards-breaking changes (`--show`/`--compare`/`--pr`/`--range` no longer write to `/tmp` by default; `--export` now caps at 50) are acceptable for this 0.x tool; no deprecation shim will be added.
