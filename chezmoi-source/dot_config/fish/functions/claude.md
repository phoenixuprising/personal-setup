# claude

A wrapper around the `claude` binary that ensures it always runs inside a dedicated tmux session with a split-pane layout.

## Usage

```
claude [args...]
```

All arguments are forwarded directly to the real `claude` binary.

## Behavior

1. **Inside tmux** — passes through immediately to `command claude [args]` with no overhead.
2. **Outside tmux** — launches a new tmuxp-managed session containing one window with two panes:
   - **Top pane** — runs `claude [args]` in the current working directory.
   - **Bottom pane** — an interactive fish shell in the same directory for running commands alongside claude.

## Details

- Uses `tmuxp` to manage the session layout (`main-horizontal` split).
- The session name is randomized (`claude-<random>`) to avoid conflicts when multiple sessions are started.
- Argument passing is handled via a temporary launcher script (`/tmp/claude-*/run.fish`) so that special characters and spaces in arguments are safely preserved without YAML-escaping issues.
- The launcher and tmuxp config are cleaned up automatically after you detach from the session.

## Notes

- Requires `tmuxp` to be installed and on `$PATH`.
- The `$TMUX` environment variable is used to detect an existing tmux session.
