"""Tests for the Tailscale CLI."""

# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib.metadata import entry_points
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from tailscale.cli import cli
from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
    TailscalePermissionError,
)
from tailscale.models import (
    AuditLog,
    AuditLogActor,
    AuditLogTarget,
    Device,
    DeviceRoutes,
    Devices,
    DNSNameservers,
    DNSPreferences,
    DNSSearchPaths,
    PolicyFile,
    PolicyFileValidation,
    PolicyTestResult,
    TailnetSettings,
    TailscaleKey,
    TailscaleService,
    TailscaleUser,
    TailscaleWebhook,
)
from tests.conftest import FIXTURES_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from syrupy.assertion import SnapshotAssertion


def _load_fixture(name: str) -> str:
    """Load a fixture file and return its text content."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _mock_tailscale(
    *,
    devices: dict[str, Device] | None = None,
    device: Device | None = None,
    device_routes: DeviceRoutes | None = None,
    raw_response: str | None = None,
) -> MagicMock:
    """Return a MagicMock that stands in for a Tailscale instance.

    The mock is wired as an async context manager so that
    ``async with _build_client(...) as client:`` returns an object
    whose async methods resolve to the supplied fixture data.
    """
    client = AsyncMock()

    if devices is not None:
        client.devices.return_value = devices
    if device is not None:
        client.device.return_value = device
    if device_routes is not None:
        client.device_routes.return_value = device_routes
    if raw_response is not None:
        client._request.return_value = raw_response  # pylint: disable=protected-access
    client.tailnet = "-"

    # The CLI does ``async with client:`` on the return of _build_client.
    # Make client itself act as an async context manager that yields itself.
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    return client


def _invoke(
    runner: CliRunner,
    args: list[str],
    mock_client: MagicMock,
) -> tuple[int, str]:
    """Invoke the CLI with a mocked Tailscale client and return the result."""
    with patch("tailscale.cli._build_client", return_value=mock_client):
        result = runner.invoke(cli, args)
    return result.exit_code, result.stdout


@pytest.fixture(autouse=True)
def stable_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force deterministic Rich rendering for stable snapshots."""
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner for invoking the Typer app."""
    return CliRunner()


@pytest.fixture
def devices_data() -> dict[str, Device]:
    """Return parsed devices from the fixture."""
    return Devices.from_json(_load_fixture("devices.json")).devices


@pytest.fixture
def device_data() -> Device:
    """Return a parsed single device from the fixture."""
    return Device.from_json(_load_fixture("device.json"))


@pytest.fixture
def routes_data() -> DeviceRoutes:
    """Return parsed device routes from the fixture."""
    return DeviceRoutes.from_json(_load_fixture("device_routes.json"))


# --- CLI structure ---


def test_cli_structure(snapshot: SnapshotAssertion) -> None:
    """The CLI exposes the expected commands and options."""
    group = get_command(cli)
    assert isinstance(group, TyperGroup)
    structure = {}
    for name, subcommand in sorted(group.commands.items()):
        if isinstance(subcommand, TyperGroup):
            structure[name] = {
                sub_name: sorted(param.name for param in sub_cmd.params)
                for sub_name, sub_cmd in sorted(subcommand.commands.items())
            }
        else:
            structure[name] = sorted(param.name for param in subcommand.params)
    assert structure == snapshot


# --- devices command ---


def test_devices_command(
    runner: CliRunner,
    devices_data: dict[str, Device],
    snapshot: SnapshotAssertion,
) -> None:
    """Devices command renders a table of all devices."""
    mock_cls = _mock_tailscale(devices=devices_data)
    exit_code, output = _invoke(
        runner,
        ["devices", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert output == snapshot


# --- device command ---


def test_device_command(
    runner: CliRunner,
    device_data: Device,
    snapshot: SnapshotAssertion,
) -> None:
    """Device command renders detailed device information."""
    mock_cls = _mock_tailscale(device=device_data)
    exit_code, output = _invoke(
        runner,
        ["device", "98765", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert output == snapshot


def test_device_command_external(
    runner: CliRunner,
    devices_data: dict[str, Device],
    snapshot: SnapshotAssertion,
) -> None:
    """Device command handles an external device with minimal fields."""
    external_device = devices_data["67890"]
    mock_cls = _mock_tailscale(device=external_device)
    exit_code, output = _invoke(
        runner,
        ["device", "67890", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert output == snapshot


# --- routes command ---


def test_routes_command(
    runner: CliRunner,
    routes_data: DeviceRoutes,
    snapshot: SnapshotAssertion,
) -> None:
    """Routes command renders a table with enabled/advertised status."""
    mock_cls = _mock_tailscale(device_routes=routes_data)
    exit_code, output = _invoke(
        runner,
        ["routes", "12345", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert output == snapshot


# --- dns commands ---


def test_dns_nameservers_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """DNS nameservers command renders a table."""
    ns = DNSNameservers.from_json(_load_fixture("dns_nameservers.json"))
    mock_client = _mock_tailscale()
    mock_client.dns_nameservers.return_value = ns
    exit_code, output = _invoke(
        runner,
        ["dns", "nameservers", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


def test_dns_preferences_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """DNS preferences command shows MagicDNS status."""
    prefs = DNSPreferences.from_json(_load_fixture("dns_preferences.json"))
    mock_client = _mock_tailscale()
    mock_client.dns_preferences.return_value = prefs
    exit_code, output = _invoke(
        runner,
        ["dns", "preferences", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


def test_dns_search_paths_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """DNS search paths command renders a table."""
    paths = DNSSearchPaths.from_json(_load_fixture("dns_searchpaths.json"))
    mock_client = _mock_tailscale()
    mock_client.dns_search_paths.return_value = paths
    exit_code, output = _invoke(
        runner,
        ["dns", "search-paths", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


def test_dns_split_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """DNS split command renders a table."""
    split = json.loads(_load_fixture("split_dns.json"))
    mock_client = _mock_tailscale()
    mock_client.split_dns.return_value = split
    exit_code, output = _invoke(
        runner,
        ["dns", "split", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


def test_dns_set_nameservers_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """DNS set-nameservers command prints confirmation."""
    ns = DNSNameservers.from_json(_load_fixture("dns_nameservers.json"))
    mock_client = _mock_tailscale()
    mock_client.set_dns_nameservers.return_value = ns
    exit_code, output = _invoke(
        runner,
        [
            "dns",
            "set-nameservers",
            "8.8.8.8",
            "8.8.4.4",
            "--api-key",
            "tskey-api-test",
        ],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_dns_nameservers.assert_called_once_with(dns=["8.8.8.8", "8.8.4.4"])


def test_dns_set_preferences_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """DNS set-preferences command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["dns", "set-preferences", "--magic-dns", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_dns_preferences.assert_called_once_with(magic_dns=True)


def test_dns_set_search_paths_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """DNS set-search-paths command prints confirmation."""
    paths = DNSSearchPaths.from_json(_load_fixture("dns_searchpaths.json"))
    mock_client = _mock_tailscale()
    mock_client.set_dns_search_paths.return_value = paths
    exit_code, output = _invoke(
        runner,
        [
            "dns",
            "set-search-paths",
            "corp.example.com",
            "internal.example.com",
            "--api-key",
            "tskey-api-test",
        ],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_dns_search_paths.assert_called_once_with(
        search_paths=["corp.example.com", "internal.example.com"]
    )


# --- user commands ---


def test_users_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Users command renders a table of all users."""
    raw = json.loads(_load_fixture("users.json"))
    users = [TailscaleUser.from_dict(u) for u in raw["users"]]
    mock_client = _mock_tailscale()
    mock_client.users.return_value = users
    exit_code, output = _invoke(
        runner,
        ["users", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


def test_user_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """User command renders detailed user information."""
    user = TailscaleUser.from_json(_load_fixture("user.json"))
    mock_client = _mock_tailscale()
    mock_client.user.return_value = user
    exit_code, output = _invoke(
        runner,
        ["user", "u12345", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


# --- key commands ---


def test_keys_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Keys command renders a table of all keys."""
    raw = json.loads(_load_fixture("keys.json"))
    keys = [TailscaleKey.from_dict(k) for k in raw["keys"]]
    mock_client = _mock_tailscale()
    mock_client.keys.return_value = keys
    exit_code, output = _invoke(
        runner,
        ["keys", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


def test_delete_key_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Delete-key command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["delete-key", "k1234567890abcdef", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.delete_key.assert_called_once_with("k1234567890abcdef")


# --- settings commands ---


def test_settings_show_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Settings show command renders a table of tailnet settings."""
    ts = TailnetSettings.from_json(_load_fixture("tailnet_settings.json"))
    mock_client = _mock_tailscale()
    mock_client.tailnet_settings.return_value = ts
    exit_code, output = _invoke(
        runner,
        ["settings", "show", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


def test_settings_device_approval_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Settings device-approval command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["settings", "device-approval", "--enable", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.update_tailnet_settings.assert_called_once_with(
        devices_approval_on=True,
    )


def test_settings_key_duration_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Settings key-duration command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["settings", "key-duration", "90", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.update_tailnet_settings.assert_called_once_with(
        devices_key_duration_days=90,
    )


def test_settings_external_tailnets_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Settings external-tailnets command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["settings", "external-tailnets", "admin", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.update_tailnet_settings.assert_called_once_with(
        users_role_allowed_to_join_external_tailnets="admin",
    )


def test_settings_show_command_unknown(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Settings show command marks settings the API left out as unknown."""
    mock_client = _mock_tailscale()
    mock_client.tailnet_settings.return_value = TailnetSettings.from_dict({})
    exit_code, output = _invoke(
        runner,
        ["settings", "show", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot


def test_settings_https_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Settings https command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["settings", "https", "--disable", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.update_tailnet_settings.assert_called_once_with(
        https_enabled=False,
    )


def test_settings_route_selection_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Settings route-selection command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        [
            "settings",
            "route-selection",
            "regional-routing",
            "--api-key",
            "tskey-api-test",
        ],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.update_tailnet_settings.assert_called_once_with(
        route_selection="regional-routing",
    )


# --- policy, webhook, Service, and audit log commands ---


def test_policy_show_command(runner: CliRunner) -> None:
    """Policy show command prints the policy file as HuJSON."""
    mock_client = _mock_tailscale()
    mock_client.policy_file.return_value = PolicyFile(
        policy='// Comment\n{"acls": []}\n', etag='"e1234"'
    )
    exit_code, output = _invoke(
        runner, ["policy", "show", "--api-key", "tskey-api-test"], mock_client
    )
    assert exit_code == 0
    assert output == '// Comment\n{"acls": []}\n\n'


def test_policy_show_etag_command(runner: CliRunner) -> None:
    """Policy show command prints the ETag with --etag."""
    mock_client = _mock_tailscale()
    mock_client.policy_file.return_value = PolicyFile(policy="{}", etag='"e1234"')
    exit_code, output = _invoke(
        runner,
        ["policy", "show", "--etag", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == '"e1234"\n'


def test_policy_validate_command(
    runner: CliRunner,
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    """Policy validate command says when the policy file is valid."""
    policy_path = tmp_path / "policy.hujson"
    policy_path.write_text('{"acls": []}')
    mock_client = _mock_tailscale()
    mock_client.validate_policy_file.return_value = PolicyFileValidation()
    exit_code, output = _invoke(
        runner,
        ["policy", "validate", str(policy_path), "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.validate_policy_file.assert_called_once_with('{"acls": []}')


def test_policy_validate_command_invalid(
    runner: CliRunner,
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    """Policy validate command shows why the policy file is not valid."""
    policy_path = tmp_path / "policy.hujson"
    policy_path.write_text('{"acls": []}')
    mock_client = _mock_tailscale()
    mock_client.validate_policy_file.return_value = PolicyFileValidation(
        message="test(s) failed",
        data=[
            PolicyTestResult(
                user="alice@example.com",
                errors=['address "100.64.0.1:22": want: Drop, got: Accept'],
            )
        ],
    )
    exit_code, output = _invoke(
        runner,
        ["policy", "validate", str(policy_path), "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 1
    assert output == snapshot


def test_policy_set_command(
    runner: CliRunner,
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    """Policy set command sets the policy file, guarded by the ETag."""
    policy_path = tmp_path / "policy.hujson"
    policy_path.write_text('{"acls": []}')
    mock_client = _mock_tailscale()
    mock_client.set_policy_file.return_value = PolicyFile(
        policy='{"acls": []}', etag='"e5678"'
    )
    exit_code, output = _invoke(
        runner,
        [
            "policy",
            "set",
            str(policy_path),
            "--etag",
            '"e1234"',
            "--api-key",
            "tskey-api-test",
        ],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_policy_file.assert_called_once_with('{"acls": []}', etag='"e1234"')


def test_webhooks_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Webhooks command renders a table of all webhooks."""
    mock_client = _mock_tailscale()
    mock_client.webhooks.return_value = [
        TailscaleWebhook(
            endpoint_id="e1234CNTRL",
            endpoint_url="https://example.com/tailscale",
            subscriptions=["nodeCreated", "nodeDeleted"],
        ),
        TailscaleWebhook(
            endpoint_id="e5678CNTRL",
            endpoint_url="https://hooks.slack.com/services/T000",
            provider_type="slack",
            subscriptions=["userNeedsApproval"],
        ),
    ]
    exit_code, output = _invoke(
        runner, ["webhooks", "--api-key", "tskey-api-test"], mock_client
    )
    assert exit_code == 0
    assert output == snapshot


def test_services_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Services command renders a table of all Services."""
    mock_client = _mock_tailscale()
    mock_client.services.return_value = [
        TailscaleService(
            name="svc:web",
            addrs=["100.100.100.100"],
            ports=["tcp:443"],
            tags=["tag:web"],
            comment="The website",
        ),
        TailscaleService(name="svc:bare"),
    ]
    exit_code, output = _invoke(
        runner, ["services", "--api-key", "tskey-api-test"], mock_client
    )
    assert exit_code == 0
    assert output == snapshot


def test_audit_logs_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Audit logs command renders a table of the configuration changes."""
    mock_client = _mock_tailscale()
    mock_client.configuration_audit_logs.return_value = [
        AuditLog(
            actor=AuditLogActor(actor_id="u1", login_name="alice@example.com"),
            event_time=datetime(2026, 10, 9, 18, 39, 35, tzinfo=UTC),
            target=AuditLogTarget(
                target_type="NODE", name="server", property="MACHINE_NAME"
            ),
            action="UPDATE",
        ),
        AuditLog(
            actor=AuditLogActor(actor_id="nDEVICE123"),
            event_time=datetime(2026, 10, 9, 19, 0, tzinfo=UTC),
            target=AuditLogTarget(target_type="ADMIN_CONSOLE"),
        ),
    ]
    exit_code, output = _invoke(
        runner,
        ["audit-logs", "--hours", "2", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot

    call = mock_client.configuration_audit_logs.call_args
    assert call.kwargs["end"] - call.kwargs["start"] == timedelta(hours=2)


# --- action commands ---


def test_authorize_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Authorize command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["authorize", "12345", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.authorize_device.assert_called_once_with("12345", authorized=True)


def test_deauthorize_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Deauthorize command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["deauthorize", "12345", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.authorize_device.assert_called_once_with("12345", authorized=False)


def test_delete_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Delete command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["delete", "12345", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.delete_device.assert_called_once_with("12345")


def test_expire_key_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Expire-key command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["expire-key", "12345", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.expire_device_key.assert_called_once_with("12345")


def test_set_key_expiry_disable_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Set-key-expiry --disable prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["set-key-expiry", "12345", "--disable", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_device_key_expiry.assert_called_once_with(
        "12345", key_expiry_disabled=True
    )


def test_set_key_expiry_enable_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Set-key-expiry --enable prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["set-key-expiry", "12345", "--enable", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_device_key_expiry.assert_called_once_with(
        "12345", key_expiry_disabled=False
    )


def test_rename_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Rename command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["rename", "12345", "new-hostname", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.rename_device.assert_called_once_with("12345", name="new-hostname")


def test_set_tags_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Set-tags command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        [
            "set-tags",
            "12345",
            "tag:server",
            "tag:prod",
            "--api-key",
            "tskey-api-test",
        ],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_device_tags.assert_called_once_with(
        "12345", tags=["tag:server", "tag:prod"]
    )


def test_set_routes_command(
    runner: CliRunner,
    routes_data: DeviceRoutes,
    snapshot: SnapshotAssertion,
) -> None:
    """Set-routes command prints updated routes."""
    mock_client = _mock_tailscale(device_routes=routes_data)
    mock_client.set_device_routes.return_value = routes_data
    exit_code, output = _invoke(
        runner,
        [
            "set-routes",
            "12345",
            "10.200.0.0/16",
            "192.168.50.0/24",
            "--api-key",
            "tskey-api-test",
        ],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_device_routes.assert_called_once_with(
        "12345", routes=["10.200.0.0/16", "192.168.50.0/24"]
    )


def test_set_ip_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Set-ip command prints confirmation."""
    mock_client = _mock_tailscale()
    exit_code, output = _invoke(
        runner,
        ["set-ip", "12345", "100.64.0.1", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert output == snapshot
    mock_client.set_device_ipv4_address.assert_called_once_with(
        "12345", ipv4_address="100.64.0.1"
    )


# --- dump commands ---


def test_dump_devices_command(
    runner: CliRunner,
) -> None:
    """Dump devices command outputs raw JSON."""
    raw = _load_fixture("devices.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "devices", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_device_command(
    runner: CliRunner,
) -> None:
    """Dump device command outputs raw JSON for a single device."""
    raw = _load_fixture("device.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "device", "98765", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_routes_command(
    runner: CliRunner,
) -> None:
    """Dump routes command outputs raw JSON for device routes."""
    raw = _load_fixture("device_routes.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "routes", "12345", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_dns_nameservers_command(
    runner: CliRunner,
) -> None:
    """Dump DNS nameservers command outputs raw JSON."""
    raw = _load_fixture("dns_nameservers.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "dns-nameservers", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_dns_preferences_command(
    runner: CliRunner,
) -> None:
    """Dump DNS preferences command outputs raw JSON."""
    raw = _load_fixture("dns_preferences.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "dns-preferences", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_dns_search_paths_command(
    runner: CliRunner,
) -> None:
    """Dump DNS search paths command outputs raw JSON."""
    raw = _load_fixture("dns_searchpaths.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "dns-search-paths", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_dns_split_command(
    runner: CliRunner,
) -> None:
    """Dump split DNS command outputs raw JSON."""
    raw = _load_fixture("split_dns.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "dns-split", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_users_command(
    runner: CliRunner,
) -> None:
    """Dump users command outputs raw JSON."""
    raw = _load_fixture("users.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "users", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_user_command(
    runner: CliRunner,
) -> None:
    """Dump user command outputs raw JSON for a single user."""
    raw = _load_fixture("user.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "user", "u12345", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_settings_command(
    runner: CliRunner,
) -> None:
    """Dump settings command outputs raw JSON."""
    raw = _load_fixture("tailnet_settings.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "settings", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_keys_command(
    runner: CliRunner,
) -> None:
    """Dump keys command outputs raw JSON."""
    raw = _load_fixture("keys.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "keys", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


def test_dump_key_command(
    runner: CliRunner,
) -> None:
    """Dump key command outputs raw JSON for a single key."""
    raw = _load_fixture("key.json")
    mock_cls = _mock_tailscale(raw_response=raw)
    exit_code, output = _invoke(
        runner,
        ["dump", "key", "k1234567890abcdef", "--api-key", "tskey-api-test"],
        mock_cls,
    )
    assert exit_code == 0
    assert json.loads(output) == json.loads(raw)


# --- missing auth ---


def test_missing_auth(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    """Commands without credentials print an error and exit with 1."""
    monkeypatch.delenv("TAILSCALE_API_KEY", raising=False)
    monkeypatch.delenv("TAILSCALE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TAILSCALE_OAUTH_CLIENT_SECRET", raising=False)
    result = runner.invoke(cli, ["devices"])
    assert result.exit_code == 1
    assert result.stdout == snapshot


# --- error handlers ---


def test_authentication_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """Authentication error handler prints a panel and exits with 1."""
    handler = cli.error_handlers[TailscaleAuthenticationError]
    with pytest.raises(SystemExit) as exc_info:
        handler(TailscaleAuthenticationError("bad key"))
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot


def test_permission_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """Permission error handler prints the reason of the API and exits with 1."""
    handler = cli.error_handlers[TailscalePermissionError]
    with pytest.raises(SystemExit) as exc_info:
        handler(
            TailscalePermissionError(
                403, "feature not available on current billing plan"
            )
        )
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot


def test_permission_error_handler_is_used_first() -> None:
    """A permission error does not get the authentication error handler."""
    handlers = list(cli.error_handlers)
    assert handlers.index(TailscalePermissionError) < handlers.index(
        TailscaleAuthenticationError
    )


def test_connection_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """Connection error handler prints a panel and exits with 1."""
    handler = cli.error_handlers[TailscaleConnectionError]
    with pytest.raises(SystemExit) as exc_info:
        handler(TailscaleConnectionError("unreachable"))
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot


def test_general_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """General error handler prints a panel and exits with 1."""
    handler = cli.error_handlers[TailscaleError]
    with pytest.raises(SystemExit) as exc_info:
        handler(TailscaleError("something went wrong"))
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot


def test_console_script() -> None:
    """The console script does not clash with the official Tailscale client."""
    scripts = {
        entry_point.name: entry_point.value
        for entry_point in entry_points(group="console_scripts")
        if entry_point.value.startswith("tailscale.")
    }
    assert scripts == {"tailscale-api": "tailscale._cli:main"}


@pytest.mark.parametrize(
    ("args", "uri"),
    [
        (["devices"], "tailnet/-/devices?fields=all"),
        (["device", "n1"], "device/n1?fields=all"),
        (["routes", "n1"], "device/n1/routes"),
        (["device-posture-attributes", "n1"], "device/n1/attributes"),
        (["device-invites", "n1"], "device/n1/device-invites"),
        (["dns-configuration"], "tailnet/-/dns/configuration"),
        (["dns-nameservers"], "tailnet/-/dns/nameservers"),
        (["dns-preferences"], "tailnet/-/dns/preferences"),
        (["dns-search-paths"], "tailnet/-/dns/searchpaths"),
        (["dns-split"], "tailnet/-/dns/split-dns"),
        (["users"], "tailnet/-/users?type=all"),
        (["user", "u1"], "users/u1"),
        (["user-invites"], "tailnet/-/user-invites"),
        (["keys"], "tailnet/-/keys?all=true"),
        (["key", "k1"], "tailnet/-/keys/k1"),
        (["settings"], "tailnet/-/settings"),
        (["policy"], "tailnet/-/acl"),
        (["webhooks"], "tailnet/-/webhooks"),
        (["services"], "tailnet/-/services"),
        (["service", "svc:web"], "tailnet/-/services/svc:web"),
        (["service-hosts", "svc:web"], "tailnet/-/services/svc:web/devices"),
        (["posture-integrations"], "tailnet/-/posture/integrations"),
        (["oauth-apps"], "tailnet/-/oauth-apps"),
        (["contacts"], "tailnet/-/contacts"),
        (["organization-tailnets"], "organizations/-/tailnets"),
        (["log-stream", "network"], "tailnet/-/logging/network/stream"),
        (
            ["log-stream-status", "configuration"],
            "tailnet/-/logging/configuration/stream/status",
        ),
    ],
)
def test_dump_commands(
    runner: CliRunner,
    args: list[str],
    uri: str,
) -> None:
    """Dump commands request their endpoint and print its raw JSON."""
    mock_client = _mock_tailscale(raw_response='{"answer": [42]}')
    exit_code, output = _invoke(
        runner,
        ["dump", *args, "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert json.loads(output) == {"answer": [42]}
    mock_client._request.assert_called_once_with(  # pylint: disable=protected-access
        uri, params=None
    )


@pytest.mark.parametrize(
    ("command", "uri"),
    [
        ("audit-logs", "tailnet/-/logging/configuration"),
        ("network-logs", "tailnet/-/logging/network"),
    ],
)
def test_dump_log_commands(
    runner: CliRunner,
    command: str,
    uri: str,
) -> None:
    """Dump log commands request the given hours of logs."""
    mock_client = _mock_tailscale(raw_response='{"logs": null}')
    exit_code, output = _invoke(
        runner,
        ["dump", command, "--hours", "2", "--api-key", "tskey-api-test"],
        mock_client,
    )
    assert exit_code == 0
    assert json.loads(output) == {"logs": None}

    mock_client._request.assert_called_once()  # pylint: disable=protected-access
    call = mock_client._request.call_args  # pylint: disable=protected-access
    assert call.args == (uri,)
    params = call.kwargs["params"]
    start = datetime.fromisoformat(params["start"])
    end = datetime.fromisoformat(params["end"])
    assert end - start == timedelta(hours=2)
    assert end.tzinfo is not None


def test_tracebacks_leave_out_locals() -> None:
    """Tracebacks of the CLI do not show the locals, which hold credentials."""
    assert cli.pretty_exceptions_show_locals is False


def _command_paths() -> list[list[str]]:
    """Return the path to every command of the CLI, like ["dns", "split"]."""
    group = get_command(cli)
    assert isinstance(group, TyperGroup)
    paths: list[list[str]] = []
    for name, command in sorted(group.commands.items()):
        if isinstance(command, TyperGroup):
            paths.extend([name, sub_name] for sub_name in sorted(command.commands))
        else:
            paths.append([name])
    return paths


@pytest.mark.parametrize("path", _command_paths(), ids=" ".join)
def test_command_help(runner: CliRunner, path: list[str]) -> None:
    """Every command shows its help, which breaks with mismatched Typer and Click."""
    result = runner.invoke(cli, [*path, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
