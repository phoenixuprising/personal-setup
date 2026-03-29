---
name: sudo-via-clipboard
description: Use this skill any time you need to run a command that requires sudo or elevated privileges. Instead of running sudo directly, copy the command (wrapped with tee for output capture) to the user's clipboard, register a pending file so the hook can inject the output automatically on their next message, then continue once the output arrives. Trigger this whenever a command would fail or be denied without sudo — package installs, system config changes, writing to protected paths, service management, etc.
---

# Sudo Via Clipboard

When a command requires `sudo`, you cannot run it directly. Hand it off to the user via clipboard — the output will be injected automatically into Claude's context when they send their next message after running it.

## Workflow

### 1. Prepare and copy in one bash call

Do everything in a single bash invocation (variables don't persist between calls):

```bash
SESSION_ID=$(cat /tmp/claude-sudo-ppid/$PPID 2>/dev/null)
UUID=$(uuidgen)
OUTPUT_FILE="/tmp/claude-sudo-${UUID}.txt"
PENDING_DIR="/tmp/claude-sudo-pending/${SESSION_ID}"

mkdir -p "$PENDING_DIR"
echo "$OUTPUT_FILE" > "${PENDING_DIR}/${UUID}"

echo "sudo <original-command> 2>&1 | tee ${OUTPUT_FILE}" | wl-copy
echo "Ready. Output will go to: $OUTPUT_FILE"
```

If SESSION_ID is empty, the hook hasn't registered yet — ask the user to send any message first, then retry.

### 2. Tell the user

Let them know:
- The command is on their clipboard — paste and run it
- Briefly what it does, so they can make an informed decision before running with sudo
- After running it, just send any message and the output will be picked up automatically

Example:
> "The command is on your clipboard — it will install ripgrep system-wide. Paste and run it, then send me any message when done."

### 3. Wait — the hook handles the rest

When the user sends their next message (after the command has run), the `sudo-output-injector` hook will detect the output file, inject its contents into Claude's context, and clean up the pending file automatically.

If the user sends a message before running the command, the hook silently does nothing — the pending file stays until the command is run.
