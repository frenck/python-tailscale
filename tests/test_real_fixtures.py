"""Tests against anonymized responses of a real tailnet.

The fixtures in `fixtures/real` are dumps of a real tailnet, made with
`tailscale-api dump`, with everything that identifies the tailnet replaced.
They keep the shape of what the API really returns, like the fields it
leaves out, and the empty values it sends instead.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from aioresponses import aioresponses

from tailscale import Tailscale

from .conftest import URL, load_fixture

DEVICE_ID = "nbbabe54da8CNTRL"
START = datetime(2026, 10, 8, tzinfo=UTC)
END = datetime(2026, 10, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("fixture", "path", "call"),
    [
        ("devices.json", "tailnet/frenck/devices?fields=all", lambda ts: ts.devices()),
        (
            "device.json",
            f"device/{DEVICE_ID}?fields=all",
            lambda ts: ts.device(DEVICE_ID),
        ),
        (
            "routes.json",
            f"device/{DEVICE_ID}/routes",
            lambda ts: ts.device_routes(DEVICE_ID),
        ),
        (
            "device-posture-attributes.json",
            f"device/{DEVICE_ID}/attributes",
            lambda ts: ts.device_posture_attributes(DEVICE_ID),
        ),
        ("users.json", "tailnet/frenck/users", lambda ts: ts.users()),
        (
            "user-invites.json",
            "tailnet/frenck/user-invites",
            lambda ts: ts.user_invites(),
        ),
        ("keys.json", "tailnet/frenck/keys?all=true", lambda ts: ts.keys()),
        ("settings.json", "tailnet/frenck/settings", lambda ts: ts.tailnet_settings()),
        (
            "dns-configuration.json",
            "tailnet/frenck/dns/configuration",
            lambda ts: ts.dns_configuration(),
        ),
        ("webhooks.json", "tailnet/frenck/webhooks", lambda ts: ts.webhooks()),
        ("services.json", "tailnet/frenck/services", lambda ts: ts.services()),
        (
            "posture-integrations.json",
            "tailnet/frenck/posture/integrations",
            lambda ts: ts.posture_integrations(),
        ),
        ("oauth-apps.json", "tailnet/frenck/oauth-apps", lambda ts: ts.oauth_apps()),
        ("contacts.json", "tailnet/frenck/contacts", lambda ts: ts.contacts()),
        (
            "organization-tailnets.json",
            "organizations/-/tailnets",
            lambda ts: ts.organization_tailnets(),
        ),
        (
            "audit-logs.json",
            "tailnet/frenck/logging/configuration"
            "?start=2026-10-08T00:00:00%2B00:00&end=2026-10-10T00:00:00%2B00:00",
            lambda ts: ts.configuration_audit_logs(start=START, end=END),
        ),
    ],
)
async def test_real_fixture(
    responses: aioresponses,
    tailscale_client: Tailscale,
    fixture: str,
    path: str,
    call: Callable[[Tailscale], Awaitable[Any]],
) -> None:
    """Test a real, anonymized response of the API parses."""
    responses.get(
        f"{URL}/{path}",
        status=200,
        body=load_fixture(f"real/{fixture}"),
        content_type="application/json",
    )
    assert await call(tailscale_client) is not None


async def test_real_devices(
    responses: aioresponses,
    tailscale_client: Tailscale,
) -> None:
    """Test the empty values of real devices end up as None."""
    responses.get(
        f"{URL}/tailnet/frenck/devices?fields=all",
        status=200,
        body=load_fixture("real/devices.json"),
        content_type="application/json",
    )
    devices = await tailscale_client.devices()

    assert len(devices) == 18
    # The API sends an empty object for an unknown distro, and an empty
    # string for a device not created by an OAuth client.
    assert any(device.distro is None for device in devices.values())
    assert all(device.oauth_client_id is None for device in devices.values())
    assert all(device.posture_status is None for device in devices.values())
    assert all(device.client_connectivity is not None for device in devices.values())
