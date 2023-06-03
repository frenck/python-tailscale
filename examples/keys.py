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

        keys = await tailscale.keys()
        print(keys)

        key_id = keys[0]
        key = await tailscale.get_key(key_id)
        print(key)

        new_key = await tailscale.create_auth_key()
        print(new_key)

        await tailscale.delete_key(new_key.key_id)

        keys_left = await tailscale.keys()
        print(keys_left)


if __name__ == "__main__":
    asyncio.run(main())
