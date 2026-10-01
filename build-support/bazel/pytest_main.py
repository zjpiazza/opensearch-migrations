"""Pytest entry point that preserves Bazel's test reporting contract."""

import os
import sys

import pytest

if __name__ == "__main__":
    args = sys.argv[1:] + ["-q", "-p", "no:cacheprovider"]
    if "XML_OUTPUT_FILE" in os.environ:
        args += ["--junitxml=" + os.environ["XML_OUTPUT_FILE"]]
    raise SystemExit(pytest.main(args))
