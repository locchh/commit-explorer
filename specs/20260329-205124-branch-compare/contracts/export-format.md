# Contract: Export File Format

**Scope**: The `.txt` file produced when the user presses "Export" on the compare screen.

## Filename

```
compare-{base}-{target}-{YYYYMMDD}.txt
```

- `{base}` and `{target}` are the short branch names with `/` replaced by `-`
- `{YYYYMMDD}` is the local date at export time
- Written to the current working directory

**Example**: `compare-main-feature-my-thing-20260329.txt`

## File Structure

```
Compare: origin/{base} → origin/{target}
Generated: {YYYY-MM-DD HH:MM:SS}
[Shallow clone warning line if applicable]

── Diff Summary ────────────────────────────────────────
{shortstat line, e.g. "3 files changed, 42 insertions(+), 5 deletions(-)"}

── Changed Files ({n}) ─────────────────────────────────
{one line per file: status + filename + (+add -del)}

── Commits ({n}) ───────────────────────────────────────
{one line per commit: short_sha  message  author  date}

── Conflicts ───────────────────────────────────────────
{either "Clean merge — no conflicts detected"
 or one block per conflicting file:
   File: {filename}
   {raw conflict-marker text}
}
```

## Invariants

- File is UTF-8 encoded.
- Sections are always present in the order shown, even if empty (e.g., "No commits" / "Clean merge").
- Shallow warning line is omitted when `shallow_warning` is False.
