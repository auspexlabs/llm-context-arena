"""Sample module for CodeRAG chunker tests."""

import os


def helper(x: int) -> int:
    return x + 1


class Widget:
    def spin(self) -> str:
        return "spinning"

    def stop(self):
        self.spin()