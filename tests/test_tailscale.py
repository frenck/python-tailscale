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


async def test_delete_request(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test DELETE requests are handled correctly."""
    responses.delete(
        f"{URL}/test",
        status=200,
        body="",
        content_type="application/json",
    )
    response = await tailscale_client._request(
        "test",
        method=aiohttp.hdrs.METH_DELETE,
    )
    assert response == ""


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
    assert device.hostname == "workstation"
    assert device.os == "linux"
    assert device.authorized is True
    assert device.device_id == "12345"
    assert device.node_id == "nSRVBN3CNTRL"
    assert device.connected_to_control is True
    assert device.ssh_enabled is True
    assert device.tailnet_lock_key == (
        "tlpub:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    )
    assert device.tailnet_lock_error is None
    assert device.client_connectivity is not None
    assert device.client_connectivity.client_supports.ipv6 is True
    assert "New York City" in device.client_connectivity.latency
    assert device.client_connectivity.latency["New York City"].latency_ms == 12.548
    assert device.client_connectivity.latency["New York City"].preferred is True


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
        body='{"devices": [{"addresses": ["100.101.102.103"],'
        '"authorized": true, "blocksIncomingConnections": false,'
        '"clientConnectivity": null, "clientVersion": "",'
        '"connectedToControl": false, "created": "",'
        '"expires": null, "hostname": "shared-node",'
        '"id": "12345", "isExternal": true, "keyExpiryDisabled": false,'
        '"lastSeen": null, "machineKey": "",'
        '"name": "shared-node.other-tailnet.ts.net", "nodeId": "nEXTRNL001",'
        '"nodeKey": "nodekey:fedcba0987654321fedcba0987654321",'
        '"os": "windows", "tailnetLockKey": "",'
        '"updateAvailable": false,'
        '"user": "admin@example.com"}]}',
        content_type="application/json",
    )
    devices = await tailscale_client.devices()
    assert devices["12345"].created is None


# --- Single device tests ---


async def test_device(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test fetching a single device from the Tailscale API."""
    responses.get(
        f"{URL}/device/98765?fields=all",
        status=200,
        body=load_fixture("device.json"),
        content_type="application/json",
    )
    device = await tailscale_client.device("98765")
    assert device.hostname == "exit-node-us"
    assert device.os == "linux"
    assert device.device_id == "98765"
    assert device.node_id == "nEXNDUS4321"
    assert device.key_expiry_disabled is True
    assert device.update_available is True
    assert device.multiple_connections is True
    assert device.ssh_enabled is False
    assert device.tags == ["tag:exit-node", "tag:us-east"]
    assert device.advertised_routes == ["10.200.0.0/16", "192.168.50.0/24"]
    assert device.enabled_routes == ["10.200.0.0/16"]
    assert device.client_connectivity is not None
    assert device.client_connectivity.mapping_varies_by_dest_ip is True
    assert "Chicago" in device.client_connectivity.latency
    assert device.client_connectivity.latency["Chicago"].latency_ms == 8.341


async def test_device_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test single device parsing matches snapshot."""
    responses.get(
        f"{URL}/device/98765?fields=all",
        status=200,
        body=load_fixture("device.json"),
        content_type="application/json",
    )
    assert await tailscale_client.device("98765") == snapshot


async def test_delete_device(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deleting a device from the Tailscale API."""
    responses.delete(
        f"{URL}/device/12345",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_device("12345")


async def test_authorize_device(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test authorizing a device."""
    responses.post(
        f"{URL}/device/12345/authorized",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.authorize_device("12345", authorized=True)


async def test_deauthorize_device(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deauthorizing a device."""
    responses.post(
        f"{URL}/device/12345/authorized",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.authorize_device("12345", authorized=False)


async def test_expire_device_key(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test expiring a device key."""
    responses.post(
        f"{URL}/device/12345/expire",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.expire_device_key("12345")


async def test_set_device_key_expiry(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting device key expiry."""
    responses.post(
        f"{URL}/device/12345/key",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.set_device_key_expiry("12345", key_expiry_disabled=True)


async def test_rename_device(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test renaming a device."""
    responses.post(
        f"{URL}/device/12345/name",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.rename_device("12345", name="new-name")


async def test_set_device_tags(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting device tags."""
    responses.post(
        f"{URL}/device/12345/tags",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.set_device_tags("12345", tags=["tag:server", "tag:prod"])


async def test_device_routes(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting device routes."""
    responses.get(
        f"{URL}/device/12345/routes",
        status=200,
        body=load_fixture("device_routes.json"),
        content_type="application/json",
    )
    routes = await tailscale_client.device_routes("12345")
    assert routes.advertised_routes == [
        "10.200.0.0/16",
        "192.168.50.0/24",
        "172.16.0.0/12",
    ]
    assert routes.enabled_routes == ["10.200.0.0/16", "192.168.50.0/24"]


async def test_device_routes_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test device routes parsing matches snapshot."""
    responses.get(
        f"{URL}/device/12345/routes",
        status=200,
        body=load_fixture("device_routes.json"),
        content_type="application/json",
    )
    assert await tailscale_client.device_routes("12345") == snapshot


async def test_set_device_routes(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting device routes."""
    responses.post(
        f"{URL}/device/12345/routes",
        status=200,
        body=load_fixture("device_routes.json"),
        content_type="application/json",
    )
    routes = await tailscale_client.set_device_routes("12345", routes=["10.200.0.0/16"])
    assert routes.advertised_routes == [
        "10.200.0.0/16",
        "192.168.50.0/24",
        "172.16.0.0/12",
    ]
    assert routes.enabled_routes == ["10.200.0.0/16", "192.168.50.0/24"]


async def test_set_device_ipv4_address(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting a device IPv4 address."""
    responses.post(
        f"{URL}/device/12345/ip",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.set_device_ipv4_address("12345", ipv4_address="100.64.0.1")


# --- DNS tests ---


async def test_dns_nameservers(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting DNS nameservers."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/nameservers",
        status=200,
        body=load_fixture("dns_nameservers.json"),
        content_type="application/json",
    )
    result = await tailscale_client.dns_nameservers()
    assert result.dns == ["8.8.8.8", "8.8.4.4", "1.1.1.1"]
    assert result.magic_dns is True


async def test_dns_nameservers_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test DNS nameservers parsing matches snapshot."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/nameservers",
        status=200,
        body=load_fixture("dns_nameservers.json"),
        content_type="application/json",
    )
    assert await tailscale_client.dns_nameservers() == snapshot


async def test_set_dns_nameservers(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting DNS nameservers."""
    responses.post(
        f"{URL}/tailnet/frenck/dns/nameservers",
        status=200,
        body=load_fixture("dns_nameservers.json"),
        content_type="application/json",
    )
    result = await tailscale_client.set_dns_nameservers(
        dns=["8.8.8.8", "8.8.4.4", "1.1.1.1"]
    )
    assert result.dns == ["8.8.8.8", "8.8.4.4", "1.1.1.1"]
    assert result.magic_dns is True


async def test_dns_preferences(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting DNS preferences."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/preferences",
        status=200,
        body=load_fixture("dns_preferences.json"),
        content_type="application/json",
    )
    result = await tailscale_client.dns_preferences()
    assert result.magic_dns is True


async def test_dns_preferences_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test DNS preferences parsing matches snapshot."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/preferences",
        status=200,
        body=load_fixture("dns_preferences.json"),
        content_type="application/json",
    )
    assert await tailscale_client.dns_preferences() == snapshot


async def test_set_dns_preferences(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting DNS preferences."""
    responses.post(
        f"{URL}/tailnet/frenck/dns/preferences",
        status=200,
        body=load_fixture("dns_preferences.json"),
        content_type="application/json",
    )
    result = await tailscale_client.set_dns_preferences(magic_dns=True)
    assert result.magic_dns is True


async def test_dns_search_paths(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting DNS search paths."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/searchpaths",
        status=200,
        body=load_fixture("dns_searchpaths.json"),
        content_type="application/json",
    )
    result = await tailscale_client.dns_search_paths()
    assert result.search_paths == ["corp.example.com", "internal.example.com"]


async def test_dns_search_paths_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test DNS search paths parsing matches snapshot."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/searchpaths",
        status=200,
        body=load_fixture("dns_searchpaths.json"),
        content_type="application/json",
    )
    assert await tailscale_client.dns_search_paths() == snapshot


async def test_set_dns_search_paths(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting DNS search paths."""
    responses.post(
        f"{URL}/tailnet/frenck/dns/searchpaths",
        status=200,
        body=load_fixture("dns_searchpaths.json"),
        content_type="application/json",
    )
    result = await tailscale_client.set_dns_search_paths(
        search_paths=["corp.example.com", "internal.example.com"]
    )
    assert result.search_paths == ["corp.example.com", "internal.example.com"]


async def test_split_dns(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting split DNS configuration."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/split-dns",
        status=200,
        body=load_fixture("split_dns.json"),
        content_type="application/json",
    )
    result = await tailscale_client.split_dns()
    assert result == {
        "corp.example.com": ["10.0.0.53", "10.0.0.54"],
        "internal.example.com": ["10.1.0.53"],
    }


async def test_set_split_dns(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test replacing split DNS configuration."""
    responses.put(
        f"{URL}/tailnet/frenck/dns/split-dns",
        status=200,
        body=load_fixture("split_dns.json"),
        content_type="application/json",
    )
    result = await tailscale_client.set_split_dns(
        split_dns={
            "corp.example.com": ["10.0.0.53", "10.0.0.54"],
            "internal.example.com": ["10.1.0.53"],
        }
    )
    assert result == {
        "corp.example.com": ["10.0.0.53", "10.0.0.54"],
        "internal.example.com": ["10.1.0.53"],
    }


async def test_update_split_dns(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test partially updating split DNS configuration."""
    responses.patch(
        f"{URL}/tailnet/frenck/dns/split-dns",
        status=200,
        body=load_fixture("split_dns.json"),
        content_type="application/json",
    )
    result = await tailscale_client.update_split_dns(
        split_dns={"corp.example.com": ["10.0.0.53", "10.0.0.54"]}
    )
    assert result == {
        "corp.example.com": ["10.0.0.53", "10.0.0.54"],
        "internal.example.com": ["10.1.0.53"],
    }


# --- User tests ---


async def test_users(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test fetching users from the Tailscale API."""
    responses.get(
        f"{URL}/tailnet/frenck/users",
        status=200,
        body=load_fixture("users.json"),
        content_type="application/json",
    )
    users = await tailscale_client.users()
    assert len(users) == 2
    assert users[0].user_id == "u12345"
    assert users[0].display_name == "Alice Engineer"
    assert users[0].login_name == "alice@example.com"
    assert users[0].role == "admin"
    assert users[0].status == "active"
    assert users[0].device_count == 3
    assert users[0].currently_connected is True
    assert users[1].user_id == "u67890"
    assert users[1].display_name == "Bob Ops"
    assert users[1].currently_connected is False


async def test_users_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test users parsing matches snapshot."""
    responses.get(
        f"{URL}/tailnet/frenck/users",
        status=200,
        body=load_fixture("users.json"),
        content_type="application/json",
    )
    assert await tailscale_client.users() == snapshot


async def test_user(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test fetching a single user from the Tailscale API."""
    responses.get(
        f"{URL}/users/u12345",
        status=200,
        body=load_fixture("user.json"),
        content_type="application/json",
    )
    user = await tailscale_client.user("u12345")
    assert user.user_id == "u12345"
    assert user.display_name == "Alice Engineer"
    assert user.login_name == "alice@example.com"
    assert user.role == "admin"
    assert user.device_count == 3


async def test_user_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test single user parsing matches snapshot."""
    responses.get(
        f"{URL}/users/u12345",
        status=200,
        body=load_fixture("user.json"),
        content_type="application/json",
    )
    assert await tailscale_client.user("u12345") == snapshot


# --- Tailnet settings tests ---


async def test_tailnet_settings(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting tailnet settings."""
    responses.get(
        f"{URL}/tailnet/frenck/settings",
        status=200,
        body=load_fixture("tailnet_settings.json"),
        content_type="application/json",
    )
    result = await tailscale_client.tailnet_settings()
    assert result.devices_approval_on is True
    assert result.devices_auto_updates_on is True
    assert result.devices_key_duration_days == 90
    assert result.users_approval_on is False
    assert result.users_role_allowed_to_join_external_tailnets == "admin"
    assert result.network_flow_logging_on is True
    assert result.regional_routing_on is False
    assert result.posture_identity_collection_on is True


async def test_tailnet_settings_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test tailnet settings parsing matches snapshot."""
    responses.get(
        f"{URL}/tailnet/frenck/settings",
        status=200,
        body=load_fixture("tailnet_settings.json"),
        content_type="application/json",
    )
    assert await tailscale_client.tailnet_settings() == snapshot


async def test_update_tailnet_settings(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test updating tailnet settings."""
    responses.patch(
        f"{URL}/tailnet/frenck/settings",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.update_tailnet_settings(
        devices_key_duration_days=30,
        network_flow_logging_on=False,
    )


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
