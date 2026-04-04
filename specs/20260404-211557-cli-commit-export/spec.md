# Feature Specification: CLI Commit Export by SHA and Range

**Feature Branch**: `20260404-211557-cli-commit-export`  
**Created**: 2026-04-04  
**Status**: Draft  
**Input**: User description: "@PROMPT.md"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Export a Single Commit (Priority: P1)

A developer wants to capture the full details of one specific commit — its metadata, changed files, and diff — without opening the TUI. They run a single command, pass a commit SHA, and get a `.txt` file they can share or archive.

**Why this priority**: The most atomic and independently useful operation. Directly addresses the core gap of the tool having no headless commit inspection.

**Independent Test**: Run `cex owner/repo --show <sha>` and verify a `.txt` file is created containing the commit's author, date, message, file changes, and full diff.

**Acceptance Scenarios**:

1. **Given** a valid repo and a short or full SHA, **When** `--show <sha>` is run, **Then** a `.txt` file is written to the output folder containing all commit metadata, file change stats, and the full per-file diff.
2. **Given** `--show <sha>` without `--out`, **When** the command runs, **Then** the file is written to `/tmp` by default.
3. **Given** `--show <sha> --out ./reports` where `./reports` does not exist, **When** the command runs, **Then** the folder is created automatically and the file is written inside it.
4. **Given** an invalid or unknown SHA, **When** `--show <sha>` is run, **Then** an error message is printed to stderr and the command exits with a non-zero code.

---

### User Story 2 - Export a Linear Range of Commits by Two SHAs (Priority: P2)

A developer wants to review all commits between two known points in history (e.g., before and after a feature landed). They pass two SHAs and get one file per commit written to a folder.

**Why this priority**: Enables audit trails, release notes generation, and code review across a span of work. High value for teams reviewing changes between milestones.

**Independent Test**: Run `cex owner/repo --range <base-sha> <target-sha>` and verify one `.txt` file per commit in the ancestor chain from `target-sha` back to (but not including) `base-sha`.

**Acceptance Scenarios**:

1. **Given** two SHAs with a linear ancestry relationship, **When** `--range <base> <target>` is run, **Then** one `.txt` file is created per commit in the range, named with the short SHA and message slug.
2. **Given** two SHAs with no ancestor relationship, **When** `--range` is run, **Then** an error is printed explaining the SHAs are unrelated, and no files are written.
3. **Given** `--range <target-sha> --depth N` (single SHA form), **When** the command runs, **Then** the N most recent ancestors of `<target-sha>` are exported, one file each.
4. **Given** `--range` without `--out`, **When** the command runs, **Then** files are written to `/tmp`.

---

### User Story 3 - Custom Output Folder for All Headless Modes (Priority: P3)

A developer wants all CLI export commands (`--show`, `--range`, `--compare`, `--pr`) to write their output to a folder they specify, with automatic folder creation.

**Why this priority**: Quality-of-life improvement that unifies output behavior across all headless modes and removes friction of manually creating directories.

**Independent Test**: Run any headless command with `--out /some/new/path` and verify the folder is created and files appear inside it.

**Acceptance Scenarios**:

1. **Given** any headless command with `--out <path>` where `<path>` does not exist, **When** the command runs, **Then** the path is created recursively and output files are written there.
2. **Given** any headless command without `--out`, **When** the command runs, **Then** output defaults to `/tmp`.
3. **Given** `--out <path>` where the user lacks write permission, **When** the command runs, **Then** a clear error is printed to stderr and the command exits with a non-zero code.

---

### Edge Cases

- What happens when `--show` is given a SHA for the initial commit (no parents, no diff)?
- What happens when `--range` produces a very large number of commits (e.g., hundreds) — should there be a warning or a cap?
- What if `--depth` is too shallow and the base SHA of a `--range` is not present in the cloned history?
- How are output filenames deduplicated if two commits produce the same short SHA prefix?
- What if the output folder path contains spaces or special characters?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept `--show <sha>` to export a single commit's full details (metadata, stats, full per-file diff) to a `.txt` file.
- **FR-002**: System MUST accept `--range <base-sha> <target-sha>` to export all commits reachable from `target-sha` back to (not including) `base-sha` — equivalent to `git log base..target` — including merge commits, one `.txt` file per commit.
- **FR-003**: System MUST accept `--range <target-sha> --depth N` (single-SHA form) to export the N most recent ancestors of `<target-sha>`, one `.txt` file per commit.
- **FR-004**: System MUST accept `--out <folder>` as a shared flag for all headless commands (`--show`, `--range`, `--compare`, `--pr`) to set the output directory.
- **FR-005**: System MUST default the output folder to `/tmp` when `--out` is not specified.
- **FR-006**: System MUST create the output folder (including any missing parent directories) if it does not already exist before writing any files.
- **FR-007**: System MUST print a clear error to stderr and exit non-zero if a given SHA cannot be resolved in the cloned repository.
- **FR-008**: System MUST print a clear error to stderr and exit non-zero if the two SHAs in `--range <base> <target>` have no ancestor relationship.
- **FR-009**: Output filenames for commit exports MUST follow the format `<date>_<short-sha>_<slug>.txt` (e.g., `20260404_abc1234_fix-null-check.txt`), falling back to full SHA if short SHA is ambiguous.
- **FR-010**: System MUST print the path of each exported file to stdout upon completion.
- **FR-011**: System MUST print `Exporting N/total…` progress per commit to stderr during `--range` execution.

### Key Entities

- **CommitExport**: A `.txt` file capturing one commit — SHA, author, date, message, file change stats, and full per-file unified diff.
- **CommitRange**: The ordered list of commits in the linear ancestor chain between two SHAs (equivalent to `git log base..target`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can export a single commit's full details with one command, receiving the output file path on stdout upon completion.
- **SC-002**: A user can export a range of commits with one command, receiving one file per commit, without any manual directory setup.
- **SC-003**: The output folder is always ready to receive files — created automatically if absent — so zero commands fail due to a missing directory.
- **SC-004**: All headless commands (`--show`, `--range`, `--compare`, `--pr`) respect the same `--out` flag with identical behavior, requiring no per-command variation in how output paths are specified.
- **SC-005**: Invalid SHA inputs produce a clear, actionable error message in under 5 seconds so the user understands the problem without reading source code.

## Clarifications

### Session 2026-04-04

- Q: Should `--range` include merge commits? → A: Yes, include merge commits like any other commit (metadata + diff, no special marker).
- Q: Should there be a warning or cap for large ranges? → A: No cap, no warning — always export all commits silently.
- Q: What is the output filename format for commit exports? → A: `<date>_<short-sha>_<slug>.txt` — e.g., `20260404_abc1234_fix-null-check.txt`.
- Q: Should `--range` print progress during export? → A: Yes, print `Exporting N/total…` per commit to stderr.

## Assumptions

- Short SHAs (7+ characters) are accepted and resolved the same way `git` resolves them; ambiguous short SHAs result in an error.
- For `--range <target> --depth N`, the `--depth` flag controls both clone depth and the number of commits exported; they are the same value.
- Output `.txt` files for commits follow the same format as existing `--compare` and `--pr` exports (metadata header + diff body), extended with commit-specific fields.
- Applying `--out` in TUI mode (no headless flag) is a no-op and does not affect behavior.
- Filename collision (two commits with identical short SHA prefix) is resolved by using the full SHA in the filename.
- The initial commit (no parents) produces a file with metadata and a note that no diff is available, rather than an error.
