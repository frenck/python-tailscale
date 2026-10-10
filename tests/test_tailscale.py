"""Tests for `tailscale.tailscale`."""

# pylint: disable=protected-access

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses
from syrupy.assertion import SnapshotAssertion
from yarl import URL as URL_TYPE

from tailscale import (
    AuditLogActor,
    AwsExternalId,
    CreatedTailnetOAuthClient,
    DeviceInvite,
    DevicePostureAttributeUpdate,
    DNSConfiguration,
    DNSConfigurationPreferences,
    DNSResolver,
    InviteUser,
    LogStreamConfiguration,
    NetworkTraffic,
    OAuthApp,
    OrganizationTailnet,
    PostureIntegration,
    ServiceApproval,
    ServiceHost,
    SharedDevice,
    TailnetContact,
    Tailscale,
    TailscaleKey,
    TailscaleService,
    TailscaleWebhook,
    UserInvite,
)
from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleNotFoundError,
    TailscalePermissionError,
    TailscaleResponseError,
    TailscaleUnauthorizedError,
)

from .conftest import URL, load_fixture
from .storage import InMemoryTokenStorage

OAUTH_URL = f"{URL}/oauth/token"
WEBHOOK_SECRET = "tskey-webhook-abcdef1234567890"  # noqa: S105


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
    with pytest.raises(TailscaleNotFoundError) as excinfo:
        await tailscale_client._request("test")

    assert excinfo.value.status == 404
    assert excinfo.value.reason == "Not Found"


async def test_http_error500(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test HTTP 500 response handling."""
    responses.get(
        f"{URL}/test",
        status=500,
        body='{"message": "something broke"}',
        content_type="application/json",
    )
    with pytest.raises(TailscaleResponseError) as excinfo:
        await tailscale_client._request("test")

    assert not isinstance(
        excinfo.value, (TailscaleAuthenticationError, TailscaleNotFoundError)
    )
    assert excinfo.value.status == 500
    assert str(excinfo.value) == "something broke"


async def test_http_error401(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test HTTP 401 response handling."""
    responses.get(
        f"{URL}/test",
        status=401,
        body='{"message": "API token invalid"}',
        content_type="application/json",
    )
    with pytest.raises(TailscaleUnauthorizedError) as excinfo:
        await tailscale_client._request("test")

    assert isinstance(excinfo.value, TailscaleAuthenticationError)
    assert excinfo.value.status == 401
    assert excinfo.value.reason == "API token invalid"


async def test_http_error403(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test HTTP 403 response handling."""
    responses.get(
        f"{URL}/test",
        status=403,
        body='{"message": "feature not available on current billing plan"}',
        content_type="application/json",
    )
    with pytest.raises(TailscalePermissionError) as excinfo:
        await tailscale_client._request("test")

    assert isinstance(excinfo.value, TailscaleAuthenticationError)
    assert excinfo.value.status == 403
    assert excinfo.value.reason == "feature not available on current billing plan"


@pytest.mark.parametrize(
    "body",
    ["", "[]", '{"message": ""}', '{"message": 42}', "not json"],
)
async def test_http_error_without_message(
    responses: aioresponses,
    tailscale_client: Tailscale,
    body: str,
) -> None:
    """Test the HTTP reason is used when the API gives no message."""
    responses.get(
        f"{URL}/test",
        status=502,
        body=body,
        content_type="application/json",
    )
    with pytest.raises(TailscaleResponseError) as excinfo:
        await tailscale_client._request("test")

    assert excinfo.value.reason == "Bad Gateway"


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
    assert device.distro is not None
    assert device.distro.name == "ubuntu"
    assert device.distro.code_name == "plucky"
    assert device.posture_identity is not None
    assert device.posture_identity.serial_numbers == ["ABC123XYZ"]
    assert device.posture_identity.hardware_addresses == ["00:11:22:33:44:55"]
    assert device.posture_status is not None
    assert device.posture_status.passing is False
    assert device.posture_status.impacting is True
    assert device.posture_status.failing_assertions == ["node:os == 'macos'"]
    assert device.oauth_client_id == "kclient1234567890"

    shared = devices["67890"]
    assert shared.distro is None
    assert shared.oauth_client_id is None
    assert shared.posture_status is None


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


async def test_devices_minimal(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test a device with only its identifiers is handled."""
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=all",
        status=200,
        body='{"devices": [{"id": "12345", "nodeId": "nMINIMAL001",'
        '"hostname": "minimal", "name": "minimal.example.ts.net"}]}',
        content_type="application/json",
    )
    devices = await tailscale_client.devices()

    device = devices["12345"]
    assert device.node_id == "nMINIMAL001"
    assert device.addresses == []
    assert device.connected_to_control is None
    assert device.client_version is None
    assert device.distro is None
    assert device.is_external is False
    assert device.posture_identity is None


async def test_devices_fallback_to_default_fields(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test the default fields are used when all fields fail with a 404.

    The Tailscale API answers a 404 for all fields when the tailnet has
    devices shared in from another tailnet.
    """
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=all",
        status=404,
        body='{"message":"unable to load devices"}',
        content_type="application/json",
    )
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=default",
        status=200,
        body='{"devices": [{"addresses": ["100.101.102.103"],'
        '"authorized": true, "blocksIncomingConnections": false,'
        '"clientVersion": "1.90.0", "connectedToControl": true,'
        '"created": "2026-01-01T00:00:00Z", "expires": null,'
        '"hostname": "shared-node", "id": "12345", "isExternal": true,'
        '"keyExpiryDisabled": false, "lastSeen": null, "machineKey": "",'
        '"name": "shared-node.other-tailnet.ts.net", "nodeId": "nEXTRNL001",'
        '"nodeKey": "nodekey:fedcba0987654321fedcba0987654321",'
        '"os": "windows", "tailnetLockKey": "", "updateAvailable": false,'
        '"user": "admin@example.com"}]}',
        content_type="application/json",
    )
    devices = await tailscale_client.devices()

    device = devices["12345"]
    assert device.is_external is True
    assert device.connected_to_control is True
    assert device.client_connectivity is None


async def test_devices_not_found(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test a 404 for the default fields as well is raised."""
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=all",
        status=404,
        body='{"message":"unable to load devices"}',
        content_type="application/json",
    )
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=default",
        status=404,
        body='{"message":"tailnet not found"}',
        content_type="application/json",
    )
    with pytest.raises(TailscaleNotFoundError):
        await tailscale_client.devices()


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


async def test_device_posture_attributes(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the posture attributes of a device."""
    responses.get(
        f"{URL}/device/nDEVICE123/attributes",
        status=200,
        body='{"attributes": {"node:os": "linux", "custom:myScore": 80,'
        '"custom:diskEncryption": true}, "expiries":'
        '{"custom:myScore": "2026-12-01T05:23:30Z"}}',
        content_type="application/json",
    )
    posture = await tailscale_client.device_posture_attributes("nDEVICE123")

    assert posture.attributes == {
        "node:os": "linux",
        "custom:myScore": 80,
        "custom:diskEncryption": True,
    }
    assert posture.expiries == {
        "custom:myScore": datetime(2026, 12, 1, 5, 23, 30, tzinfo=UTC)
    }


async def test_set_device_posture_attribute(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting a custom posture attribute of a device."""
    responses.post(
        f"{URL}/device/nDEVICE123/attributes/custom:myScore",
        status=200,
        body='{"attributes": {"custom:myScore": 80}}',
        content_type="application/json",
    )
    posture = await tailscale_client.set_device_posture_attribute(
        "nDEVICE123",
        "custom:myScore",
        value=80,
        expiry=datetime(2026, 12, 1, 5, 23, 30, tzinfo=UTC),
        comment="Scored by the scanner",
    )
    assert posture.attributes == {"custom:myScore": 80}

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "value": 80,
        "expiry": "2026-12-01T05:23:30+00:00",
        "comment": "Scored by the scanner",
    }


async def test_delete_device_posture_attribute(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deleting a custom posture attribute of a device."""
    responses.delete(
        f"{URL}/device/nDEVICE123/attributes/custom:myScore",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_device_posture_attribute(
        "nDEVICE123", "custom:myScore"
    )


async def test_update_device_posture_attributes(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting and deleting posture attributes of several devices."""
    responses.patch(
        f"{URL}/tailnet/frenck/device-attributes",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.update_device_posture_attributes(
        {
            "nDEVICE123": {
                "custom:myScore": DevicePostureAttributeUpdate(value=80),
                "custom:old": None,
            },
            "nDEVICE456": {
                "custom:flag": DevicePostureAttributeUpdate(
                    value=True,
                    expiry=datetime(2026, 12, 1, 5, 23, 30, tzinfo=UTC),
                ),
            },
        },
        comment="Bulk update",
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "nodes": {
            "nDEVICE123": {"custom:myScore": {"value": 80}, "custom:old": None},
            "nDEVICE456": {
                "custom:flag": {
                    "value": True,
                    "expiry": "2026-12-01T05:23:30+00:00",
                },
            },
        },
        "comment": "Bulk update",
    }


async def test_dns_configuration(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the full DNS configuration."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/configuration",
        status=200,
        body=load_fixture("dns_configuration.json"),
        content_type="application/json",
    )
    configuration = await tailscale_client.dns_configuration()

    assert configuration.nameservers == [
        DNSResolver(address="8.8.8.8", use_with_exit_node=True),
        DNSResolver(address="1.1.1.1"),
    ]
    assert configuration.split_dns == {
        "corp.example.com": [DNSResolver(address="10.0.0.53", use_with_exit_node=True)],
        "other.internal": [],
    }
    assert configuration.search_paths == ["user1.example.com"]
    assert configuration.preferences.magic_dns is True
    assert configuration.preferences.override_local_dns is True


async def test_dns_configuration_empty(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test a DNS configuration the API leaves mostly out."""
    responses.get(
        f"{URL}/tailnet/frenck/dns/configuration",
        status=200,
        body='{"splitDNS": null, "preferences": {"magicDNS": false}}',
        content_type="application/json",
    )
    configuration = await tailscale_client.dns_configuration()

    assert configuration.nameservers == []
    assert configuration.split_dns == {}
    assert configuration.preferences.magic_dns is False
    assert configuration.preferences.override_local_dns is None


async def test_set_dns_configuration(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test replacing the full DNS configuration."""
    responses.post(
        f"{URL}/tailnet/frenck/dns/configuration",
        status=200,
        body=load_fixture("dns_configuration.json"),
        content_type="application/json",
    )
    configuration = DNSConfiguration(
        nameservers=[DNSResolver(address="1.1.1.1", use_with_exit_node=False)],
        preferences=DNSConfigurationPreferences(magic_dns=True),
        split_dns={"corp.example.com": [DNSResolver(address="10.0.0.53")]},
    )
    await tailscale_client.set_dns_configuration(configuration)

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "nameservers": [{"address": "1.1.1.1", "useWithExitNode": False}],
        "preferences": {"magicDNS": True},
        "searchPaths": [],
        "splitDNS": {"corp.example.com": [{"address": "10.0.0.53"}]},
    }


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
    assert users[0].profile_pic_url == "https://profiles.example.com/alice.jpg"
    assert users[0].tailnet_id == "T1234CNTRL"
    assert users[1].user_id == "u67890"
    assert users[1].display_name == "Bob Ops"
    assert users[1].currently_connected is False


async def test_users_filtered(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test filtering users by type and role."""
    responses.get(
        f"{URL}/tailnet/frenck/users?type=all&role=admin",
        status=200,
        body=load_fixture("users.json"),
        content_type="application/json",
    )
    users = await tailscale_client.users(user_type="all", role="admin")
    assert len(users) == 2


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


# --- Key tests ---


async def test_keys(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test fetching keys from the Tailscale API."""
    responses.get(
        f"{URL}/tailnet/frenck/keys?all=true",
        status=200,
        body=load_fixture("keys.json"),
        content_type="application/json",
    )
    keys = await tailscale_client.keys()
    assert len(keys) == 5
    assert keys[0].key_id == "k1234567890abcdef"
    assert keys[0].description == "CI deploy key"
    assert keys[0].key_type == "auth"
    assert keys[0].capabilities.devices.create.reusable is True
    assert keys[0].capabilities.devices.create.preauthorized is True
    assert keys[0].capabilities.devices.create.tags == ["tag:ci", "tag:deploy"]
    assert keys[1].key_id == "kfedcba0987654321"
    assert keys[1].capabilities.devices.create.ephemeral is True

    client = keys[2]
    assert client.key_type == "client"
    assert client.scopes == ["devices:core:read", "users:read"]
    assert client.tags == ["tag:homeassistant"]
    assert client.user_id == "u12345"
    assert client.updated is not None

    federated = keys[3]
    assert federated.key_type == "federated"
    assert federated.issuer == "https://token.actions.githubusercontent.com"
    assert federated.subject == "repo:frenck/python-tailscale:*"
    assert federated.audience == "api.tailscale.com/kfederated123456"
    assert federated.custom_claim_rules == {"repository_owner": "frenck"}

    api = keys[4]
    assert api.key_type == "api"
    assert api.expiry_seconds == 7776000
    assert api.scopes == ["all", "all:read"]


async def test_keys_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test keys parsing matches snapshot."""
    responses.get(
        f"{URL}/tailnet/frenck/keys?all=true",
        status=200,
        body=load_fixture("keys.json"),
        content_type="application/json",
    )
    assert await tailscale_client.keys() == snapshot


async def test_key(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test fetching a single key from the Tailscale API."""
    responses.get(
        f"{URL}/tailnet/frenck/keys/k1234567890abcdef",
        status=200,
        body=load_fixture("key.json"),
        content_type="application/json",
    )
    key = await tailscale_client.key("k1234567890abcdef")
    assert key.key_id == "k1234567890abcdef"
    assert key.description == "CI deploy key"
    assert key.key == ("tskey-auth-k1234567890abcdef-abcdef1234567890abcdef1234567890")


async def test_key_snapshot(
    responses: aioresponses,
    tailscale_client: Tailscale,
    snapshot: SnapshotAssertion,
) -> None:
    """Test single key parsing matches snapshot."""
    responses.get(
        f"{URL}/tailnet/frenck/keys/k1234567890abcdef",
        status=200,
        body=load_fixture("key.json"),
        content_type="application/json",
    )
    assert await tailscale_client.key("k1234567890abcdef") == snapshot


async def test_create_key(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating an auth key."""
    responses.post(
        f"{URL}/tailnet/frenck/keys",
        status=200,
        body=load_fixture("key.json"),
        content_type="application/json",
    )
    key = await tailscale_client.create_key(
        description="CI deploy key",
        reusable=True,
        preauthorized=True,
        tags=["tag:ci", "tag:deploy"],
    )
    assert key.key_id == "k1234567890abcdef"
    assert key.key != ""

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "keyType": "auth",
        "description": "CI deploy key",
        "expirySeconds": 86400,
        "capabilities": {
            "devices": {
                "create": {
                    "reusable": True,
                    "ephemeral": False,
                    "preauthorized": True,
                    "tags": ["tag:ci", "tag:deploy"],
                },
            },
        },
    }


async def test_create_oauth_client(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating an OAuth client."""
    responses.post(
        f"{URL}/tailnet/frenck/keys",
        status=200,
        body=load_fixture("key.json"),
        content_type="application/json",
    )
    await tailscale_client.create_key(
        key_type="client",
        description="Home Assistant",
        scopes=["devices:core:read"],
        tags=["tag:homeassistant"],
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "keyType": "client",
        "description": "Home Assistant",
        "scopes": ["devices:core:read"],
        "tags": ["tag:homeassistant"],
    }


async def test_create_federated_identity(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating a federated identity."""
    responses.post(
        f"{URL}/tailnet/frenck/keys",
        status=200,
        body=load_fixture("key.json"),
        content_type="application/json",
    )
    await tailscale_client.create_key(
        key_type="federated",
        scopes=["auth_keys"],
        tags=["tag:ci"],
        issuer="https://token.actions.githubusercontent.com",
        subject="repo:frenck/python-tailscale:*",
        custom_claim_rules={"repository_owner": "frenck"},
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "keyType": "federated",
        "description": "",
        "scopes": ["auth_keys"],
        "tags": ["tag:ci"],
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:frenck/python-tailscale:*",
        "customClaimRules": {"repository_owner": "frenck"},
    }


async def test_set_key(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting the configuration of an OAuth client."""
    responses.put(
        f"{URL}/tailnet/frenck/keys/kclient1234567890",
        status=200,
        body=load_fixture("key.json"),
        content_type="application/json",
    )
    key = await tailscale_client.set_key(
        "kclient1234567890",
        key_type="client",
        scopes=["devices:core:read", "users:read"],
        description="Home Assistant",
    )
    assert key.key_id == "k1234567890abcdef"

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "keyType": "client",
        "description": "Home Assistant",
        "scopes": ["devices:core:read", "users:read"],
    }


async def test_delete_key(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deleting a key."""
    responses.delete(
        f"{URL}/tailnet/frenck/keys/k1234567890abcdef",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_key("k1234567890abcdef")


# --- Tailnet settings tests ---


async def test_set_user_role(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting the role of a user."""
    responses.post(
        f"{URL}/users/u12345/role",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.set_user_role("u12345", role="admin")

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {"role": "admin"}


@pytest.mark.parametrize(
    ("method", "action"),
    [
        ("approve_user", "approve"),
        ("suspend_user", "suspend"),
        ("restore_user", "restore"),
        ("delete_user", "delete"),
    ],
)
async def test_user_actions(
    responses: aioresponses,
    tailscale_client: Tailscale,
    method: str,
    action: str,
) -> None:
    """Test the actions on a user."""
    responses.post(
        f"{URL}/users/u12345/{action}",
        status=200,
        body="",
        content_type="application/json",
    )
    await getattr(tailscale_client, method)("u12345")

    assert responses.requests
    ((request_method, request_url),) = responses.requests
    assert request_method == "POST"
    assert str(request_url) == f"{URL}/users/u12345/{action}"


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
    assert result.https_enabled is True
    assert result.route_selection == "active-passive-failover"
    assert result.acls_externally_managed_on is False
    assert result.acls_external_link is None


async def test_tailnet_settings_empty(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test settings the API leaves out are None."""
    responses.get(
        f"{URL}/tailnet/frenck/settings",
        status=200,
        body="{}",
        content_type="application/json",
    )
    result = await tailscale_client.tailnet_settings()
    assert result.devices_approval_on is None
    assert result.devices_key_duration_days is None
    assert result.route_selection is None


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
        devices_approval_on=True,
        devices_auto_updates_on=True,
        devices_key_duration_days=30,
        users_approval_on=False,
        users_role_allowed_to_join_external_tailnets="member",
        network_flow_logging_on=False,
        regional_routing_on=True,
        posture_identity_collection_on=False,
        https_enabled=True,
        route_selection="regional-routing",
        acls_externally_managed_on=True,
        acls_external_link="https://github.com/frenck/tailnet-policy",
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "devicesApprovalOn": True,
        "devicesAutoUpdatesOn": True,
        "devicesKeyDurationDays": 30,
        "usersApprovalOn": False,
        "usersRoleAllowedToJoinExternalTailnets": "member",
        "networkFlowLoggingOn": False,
        "regionalRoutingOn": True,
        "postureIdentityCollectionOn": False,
        "httpsEnabled": True,
        "routeSelection": "regional-routing",
        "aclsExternallyManagedOn": True,
        "aclsExternalLink": "https://github.com/frenck/tailnet-policy",
    }


# --- Policy file tests ---


async def test_policy_file(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the policy file as HuJSON, with its ETag."""
    responses.get(
        f"{URL}/tailnet/frenck/acl",
        status=200,
        body=load_fixture("policy.hujson"),
        headers={"ETag": '"e1234"'},
        content_type="application/hujson",
    )
    policy_file = await tailscale_client.policy_file()

    assert policy_file.policy == load_fixture("policy.hujson")
    assert policy_file.etag == '"e1234"'

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["headers"]["Accept"] == "application/hujson"


async def test_set_policy_file(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting the policy file, guarded by the ETag."""
    responses.post(
        f"{URL}/tailnet/frenck/acl",
        status=200,
        body=load_fixture("policy.hujson"),
        headers={"ETag": '"e5678"'},
        content_type="application/hujson",
    )
    policy_file = await tailscale_client.set_policy_file(
        load_fixture("policy.hujson"), etag='"e1234"'
    )

    assert policy_file.etag == '"e5678"'

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["data"] == load_fixture("policy.hujson")
    assert request.kwargs["json"] is None
    assert request.kwargs["headers"]["Content-Type"] == "application/hujson"
    assert request.kwargs["headers"]["If-Match"] == '"e1234"'


async def test_set_policy_file_without_etag(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting the policy file without an ETag."""
    responses.post(
        f"{URL}/tailnet/frenck/acl",
        status=200,
        body=load_fixture("policy.hujson"),
        content_type="application/hujson",
    )
    policy_file = await tailscale_client.set_policy_file(load_fixture("policy.hujson"))

    assert policy_file.etag is None

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert "If-Match" not in request.kwargs["headers"]


async def test_validate_policy_file(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test validating a valid policy file."""
    responses.post(
        f"{URL}/tailnet/frenck/acl/validate",
        status=200,
        body="{}",
        content_type="application/json",
    )
    validation = await tailscale_client.validate_policy_file(
        load_fixture("policy.hujson")
    )

    assert validation.valid is True
    assert validation.message is None
    assert validation.data == []


async def test_validate_policy_file_invalid(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test validating an invalid policy file."""
    responses.post(
        f"{URL}/tailnet/frenck/acl/validate",
        status=200,
        body='{"message":"action=\\"nope\\" is not supported"}',
        content_type="application/json",
    )
    validation = await tailscale_client.validate_policy_file(
        '{"acls": [{"action": "nope"}]}'
    )

    assert validation.valid is False
    assert validation.message == 'action="nope" is not supported'


async def test_test_policy_file(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test running tests against the current policy file."""
    responses.post(
        f"{URL}/tailnet/frenck/acl/validate",
        status=200,
        body='{"message":"test(s) failed","data":[{"user":"alice@example.com",'
        '"errors":["address \\"100.64.0.1:22\\": want: Drop, got: Accept"],'
        '"warnings":null}]}',
        content_type="application/json",
    )
    tests = [{"src": "alice@example.com", "deny": ["100.64.0.1:22"]}]
    validation = await tailscale_client.test_policy_file(tests)

    assert validation.valid is False
    (result,) = validation.data
    assert result.user == "alice@example.com"
    assert result.errors == ['address "100.64.0.1:22": want: Drop, got: Accept']
    assert result.warnings == []

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert json.loads(request.kwargs["data"]) == tests
    assert request.kwargs["headers"]["Content-Type"] == "application/json"


async def test_preview_policy_rules(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test previewing the rules that apply to a resource."""
    responses.post(
        f"{URL}/tailnet/frenck/acl/preview?type=ipport&previewFor=100.64.0.1:22",
        status=200,
        body='{"matches":[{"users":["*"],"ports":["*:*"],"lineNumber":4,'
        '"postures":null}],"type":"ipport","previewFor":"100.64.0.1:22"}',
        content_type="application/json",
    )
    preview = await tailscale_client.preview_policy_rules(
        load_fixture("policy.hujson"),
        preview_type="ipport",
        preview_for="100.64.0.1:22",
    )

    assert preview.preview_type == "ipport"
    assert preview.preview_for == "100.64.0.1:22"
    (match,) = preview.matches
    assert match.users == ["*"]
    assert match.ports == ["*:*"]
    assert match.postures == []
    assert match.line_number == 4


# --- Webhook tests ---


async def test_webhooks(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the webhooks."""
    responses.get(
        f"{URL}/tailnet/frenck/webhooks",
        status=200,
        body=load_fixture("webhooks.json"),
        content_type="application/json",
    )
    webhooks = await tailscale_client.webhooks()

    assert len(webhooks) == 2
    assert webhooks[0].endpoint_id == "e1234CNTRL"
    assert webhooks[0].endpoint_url == "https://example.com/tailscale"
    assert webhooks[0].provider_type is None
    assert webhooks[0].secret is None
    assert webhooks[0].subscriptions == ["nodeCreated", "nodeKeyExpired"]
    assert webhooks[1].provider_type == "slack"


async def test_webhooks_none(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the webhooks when there are none."""
    responses.get(
        f"{URL}/tailnet/frenck/webhooks",
        status=200,
        body='{"webhooks": null}',
        content_type="application/json",
    )
    assert await tailscale_client.webhooks() == []


async def test_webhook(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting a single webhook."""
    responses.get(
        f"{URL}/webhooks/e1234CNTRL",
        status=200,
        body=load_fixture("webhook.json"),
        content_type="application/json",
    )
    webhook = await tailscale_client.webhook("e1234CNTRL")

    assert webhook.creator_login_name == "alice@example.com"
    assert webhook.created is not None
    assert webhook.last_modified is not None
    assert webhook.secret == WEBHOOK_SECRET


async def test_create_webhook(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating a webhook."""
    responses.post(
        f"{URL}/tailnet/frenck/webhooks",
        status=200,
        body=load_fixture("webhook.json"),
        content_type="application/json",
    )
    webhook = await tailscale_client.create_webhook(
        endpoint_url="https://hooks.slack.com/services/T000/B000/XXXX",
        subscriptions=["userNeedsApproval"],
        provider_type="slack",
    )
    assert webhook.secret == WEBHOOK_SECRET

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "endpointUrl": "https://hooks.slack.com/services/T000/B000/XXXX",
        "subscriptions": ["userNeedsApproval"],
        "providerType": "slack",
    }


async def test_create_webhook_without_provider(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating a webhook without a provider type."""
    responses.post(
        f"{URL}/tailnet/frenck/webhooks",
        status=200,
        body=load_fixture("webhook.json"),
        content_type="application/json",
    )
    await tailscale_client.create_webhook(
        endpoint_url="https://example.com/tailscale",
        subscriptions=["nodeCreated"],
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert "providerType" not in request.kwargs["json"]


async def test_update_webhook(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test updating the subscriptions of a webhook."""
    responses.patch(
        f"{URL}/webhooks/e1234CNTRL",
        status=200,
        body=load_fixture("webhook.json"),
        content_type="application/json",
    )
    await tailscale_client.update_webhook("e1234CNTRL", subscriptions=["nodeDeleted"])

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {"subscriptions": ["nodeDeleted"]}


async def test_delete_webhook(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deleting a webhook."""
    responses.delete(
        f"{URL}/webhooks/e1234CNTRL",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_webhook("e1234CNTRL")


async def test_test_webhook(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test sending a test event to a webhook."""
    responses.post(
        f"{URL}/webhooks/e1234CNTRL/test",
        status=202,
        body="",
        content_type="application/json",
    )
    await tailscale_client.test_webhook("e1234CNTRL")


async def test_rotate_webhook_secret(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test rotating the secret of a webhook."""
    responses.post(
        f"{URL}/webhooks/e1234CNTRL/rotate",
        status=200,
        body=load_fixture("webhook.json"),
        content_type="application/json",
    )
    webhook = await tailscale_client.rotate_webhook_secret("e1234CNTRL")
    assert webhook.secret == WEBHOOK_SECRET


# --- Service tests ---


async def test_services(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the Services."""
    responses.get(
        f"{URL}/tailnet/frenck/services",
        status=200,
        body=load_fixture("services.json"),
        content_type="application/json",
    )
    services = await tailscale_client.services()

    assert services == [
        TailscaleService(
            name="svc:example",
            addrs=["100.100.100.100", "fd7a:115c:a1e0::1"],
            comment="An example Service",
            display_name="Example",
            ports=["tcp:80", "tcp:443"],
            tags=["tag:web"],
        ),
        TailscaleService(name="svc:bare", ports=["do-not-validate"]),
    ]


async def test_services_none(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the Services when there are none."""
    responses.get(
        f"{URL}/tailnet/frenck/services",
        status=200,
        body='{"vipServices": null}',
        content_type="application/json",
    )
    assert await tailscale_client.services() == []


async def test_service(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting a single Service."""
    responses.get(
        f"{URL}/tailnet/frenck/services/svc:example",
        status=200,
        body='{"name": "svc:example", "ports": ["tcp:443"]}',
        content_type="application/json",
    )
    service = await tailscale_client.service("svc:example")
    assert service == TailscaleService(name="svc:example", ports=["tcp:443"])


async def test_set_service(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating a Service."""
    responses.put(
        f"{URL}/tailnet/frenck/services/svc:example",
        status=200,
        body='{"name": "svc:example", "addrs": ["100.100.100.100"],'
        '"ports": ["tcp:443"]}',
        content_type="application/json",
    )
    service = await tailscale_client.set_service(
        TailscaleService(name="svc:example", ports=["tcp:443"], comment="Web")
    )
    assert service.addrs == ["100.100.100.100"]

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "name": "svc:example",
        "addrs": [],
        "comment": "Web",
        "ports": ["tcp:443"],
        "tags": [],
    }


async def test_rename_service(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test renaming a Service, by its current name."""
    responses.put(
        f"{URL}/tailnet/frenck/services/svc:old",
        status=200,
        body='{"name": "svc:new"}',
        content_type="application/json",
    )
    service = await tailscale_client.set_service(
        TailscaleService(name="svc:new"), name="svc:old"
    )
    assert service.name == "svc:new"


async def test_delete_service(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deleting a Service."""
    responses.delete(
        f"{URL}/tailnet/frenck/services/svc:example",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_service("svc:example")


async def test_service_hosts(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the devices that host a Service."""
    responses.get(
        f"{URL}/tailnet/frenck/services/svc:example/devices",
        status=200,
        body='{"hosts": [{"stableNodeID": "nDEVICE123",'
        '"approvalLevel": "approved:manual", "configured": "configured"}]}',
        content_type="application/json",
    )
    hosts = await tailscale_client.service_hosts("svc:example")
    assert hosts == [
        ServiceHost(
            stable_node_id="nDEVICE123",
            approval_level="approved:manual",
            configured="configured",
        )
    ]


async def test_service_approval(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the approval of a Service on a device."""
    responses.get(
        f"{URL}/tailnet/frenck/services/svc:example/device/nDEVICE123/approved",
        status=200,
        body='{"approved": true, "autoApproved": true}',
        content_type="application/json",
    )
    approval = await tailscale_client.service_approval("svc:example", "nDEVICE123")
    assert approval == ServiceApproval(approved=True, auto_approved=True)


async def test_set_service_approval(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test revoking the approval of a Service on a device."""
    responses.post(
        f"{URL}/tailnet/frenck/services/svc:example/device/nDEVICE123/approved",
        status=200,
        body='{"approved": false, "autoApproved": false}',
        content_type="application/json",
    )
    approval = await tailscale_client.set_service_approval(
        "svc:example", "nDEVICE123", approved=False
    )
    assert approval.approved is False

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {"approved": False}


# --- Invite tests ---


async def test_device_invites(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the invites to share a device."""
    responses.get(
        f"{URL}/device/nDEVICE123/device-invites",
        status=200,
        body=load_fixture("device_invites.json"),
        content_type="application/json",
    )
    invites = await tailscale_client.device_invites("nDEVICE123")

    accepted, pending = invites
    assert accepted.invite_id == "12346"
    assert accepted.device_id == 11055
    assert accepted.tailnet_id == 59954
    assert accepted.multi_use is True
    assert accepted.allow_exit_node is True
    assert accepted.email is None
    assert accepted.last_email_sent_at is None
    assert accepted.accepted_by == InviteUser(
        user_id=33223, login_name="bob@example.com"
    )
    assert pending.email == "carol@example.com"
    assert pending.last_email_sent_at is not None
    assert pending.accepted is False
    assert pending.accepted_by is None


async def test_device_invites_none(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the invites to share a device when there are none."""
    responses.get(
        f"{URL}/device/nDEVICE123/device-invites",
        status=200,
        body="null",
        content_type="application/json",
    )
    assert await tailscale_client.device_invites("nDEVICE123") == []


async def test_create_device_invite(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating an invite to share a device."""
    responses.post(
        f"{URL}/device/nDEVICE123/device-invites",
        status=200,
        body=load_fixture("device_invites.json"),
        content_type="application/json",
    )
    invite = await tailscale_client.create_device_invite(
        "nDEVICE123", email="carol@example.com", multi_use=True
    )
    assert invite.invite_id == "12346"

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == [
        {"multiUse": True, "allowExitNode": False, "email": "carol@example.com"}
    ]


async def test_device_invite(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting a single invite to share a device."""
    responses.get(
        f"{URL}/device-invites/12347",
        status=200,
        body='{"id": "12347", "accepted": false}',
        content_type="application/json",
    )
    invite = await tailscale_client.device_invite("12347")
    assert invite == DeviceInvite(invite_id="12347")


@pytest.mark.parametrize(
    ("method", "http_method", "path"),
    [
        ("delete_device_invite", "DELETE", "device-invites/12347"),
        ("resend_device_invite", "POST", "device-invites/12347/resend"),
        ("delete_user_invite", "DELETE", "user-invites/12347"),
        ("resend_user_invite", "POST", "user-invites/12347/resend"),
    ],
)
async def test_invite_actions(
    responses: aioresponses,
    tailscale_client: Tailscale,
    method: str,
    http_method: str,
    path: str,
) -> None:
    """Test deleting and resending invites."""
    responses.add(
        f"{URL}/{path}",
        method=http_method,
        status=200,
        body="",
        content_type="application/json",
    )
    await getattr(tailscale_client, method)("12347")

    assert responses.requests
    ((request_method, request_url),) = responses.requests
    assert request_method == http_method
    assert str(request_url) == f"{URL}/{path}"


async def test_accept_device_invite(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test accepting an invite to share a device."""
    responses.post(
        f"{URL}/device-invites/-/accept",
        status=200,
        body='{"device": {"id": "nDEVICE123", "os": "linux", "name": "server",'
        '"fqdn": "server.example.ts.net", "ipv4": "100.64.0.1",'
        '"ipv6": "fd7a:115c:a1e0::1", "includeExitNode": true},'
        '"sharer": {"id": "u1", "displayName": "Alice",'
        '"loginName": "alice@example.com",'
        '"profilePicURL": "https://example.com/alice.png"},'
        '"acceptedBy": {"id": "u2", "displayName": "Bob",'
        '"loginName": "bob@example.com", "profilePicURL": ""}}',
        content_type="application/json",
    )
    accepted = await tailscale_client.accept_device_invite("abcdef")

    assert accepted.device == SharedDevice(
        device_id="nDEVICE123",
        fqdn="server.example.ts.net",
        include_exit_node=True,
        ipv4="100.64.0.1",
        ipv6="fd7a:115c:a1e0::1",
        name="server",
        os="linux",
    )
    assert accepted.sharer == InviteUser(
        user_id="u1",
        display_name="Alice",
        login_name="alice@example.com",
        profile_pic_url="https://example.com/alice.png",
    )
    assert accepted.accepted_by == InviteUser(
        user_id="u2", display_name="Bob", login_name="bob@example.com"
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {"invite": "abcdef"}


async def test_user_invites(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the open invites for users."""
    responses.get(
        f"{URL}/tailnet/frenck/user-invites",
        status=200,
        body=load_fixture("user_invites.json"),
        content_type="application/json",
    )
    (invite,) = await tailscale_client.user_invites()

    assert invite.invite_id == "29214"
    assert invite.role == "admin"
    assert invite.inviter_id == 22012
    assert invite.email == "dave@example.com"
    assert invite.invite_url == "https://login.tailscale.com/uinv/mnopqr"


async def test_user_invites_none(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the invites for users when there are none."""
    responses.get(
        f"{URL}/tailnet/frenck/user-invites",
        status=200,
        body="null",
        content_type="application/json",
    )
    assert await tailscale_client.user_invites() == []


async def test_create_user_invite(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating an invite for a user."""
    responses.post(
        f"{URL}/tailnet/frenck/user-invites",
        status=200,
        body=load_fixture("user_invites.json"),
        content_type="application/json",
    )
    invite = await tailscale_client.create_user_invite(
        role="admin", email="dave@example.com"
    )
    assert invite.invite_id == "29214"

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == [{"role": "admin", "email": "dave@example.com"}]


async def test_user_invite(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting a single invite for a user."""
    responses.get(
        f"{URL}/user-invites/29214",
        status=200,
        body='{"id": "29214", "role": "member", "tailnetId": 59954,"inviterId": 22012}',
        content_type="application/json",
    )
    invite = await tailscale_client.user_invite("29214")
    assert invite == UserInvite(
        invite_id="29214", role="member", inviter_id=22012, tailnet_id=59954
    )


# --- Contact tests ---


async def test_contacts(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the contacts of the tailnet."""
    responses.get(
        f"{URL}/tailnet/frenck/contacts",
        status=200,
        body='{"account": {"email": "alice@example.com",'
        '"needsVerification": false},'
        '"support": {"email": "new@example.com",'
        '"fallbackEmail": "alice@example.com", "needsVerification": true},'
        '"security": {"email": "", "needsVerification": false}}',
        content_type="application/json",
    )
    contacts = await tailscale_client.contacts()

    assert contacts.account == TailnetContact(email="alice@example.com")
    assert contacts.support == TailnetContact(
        email="new@example.com",
        fallback_email="alice@example.com",
        needs_verification=True,
    )
    assert contacts.security == TailnetContact()


async def test_set_contact(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting the email address of a contact."""
    responses.patch(
        f"{URL}/tailnet/frenck/contacts/security",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.set_contact("security", email="security@example.com")

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {"email": "security@example.com"}


async def test_resend_contact_verification(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test resending the verification of a contact."""
    responses.post(
        f"{URL}/tailnet/frenck/contacts/support/resend-verification-email",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.resend_contact_verification("support")


# --- Organization tests ---


async def test_organization_tailnets(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting a page of the tailnets of an organization."""
    responses.get(
        f"{URL}/organizations/-/tailnets",
        status=200,
        body='{"totalCount": 3, "cursor": "next-page", "tailnets": [{'
        '"id": "T1234CNTRL", "displayName": "example.github",'
        '"orgId": "o1234CNTRL", "createdAt": "2021-08-19T08:36:50Z"}]}',
        content_type="application/json",
    )
    page = await tailscale_client.organization_tailnets()

    assert page.total_count == 3
    assert page.cursor == "next-page"
    assert page.tailnets == [
        OrganizationTailnet(
            tailnet_id="T1234CNTRL",
            created_at=datetime(2021, 8, 19, 8, 36, 50, tzinfo=UTC),
            display_name="example.github",
            org_id="o1234CNTRL",
        )
    ]


async def test_organization_tailnets_next_page(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the next page of the tailnets of an organization."""
    responses.get(
        f"{URL}/organizations/o1234CNTRL/tailnets?limit=1&cursor=next-page",
        status=200,
        body='{"totalCount": 3, "tailnets": []}',
        content_type="application/json",
    )
    page = await tailscale_client.organization_tailnets(
        "o1234CNTRL", limit=1, cursor="next-page"
    )
    assert page.cursor is None
    assert page.tailnets == []


async def test_create_organization_tailnet(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating an API-only tailnet."""
    responses.post(
        f"{URL}/organizations/-/tailnets",
        status=200,
        body='{"id": "T5678CNTRL", "displayName": "Robots",'
        '"orgId": "o1234CNTRL", "dnsName": "tail1234.ts.net",'
        '"createdAt": "2026-10-10T09:00:00Z", "alreadyExists": false,'
        '"oauthClient": {"id": "kclient5678", "secret": "tskey-client-secret"}}',
        content_type="application/json",
    )
    tailnet = await tailscale_client.create_organization_tailnet("Robots")

    assert tailnet.tailnet_id == "T5678CNTRL"
    assert tailnet.dns_name == "tail1234.ts.net"
    assert tailnet.already_exists is False
    assert tailnet.oauth_client == CreatedTailnetOAuthClient(
        client_id="kclient5678",
        secret="tskey-client-secret",  # noqa: S106
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {"displayName": "Robots"}


async def test_delete_tailnet(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deleting the tailnet."""
    responses.delete(
        f"{URL}/tailnet/frenck",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_tailnet()


# --- OAuth app tests ---


async def test_oauth_apps(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the OAuth apps."""
    responses.get(
        f"{URL}/tailnet/frenck/oauth-apps",
        status=200,
        body='{"oauthApps": [{"id": "a1234CNTRL", "name": "Home Assistant",'
        '"description": "", "redirectURIs": ["https://example.com/callback"],'
        '"scopes": ["devices:core:read"], "allowedNodeAttributes": null,'
        '"created": "2026-10-01T09:00:00Z", "updated": "2026-10-02T09:00:00Z"}]}',
        content_type="application/json",
    )
    (app,) = await tailscale_client.oauth_apps()

    assert app.app_id == "a1234CNTRL"
    assert app.name == "Home Assistant"
    assert app.description is None
    assert app.redirect_uris == ["https://example.com/callback"]
    assert app.scopes == ["devices:core:read"]
    assert app.allowed_node_attributes == []
    assert app.client_secret is None
    assert app.updated == datetime(2026, 10, 2, 9, tzinfo=UTC)


async def test_oauth_apps_none(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the OAuth apps when there are none."""
    responses.get(
        f"{URL}/tailnet/frenck/oauth-apps",
        status=200,
        body='{"oauthApps": []}',
        content_type="application/json",
    )
    assert await tailscale_client.oauth_apps() == []


async def test_oauth_app(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting a single OAuth app."""
    responses.get(
        f"{URL}/tailnet/frenck/oauth-apps/a1234CNTRL",
        status=200,
        body='{"id": "a1234CNTRL", "name": "Home Assistant"}',
        content_type="application/json",
    )
    app = await tailscale_client.oauth_app("a1234CNTRL")
    assert app == OAuthApp(app_id="a1234CNTRL", name="Home Assistant")


async def test_create_oauth_app(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating an OAuth app."""
    responses.post(
        f"{URL}/tailnet/frenck/oauth-apps",
        status=200,
        body='{"id": "a1234CNTRL", "name": "Home Assistant",'
        '"clientSecret": "tskey-client-secret"}',
        content_type="application/json",
    )
    app = await tailscale_client.create_oauth_app(
        name="Home Assistant",
        redirect_uris=["https://example.com/callback"],
        scopes=["devices:core:read"],
        allowed_node_attributes=["custom:ha"],
    )
    assert app.client_secret == "tskey-client-secret"  # noqa: S105

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "name": "Home Assistant",
        "redirectURIs": ["https://example.com/callback"],
        "scopes": ["devices:core:read"],
        "allowedNodeAttributes": ["custom:ha"],
    }


async def test_set_oauth_app(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting the configuration of an OAuth app."""
    responses.put(
        f"{URL}/tailnet/frenck/oauth-apps/a1234CNTRL",
        status=200,
        body='{"id": "a1234CNTRL", "name": "Home Assistant"}',
        content_type="application/json",
    )
    await tailscale_client.set_oauth_app(
        "a1234CNTRL",
        name="Home Assistant",
        redirect_uris=["https://example.com/callback"],
        scopes=["devices:core:read", "users:read"],
        description="Monitors the tailnet",
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "name": "Home Assistant",
        "redirectURIs": ["https://example.com/callback"],
        "scopes": ["devices:core:read", "users:read"],
        "description": "Monitors the tailnet",
    }


async def test_delete_oauth_app(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deleting an OAuth app."""
    responses.delete(
        f"{URL}/tailnet/frenck/oauth-apps/a1234CNTRL",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_oauth_app("a1234CNTRL")


# --- Log streaming tests ---


async def test_log_stream_configuration(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the log streaming configuration."""
    responses.get(
        f"{URL}/tailnet/frenck/logging/network/stream",
        status=200,
        body='{"logType": "network", "destinationType": "s3", "url": "",'
        '"uploadPeriodMinutes": 5, "compressionFormat": "zstd",'
        '"s3Bucket": "tailnet-logs", "s3Region": "eu-west-1",'
        '"s3AuthenticationType": "rolearn",'
        '"s3RoleArn": "arn:aws:iam::123456789012:role/tailscale",'
        '"s3ExternalId": "ext-1234", "gcsScopes": null}',
        content_type="application/json",
    )
    configuration = await tailscale_client.log_stream_configuration("network")

    assert configuration == LogStreamConfiguration(
        destination_type="s3",
        compression_format="zstd",
        log_type="network",
        s3_authentication_type="rolearn",
        s3_bucket="tailnet-logs",
        s3_external_id="ext-1234",
        s3_region="eu-west-1",
        s3_role_arn="arn:aws:iam::123456789012:role/tailscale",
        upload_period_minutes=5,
    )


async def test_set_log_stream_configuration(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test setting the log streaming configuration."""
    responses.put(
        f"{URL}/tailnet/frenck/logging/configuration/stream",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.set_log_stream_configuration(
        "configuration",
        LogStreamConfiguration(
            destination_type="splunk",
            url="https://splunk.example.com:8088",
            user="tailscale",
            token="s3cr3t",  # noqa: S106
        ),
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "destinationType": "splunk",
        "token": "s3cr3t",
        "url": "https://splunk.example.com:8088",
        "user": "tailscale",
    }


async def test_disable_log_streaming(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test disabling log streaming."""
    responses.delete(
        f"{URL}/tailnet/frenck/logging/network/stream",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.disable_log_streaming("network")


async def test_log_stream_status(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the log streaming status."""
    responses.get(
        f"{URL}/tailnet/frenck/logging/configuration/stream/status",
        status=200,
        body='{"lastActivity": "2026-10-09T20:00:00Z", "lastError": "",'
        '"maxBodySize": 4096, "numBytesSent": 123456, "numEntriesSent": 42,'
        '"numSpoofedEntries": 0, "numTotalRequests": 10,'
        '"numFailedRequests": 1, "rateBytesSent": 12.5,'
        '"rateEntriesSent": 0.25, "rateTotalRequests": 0.1,'
        '"rateFailedRequests": 0}',
        content_type="application/json",
    )
    status = await tailscale_client.log_stream_status("configuration")

    assert status.last_activity == datetime(2026, 10, 9, 20, tzinfo=UTC)
    assert status.last_error is None
    assert status.num_entries_sent == 42
    assert status.num_failed_requests == 1
    assert status.rate_bytes_sent == 12.5
    assert status.rate_failed_requests == 0


async def test_aws_external_id(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting an AWS external ID."""
    responses.post(
        f"{URL}/tailnet/frenck/aws-external-id",
        status=200,
        body='{"externalId": "ext-1234", "tailscaleAwsAccountId": "123456789012"}',
        content_type="application/json",
    )
    external_id = await tailscale_client.aws_external_id(reusable=True)
    assert external_id == AwsExternalId(
        external_id="ext-1234", tailscale_aws_account_id="123456789012"
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {"reusable": True}


async def test_validate_aws_trust_policy(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test validating an AWS trust policy."""
    responses.post(
        f"{URL}/tailnet/frenck/aws-external-id/ext-1234/validate-aws-trust-policy",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.validate_aws_trust_policy(
        "ext-1234", role_arn="arn:aws:iam::123456789012:role/tailscale"
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "roleArn": "arn:aws:iam::123456789012:role/tailscale"
    }


async def test_validate_aws_trust_policy_invalid(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test an AWS trust policy Tailscale cannot assume the role with."""
    responses.post(
        f"{URL}/tailnet/frenck/aws-external-id/ext-1234/validate-aws-trust-policy",
        status=422,
        body='{"message": "unable to assume role"}',
        content_type="application/json",
    )
    with pytest.raises(TailscaleResponseError) as excinfo:
        await tailscale_client.validate_aws_trust_policy(
            "ext-1234", role_arn="arn:aws:iam::123456789012:role/tailscale"
        )

    assert excinfo.value.status == 422
    assert excinfo.value.reason == "unable to assume role"


# --- Logging tests ---


async def test_configuration_audit_logs(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the configuration audit logs."""
    responses.get(
        f"{URL}/tailnet/frenck/logging/configuration"
        "?start=2026-10-09T00:00:00%2B00:00&end=2026-10-10T00:00:00%2B00:00",
        status=200,
        body=load_fixture("configuration_audit_logs.json"),
        content_type="application/json",
    )
    created, renamed = await tailscale_client.configuration_audit_logs(
        start=datetime(2026, 10, 9, tzinfo=UTC),
        end=datetime(2026, 10, 10, tzinfo=UTC),
    )

    assert created.action == "CREATE"
    assert created.origin == "CONFIG_API"
    assert created.event_group_id == "6a3b9c0d1e2f"
    assert created.actor == AuditLogActor(
        actor_id="u12345",
        actor_type="USER",
        display_name="Alice Engineer",
        login_name="alice@example.com",
    )
    assert created.target.target_type == "WEBHOOK_ENDPOINT"
    assert created.new == {"events": ["nodeCreated"]}
    assert created.old is None

    assert renamed.event_group_id is None
    assert renamed.deferred_at is not None
    assert renamed.actor.login_name is None
    assert renamed.actor.tags == ["tag:server"]
    assert renamed.target.property == "MACHINE_NAME"
    assert renamed.target.is_ephemeral is False
    assert (renamed.old, renamed.new) == ("server", "server-new")


async def test_configuration_audit_logs_filtered(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test filtering the configuration audit logs."""
    responses.get(
        f"{URL}/tailnet/frenck/logging/configuration"
        "?start=2026-10-09T00:00:00%2B00:00&end=2026-10-10T00:00:00%2B00:00"
        "&actor=u12345&actor=~bob&target=server&event=NODE.CREATE",
        status=200,
        body='{"logs": null}',
        content_type="application/json",
    )
    logs = await tailscale_client.configuration_audit_logs(
        start=datetime(2026, 10, 9, tzinfo=UTC),
        end=datetime(2026, 10, 10, tzinfo=UTC),
        actors=["u12345", "~bob"],
        targets=["server"],
        events=["NODE.CREATE"],
    )
    assert logs == []


async def test_network_flow_logs(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting the network flow logs."""
    responses.get(
        f"{URL}/tailnet/frenck/logging/network"
        "?start=2026-10-09T00:00:00%2B00:00&end=2026-10-10T00:00:00%2B00:00",
        status=200,
        body=load_fixture("network_flow_logs.json"),
        content_type="application/json",
    )
    (flow,) = await tailscale_client.network_flow_logs(
        start=datetime(2026, 10, 9, tzinfo=UTC),
        end=datetime(2026, 10, 10, tzinfo=UTC),
    )

    assert flow.node_id == "nDEVICE123"
    assert flow.virtual_traffic == [
        NetworkTraffic(
            dst="100.64.0.2:443",
            proto="tcp",
            src="100.64.0.1:51234",
            rx_bytes=6400,
            rx_pkts=8,
            tx_bytes=1200,
            tx_pkts=10,
        )
    ]
    assert flow.physical_traffic[0].tx_pkts == 10
    assert flow.physical_traffic[0].rx_bytes == 0
    assert flow.subnet_traffic == []
    assert flow.exit_traffic == []


# --- Posture integration tests ---


async def test_posture_integrations(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the posture integrations."""
    responses.get(
        f"{URL}/tailnet/frenck/posture/integrations",
        status=200,
        body=load_fixture("posture_integrations.json"),
        content_type="application/json",
    )
    intune, kandji = await tailscale_client.posture_integrations()

    assert intune.integration_id == "p56wQiqrn7mfDEVEL"
    assert intune.provider == "intune"
    assert intune.tenant_id == "d1ae389b-5207-43a2-afca-2de6b03ac7e3"
    assert intune.config_updated is not None
    assert intune.status is not None
    assert intune.status.error == "Invalid Tenant ID."
    assert intune.status.matched_count == 0

    assert kandji.cloud_id is None
    assert kandji.client_id is None
    assert kandji.tenant_id is None
    assert kandji.status is not None
    assert kandji.status.error is None
    assert kandji.status.matched_count == 12
    assert kandji.status.possible_matched_count == 14
    assert kandji.status.provider_host_count == 15


async def test_posture_integrations_none(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test listing the posture integrations when there are none."""
    responses.get(
        f"{URL}/tailnet/frenck/posture/integrations",
        status=200,
        body='{"integrations": []}',
        content_type="application/json",
    )
    assert await tailscale_client.posture_integrations() == []


async def test_posture_integration(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test getting a single posture integration."""
    responses.get(
        f"{URL}/posture/integrations/pKANDJI1234DEVEL",
        status=200,
        body='{"id": "pKANDJI1234DEVEL", "provider": "kandji"}',
        content_type="application/json",
    )
    integration = await tailscale_client.posture_integration("pKANDJI1234DEVEL")
    assert integration == PostureIntegration(
        integration_id="pKANDJI1234DEVEL", provider="kandji"
    )


async def test_create_posture_integration(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test creating a posture integration."""
    responses.post(
        f"{URL}/tailnet/frenck/posture/integrations",
        status=200,
        body='{"id": "p56wQiqrn7mfDEVEL", "provider": "intune"}',
        content_type="application/json",
    )
    integration = await tailscale_client.create_posture_integration(
        provider="intune",
        client_secret="s3cr3t",  # noqa: S106
        client_id="93013672-b00c-4344-80ca-7ecf74f9dce1",
        cloud_id="global",
        tenant_id="d1ae389b-5207-43a2-afca-2de6b03ac7e3",
    )
    assert integration.integration_id == "p56wQiqrn7mfDEVEL"

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "provider": "intune",
        "clientSecret": "s3cr3t",
        "clientId": "93013672-b00c-4344-80ca-7ecf74f9dce1",
        "cloudId": "global",
        "tenantId": "d1ae389b-5207-43a2-afca-2de6b03ac7e3",
    }


async def test_update_posture_integration(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test updating a posture integration, keeping its client secret."""
    responses.patch(
        f"{URL}/posture/integrations/p56wQiqrn7mfDEVEL",
        status=200,
        body='{"id": "p56wQiqrn7mfDEVEL", "provider": "intune"}',
        content_type="application/json",
    )
    await tailscale_client.update_posture_integration(
        "p56wQiqrn7mfDEVEL", tenant_id="0f2a7c51-3c6d-4a8b-9e1f-5b7d2c4e6a80"
    )

    assert responses.requests
    (request,) = next(iter(responses.requests.values()))
    assert request.kwargs["json"] == {
        "tenantId": "0f2a7c51-3c6d-4a8b-9e1f-5b7d2c4e6a80"
    }


async def test_delete_posture_integration(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test deleting a posture integration."""
    responses.delete(
        f"{URL}/posture/integrations/p56wQiqrn7mfDEVEL",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_posture_integration("p56wQiqrn7mfDEVEL")


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


async def test_http_401_invalidates_oauth_token() -> None:
    """Test a 401 invalidates the OAuth token."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "short-lived-token", "expires_in": 3600}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=401,
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
            with pytest.raises(TailscaleUnauthorizedError):
                await tailscale._request("test")
            assert tailscale.api_key is None
            assert tailscale._get_oauth_token_task is None
            assert tailscale._expire_oauth_token_task is None
            await tailscale.close()


async def test_http_403_keeps_oauth_token() -> None:
    """Test a 403 keeps the OAuth token, as a new one would not help."""
    with aioresponses() as mocked:
        mocked.post(
            OAUTH_URL,
            status=200,
            body='{"access_token": "short-lived-token", "expires_in": 3600}',
            content_type="application/json",
        )
        mocked.get(
            f"{URL}/test",
            status=403,
            body='{"message": "feature not available on current billing plan"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            with pytest.raises(TailscalePermissionError):
                await tailscale._request("test")
            assert tailscale.api_key == "short-lived-token"
            assert tailscale._expire_oauth_token_task is not None
            await tailscale.close()


def _oauth_requests(mocked: aioresponses) -> list[Any]:
    """Return the requests made for an OAuth token."""
    assert mocked.requests is not None
    return [
        request
        for (method, url), requests in mocked.requests.items()
        if method == "POST" and str(url) == OAUTH_URL
        for request in requests
    ]


async def test_oauth_recovers_after_failed_token_request() -> None:
    """Test a failed token request does not keep the client from recovering."""
    with aioresponses() as mocked:
        mocked.post(OAUTH_URL, status=500, body="{}", content_type="application/json")
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
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            with pytest.raises(TailscaleResponseError):
                await tailscale._request("test")
            assert tailscale._get_oauth_token_task is None

            await tailscale._request("test")
            assert tailscale.api_key == "fresh-token"
            assert len(_oauth_requests(mocked)) == 2
            await tailscale.close()


async def test_oauth_token_request_survives_cancelled_caller() -> None:
    """Test cancelling one request does not cancel the token for the others."""
    token_requested = asyncio.Event()
    release_token = asyncio.Event()

    async def slow_token(*_args: Any, **_kwargs: Any) -> CallbackResult:
        token_requested.set()
        await release_token.wait()
        return CallbackResult(
            status=200,
            body='{"access_token": "fresh-token", "expires_in": 3600}',
            content_type="application/json",
        )

    with aioresponses() as mocked:
        mocked.post(OAUTH_URL, callback=slow_token)
        mocked.get(
            f"{URL}/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            cancelled = asyncio.create_task(tailscale._request("test"))
            waiting = asyncio.create_task(tailscale._request("test"))
            await token_requested.wait()

            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            release_token.set()

            assert await waiting == '{"status": "ok"}'
            assert tailscale.api_key == "fresh-token"
            assert len(_oauth_requests(mocked)) == 1
            await tailscale.close()


async def test_rejected_stored_oauth_token_is_replaced() -> None:
    """Test a stored token the API refuses is not loaded from storage again."""
    with aioresponses() as mocked:
        mocked.get(
            f"{URL}/test",
            status=401,
            body='{"message": "API token invalid"}',
            content_type="application/json",
        )
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
                "revoked-token",
                datetime.now(UTC) + timedelta(hours=1),
            )
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
                token_storage=token_storage,
            )
            with pytest.raises(TailscaleUnauthorizedError):
                await tailscale._request("test")

            await tailscale._request("test")
            assert tailscale.api_key == "fresh-token"
            assert token_storage._access_token == "fresh-token"  # noqa: S105
            assert len(_oauth_requests(mocked)) == 1
            await tailscale.close()


async def test_oauth_token_is_stored_before_it_is_used() -> None:
    """Test concurrent requests share one token while slow storage saves it."""

    class SlowTokenStorage(InMemoryTokenStorage):
        """Token storage that takes a while to save a token."""

        async def set_token(self, access_token: str, expires_at: datetime) -> None:
            await asyncio.sleep(0.01)
            await super().set_token(access_token, expires_at)

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
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
                token_storage=SlowTokenStorage(),
            )
            first = asyncio.create_task(tailscale._request("test"))
            await asyncio.sleep(0)
            second = asyncio.create_task(tailscale._request("test"))
            assert await asyncio.gather(first, second) == ['{"status": "ok"}'] * 2
            assert len(_oauth_requests(mocked)) == 1
            await tailscale.close()


async def test_oauth_token_on_the_wire() -> None:
    """Test the OAuth client credentials and the token are sent as they should."""
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
            await tailscale.close()

        (token_request,) = _oauth_requests(mocked)
        assert token_request.kwargs["data"] == {
            "client_id": "client",
            "client_secret": "notsosecret",
        }
        assert "Authorization" not in token_request.kwargs["headers"]

        assert mocked.requests is not None
        (api_request,) = mocked.requests[("GET", URL_TYPE(f"{URL}/test"))]
        assert api_request.kwargs["headers"]["Authorization"] == (
            "Bearer short-lived-token"
        )


# --- Hardening tests ---


async def test_ids_cannot_change_the_request_path(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test an ID is escaped, so it cannot send a request to another endpoint."""
    responses.delete(
        f"{URL}/device/..%2Ftailnet%2F-%2Fkeys%2Fk1234",
        status=200,
        body="",
        content_type="application/json",
    )
    await tailscale_client.delete_device("../tailnet/-/keys/k1234")

    assert responses.requests
    ((method, url),) = responses.requests
    assert method == "DELETE"
    assert url.raw_path == "/api/v2/device/..%2Ftailnet%2F-%2Fkeys%2Fk1234"


async def test_ids_keep_their_colons(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test the colon in names like "svc:web" is kept as is."""
    responses.get(
        f"{URL}/tailnet/frenck/services/svc:web",
        status=200,
        body='{"name": "svc:web"}',
        content_type="application/json",
    )
    service = await tailscale_client.service("svc:web")
    assert service.name == "svc:web"


@pytest.mark.parametrize("device_id", ["", ".", ".."])
async def test_ids_that_cannot_be_escaped(
    tailscale_client: Tailscale,
    device_id: str,
) -> None:
    """Test IDs that change the path whatever the escaping are refused."""
    with pytest.raises(ValueError, match="Invalid value for a path segment"):
        await tailscale_client.delete_device(device_id)


def test_repr_leaves_out_secrets() -> None:
    """Test the repr of the client and of models does not hold their secrets."""
    key = TailscaleKey(key_id="k1234", key="key-value")
    values = [
        Tailscale(
            api_key="api-key-value",
            oauth_client_secret="client-secret-value",  # noqa: S106
        ),
        key,
        TailscaleWebhook(
            endpoint_id="e1234",
            endpoint_url="https://example.com",
            secret="webhook-secret-value",  # noqa: S106
        ),
    ]
    secrets = ("api-key-value", "client-secret-value", "key-value", "webhook-secret")

    for value in values:
        assert not any(secret in repr(value) for secret in secrets)
    assert key.to_dict()["key"] == "key-value"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("not json", "not a JSON object"),
        ('["token"]', "not a JSON object"),
        ('{"expires_in": 3600}', "no access token"),
        ('{"access_token": null, "expires_in": 3600}', "no access token"),
        ('{"access_token": "", "expires_in": 3600}', "no access token"),
        ('{"access_token": 42, "expires_in": 3600}', "no access token"),
        ('{"access_token": "tskey-secret"}', "no valid expiry"),
        ('{"access_token": "tskey-secret", "expires_in": "3600"}', "no valid expiry"),
        ('{"access_token": "tskey-secret", "expires_in": true}', "no valid expiry"),
        ('{"access_token": "tskey-secret", "expires_in": -1}', "no valid expiry"),
        ('{"access_token": "tskey-secret", "expires_in": NaN}', "no valid expiry"),
    ],
)
async def test_malformed_oauth_token_response(body: str, reason: str) -> None:
    """Test a malformed token response raises an error without the token."""
    with aioresponses() as mocked:
        mocked.post(OAUTH_URL, status=200, body=body, content_type="application/json")
        async with aiohttp.ClientSession() as session:
            tailscale = Tailscale(
                tailnet="frenck",
                oauth_client_id="client",
                oauth_client_secret="notsosecret",  # noqa: S106
                session=session,
            )
            with pytest.raises(TailscaleAuthenticationError, match=reason) as excinfo:
                await tailscale._request("test")
            assert "tskey-secret" not in str(excinfo.value)
            assert tailscale.api_key is None
            await tailscale.close()
