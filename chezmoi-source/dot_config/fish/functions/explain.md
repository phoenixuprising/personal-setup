# explain

Reads and displays the markdown documentation file associated with a fish function.

## Usage

```
explain <function-name>
```

## Arguments

| Argument | Description |
|----------|-------------|
| `function-name` | Name of the fish function to look up (without the `.fish` extension) |

## Behavior

Looks for a `.md` file alongside the function's `.fish` file in `~/.config/fish/functions/`. Renders it using the best available tool:

1. `glow` — full terminal markdown rendering (preferred)
2. `bat` — syntax-highlighted plaintext fallback
3. `cat` — raw fallback if neither is installed

Exits with status `1` and prints the expected file path if no documentation file is found.

## Notes

- Documentation files are expected at `~/.config/fish/functions/<name>.md`.
- New fish functions written by Claude automatically get a companion `.md` file via a `PostToolUse` hook.
