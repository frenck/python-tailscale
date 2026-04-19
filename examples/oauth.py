"""Asynchronous Python client for the Tailscale API."""

import asyncio
import os

from tailscale import Tailscale

TAILNET = os.environ.get("TS_TAILNET", "-")
OAUTH_CLIENT_ID = os.environ.get("TS_API_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("TS_API_CLIENT_SECRET", "")


async def main() -> None:
    """Show example of using the Tailscale API client with OAuth."""
    async with Tailscale(
        tailnet=TAILNET,
        oauth_client_id=OAUTH_CLIENT_ID,
        oauth_client_secret=OAUTH_CLIENT_SECRET,
    ) as tailscale:
        devices = await tailscale.devices()

        for device_id, device in devices.items():
            print(f"{device.hostname} ({device.os})")
            print(f"  ID: {device_id}")
            print(f"  Addresses: {', '.join(device.addresses)}")


if __name__ == "__main__":
    asyncio.run(main())
