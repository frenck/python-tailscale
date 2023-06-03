# pylint: disable=W0621
"""Asynchronous client for the Tailscale API."""

import asyncio
import random

from tailscale import Tailscale


async def main() -> None:
    """Show example on using the Tailscale API client."""
    async with Tailscale(
        tailnet="frenck",
        api_key="tskey-somethingsomething",
    ) as tailscale:

        devices = await tailscale.devices()
        print(devices)

        device_id = random.choice(list(devices.keys()))
        device = await tailscale.device(device_id)
        print(device)

        unauthorized = await tailscale.authorize_device(device_id, authorized=False)
        print(unauthorized)

        authorized = await tailscale.authorize_device(device_id, authorized=True)
        print(authorized)

        await tailscale.tag_device(device_id, tags=device.tags.append("tag:some-tag"))
        tagged_device = await tailscale.device(device_id)
        print(tagged_device.tags)

        await tailscale.delete_device(device_id)


if __name__ == "__main__":
    asyncio.run(main())
