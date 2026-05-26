"""
Shared fixtures for all tests.
Uses the pre-indexed 'sparrow' project to avoid re-indexing in every test.
"""
import os
import sys
import pytest

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("CASSETTO_PROJECT_ID", "sparrow")

SPARROW_DIR = os.path.join(ROOT, "sparrow")


@pytest.fixture(scope="session")
def project_id():
    return "sparrow"


@pytest.fixture(scope="session")
def sparrow_dir():
    return SPARROW_DIR
