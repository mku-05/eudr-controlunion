import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("EUDR_DATA_DIR", str(ROOT / "data" / "test"))
os.environ.setdefault("EUDR_GEO_PROVIDER", "mock")

from tests.fixtures.build_fixtures import build  # noqa: E402


@pytest.fixture(scope="session")
def fixture_case_dir() -> Path:
    return build()


@pytest.fixture(scope="session")
def layers_dir(fixture_case_dir) -> Path:
    return ROOT / "tests" / "fixtures" / "layers"


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "live" in item.keywords and not os.environ.get("EUDR_LIVE"):
            item.add_marker(pytest.mark.skip(reason="set EUDR_LIVE=1"))
        if "agent" in item.keywords and not os.environ.get("EUDR_AGENT"):
            item.add_marker(pytest.mark.skip(reason="set EUDR_AGENT=1"))
