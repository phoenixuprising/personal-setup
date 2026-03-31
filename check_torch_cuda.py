#!/usr/bin/env python3
"""Print basic PyTorch CUDA availability details."""

import torch


def main() -> None:
    print("torch_version", torch.__version__)
    print("torch_cuda_build", torch.version.cuda)
    print("cuda_available", torch.cuda.is_available())
    print("cuda_device_count", torch.cuda.device_count())
    if torch.cuda.is_available():
        print("device_name", torch.cuda.get_device_name(0))


if __name__ == "__main__":
    main()
