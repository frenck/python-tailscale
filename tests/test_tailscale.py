"""Tests for `tailscale.tailscale`."""

# pylint: disable=protected-access

import aiohttp
import pytest
from aioresponses import aioresponses
from syrupy.assertion import SnapshotAssertion

from tailscale import Tailscale
from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)

from .conftest import URL, load_fixture


async def test_json_request(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test JSON response is handled correctly."""
    responses.get(
        f"{URL}/test",
        status=200,
        body='{"status": "ok"}',
        content_type="application/json",
    )
    response = await tailscale_client._request("test")
    assert response == '{"status": "ok"}'


async def test_internal_session() -> None:
    """Test internal session is created and closed correctly."""
    with aioresponses() as mocked:
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with Tailscale(tailnet="frenck", api_key="abc") as tailscale:
            response = await tailscale._request("test")
            assert response == '{"status": "ok"}'


async def test_post_request(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test POST requests are handled correctly."""
    responses.post(
        f"{URL}/test",
        status=200,
        body='{"status": "ok"}',
        content_type="application/json",
    )
    response = await tailscale_client._request(
        "test",
        method=aiohttp.hdrs.METH_POST,
        data={},
    )
    assert response == '{"status": "ok"}'


async def test_timeout(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test request timeout from the Tailscale API."""
    responses.get(
        f"{URL}/test",
        exception=TimeoutError(),
    )
    tailscale_client.request_timeout = 1
    with pytest.raises(TailscaleConnectionError):
        await tailscale_client._request("test")


async def test_http_error404(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test HTTP 404 response handling."""
    responses.get(
        f"{URL}/test",
        status=404,
        body="OMG PUPPIES!",
        content_type="text/plain",
    )
    with pytest.raises(TailscaleError):
        await tailscale_client._request("test")


async def test_http_error401(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test HTTP 401 response handling."""
    responses.get(
        f"{URL}/test",
        status=401,
        body="Access denied!",
        content_type="text/plain",
    )
    with pytest.raises(TailscaleAuthenticationError):
        await tailscale_client._request("test")


async def test_connection_error(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test connection error handling."""
    responses.get(
        f"{URL}/test",
        exception=aiohttp.ClientError(),
    )
    with pytest.raises(TailscaleConnectionError):
        await tailscale_client._request("test")


async def test_devices(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test fetching devices from the Tailscale API."""
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=all",
        status=200,
        body=load_fixture("devices.json"),
        content_type="application/json",
    )
    devices = await tailscale_client.devices()

    assert len(devices) == 2
    assert "12345" in devices
    assert "67890" in devices

    device = devices["12345"]
    assert device.hostname == "my-device"
    assert device.os == "linux"
    assert device.authorized is True
    assert device.device_id == "12345"
    assert device.node_id == "n12345"
    assert device.connected_to_control is True
    assert device.ssh_enabled is True
    assert device.tailnet_lock_key == "tlpub:abc123"
    assert device.tailnet_lock_error is None
    assert device.client_connectivity is not None
    assert device.client_connectivity.client_supports.ipv6 is True
    assert "New York" in device.client_connectivity.latency
    assert device.client_connectivity.latency["New York"].latency_ms == 25.5
    assert device.client_connectivity.latency["New York"].preferred is True


async def test_devices_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test device parsing matches snapshot."""
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=all",
        status=200,
        body=load_fixture("devices.json"),
        content_type="application/json",
    )
    assert await tailscale_client.devices() == snapshot


async def test_devices_empty_created(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test device with empty created field is handled."""
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=all",
        status=200,
        body='{"devices": [{"addresses": ["100.100.100.100"],'
        '"authorized": true, "blocksIncomingConnections": false,'
        '"clientConnectivity": null, "clientVersion": "1.30.0",'
        '"connectedToControl": true, "created": "",'
        '"expires": null, "hostname": "my-device",'
        '"id": "12345", "isExternal": false, "keyExpiryDisabled": false,'
        '"lastSeen": null, "machineKey": "mkey:abc123",'
        '"name": "my-device.tailnet.ts.net", "nodeId": "n12345",'
        '"nodeKey": "nodekey:def456",'
        '"os": "linux", "tailnetLockKey": "tlpub:abc",'
        '"updateAvailable": false,'
        '"user": "user@example.com"}]}',
        content_type="application/json",
    )
    devices = await tailscale_client.devices()
    assert devices["12345"].created is None
