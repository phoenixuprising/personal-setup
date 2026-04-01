#!/usr/bin/env python3
"""Shared logging and summary helpers for repo-local CLI tools."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

LogFormat = Literal["text", "json"]


@dataclass
class ToolRuntime:
    """Emit human-readable logs and optionally machine-readable summaries."""

    tool_name: str
    log_format: LogFormat = "text"
    json_output: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _emit_log(self, level: str, message: str, **fields: Any) -> None:
        payload = {
            "timestamp": self._timestamp(),
            "tool": self.tool_name,
            "level": level,
            "message": message,
        }
        if fields:
            payload["fields"] = fields

        if self.log_format == "json":
            print(json.dumps(payload, sort_keys=True), file=sys.stderr)
            return

        suffix = ""
        if fields:
            rendered = ", ".join(f"{key}={value}" for key, value in sorted(fields.items()))
            suffix = f" ({rendered})"
        print(f"{level.upper():<5} {message}{suffix}", file=sys.stderr)

    def info(self, message: str, **fields: Any) -> None:
        """Emit an informational log line."""
        self._emit_log("info", message, **fields)

    def warn(self, message: str, **fields: Any) -> None:
        """Emit a warning log line."""
        self._emit_log("warn", message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        """Emit an error log line."""
        self._emit_log("error", message, **fields)

    def record_event(self, action: str, status: str = "ok", **fields: Any) -> None:
        """Append a structured event to the eventual JSON summary."""
        event = {
            "timestamp": self._timestamp(),
            "action": action,
            "status": status,
        }
        if fields:
            event["fields"] = fields
        self.events.append(event)

    def emit_summary(self, **fields: Any) -> None:
        """Write the tool summary to stdout when JSON output is enabled."""
        if not self.json_output:
            return
        payload = {
            "tool": self.tool_name,
            "events": self.events,
        }
        payload.update(fields)
        print(json.dumps(payload, indent=2, sort_keys=True))
