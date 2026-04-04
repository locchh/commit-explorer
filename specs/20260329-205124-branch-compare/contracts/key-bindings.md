# Contract: Key Bindings

**Scope**: New bindings introduced by the Branch Comparison feature.

## New Bindings

### Main `CommitExplorer` app

| Key | Action | Description | Condition |
|-----|--------|-------------|-----------|
| `c` | `compare` | Open compare screen | Repo must be loaded (`_owner` set) |

### `CompareScreen`

| Key | Action | Description |
|-----|--------|-------------|
| `escape` | `dismiss` | Return to main commit view |

## Existing Bindings (unchanged)

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Reload |
| `n` | Next page |

## Footer Display

Both screens display their bindings in the Textual `Footer`. The compare key (`c`) MUST only appear / be active after a repo is loaded.
