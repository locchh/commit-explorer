# Tasks: Agent-Friendly CLI (Progressive Disclosure)

**Input**: Design documents from `specs/20260418-212347-agent-friendly-cli/`  
**Prerequisites**: plan.md ✓, spec.md ✓, data-model.md ✓, contracts/cli-flags.md ✓, quickstart.md ✓

**Baseline**: 73 existing tests must pass after every phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no shared state)
- **[US#]**: Which user story this task belongs to
- Tests are included (SC-005, SC-006 require ≥ 90% coverage of new code paths)

---

## Phase 1: Setup

**Purpose**: Unblock development — the constitution gate must clear before any code changes.

- [ ] T001 Amend `.specify/memory/constitution.md` — replace Principle I (`app.py` single-file rule) with the current `src/commit_explorer/` package layout; bump version to 1.1.0

**Checkpoint**: Constitution gate passes; implementation can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Stdout routing flip + OutputConfig + parser additions. Every user story depends on this phase.

⚠️ **CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T002 Add `OutputConfig` dataclass to `src/commit_explorer/cli.py` — fields: `stream`, `out_dir`, `include_diff`, `include_files`, `file_filter`, `max_lines`, `max_bytes`, `limit`, `offset`, `fmt`, `color`; implement the invariants from `data-model.md` (stream/out_dir mutual exclusion; `--diff` without `--max-lines` → 500; `fmt json/ndjson` → `color=never`)
- [ ] T003 [P] Add `stream: IO[str] | None = None` parameter to `write_export()` in `src/commit_explorer/export.py` — when stream is set, write lines to it and return `None`; else write to file and return path (existing behaviour preserved)
- [ ] T004 [P] Add `stream: IO[str] | None = None` parameter to `write_commit_export()` in `src/commit_explorer/export.py` — same semantics as T003
- [ ] T005 Extend `_build_parser()` in `src/commit_explorer/cli.py` with all new flags: `--summary`, `--diff`, `--no-diff`, `--file PATH` (append, repeatable), `--max-lines N`, `--max-bytes N`, `--limit N`, `--offset M`, `--format {text,json,ndjson}`, `--color {auto,always,never}`
- [ ] T006 Update `main()` in `src/commit_explorer/cli.py` — assemble `OutputConfig` from parsed args; remove `/tmp` default for all file commands (no `--out` → stdout); pass `OutputConfig` to every handler
- [ ] T007 [P] Refactor `_show()` in `src/commit_explorer/cli.py` to accept `OutputConfig`; when `out_dir is None` call `write_commit_export(..., stream=sys.stdout)`; when `out_dir` set, write file and print path (unchanged)
- [ ] T008 [P] Refactor `_compare()` in `src/commit_explorer/cli.py` to accept `OutputConfig`; stdout default (remove summary print + "Exported to" print; write full content to stream)
- [ ] T009 [P] Refactor `_pr_review()` in `src/commit_explorer/cli.py` to accept `OutputConfig`; stdout default (same as T008)
- [ ] T010 [P] Refactor `_range()` in `src/commit_explorer/cli.py` to accept `OutputConfig`; write per-commit output to stdout with `\n---\n` separator between entries (no per-commit file writes)
- [ ] T011 Refactor `_export()` in `src/commit_explorer/cli.py` to accept `OutputConfig`; stdout remains default (already was), wire config through
- [ ] T012 [P] Add stdout-mode tests in `tests/test_exports.py` — use `stream=io.StringIO()` to verify `write_export()` and `write_commit_export()` produce correct content without writing files; verify `out_dir` path still returns file path
- [ ] T013 [P] Update `tests/test_cli.py` — add tests: `--out PATH` writes file and prints path; default `--show` and `--compare` print full content to stdout without creating files

**Checkpoint**: All 73 baseline tests pass; stdout routing works; `--out` compat verified.

---

## Phase 3: User Story 1 — Safe Large-Repo Exploration (Priority: P1) 🎯 MVP

**Goal**: Default `--export` returns at most 50 commits with a `Next:` hint; `--offset`/`--limit` pages through the full history safely.

**Independent Test**: Run `cex owner/repo --export` and verify output ≤ 55 lines with `[N of M commits shown]` footer and `Next:` command. Run `Next:` verbatim and verify the next page arrives with no duplicates.

- [ ] T014 [US1] Add `_fmt_page_footer(shown, total, offset, limit, base_cmd)` helper in `src/commit_explorer/cli.py` — returns two-line string: `[N of M commits shown]\nNext: cex ... --offset X --limit Y` (or empty string when all shown)
- [ ] T015 [US1] Apply default `limit=50` and `offset=0` from `OutputConfig` in `_export()` in `src/commit_explorer/cli.py` — slice the resolved commit list; call `_fmt_page_footer`; print footer after graph output
- [ ] T016 [US1] Apply `--limit` and `--offset` to `_range()` in `src/commit_explorer/cli.py` — slice `entries` list by offset/limit; print `_fmt_page_footer` after last entry
- [ ] T017 [P] [US1] Add pagination tests in `tests/test_cli.py` — verify: default `--export` returns ≤ 50 entries; footer `[N of M]` present; `--offset 50` returns next page; `--limit 0` returns all; footer absent when all entries fit

**Checkpoint**: US1 independently testable — any repo, any size, default is safe.

---

## Phase 4: User Story 2 — File History (Priority: P1)

**Goal**: `--export --file PATH` returns only commits that touched that path (rename-aware); paginates the same way as the full graph.

**Independent Test**: Run `cex owner/repo --export --file src/commit_explorer/backend.py` and confirm only commits that modified that file are listed, with a `Next:` hint that preserves `--file` in the command.

- [ ] T018 [US2] Implement file-history filter in `_export()` in `src/commit_explorer/cli.py` — when `config.file_filter` is non-empty, run `git --git-dir TMPDIR log --follow --format=%H -- PATH` subprocess per path, union the resulting SHA sets, filter the commit list to matching SHAs before applying limit/offset
- [ ] T019 [US2] Include `--file PATH` flag(s) in the `Next:` hint produced by `_fmt_page_footer` in `src/commit_explorer/cli.py` — one `--file X` token per path in `config.file_filter`
- [ ] T020 [US2] Add warning line when `git log --follow` returns 0 results for a given path in `_export()` in `src/commit_explorer/cli.py` — print to stderr: `Warning: no commits found touching 'PATH'`
- [ ] T021 [P] [US2] Add file-history filter tests in `tests/test_file_history.py` — verify: only commits touching the path appear; unknown path prints warning and returns empty list; `--file` appears in `Next:` hint; pagination still works with filter applied

**Checkpoint**: US2 independently testable — file-evolution queries produce bounded, filtered output.

---

## Phase 5: User Story 3 — Progressive PR Review (Priority: P2)

**Goal**: `--show`/`--compare`/`--pr` default to file-list-only (no diff); `--summary` strips to metadata; `--diff` opts in; `--file PATH` restricts diff to one file.

**Independent Test**: Run `cex --pr URL --summary` → ≤ 20 lines. Run `cex --pr URL` → file list, no diff. Run `cex --pr URL --file path` → only that file's diff.

- [ ] T022 [US3] Add section-control params to `write_export()` in `src/commit_explorer/export.py` — `include_diff: bool = True` (preserves current behaviour as default for file writes; callers from handlers pass `False`); `include_files: bool = True` — when False omit CHANGED FILES section; when `include_diff=False` omit FULL DIFF section entirely
- [ ] T023 [P] [US3] Add section-control params to `write_commit_export()` in `src/commit_explorer/export.py` — same semantics as T022
- [ ] T024 [US3] Resolve section-flag priority order in `OutputConfig` construction in `src/commit_explorer/cli.py`: `--summary` → `include_diff=False, include_files=False`; `--no-diff` → `include_diff=False`; `--diff` → `include_diff=True, max_lines=500` (if not set); `--file PATH` on show/compare/pr/range → `include_diff=True` for those paths only (store in `file_filter`)
- [ ] T025 [P] [US3] Pass `include_diff`, `include_files`, `file_filter` from `OutputConfig` into `write_commit_export()` in `_show()` in `src/commit_explorer/cli.py`
- [ ] T026 [P] [US3] Pass section params from `OutputConfig` into `write_export()` in `_compare()` and `_pr_review()` in `src/commit_explorer/cli.py`
- [ ] T027 [P] [US3] Pass section params per-commit in `_range()` in `src/commit_explorer/cli.py`
- [ ] T028 [P] [US3] Filter diff output to `file_filter` paths in `write_commit_export()` in `src/commit_explorer/export.py` — when `file_filter` non-empty, only emit diff hunks for matching paths (parse `diff --git a/PATH` lines to detect boundaries)
- [ ] T029 [P] [US3] Add progressive-disclosure tests in `tests/test_exports.py` — verify: `--summary` → no CHANGED FILES, no FULL DIFF; `--diff` → FULL DIFF present; `--file path` → only that path's diff; `--no-diff` → no diff; section defaults (no diff by default)

**Checkpoint**: US3 independently testable — PR review uses 3–5 bounded calls instead of one dump.

---

## Phase 6: User Story 4 — JSON / ndjson Format (Priority: P2)

**Goal**: `--format json` emits a schema-stable JSON object; `--format ndjson` emits one object per commit plus a page footer. No ANSI codes ever in JSON output.

**Independent Test**: `cex owner/repo --show SHA --format json | python -m json.tool` exits 0. Every mandatory key is present. `cex owner/repo --export --format ndjson` — last line is a valid `{"kind":"page",...}` object.

- [ ] T030 [US4] Create `src/commit_explorer/format.py` — move `OutputConfig` here (import it back in `cli.py` for now); add `_strip_ansi(text)` helper; add `commit_detail_to_dict(detail, config)` → schema-stable dict per `data-model.md`; add `branch_comparison_to_dict(result, pr_meta, config)` → same
- [ ] T031 [P] [US4] Add `render_json(data_dict, stream)` in `src/commit_explorer/format.py` — serialize with `json.dumps(indent=2)` to stream; include `"next"` hints; set `"truncated": false` and `"diff": null` when diff excluded
- [ ] T032 [P] [US4] Add `render_ndjson(entries, page_info, stream)` in `src/commit_explorer/format.py` — one `json.dumps` per entry on its own line; final line is `{"kind":"page",...}` with `next` command string
- [ ] T033 [US4] Wire `--format json` in `_show()` in `src/commit_explorer/cli.py` — when `config.fmt == "json"` call `render_json(commit_detail_to_dict(...), stream)` instead of `write_commit_export()`
- [ ] T034 [P] [US4] Wire `--format json` in `_compare()` and `_pr_review()` in `src/commit_explorer/cli.py` — call `render_json(branch_comparison_to_dict(...), stream)`
- [ ] T035 [P] [US4] Wire `--format ndjson` in `_export()` and `_range()` in `src/commit_explorer/cli.py` — emit one line per commit then call `render_ndjson` footer
- [ ] T036 [US4] Enforce `color="never"` when `fmt in ("json","ndjson")` in `OutputConfig.__post_init__` in `src/commit_explorer/format.py`
- [ ] T037 [P] [US4] Add JSON schema tests in `tests/test_format.py` — verify all mandatory keys present; no ANSI escape sequences in output; `truncated` field correct; `next` hints echo correct command with all flags
- [ ] T038 [P] [US4] Add ndjson tests in `tests/test_format.py` — verify one JSON object per commit; last line is `{"kind":"page",...}`; every line is individually valid JSON; pagination `next` field correct

**Checkpoint**: US4 independently testable — agents can parse every response with `json.loads()`.

---

## Phase 7: User Story 5 — Shell Scripts Retain File-Output Behaviour (Priority: P3)

**Goal**: `--out PATH` still writes file and prints resolved path; parent directories created automatically.

**Independent Test**: `cex owner/repo --show SHA --out /tmp/test-dir/out.txt` → file created at that path; `/tmp/test-dir/out.txt` printed to stdout.

- [ ] T039 [US5] Verify `--out PATH` path in `main()` in `src/commit_explorer/cli.py` — `out_dir` set → `os.makedirs(out_dir, exist_ok=True)`; handlers receive `out_dir` via `OutputConfig`; stream remains `None` so writers use file path
- [ ] T040 [P] [US5] Add `--out` compat tests in `tests/test_cli.py` — verify: file created at exact path; parent dirs created if missing; resolved path printed to stdout; no other stdout content

**Checkpoint**: US5 testable — existing shell scripts work with `--out /tmp`.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Size caps, colour control, documentation.

- [ ] T041 Implement `--max-lines N` truncation in `src/commit_explorer/cli.py` — wrap the output stream with a `_LineLimitStream` class that counts `\n` chars; when limit reached, flush remaining buffer, append `\n… output truncated. Run: <next-cmd> for full output.`; `N=0` disables wrapping
- [ ] T042 [P] Implement `--max-bytes N` truncation in `src/commit_explorer/cli.py` — same pattern as T041 with byte counter
- [ ] T043 [P] Implement `--color auto/always/never` in `src/commit_explorer/cli.py` — for `auto`: check `sys.stdout.isatty() and not os.environ.get("NO_COLOR")`; for `never`: strip ANSI from output stream; wire into `_export()` graph subprocess `--color` flag
- [ ] T044 [P] Add size-cap tests in `tests/test_cli.py` — verify `--max-lines 5` caps output at 5 lines and appends truncation marker; `--max-lines 0` does not truncate; marker contains correct next-command
- [ ] T045 [P] Update `CLAUDE.md` — document new flags, stdout-default behaviour, and progressive disclosure pattern
- [ ] T046 Run full test suite: `uv run pytest -x` — confirm all baseline + new tests green; confirm 73 original tests untouched

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
  └── Phase 2 (Foundational) ← BLOCKS ALL
        ├── Phase 3 (US1 — Pagination)
        ├── Phase 4 (US2 — File History)   ← depends on Phase 3 (_export stub)
        ├── Phase 5 (US3 — Progressive Flags)
        ├── Phase 6 (US4 — JSON Format)    ← depends on Phase 5 (section params)
        └── Phase 7 (US5 — --out Compat)   ← covered by Phase 2; verify only
              └── Phase 8 (Polish)
```

### User Story Dependencies

| Story | Depends On | Can Parallelise With |
|-------|-----------|----------------------|
| US1 (Phase 3) | Phase 2 | US3, US5 |
| US2 (Phase 4) | Phase 2 + Phase 3 stub | US3, US5 |
| US3 (Phase 5) | Phase 2 | US1, US2, US5 |
| US4 (Phase 6) | Phase 2 + Phase 5 (section params) | US1, US2 |
| US5 (Phase 7) | Phase 2 | US1, US2, US3 |

### Within Each Phase

- `[P]` tasks share no files — launch simultaneously
- Non-`[P]` tasks within the same phase are sequential (typically: core logic before wire-up)
- Tests within a phase can run after their implementation task; rerun full suite at each checkpoint

---

## Parallel Opportunities

### Phase 2 (Foundational) — launch these together

```
T003 (write_export stream param)  +  T004 (write_commit_export stream param)
T007 (_show refactor)  +  T008 (_compare)  +  T009 (_pr_review)  +  T010 (_range)
T012 (export tests)  +  T013 (cli tests)
```

### Phase 5 (US3) — launch these together after T022/T023

```
T025 (_show wiring)  +  T026 (_compare/_pr wiring)  +  T027 (_range wiring)
T028 (diff path filter)  +  T029 (tests)
```

### Phase 6 (US4) — launch these together after T030

```
T031 (render_json)  +  T032 (render_ndjson)
T037 (json tests)  +  T038 (ndjson tests)
```

---

## Implementation Strategy

### MVP (US1 + US5 only — Phases 1–3 + 7)

1. Phase 1: Constitution amendment
2. Phase 2: Foundational routing flip
3. Phase 3: Pagination (US1)
4. Phase 7: --out compat verify (US5)
5. **Validate**: `cex locchh/commit-explorer --export` returns ≤ 55 lines; `--out /tmp` still works

### Incremental Delivery

```
Phases 1–2 → safe stdout routing (US5 done)
+ Phase 3  → safe pagination (US1 done)
+ Phase 4  → file history (US2 done)
+ Phase 5  → progressive flags (US3 done)
+ Phase 6  → JSON format (US4 done)
+ Phase 8  → size caps + colour + docs
```

Each increment keeps all prior tests green and delivers independently demonstrable value.

---

## Notes

- `[P]` = different files, no dependencies within the phase — safe to run in parallel
- `[US#]` maps each task to its user story for traceability
- Run `uv run pytest -x` at every checkpoint; a red baseline is a blocker
- T003/T004 preserve backward compat: existing callers (`out_dir=tmp_path`) are unchanged
- T028 (diff path filter) is the trickiest task — diff text must be parsed by `diff --git a/PATH` header lines; test thoroughly before wiring into handlers
- The `--range` open question (summary vs file-list default) is resolved in T010: file-list default, 50-entry limit; revisit if agents report context pressure
