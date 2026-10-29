"""Default paths resolved at runtime relative to the working directory of the
process.
"""

from pathlib import Path


def default_output_dir() -> Path:
    return Path.cwd() / "output"
