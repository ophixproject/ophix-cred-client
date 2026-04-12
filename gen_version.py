#!/usr/bin/env python3
"""
Generate cred_client/_version.py from pyproject.toml.

Run this after bumping the version in pyproject.toml:
    python gen_version.py

The generated _version.py is committed and ships with the installed package,
preserving the verbatim version string (pip normalises leading zeroes away).
"""

import tomli
from pathlib import Path

pyproject_path = Path(__file__).parent / "pyproject.toml"
version_file_path = Path(__file__).parent / "src" / "cred_client" / "_version.py"

with pyproject_path.open("rb") as f:
    pyproject_data = tomli.load(f)

version = pyproject_data["project"]["version"]

version_file_path.write_text(f'__version__ = "{version}"\n', encoding="utf-8")

print(f"Generated {version_file_path} with version {version}")
