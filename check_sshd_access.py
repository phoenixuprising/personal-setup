#!/usr/bin/env python3
"""Inspect local SSH reachability, firewall state, and recent sshd logs."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any

from tool_runtime import ToolRuntime


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for SSH diagnostics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-format",
        choices=("text", "json"),
        default="text",
        help="Emit human-readable or JSON logs to stderr.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable diagnostic summary to stdout.",
    )
    parser.add_argument(
        "--journal-lines",
        type=int,
        default=50,
        help="Number of sshd journal lines to fetch. Default: 50.",
    )
    parser.add_argument(
        "--require-sudo",
        action="store_true",
        help="Exit non-zero if sudo-backed checks cannot run.",
    )
    return parser


def run_command(command: list[str], *, use_sudo: bool = False) -> dict[str, Any]:
    """Run a diagnostic command and return structured output."""
    full_command = ["sudo", *command] if use_sudo else command
    try:
        result = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "command": full_command,
            "error": str(exc),
            "stdout": "",
            "stderr": "",
            "returncode": None,
        }

    return {
        "ok": result.returncode == 0,
        "command": full_command,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
    }


def main() -> int:
    """Run SSH connectivity diagnostics for the local machine."""
    args = build_parser().parse_args()
    runtime = ToolRuntime("check-sshd-access", log_format=args.log_format, json_output=args.json)

    diagnostics: dict[str, Any] = {}
    diagnostics["ip_addr"] = run_command(["ip", "-br", "addr"])
    diagnostics["sshd_status"] = run_command(["systemctl", "status", "sshd", "--no-pager"], use_sudo=True)
    diagnostics["sshd_logs"] = run_command(
        ["journalctl", "-u", "sshd", "-n", str(args.journal_lines), "--no-pager"],
        use_sudo=True,
    )
    diagnostics["listeners"] = run_command(["ss", "-ltnp"], use_sudo=True)
    diagnostics["ufw_status"] = run_command(["ufw", "status", "verbose"], use_sudo=True)

    sudo_unavailable = []
    for key in ("sshd_status", "sshd_logs", "listeners", "ufw_status"):
        diag = diagnostics[key]
        stderr = diag["stderr"].lower()
        if diag["returncode"] and ("sudo" in " ".join(diag["command"])) and (
            "password" in stderr or "a terminal is required" in stderr
        ):
            sudo_unavailable.append(key)

    if sudo_unavailable:
        runtime.warn(
            "Some privileged checks could not run without a sudo password",
            checks=",".join(sudo_unavailable),
        )
        # TODO: Add platform-aware privileged execution once macOS/Debian support is introduced.

    summary = {
        "tool": "check-sshd-access",
        "ok": not (args.require_sudo and sudo_unavailable),
        "sudo_available": not sudo_unavailable,
        "diagnostics": diagnostics,
    }

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["ok"] else 1

    runtime.info("Local IP summary", output=diagnostics["ip_addr"]["stdout"])
    for key in ("sshd_status", "listeners", "ufw_status"):
        diag = diagnostics[key]
        if diag["ok"]:
            runtime.info(f"{key} succeeded")
        else:
            runtime.warn(f"{key} failed", stderr=diag["stderr"] or "no stderr")

    if diagnostics["sshd_logs"]["ok"]:
        print("\n[sshd logs]\n")
        print(diagnostics["sshd_logs"]["stdout"])
    elif diagnostics["sshd_logs"]["stderr"]:
        print("\n[sshd logs unavailable]\n")
        print(diagnostics["sshd_logs"]["stderr"])

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
