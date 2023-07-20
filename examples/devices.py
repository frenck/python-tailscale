# pylint: disable=W0621
"""Asynchronous client for the Tailscale API."""

import asyncio
import os

from tailscale import Tailscale

API_KEY = os.environ.get("TS_API_KEY", "tskey-somethingsomething")
TAILNET = os.environ.get("TS_TAILNET", "-")  # "-" is the default tailnet of the API key
OAUTH_CLIENT_ID = os.environ.get("TS_API_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("TS_API_CLIENT_SECRET", "")


async def main() -> None:
    """Show example on using the Tailscale API client."""
    async with Tailscale(
        tailnet=TAILNET,
        api_key=API_KEY,
        oauth_client_id=OAUTH_CLIENT_ID,
        oauth_client_secret=OAUTH_CLIENT_SECRET,
    ) as tailscale:

        devices = await tailscale.devices()
        print(devices)


if __name__ == "__main__":
    asyncio.run(main())
