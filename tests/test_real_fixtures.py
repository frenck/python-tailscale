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


def _check_devices(devices: Any) -> None:
    assert len(devices) == 18
    # Devices are keyed by their legacy ID, not their node ID.
    (device,) = (device for device in devices.values() if device.node_id == DEVICE_ID)
    assert devices[device.device_id] is device
    assert device.os == "macOS"
    assert device.last_seen == datetime(2019, 6, 19, 17, 7, 49, tzinfo=UTC)


def _check_device(device: Any) -> None:
    assert device.node_id == DEVICE_ID
    assert device.client_version == "1.20.4-t8c6cb1cea-g2accf24a5"


def _check_routes(routes: Any) -> None:
    assert routes.advertised_routes == []
    assert routes.enabled_routes == []


def _check_posture_attributes(posture: Any) -> None:
    assert posture.attributes["node:osVersion"] == "11.5.2"
    assert posture.attributes["node:tsAutoUpdate"] is False
    assert posture.expiries == {}


def _check_users(users: Any) -> None:
    (user,) = users
    assert (user.role, user.status, user.device_count) == ("owner", "active", 18)


def _check_keys(keys: Any) -> None:
    (key,) = keys
    assert key.key_type == "api"
    assert key.scopes == ["all", "all:read"]
    assert key.expiry_seconds == 7776000


def _check_settings(settings: Any) -> None:
    assert settings.devices_key_duration_days == 180
    assert settings.https_enabled is True
    assert settings.route_selection == "active-passive-failover"


def _check_dns_configuration(configuration: Any) -> None:
    assert [resolver.address for resolver in configuration.nameservers] == [
        "203.0.113.50"
    ]
    assert configuration.preferences.magic_dns is True
    assert configuration.split_dns == {}


def _check_contacts(contacts: Any) -> None:
    # The API sends an empty email for a contact that is not set.
    assert contacts.account is not None
    assert contacts.account.email is None
    assert contacts.account.needs_verification is False


def _check_organization_tailnets(page: Any) -> None:
    assert page.total_count == 1
    assert page.cursor is None
    assert [tailnet.display_name for tailnet in page.tailnets] == ["example1.com"]


def _check_audit_logs(logs: Any) -> None:
    assert len(logs) == 29
    # Nanoseconds from the API end up as the microseconds Python has.
    assert logs[0].event_time == datetime(2024, 1, 13, 18, 39, 35, 416440, tzinfo=UTC)
    assert logs[0].action == "LOGIN"
    assert sum(log.event_group_id is None for log in logs) == 7


def _check_empty(result: Any) -> None:
    assert result == []


@pytest.mark.parametrize(
    ("fixture", "path", "call", "check"),
    [
        (
            "devices.json",
            "tailnet/frenck/devices?fields=all",
            lambda ts: ts.devices(),
            _check_devices,
        ),
        (
            "device.json",
            f"device/{DEVICE_ID}?fields=all",
            lambda ts: ts.device(DEVICE_ID),
            _check_device,
        ),
        (
            "routes.json",
            f"device/{DEVICE_ID}/routes",
            lambda ts: ts.device_routes(DEVICE_ID),
            _check_routes,
        ),
        (
            "device-posture-attributes.json",
            f"device/{DEVICE_ID}/attributes",
            lambda ts: ts.device_posture_attributes(DEVICE_ID),
            _check_posture_attributes,
        ),
        ("users.json", "tailnet/frenck/users", lambda ts: ts.users(), _check_users),
        (
            "user-invites.json",
            "tailnet/frenck/user-invites",
            lambda ts: ts.user_invites(),
            _check_empty,
        ),
        (
            "keys.json",
            "tailnet/frenck/keys?all=true",
            lambda ts: ts.keys(),
            _check_keys,
        ),
        (
            "settings.json",
            "tailnet/frenck/settings",
            lambda ts: ts.tailnet_settings(),
            _check_settings,
        ),
        (
            "dns-configuration.json",
            "tailnet/frenck/dns/configuration",
            lambda ts: ts.dns_configuration(),
            _check_dns_configuration,
        ),
        (
            "webhooks.json",
            "tailnet/frenck/webhooks",
            lambda ts: ts.webhooks(),
            _check_empty,
        ),
        (
            "services.json",
            "tailnet/frenck/services",
            lambda ts: ts.services(),
            _check_empty,
        ),
        (
            "posture-integrations.json",
            "tailnet/frenck/posture/integrations",
            lambda ts: ts.posture_integrations(),
            _check_empty,
        ),
        (
            "oauth-apps.json",
            "tailnet/frenck/oauth-apps",
            lambda ts: ts.oauth_apps(),
            _check_empty,
        ),
        (
            "contacts.json",
            "tailnet/frenck/contacts",
            lambda ts: ts.contacts(),
            _check_contacts,
        ),
        (
            "organization-tailnets.json",
            "organizations/-/tailnets",
            lambda ts: ts.organization_tailnets(),
            _check_organization_tailnets,
        ),
        (
            "audit-logs.json",
            "tailnet/frenck/logging/configuration"
            "?start=2026-10-08T00:00:00%2B00:00&end=2026-10-10T00:00:00%2B00:00",
            lambda ts: ts.configuration_audit_logs(start=START, end=END),
            _check_audit_logs,
        ),
    ],
)
async def test_real_fixture(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    responses: aioresponses,
    tailscale_client: Tailscale,
    fixture: str,
    path: str,
    call: Callable[[Tailscale], Awaitable[Any]],
    check: Callable[[Any], None],
) -> None:
    """Test a real, anonymized response of the API parses into what it holds."""
    responses.get(
        f"{URL}/{path}",
        status=200,
        body=load_fixture(f"real/{fixture}"),
        content_type="application/json",
    )
    check(await call(tailscale_client))


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
