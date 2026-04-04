# Feature Specification: PR/MR Review from URL

**Feature Branch**: `20260329-233618-pr-review`
**Created**: 2026-03-29
**Status**: Draft
**Input**: Given a PR/MR URL, automatically resolve the base and head branches, run the existing branch comparison, and produce a detailed review report — usable both from the CLI and the TUI.

## Clarifications

### Session 2026-03-29

- Q: Which providers should be supported? → A: GitHub PRs and GitLab MRs (same providers already supported by the tool).
- Q: How are base/head branches resolved from a PR URL? → A: Via the provider REST API (GitHub: `GET /repos/{owner}/{repo}/pulls/{number}`, GitLab: `GET /projects/{id}/merge_requests/{iid}`). Requires an API token already used by the tool.
- Q: Is Azure DevOps PRs in scope? → A: Out of scope for this spec — GitHub and GitLab only.
- Q: Should the TUI also support `--pr`? → A: Yes — TUI gets a new input field for a PR URL on the compare screen, alongside the existing branch name inputs.
- Q: What if the PR is already merged or closed? → A: Still produce the report using the recorded base/head SHAs or branch names; show a warning banner if the head branch no longer exists on the remote.
- Q: Where is the output written? → A: Same as `--compare` — a `.txt` file in CWD, filename encodes owner, repo, PR number, and date.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review PR from CLI (Priority: P1)

The user runs `cex owner/repo --pr <URL>` (or `cex --pr <URL>` with repo inferred from URL). The tool fetches PR metadata, resolves base and head branches, clones the repo, runs the comparison, prints a summary to stdout, and writes a detailed `.txt` report.

**Why this priority**: The core use case — reviewing a PR without opening a browser, scriptable in CI.

**Independent Test**: Run `cex --pr https://github.com/owner/repo/pull/123` and verify the output matches the base/head shown on the GitHub PR page, and that the `.txt` report contains the correct diff and commit log.

**Acceptance Scenarios**:

1. **Given** a valid GitHub PR URL, **When** the user runs `cex --pr <URL>`, **Then** the tool resolves base and head branches via the GitHub API and runs the comparison.
2. **Given** a valid GitLab MR URL, **When** the user runs `cex --pr <URL>`, **Then** the tool resolves base and head branches via the GitLab API and runs the comparison.
3. **Given** the PR URL includes the repo path (e.g. `github.com/owner/repo/pull/N`), **When** no explicit `owner/repo` positional argument is given, **Then** the tool infers owner/repo from the URL.
4. **Given** the API token is missing or invalid, **When** the tool attempts to resolve the PR, **Then** an error message is shown and the tool exits cleanly.
5. **Given** the head branch no longer exists on the remote (merged/deleted), **When** the comparison runs, **Then** a warning is shown and the report notes the branch is unavailable.

---

### User Story 2 - Review PR from TUI Compare Screen (Priority: P2)

On the compare screen, the user can paste a PR/MR URL into a dedicated input field. The tool resolves the branches and pre-fills the base/target inputs, then runs the comparison automatically.

**Why this priority**: Keeps the TUI workflow consistent — users already on the compare screen shouldn't have to switch to the CLI.

**Independent Test**: Open the compare screen, paste a PR URL, verify the base and target inputs are populated and comparison runs correctly.

**Acceptance Scenarios**:

1. **Given** the compare screen is active, **When** the user pastes a PR URL into the URL input and submits, **Then** the base and target inputs are auto-filled and comparison starts.
2. **Given** an invalid or non-PR URL is entered, **When** the user submits, **Then** an error notification is shown and inputs remain editable.

---

### Edge Cases

- PR URLs with extra query params or fragments (e.g. `?diff=unified#files`) must be parsed correctly.
- GitLab MR URLs use `/merge_requests/` path, GitHub uses `/pull/`.
- Azure DevOps URLs must be rejected with a clear "not supported" message.
- If the repo positional argument and the repo in the URL disagree, the URL takes precedence with a warning.
- Rate-limited API responses must surface a clear error, not a silent failure.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The CLI MUST accept `--pr <URL>` as an alternative to `--compare BASE TARGET`; `owner/repo` MAY be omitted if inferrable from the URL.
- **FR-002**: The tool MUST support GitHub PR URLs (`github.com/{owner}/{repo}/pull/{N}`) and GitLab MR URLs (`gitlab.com/{owner}/{repo}/-/merge_requests/{N}` or self-hosted).
- **FR-003**: Branch resolution MUST use the provider REST API (`base` and `head`/`source_branch` fields from the PR/MR response).
- **FR-004**: After branch resolution, `--pr` MUST reuse the existing `compare_branches()` pipeline unchanged.
- **FR-005**: The export filename MUST encode the PR number: `compare-{owner}-{repo}-pr{N}-{YYYYMMDD}.txt`.
- **FR-006**: The CLI summary output MUST include the PR title, number, state (open/closed/merged), and author before the diff summary.
- **FR-007**: The TUI compare screen MUST add a PR URL input field; submitting it auto-fills base/target inputs and triggers comparison.
- **FR-008**: If the API token is absent, the tool MUST print a clear error naming the required environment variable and exit with a non-zero code.

### Key Entities

- **PR/MR URL**: A string identifying a pull/merge request; parsed into provider, owner, repo, and number.
- **PR Metadata**: API response containing at minimum: title, number, state, author, base branch name, head branch name.
- **Review Report**: The exported `.txt` — same format as branch comparison, with a PR metadata header section prepended.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `cex --pr <url>` produces a report in under 30 seconds for a PR with up to 200 commits on a standard internet connection.
- **SC-002**: Base and head branch names in the report match those shown on the provider website in 100% of tested cases.
- **SC-003**: The export file contains all sections (PR metadata, diff summary, changed files, commit log, full diff, conflicts) in 100% of test cases.
- **SC-004**: Unsupported URL formats (Azure, random URLs) produce a clear error message and non-zero exit code in 100% of cases.

## Assumptions

- The existing `GITHUB_TOKEN` / `GITLAB_TOKEN` environment variables are reused for API calls — no new auth mechanism needed.
- GitLab self-hosted instances are supported if the user provides the base URL via an existing env var or a new `--gitlab-url` flag (out of scope for this spec — default to `gitlab.com`).
- The PR/MR API call fetches only metadata (one small JSON response) — no pagination needed.
- The existing `filter=blob:none` clone strategy is reused unchanged.
- Comparing more than one PR at a time is out of scope.
