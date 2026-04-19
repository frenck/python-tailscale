"""Common fixtures and helpers for Tailscale tests."""

from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import aiohttp
import pytest
from aioresponses import aioresponses

from tailscale import Tailscale

FIXTURES_DIR = Path(__file__).parent / "fixtures"

URL = "https://api.tailscale.com/api/v2"


def load_fixture(name: str) -> str:
    """Load a fixture file by name."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def responses() -> Generator[aioresponses, None, None]:
    """Yield an aioresponses instance that patches aiohttp client sessions."""
    with aioresponses() as mocker:
        yield mocker


@pytest.fixture
async def tailscale_client() -> AsyncGenerator[Tailscale, None]:
    """Yield a Tailscale client wired to a test tailnet."""
    async with aiohttp.ClientSession() as session:
        yield Tailscale(tailnet="frenck", api_key="abc", session=session)
