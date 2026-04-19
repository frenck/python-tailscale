# pylint: disable=W0621
"""Asynchronous Python client for the Tailscale API."""

import asyncio

from tailscale import Tailscale


async def main() -> None:
    """Show example of using the Tailscale API client."""
    async with Tailscale(
        tailnet="frenck",
        api_key="tskey-somethingsomething",
    ) as tailscale:
        devices = await tailscale.devices()

        for device_id, device in devices.items():
            print(f"{device.hostname} ({device.os})")
            print(f"  ID: {device_id}")
            print(f"  Addresses: {', '.join(device.addresses)}")
            print(f"  Last seen: {device.last_seen}")
            print(f"  Update available: {device.update_available}")


if __name__ == "__main__":
    asyncio.run(main())
