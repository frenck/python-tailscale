# pylint: disable=W0621
"""Asynchronous client for the Tailscale API."""

import asyncio

from tailscale import Tailscale


async def main() -> None:
    """Show example on using the Tailscale API client."""
    async with Tailscale(
        tailnet="frenck",
        api_key="tskey-somethingsomething",
    ) as tailscale:

        devices = await tailscale.devices()
        print(devices)


if __name__ == "__main__":
    asyncio.run(main())
