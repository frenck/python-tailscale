"""Tests for `tailscale.tailscale`."""

# pylint: disable=protected-access

import asyncio
from datetime import UTC, datetime, timedelta

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
from .storage import InMemoryTokenStorage

OAUTH_URL = f"{URL}/oauth/token"


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


# --- OAuth tests ---


async def test_wrong_arguments_no_auth() -> None:
    """Test that missing authentication raises an error."""
    async with Tailscale() as tailscale:
        with pytest.raises(TailscaleAuthenticationError):
            await tailscale._request("test")


async def test_wrong_arguments_both_auth() -> None:
    """Test that providing both api_key and OAuth credentials raises an error."""
    async with Tailscale(
        api_key="abc",
        oauth_client_id="client",
        oauth_client_secret="notsosecret",  # noqa: S106
    ) as tailscale:
        with pytest.raises(TailscaleAuthenticationError):
            await tailscale._request("test")


async def test_wrong_arguments_partial_oauth() -> None:
    """Test that providing only oauth_client_id raises an error."""
    async with Tailscale(
        oauth_client_id="client",
    ) as tailscale:
        with pytest.raises(TailscaleAuthenticationError):
            await tailscale._request("test")


async def test_key_from_oauth() -> None:
    """Test OAuth token is retrieved and used for authentication."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "short-lived-token", "expires_in": 3600}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            await tailscale._request("test")
            assert tailscale.api_key == "short-lived-token"
            await tailscale.close()


async def test_key_from_oauth_with_race_condition() -> None:
    """Test OAuth token request is sent only once under concurrent access."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "short-lived-token", "expires_in": 3600}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            first_task = asyncio.create_task(tailscale._request("test"))
            second_task = asyncio.create_task(tailscale._request("test"))
            await asyncio.gather(first_task, second_task)
            await tailscale.close()


async def test_new_key_from_oauth_on_manual_invalidation() -> None:
    """Test OAuth token is refreshed after manual invalidation."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "token-1", "expires_in": 3600}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "token-2", "expires_in": 3600}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            await tailscale._request("test")
            assert tailscale.api_key == "token-1"
            tailscale.api_key = None
            await tailscale._request("test")
            assert tailscale.api_key == "token-2"
            await tailscale.close()


async def test_oauth_key_expiration() -> None:
    """Test OAuth token is expired before its TTL."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "short-lived-token", "expires_in": 61}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            await tailscale._request("test")
            assert tailscale.api_key == "short-lived-token"
            assert tailscale._expire_oauth_token_task is not None
            await asyncio.sleep(2)
            assert tailscale.api_key is None
            assert tailscale._get_oauth_token_task is None
            assert tailscale._expire_oauth_token_task is None
            await tailscale.close()


async def test_key_from_storage() -> None:
    """Test OAuth token is loaded from token storage."""
    with aioresponses() as mocked:
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
                token_storage=InMemoryTokenStorage(
                    "stored-token",
                    datetime.now(UTC) + timedelta(hours=1),
                ),
            )
            await tailscale._request("test")
            assert tailscale.api_key == "stored-token"
            await tailscale.close()


async def test_expired_key_from_storage() -> None:
    """Test expired token in storage triggers a fresh OAuth request."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "fresh-token", "expires_in": 3600}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            token_storage = InMemoryTokenStorage(
                "stored-token",
                datetime.now(UTC) + timedelta(seconds=30),
            )
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
                token_storage=token_storage,
            )
            await tailscale._request("test")
            assert tailscale.api_key == "fresh-token"
            assert token_storage._access_token == "fresh-token"  # noqa: S105
            await tailscale.close()


async def test_bad_oauth() -> None:
    """Test bad OAuth response raises an error."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"error": "unauthorized"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            with pytest.raises(TailscaleAuthenticationError):
                await tailscale._request("test")
            await tailscale.close()


async def test_too_short_oauth_expiration() -> None:
    """Test OAuth token with too short expiration raises an error."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "short-lived-token", "expires_in": 60}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            with pytest.raises(TailscaleAuthenticationError):
                await tailscale._request("test")
            await tailscale.close()


@pytest.mark.parametrize("status_code", [401, 403])
async def test_http_auth_error_invalidates_oauth_token(status_code: int) -> None:
    """Test HTTP 401/403 invalidates the OAuth token."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "short-lived-token", "expires_in": 3600}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=status_code,
            body="Access denied!",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            with pytest.raises(TailscaleAuthenticationError):
                await tailscale._request("test")
            assert tailscale.api_key is None
            assert tailscale._get_oauth_token_task is None
            assert tailscale._expire_oauth_token_task is None
            await tailscale.close()
