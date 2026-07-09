"""Tests for CUDA wheel sanity checks."""

from backend.cuda_bootstrap import ensure_nvidia_cuda_libs, missing_nvidia_cuda_libs


class TestCudaBootstrap:
    def test_libs_present_on_this_machine(self):
        assert missing_nvidia_cuda_libs() == []
        assert ensure_nvidia_cuda_libs() is True