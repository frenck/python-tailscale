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

        policy = await tailscale.policy()
        print(policy)

        if policy.tag_owners:
            policy.tag_owners.update({"tag:environment-dev": ["group:dev"]})
        new_policy = await tailscale.update_policy(policy)
        print(new_policy)


if __name__ == "__main__":
    asyncio.run(main())
