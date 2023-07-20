"""Asynchronous client for the Tailscale API."""
# pylint: disable=protected-access
# pyright: reportGeneralTypeIssues=false
import json
from typing import Dict

import aiohttp
import pytest
from aresponses import ResponsesMockServer

from tailscale import Tailscale

test_device_1 = {
    "addresses": ["100.71.74.78", "fd7a:115c:a1e0:ac82:4843:ca90:697d:c36e"],
    "id": "test",
    "user": "amelie@example.com",
    "name": "pangolin.tailfe8c.ts.net",
    "hostname": "pangolin",
    "clientVersion": "",
    "updateAvailable": False,
    "os": "linux",
    "created": "2022-12-01T05:23:30Z",
    "lastSeen": "2022-12-01T05:23:30Z",
    "keyExpiryDisabled": True,
    "expires": "2023-07-30T04:44:05Z",
    "authorized": True,
    "isExternal": False,
    "machineKey": "test",
    "nodeKey": "nodekey:01234567890abcdef",
    "blocksIncomingConnections": False,
    "enabledRoutes": [
        "10.0.0.0/16",
        "192.168.1.0/24",
    ],
    "advertisedRoutes": [
        "10.0.0.0/16",
        "192.168.1.0/24",
    ],
    "clientConnectivity": {
        "endpoints": ["199.9.14.201:59128", "192.68.0.21:59128"],
        "derp": "1.1.1.1:8080",
        "mappingVariesByDestIP": False,
        "latency": {
            "Dallas": {"latencyMs": 60.463043},
            "New York City": {"preferred": True, "latencyMs": 31.323811},
        },
        "clientSupports": {
            "hairPinning": False,
            "ipv6": False,
            "pcp": False,
            "pmp": False,
            "udp": True,
            "upnp": False,
        },
    },
    "tags": ["tag:golink"],
    "tailnetLockError": "",
    "tailnetLockKey": "",
}
test_device_2 = {
    "addresses": ["100.71.70.69", "fd7a:115c:a1e0:ac82:4843:ca90:697d:c36e"],
    "id": "testing",
    "user": "pangolin@example.com",
    "name": "bat.tailfe8c.ts.net",
    "hostname": "bat",
    "clientVersion": "",
    "updateAvailable": False,
    "os": "linux",
    "created": "",
    "lastSeen": "2022-12-01T05:23:30Z",
    "tags": ["tag:golink"],
    "keyExpiryDisabled": True,
    "expires": "2023-07-30T04:44:05Z",
    "authorized": True,
    "isExternal": False,
    "machineKey": "test",
    "nodeKey": "nodekey:01234567890abcdef",
    "blocksIncomingConnections": False,
    "clientConnectivity": {
        "derp": "",
        "clientSupports": {
            "hairPinning": False,
        },
    },
}
example_devices = {
    "devices": [
        test_device_1,
        test_device_2,
    ]
}


@pytest.mark.asyncio
async def test_devices(aresponses: ResponsesMockServer) -> None:
    """Tests getting all devices."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/tailnet/frenck/devices",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=json.dumps(example_devices),
        ),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        devices = await tailscale.devices()
        assert isinstance(devices, Dict)
        assert devices["test"].device_id == "test"
        assert devices["testing"].device_id == "testing"
