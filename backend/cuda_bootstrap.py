"""CUDA wheel sanity checks before importing torch."""

from __future__ import annotations

import importlib.metadata as im
import logging
import os
from typing import Iterable

logger = logging.getLogger(__name__)

# Torch's Linux wheels expect these pip packages to ship matching .so files.
_CRITICAL_NVIDIA_PACKAGES = (
    "nvidia-cudnn-cu12",
    "nvidia-cusparselt-cu12",
    "nvidia-nccl-cu12",
)


def _so_files(dist: im.Distribution) -> Iterable[str]:
    for entry in dist.files or ():
        path = str(entry)
        if ".so" in path:
            yield path


def missing_nvidia_cuda_libs() -> list[str]:
    """Return pip NVIDIA packages whose recorded .so files are absent on disk."""
    missing: list[str] = []
    for package in _CRITICAL_NVIDIA_PACKAGES:
        try:
            dist = im.distribution(package)
        except im.PackageNotFoundError:
            missing.append(f"{package} (not installed)")
            continue

        absent = [
            path
            for path in _so_files(dist)
            if not os.path.exists(dist.locate_file(path))
        ]
        if absent:
            missing.append(f"{package} ({len(absent)} library file(s) missing)")
    return missing


def ensure_nvidia_cuda_libs() -> bool:
    """Log a repair hint when pip NVIDIA wheels are only partially installed."""
    gaps = missing_nvidia_cuda_libs()
    if not gaps:
        return True

    logger.error(
        "NVIDIA CUDA libraries are incomplete (%s). "
        "GPU is present but PyTorch cannot load until wheels are repaired. "
        "Run: uv sync --reinstall-package torch",
        "; ".join(gaps),
    )
    return False