# Tasks: PR/MR Review from URL

**Input**: Design documents from `/specs/20260329-233618-pr-review/`
**Prerequisites**: spec.md ✓

**Structure**: All code lives in `app.py` (single-file architecture per constitution).

---

## Phase 1: Core Types & URL Resolution

- [X] T001 Add `PRMetadata` NamedTuple to Types section of `app.py` — fields: `provider`, `owner`, `repo`, `number`, `title`, `state`, `author`, `base`, `head`, `url`, `head_clone_url`, `head_owner`, `description`
- [X] T002 Implement `_resolve_pr_url(url) -> PRMetadata` in `app.py` — parses GitHub PR URLs (`github.com/.../pull/N`) and GitLab MR URLs (`gitlab.com/.../merge_requests/N`); calls provider REST API to fetch base/head branch names, title, state, author, description; raises `ValueError` for unsupported URL formats

---

## Phase 2: CLI `--pr` Flag

- [X] T003 Implement `_add_fork_remote(tmpdir, fork_url, branch)` helper in `app.py` — adds `pr-head` remote pointing at the fork and fetches the given branch with `--filter=blob:none`
- [X] T004 Implement `_pr_review(url, provider_key, depth)` async function in `app.py` — resolves PR metadata, clones base repo, adds fork remote for cross-fork PRs, calls `compare_branches(base, head_ref)`, writes export via `_write_export(result, pr_meta=pr)`, prints summary to stdout
- [X] T005 Add `--pr URL` argument to `main()` argparse in `app.py` — takes priority over `--compare`; `owner/repo` positional arg optional (inferred from URL)
- [X] T006 Update `_write_export()` to accept optional `pr_meta` — when present: use `compare-{owner}-{repo}-pr{N}-{YYYYMMDD}.txt` filename; prepend PR metadata header (URL, title, author, state, description) before diff sections

---

## Phase 3: TUI Integration

- [X] T007 Pass `owner`, `repo`, `provider` to `CompareScreen.__init__()` from `action_compare()` in `CommitExplorer`
- [X] T008 Add PR/MR number input row to `CompareScreen.compose()` — `Input` with placeholder "PR/MR number (e.g. 123)" + "Fill branches" `Button`; placed above existing branch inputs
- [X] T009 Implement `_build_pr_url(number)` method on `CompareScreen` — constructs full GitHub/GitLab URL from loaded repo context; raises `ValueError` if repo not loaded or provider unsupported
- [X] T010 Implement `_run_pr_resolve()` `@work` method on `CompareScreen` — resolves PR URL, adds fork remote if cross-fork, auto-fills base/target inputs, triggers `_run_comparison()`; stores `pr_meta` in `self._last_pr`
- [X] T011 Update `_render_comparison()` to show PR header when `self._last_pr` is set — display title, author, state, and up to 20 lines of description (truncated with "… see export" notice)
- [X] T012 Update `on_export_pressed()` to pass `pr_meta=self._last_pr` to `_write_export()` so export filename includes PR number

---

## Phase 4: Cross-Fork PR Support

- [X] T013 Detect cross-fork PRs in `_pr_review()` — compare `pr.head_owner` vs `pr.owner`; if different, call `_add_fork_remote()` and set `head_ref = "pr-head/<branch>"`
- [X] T014 Detect cross-fork PRs in `CompareScreen._run_pr_resolve()` — same logic; set target input to `pr-head/<branch>` so `_run_comparison()` uses the correct ref
- [X] T015 Update `compare_branches()` ref resolution — handle pre-qualified refs (`pr-head/...`) without adding `origin/` prefix; update blob fetch to use correct remote per ref

---

## Validation

- [X] T016 CLI: tested with `cex --pr https://github.com/anthropics/claude-code/pull/40594` (cross-fork PR) — 7 files changed, correct diff and commit log in export
- [X] T017 TUI: tested with PR number input `40586` on `anthropics/claude-code` — base/target auto-filled, comparison runs, PR title shown in results
