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
========================================================================
Compare: origin/{base} → origin/{target}
Generated: {YYYY-MM-DD HH:MM:SS}
[WARNING: Shallow clone — commit log and conflict results may be incomplete]

========================================================================

DIFF SUMMARY
------------------------------------------------------------------------
{shortstat line, e.g. "3 files changed, 42 insertions(+), 5 deletions(-)"}

CHANGED FILES ({n})
------------------------------------------------------------------------
  {STATUS}      {filename}    +{additions}  -{deletions}
  ...

COMMIT LOG ({n} commits in origin/{target} not in origin/{base})
------------------------------------------------------------------------
{full git log --stat output with commit SHA, Author, Date, message, file stats}

FULL DIFF
------------------------------------------------------------------------
{full git diff output — all hunks, context lines, every changed file}

CONFLICTS
------------------------------------------------------------------------
{either "Clean merge — no conflicts detected"
 or one block per conflicting file:
   File: {filename}
   ------------------------------------------------------------------------
   {raw conflict-marker text with <<<<<<< / ======= / >>>>>>> lines}
}
```

## Invariants

- File is UTF-8 encoded.
- Sections are always present in the order shown, even if empty.
- Shallow warning line is omitted when `shallow_warning` is False.
- COMMIT LOG uses full `git log --stat` format (full SHA, author email, timestamp, per-file stats).
- FULL DIFF contains the complete `git diff` output with all hunks untruncated.
