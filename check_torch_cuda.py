#!/usr/bin/env python3
"""Print basic PyTorch CUDA availability details."""

import argparse
import json

import torch

from tool_runtime import ToolRuntime


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the CUDA verification helper."""
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
        help="Emit a machine-readable summary to stdout.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    runtime = ToolRuntime("check-torch-cuda", log_format=args.log_format, json_output=args.json)

    payload = {
        "torch_version": torch.__version__,
        "torch_cuda_build": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
    }
    if payload["cuda_available"]:
        payload["device_name"] = torch.cuda.get_device_name(0)

    runtime.record_event("inspect-torch-cuda", **payload)

    if args.json:
        runtime.emit_summary(ok=True, **payload)
        return

    for key, value in payload.items():
        print(key, value)


if __name__ == "__main__":
    main()
