# Tasks: CLI Commit Export by SHA and Range

**Input**: Design documents from `/specs/20260404-211557-cli-commit-export/`  
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/cli-flags.md ✅, quickstart.md ✅

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files or non-overlapping sections)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- All changes go to `app.py` (single-file architecture)

---

## Phase 1: Setup

**Purpose**: Verify the working baseline before touching any code.

- [x] T001 Confirm `uv run cex --help` lists current flags (`--export`, `--compare`, `--pr`, `--depth`, `--provider`) and that `uv run cex owner/repo --export` produces output — establishes the no-regression baseline

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared helpers required by ALL user stories. Must be complete before Phase 3+.

**⚠️ CRITICAL**: US1, US2 both depend on these helpers existing in `app.py`.

- [x] T002 Add `_slugify(text: str) -> str` function to `app.py` (place near `_write_export`): lowercase input, replace non-alphanumeric runs with `-`, strip leading/trailing `-`, truncate to 40 chars — used to build commit export filenames
- [x] T003 Add `_write_commit_export(detail: CommitDetail, out_dir: str) -> str` function to `app.py` (place after `_slugify`): writes a single commit's full details to `<out_dir>/<YYYYMMDD>_<short-sha>_<slug>.txt`; file sections: header block (SHA, author, date, message, generated timestamp), DIFF SUMMARY, CHANGED FILES table, FULL DIFF (unified diff per file from `detail.files`); returns the file path; for initial commit (no parents), write metadata + note "No diff available (initial commit)" instead of empty diff section

**Checkpoint**: `_slugify` and `_write_commit_export` exist in `app.py` and are importable/callable.

---

## Phase 3: User Story 1 — Export a Single Commit (Priority: P1) 🎯 MVP

**Goal**: `cex owner/repo --show <sha>` exports full commit details to a `.txt` file and prints the path.

**Independent Test**: Run `uv run cex owner/repo --show <short-or-full-sha> --out /tmp` — verify `/tmp/<date>_<sha>_<slug>.txt` exists and contains SHA, author, date, diff sections.

- [x] T004 [US1] Add `--show SHA` argument and `--out PATH` argument (default `/tmp`) to `main()` argparse in `app.py`; add `os.makedirs(args.out, exist_ok=True)` in `main()` before the dispatch block so the folder is always ready when any headless mode runs
- [x] T005 [US1] Implement `async _show(owner: str, repo: str, provider_key: str, sha: str, depth: Optional[int], out_dir: str) -> None` in `app.py` (place after `_export`): clone repo via provider, resolve `sha` using `Repo(backend._tmpdir)[sha.encode()]` (catch `KeyError` → print error to stderr + `sys.exit(1)`), call `backend.get_detail(sha)`, call `_write_commit_export(detail, out_dir)`, print returned path to stdout
- [x] T006 [US1] Wire `--show` dispatch in `main()` in `app.py`: add `elif args.show:` branch (validate `args.repo` has `owner/repo` format, split, call `asyncio.run(_show(owner, repo, args.provider, args.show, args.depth, args.out))`) — place this branch before `elif args.export`
- [x] T007 [US1] Manual smoke test per quickstart.md: run `uv run cex owner/repo --show <sha>`, `uv run cex owner/repo --show <sha> --out ./exports` (folder auto-created), and `uv run cex owner/repo --show invalid000` (expect non-zero exit + stderr error)

**Checkpoint**: `--show` works end-to-end. US1 independently complete and testable.

---

## Phase 4: User Story 2 — Export a Commit Range (Priority: P2)

**Goal**: `cex owner/repo --range <base> <target>` or `--range <sha> --depth N` exports one `.txt` file per commit with stderr progress.

**Independent Test**: Run `uv run cex owner/repo --range <base-sha> <target-sha> --out /tmp` — verify one file per commit in the range exists in `/tmp`, progress lines printed to stderr, merge commits included.

- [x] T008 [US2] Add `--range SHA [SHA]` argument (`nargs='+'`, `metavar='SHA'`) to `main()` argparse in `app.py`; add validation in dispatch: if `len(args.range) > 2`, print error and exit; if `--range` used without `--depth` and only 1 SHA, print error requiring either 2 SHAs or `--depth N`
- [x] T009 [US2] Implement `async _range(owner: str, repo: str, provider_key: str, range_shas: list[str], depth: Optional[int], out_dir: str) -> None` in `app.py` (place after `_show`):
  - Clone repo (same pattern as `_show`)
  - **2-SHA form** (`len(range_shas) == 2`): resolve both SHAs, use `repo.get_walker(include=[target_bytes], exclude=[base_bytes])` from `dulwich.walk` to collect commits; if walker yields 0 commits, print error "SHAs have no ancestor relationship" to stderr and exit non-zero
  - **1-SHA form** (`len(range_shas) == 1`): resolve SHA, use `repo.get_walker(include=[sha_bytes], max_entries=depth)`
  - Reverse collected commits to oldest-first
  - For each commit: print `Exporting N/total…` to stderr, call `backend.get_detail(sha)`, call `_write_commit_export(detail, out_dir)`, print file path to stdout
- [x] T010 [US2] Wire `--range` dispatch in `main()` in `app.py`: add `elif args.range:` branch (validate `args.repo`, split owner/repo, call `asyncio.run(_range(...))`) — place after `--show` branch
- [x] T011 [US2] Manual smoke test per quickstart.md: run `--range <base> <target>`, `--range <sha> --depth 5`, and `--range <unrelated-sha1> <unrelated-sha2>` (expect error); verify progress lines on stderr and one file per commit in output folder

**Checkpoint**: `--range` works end-to-end. US2 independently complete and testable.

---

## Phase 5: User Story 3 — Unified `--out` for Existing Headless Modes (Priority: P3)

**Goal**: `--compare` and `--pr` also write to `--out` folder instead of always writing to CWD.

**Independent Test**: Run `uv run cex owner/repo --compare main feature/foo --out ./exports` — verify report `.txt` appears in `./exports/`, not CWD.

- [x] T012 [US3] Update `_write_export(result, pr_meta, out_dir: str = ".")` signature in `app.py`: add `out_dir` parameter with default `"."`, update the `open(filename, "w")` call to `open(os.path.join(out_dir, filename), "w")`
- [x] T013 [P] [US3] Update `_compare(owner, repo, provider_key, depth, base, target, out_dir: str)` signature in `app.py`: add `out_dir` parameter, pass it to `_write_export(result, out_dir=out_dir)`
- [x] T014 [P] [US3] Update `_pr_review(url, provider_key, depth, out_dir: str)` signature in `app.py`: add `out_dir` parameter, pass it to `_write_export(result, pr_meta=pr, out_dir=out_dir)`
- [x] T015 [US3] Update `main()` dispatch in `app.py` to pass `args.out` to `_compare()` and `_pr_review()` calls
- [x] T016 [US3] Manual smoke test: run `--compare main <branch> --out ./exports` and `--pr <url> --out ./exports`; verify files appear in `./exports/` not CWD

**Checkpoint**: All headless modes (`--show`, `--range`, `--compare`, `--pr`) honour `--out`. US3 complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T017 Update `CLI.md` at repo root: add `--show`, `--range`, `--out` to the synopsis table and add examples to the Quick Examples section; update the `--depth` row to note its dual meaning with `--range`
- [x] T018 Regression check: run `uv run cex owner/repo --export`, `--compare`, and `--pr` without `--out` and verify output still goes to CWD (default `"."` preserved) and existing behaviour unchanged

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — **BLOCKS Phase 3 and Phase 4**
- **Phase 3 (US1)**: Depends on Phase 2
- **Phase 4 (US2)**: Depends on Phase 2; can run in parallel with Phase 3 if desired
- **Phase 5 (US3)**: Depends on Phase 3 (needs `--out` arg added to `main()`); T013 and T014 can run in parallel
- **Phase 6 (Polish)**: Depends on all story phases

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational (T002, T003). No dependency on US2 or US3.
- **US2 (P2)**: Depends on Foundational (T002, T003). No dependency on US1 or US3 (though `--out` arg from T004 must exist — implement T004 before T008 or add `--out` in T008).
- **US3 (P3)**: Depends on US1 completing T004 (which adds `--out` to argparse and `makedirs`).

### Parallel Opportunities

- T002 and T003 are independent within Phase 2
- T013 and T014 (Phase 5) are independent — different functions in `app.py`
- Phase 3 (US1) and Phase 4 (US2) can overlap after Phase 2 is done

---

## Parallel Example: Phase 2

```
# Both foundational helpers can be written simultaneously (non-overlapping code):
Task T002: "_slugify() helper in app.py"
Task T003: "_write_commit_export() in app.py"
```

## Parallel Example: Phase 5

```
# T013 and T014 touch different functions — can be done in parallel:
Task T013: "Update _compare() signature and _write_export call"
Task T014: "Update _pr_review() signature and _write_export call"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002, T003)
3. Complete Phase 3: User Story 1 (T004–T007)
4. **STOP and VALIDATE**: `uv run cex owner/repo --show <sha>` works
5. Ship `--show` as first CLI enhancement

### Incremental Delivery

1. Phase 1 + Phase 2 → shared helpers ready
2. Phase 3 → `--show` works → MVP CLI export
3. Phase 4 → `--range` works → range export
4. Phase 5 → `--out` for all modes → unified output control
5. Phase 6 → docs + regression checks

---

## Notes

- All tasks modify `app.py` only — single-file architecture per constitution
- No new dependencies needed — Dulwich `get_walker` handles range walk natively
- `[P]` tasks within Phase 2 and Phase 5 can be done in parallel since they touch non-overlapping functions
- Stop at each checkpoint to manually validate the story before proceeding
- Commit after each phase or logical group (Conventional Commits: `feat:`, `fix:`)
