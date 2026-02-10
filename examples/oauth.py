#!/usr/bin/env python3
# pylint: disable=W0621
"""Asynchronous client for the Tailscale API."""

import asyncio
import os

from tailscale import Tailscale

# "-" is the default tailnet of the API key
TAILNET = os.environ.get("TS_TAILNET", "-")

# OAuth client ID and secret are required for OAuth authentication
OAUTH_CLIENT_ID = os.environ.get("TS_API_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("TS_API_CLIENT_SECRET", "")


async def main_oauth() -> None:
    """Show example on using the Tailscale API client with OAuth."""
    async with Tailscale(
        tailnet=TAILNET,
        oauth_client_id=OAUTH_CLIENT_ID,
        oauth_client_secret=OAUTH_CLIENT_SECRET,
    ) as tailscale:
        devices = await tailscale.devices()
        print(devices)


if __name__ == "__main__":
    asyncio.run(main_oauth())
