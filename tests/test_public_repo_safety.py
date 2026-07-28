"""Public repository safety checks."""

import subprocess
import sys
from pathlib import Path


def test_sensitive_information_scan() -> None:
    """The repository contains no likely credential or capture artifacts."""
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "scripts/check_no_secrets.py"],
        cwd=root,
        check=True,
    )
