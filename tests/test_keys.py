"""Asynchronous client for the Tailscale API."""
# pylint: disable=protected-access
import asyncio
import json
from typing import Dict

import aiohttp
import pytest
from aresponses import Response, ResponsesMockServer

from tailscale import Tailscale
from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)
from tailscale.models import AuthKey

test_authkey_1 = {
    "id": "k01234567890abcdef",
    "description": "test key",
    "created": "2022-12-01T05:23:30Z",
    "lastUsed": "2022-12-01T05:23:30Z",
    "expires": "2023-07-30T04:44:05Z",
    "user": "user@example.com",
    "node": "test",
    "tags": ["tag:golink"],
    "comment": "This is a test auth key",
}


@pytest.mark.asyncio
async def test_key_get(aresponses: ResponsesMockServer):
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/tailnet/frenck/keys/test",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=json.dumps(test_authkey_1),
        ),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        key = await tailscale.get_key("test")
        assert isinstance(key, AuthKey)
        assert key.key == "test"
