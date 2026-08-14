"""Shared pytest configuration.

Puts the repository root on sys.path so the test suite runs against the
working tree without requiring an editable install.
"""
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEST_FOLDER = REPO_ROOT / 'test'
