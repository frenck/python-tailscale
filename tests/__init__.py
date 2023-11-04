"""Asynchronous client for the Tailscale API."""

from pathlib import Path


def load_fixture(filename: str) -> str:
    """Load a fixture."""
    path = Path(__file__).parent / "fixtures" / filename
    return path.read_text()
