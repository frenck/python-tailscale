# pylint: disable=W0621
"""Asynchronous client for the Tailscale API."""

import asyncio
import os

from tailscale import Tailscale

API_KEY = os.environ.get("TS_API_KEY", "tskey-somethingsomething")
TAILNET = os.environ.get("TS_TAILNET", "-")  # "-" is the default tailnet of the API key


async def main() -> None:
    """Show example on using the Tailscale API client."""
    async with Tailscale(
        tailnet=TAILNET,
        api_key=API_KEY,
    ) as tailscale:

        devices = await tailscale.devices()
        print(devices)

        device_id = devices.popitem()[0]
        device_info = await tailscale.device(device_id)
        print(device_info)

        await tailscale.authorize_device(device_id, authorized=False)
        print(await tailscale.device(device_id))

        await tailscale.authorize_device(device_id, authorized=True)
        print(await tailscale.device(device_id))

        if device_info.tags:
            tags = device_info.tags + ["tag:some-tag"]
        else:
            tags = ["tag:some-tag"]
        await tailscale.tag_device(
            device_id,
            tags=tags,
        )
        tagged_device = await tailscale.device(device_id)
        print(tagged_device.tags)

        await tailscale.delete_device(device_id)


if __name__ == "__main__":
    asyncio.run(main())
