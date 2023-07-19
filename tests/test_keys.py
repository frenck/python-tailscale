"""Asynchronous client for the Tailscale API."""
# pylint: disable=protected-access
import asyncio
import json
from typing import Dict

import aiohttp
import pytest
from aresponses import ResponsesMockServer

from tailscale import Tailscale
from tailscale.models import AuthKey

test_authkey_1 = {
    "id": "test",
    "description": "test key",
    "created": "2022-12-01T05:23:30Z",
    "lastUsed": "2022-12-01T05:23:30Z",
    "expires": "2023-07-30T04:44:05Z",
    "user": "user@example.com",
    "tags": ["tag:golink"],
}

test_authkeys = {
    "keys" : [
        {
            "id": "kjkdshCNTRL",
            "description": "information about key"
        },
        {
            "id": "ksdDc5CNTRL"
        }
    ]
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
        assert key.key_id == "test"


@pytest.mark.asyncio
async def test_keys_get(aresponses: ResponsesMockServer):
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/tailnet/frenck/keys",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=json.dumps(test_authkeys),
        ),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        ts_keys = await tailscale.keys()
        assert isinstance(ts_keys, Dict)
        assert len(ts_keys.keys()) == 2
        assert ts_keys.pop("kjkdshCNTRL") == "information about key"
