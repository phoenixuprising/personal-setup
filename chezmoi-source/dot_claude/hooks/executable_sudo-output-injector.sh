#!/bin/bash
# Injects sudo command output into Claude's context automatically.
# Works in tandem with the sudo-via-clipboard skill:
#   - The skill writes a pending file to /tmp/claude-sudo-pending/<session_id>/<uuid>
#   - This hook checks for ready pending files on every user message
#   - If output files exist, their contents are injected into Claude's context

set -euo pipefail

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

if [ -z "$SESSION_ID" ]; then
  exit 0
fi

# Register session_id keyed by our PPID so the skill's bash commands can look it up
PPID_DIR="/tmp/claude-sudo-ppid"
mkdir -p "$PPID_DIR"
echo "$SESSION_ID" > "$PPID_DIR/$PPID"

PENDING_DIR="/tmp/claude-sudo-pending/$SESSION_ID"

if [ ! -d "$PENDING_DIR" ]; then
  exit 0
fi

# Collect output from all ready pending commands
COLLECTED=""
for PENDING_FILE in "$PENDING_DIR"/*; do
  [ -f "$PENDING_FILE" ] || continue

  OUTPUT_FILE=$(cat "$PENDING_FILE")
  [ -f "$OUTPUT_FILE" ] || continue  # Command hasn't run yet — skip silently

  CONTENT=$(cat "$OUTPUT_FILE")
  LABEL=$(basename "$OUTPUT_FILE")
  COLLECTED="$COLLECTED\n### Output from $LABEL\n\`\`\`\n$CONTENT\n\`\`\`\n"

  rm "$PENDING_FILE"
done

if [ -z "$COLLECTED" ]; then
  exit 0
fi

# Inject all collected outputs into Claude's context
CONTEXT=$(printf "The sudo command(s) you requested have been run. Here are the outputs:\n%b\nContinue your task using these results." "$COLLECTED")

jq -n --arg ctx "$CONTEXT" '{
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: $ctx
  }
}'

exit 0
