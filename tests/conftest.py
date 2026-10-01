from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aievidence.scenario import Plants, run

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    """A fresh copy of the demo directory with the scenario run inside it."""
    d = tmp_path / "demo"
    d.mkdir()
    shutil.copy(REPO / "demo" / "reviewers.yaml", d / "reviewers.yaml")
    run(d, plants=Plants())
    return d
