"""Command-line interface for the Tailscale API."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
    TailscalePermissionError,
)
from tailscale.tailscale import Tailscale

from .async_typer import AsyncTyper

cli = AsyncTyper(
    help="Tailscale CLI — query and manage your tailnet from the terminal.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

Tailnet = Annotated[
    str,
    typer.Option(
        help="Tailnet name, or '-' for the default tailnet",
        show_default=True,
        envvar="TAILSCALE_TAILNET",
    ),
]
ApiKey = Annotated[
    str | None,
    typer.Option(
        help="API access token (tskey-api-...)",
        show_default=False,
        envvar="TAILSCALE_API_KEY",
    ),
]
OAuthClientId = Annotated[
    str | None,
    typer.Option(
        help="OAuth client ID",
        show_default=False,
        envvar="TAILSCALE_OAUTH_CLIENT_ID",
    ),
]
OAuthClientSecret = Annotated[
    str | None,
    typer.Option(
        help="OAuth client secret",
        show_default=False,
        envvar="TAILSCALE_OAUTH_CLIENT_SECRET",
    ),
]


# Registered before the authentication error handler, as the first handler that
# matches is used, and a permission error is an authentication error too.
@cli.error_handler(TailscalePermissionError)
def permission_error_handler(err: TailscalePermissionError) -> None:
    """Handle the API refusing a request the credentials are not allowed."""
    panel = Panel(
        f"The Tailscale API refused the request: {err.reason}",
        expand=False,
        title="Permission denied",
        border_style="red bold",
    )
    console.print(panel)
    sys.exit(1)


@cli.error_handler(TailscaleAuthenticationError)
def authentication_error_handler(_: TailscaleAuthenticationError) -> None:
    """Handle authentication errors."""
    message = """
    Authentication failed. Please check your API key or
    OAuth credentials and try again.
    """
    panel = Panel(
        message,
        expand=False,
        title="Authentication error",
        border_style="red bold",
    )
    console.print(panel)
    sys.exit(1)


@cli.error_handler(TailscaleConnectionError)
def connection_error_handler(_: TailscaleConnectionError) -> None:
    """Handle connection errors."""
    message = """
    Could not connect to the Tailscale API. Please check your
    internet connection and try again.
    """
    panel = Panel(
        message,
        expand=False,
        title="Connection error",
        border_style="red bold",
    )
    console.print(panel)
    sys.exit(1)


@cli.error_handler(TailscaleError)
def general_error_handler(err: TailscaleError) -> None:
    """Handle general Tailscale errors."""
    panel = Panel(
        str(err),
        expand=False,
        title="Tailscale API error",
        border_style="red bold",
    )
    console.print(panel)
    sys.exit(1)


def _build_client(
    tailnet: str,
    api_key: str | None,
    oauth_client_id: str | None,
    oauth_client_secret: str | None,
) -> Tailscale:
    """Build a Tailscale client from CLI options."""
    if not api_key and not (oauth_client_id and oauth_client_secret):
        console.print(
            "[red]Authentication required.[/red]\n"
            "Provide [bold]--api-key[/bold] (or TAILSCALE_API_KEY),\n"
            "or [bold]--oauth-client-id[/bold] and"
            " [bold]--oauth-client-secret[/bold]."
        )
        raise typer.Exit(code=1)
    return Tailscale(
        tailnet=tailnet,
        api_key=api_key,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
    )


@cli.command("devices")
async def devices_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """List all devices in the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        devices = await client.devices()

    table = Table(title="Devices", show_header=True, border_style="dim")
    table.add_column("Node ID", style="cyan")
    table.add_column("Hostname", style="bold")
    table.add_column("OS")
    table.add_column("Addresses")
    table.add_column("Authorized")
    table.add_column("Last Seen")
    table.add_column("Tags")

    for device in devices.values():
        authorized = "[green]Yes[/green]" if device.authorized else "[red]No[/red]"
        last_seen = str(device.last_seen) if device.last_seen else "[dim]-[/dim]"
        tags = ", ".join(device.tags) if device.tags else "[dim]-[/dim]"
        addresses = ", ".join(device.addresses)
        table.add_row(
            device.node_id,
            device.hostname,
            device.os,
            addresses,
            authorized,
            last_seen,
            tags,
        )

    console.print(table)


@cli.command("device")
async def device_command(  # noqa: PLR0912, PLR0915  # pylint: disable=too-many-branches,too-many-statements
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show detailed information for a single device."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        device = await client.device(device_id)

    info = Table(show_header=False, box=None, padding=(0, 2))
    info.add_column("Field", style="bold")
    info.add_column("Value")

    info.add_row("Name", device.name)
    info.add_row("Hostname", device.hostname)
    info.add_row("Device ID", device.device_id)
    info.add_row("Node ID", device.node_id)
    info.add_row("OS", device.os)
    info.add_row("Addresses", ", ".join(device.addresses))
    info.add_row("Client Version", device.client_version)
    info.add_row("User", device.user)

    authorized = "[green]Yes[/green]" if device.authorized else "[red]No[/red]"
    info.add_row("Authorized", authorized)

    info.add_row(
        "Key Expiry",
        "[yellow]Disabled[/yellow]"
        if device.key_expiry_disabled
        else str(device.expires or "[dim]-[/dim]"),
    )
    info.add_row(
        "Connected to Control",
        "[green]Yes[/green]" if device.connected_to_control else "[red]No[/red]",
    )

    if device.ssh_enabled is not None:
        ssh = "[green]Yes[/green]" if device.ssh_enabled else "[dim]No[/dim]"
        info.add_row("SSH Enabled", ssh)

    if device.is_external:
        info.add_row("External", "[yellow]Yes[/yellow]")

    if device.is_ephemeral:
        info.add_row("Ephemeral", "[yellow]Yes[/yellow]")

    if device.update_available:
        info.add_row("Update Available", "[yellow]Yes[/yellow]")

    if device.tags:
        info.add_row("Tags", ", ".join(device.tags))

    if device.advertised_routes:
        info.add_row("Advertised Routes", ", ".join(device.advertised_routes))

    if device.enabled_routes:
        info.add_row("Enabled Routes", ", ".join(device.enabled_routes))

    if device.last_seen:
        info.add_row("Last Seen", str(device.last_seen))

    if device.created:
        info.add_row("Created", str(device.created))

    console.print(Panel(info, title=device.hostname, border_style="green"))

    if device.client_connectivity:
        cc = device.client_connectivity
        conn = Table(show_header=False, box=None, padding=(0, 2))
        conn.add_column("Field", style="bold")
        conn.add_column("Value")

        if cc.endpoints:
            conn.add_row("Endpoints", ", ".join(cc.endpoints))

        cs = cc.client_supports
        supports = []
        if cs.ipv6:
            supports.append("IPv6")
        if cs.udp:
            supports.append("UDP")
        if cs.pcp:
            supports.append("PCP")
        if cs.pmp:
            supports.append("PMP")
        if cs.upnp:
            supports.append("UPnP")
        if supports:
            conn.add_row("Supports", ", ".join(supports))

        if cc.latency:
            latency_parts = []
            for region, lat in cc.latency.items():
                pref = " *" if lat.preferred else ""
                latency_parts.append(f"{region}: {lat.latency_ms:.1f}ms{pref}")
            conn.add_row("DERP Latency", "\n".join(latency_parts))

        console.print(Panel(conn, title="Connectivity", border_style="cyan"))


@cli.command("routes")
async def routes_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show subnet routes for a device."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        routes = await client.device_routes(device_id)

    table = Table(title="Subnet Routes", show_header=True, border_style="dim")
    table.add_column("Route", style="bold")
    table.add_column("Status")

    for route in routes.advertised_routes:
        if route in routes.enabled_routes:
            status = "[green]Enabled[/green]"
        else:
            status = "[yellow]Advertised[/yellow]"
        table.add_row(route, status)

    console.print(table)


@cli.command("authorize")
async def authorize_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Authorize a device on the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.authorize_device(device_id, authorized=True)
    console.print(f"[green]Device {device_id} authorized.[/green]")


@cli.command("deauthorize")
async def deauthorize_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Deauthorize a device on the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.authorize_device(device_id, authorized=False)
    console.print(f"[yellow]Device {device_id} deauthorized.[/yellow]")


@cli.command("delete")
async def delete_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Delete a device from the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.delete_device(device_id)
    console.print(f"[red]Device {device_id} deleted.[/red]")


@cli.command("expire-key")
async def expire_key_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Expire a device's key, forcing it to re-authenticate."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.expire_device_key(device_id)
    console.print(f"[yellow]Key expired for device {device_id}.[/yellow]")


@cli.command("set-key-expiry")
async def set_key_expiry_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    disable: Annotated[
        bool,
        typer.Option("--disable/--enable", help="Disable or enable key expiry"),
    ] = False,
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Enable or disable key expiry for a device."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.set_device_key_expiry(device_id, key_expiry_disabled=disable)
    state = "disabled" if disable else "enabled"
    console.print(f"[green]Key expiry {state} for device {device_id}.[/green]")


@cli.command("rename")
async def rename_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    name: Annotated[
        str,
        typer.Argument(help="New device name (empty string resets to OS hostname)"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Rename a device."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.rename_device(device_id, name=name)
    console.print(f"[green]Device {device_id} renamed to {name}.[/green]")


@cli.command("set-tags")
async def set_tags_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tags: Annotated[
        list[str],
        typer.Argument(help="ACL tags (e.g. tag:server tag:prod)"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set ACL tags for a device."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.set_device_tags(device_id, tags=tags)
    console.print(f"[green]Tags set for device {device_id}: {', '.join(tags)}[/green]")


@cli.command("set-routes")
async def set_routes_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    routes: Annotated[
        list[str],
        typer.Argument(help="Routes to enable (e.g. 10.0.0.0/24 192.168.1.0/24)"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set enabled subnet routes for a device."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        result = await client.set_device_routes(device_id, routes=routes)
    console.print(
        f"[green]Routes updated for device {device_id}.[/green]\n"
        f"Advertised: {', '.join(result.advertised_routes)}\n"
        f"Enabled: {', '.join(result.enabled_routes)}"
    )


@cli.command("set-ip")
async def set_ip_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    ipv4_address: Annotated[
        str,
        typer.Argument(help="Tailscale IPv4 address to assign"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set the Tailscale IPv4 address for a device."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.set_device_ipv4_address(device_id, ipv4_address=ipv4_address)
    console.print(
        f"[green]IPv4 address for device {device_id} set to {ipv4_address}.[/green]"
    )


dns = AsyncTyper(
    help="Manage DNS configuration for the tailnet.",
    no_args_is_help=True,
)
cli.add_typer(dns, name="dns")


@dns.command("nameservers")
async def dns_nameservers_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show the DNS nameservers for the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        result = await client.dns_nameservers()

    table = Table(title="DNS Nameservers", show_header=True, border_style="dim")
    table.add_column("Nameserver", style="bold")

    for ns in result.dns:
        table.add_row(ns)

    console.print(table)
    if result.magic_dns is not None:
        magic = "[green]Enabled[/green]" if result.magic_dns else "[dim]Disabled[/dim]"
        console.print(f"MagicDNS: {magic}")


@dns.command("set-nameservers")
async def dns_set_nameservers_command(
    nameservers: Annotated[
        list[str],
        typer.Argument(help="DNS nameserver IP addresses"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set the DNS nameservers for the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        result = await client.set_dns_nameservers(dns=nameservers)
    console.print(f"[green]DNS nameservers updated: {', '.join(result.dns)}[/green]")


@dns.command("preferences")
async def dns_preferences_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show the DNS preferences for the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        result = await client.dns_preferences()

    magic = "[green]Enabled[/green]" if result.magic_dns else "[dim]Disabled[/dim]"
    console.print(f"MagicDNS: {magic}")


@dns.command("set-preferences")
async def dns_set_preferences_command(
    magic_dns: Annotated[
        bool,
        typer.Option("--magic-dns/--no-magic-dns", help="Enable or disable MagicDNS"),
    ] = True,
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set the DNS preferences for the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.set_dns_preferences(magic_dns=magic_dns)
    state = "enabled" if magic_dns else "disabled"
    console.print(f"[green]MagicDNS {state}.[/green]")


@dns.command("search-paths")
async def dns_search_paths_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show the DNS search paths for the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        result = await client.dns_search_paths()

    table = Table(title="DNS Search Paths", show_header=True, border_style="dim")
    table.add_column("Search Path", style="bold")

    for path in result.search_paths:
        table.add_row(path)

    console.print(table)


@dns.command("set-search-paths")
async def dns_set_search_paths_command(
    search_paths: Annotated[
        list[str],
        typer.Argument(help="DNS search paths"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set the DNS search paths for the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        result = await client.set_dns_search_paths(search_paths=search_paths)
    console.print(
        f"[green]DNS search paths updated: {', '.join(result.search_paths)}[/green]"
    )


@dns.command("split")
async def dns_split_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show the split DNS configuration for the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        result = await client.split_dns()

    table = Table(title="Split DNS", show_header=True, border_style="dim")
    table.add_column("Domain", style="bold")
    table.add_column("Nameservers")

    for domain, nameservers in result.items():
        table.add_row(domain, ", ".join(nameservers))

    console.print(table)


@cli.command("users")
async def users_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """List all users in the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        users = await client.users()

    table = Table(title="Users", show_header=True, border_style="dim")
    table.add_column("User ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Login")
    table.add_column("Role")
    table.add_column("Status")
    table.add_column("Devices", justify="right")
    table.add_column("Connected")

    for user in users:
        connected = (
            "[green]Yes[/green]" if user.currently_connected else "[dim]No[/dim]"
        )
        table.add_row(
            user.user_id,
            user.display_name,
            user.login_name,
            user.role,
            user.status,
            str(user.device_count or 0),
            connected,
        )

    console.print(table)


@cli.command("user")
async def user_command(
    user_id: Annotated[
        str,
        typer.Argument(help="User ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show detailed information for a single user."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        user = await client.user(user_id)

    info = Table(show_header=False, box=None, padding=(0, 2))
    info.add_column("Field", style="bold")
    info.add_column("Value")

    info.add_row("User ID", user.user_id)
    info.add_row("Name", user.display_name)
    info.add_row("Login", user.login_name)
    info.add_row("Role", user.role)
    info.add_row("Status", user.status)
    info.add_row("Type", user.user_type)

    if user.device_count is not None:
        info.add_row("Devices", str(user.device_count))

    if user.currently_connected is not None:
        connected = (
            "[green]Yes[/green]" if user.currently_connected else "[dim]No[/dim]"
        )
        info.add_row("Connected", connected)

    if user.last_seen:
        info.add_row("Last Seen", str(user.last_seen))

    if user.created:
        info.add_row("Created", str(user.created))

    console.print(Panel(info, title=user.display_name, border_style="green"))


settings = AsyncTyper(
    help="View and manage tailnet settings.",
    no_args_is_help=True,
)
cli.add_typer(settings, name="settings")


def _bool_display(val: bool | None) -> str:
    """Format a boolean for Rich display."""
    if val is None:
        return "[dim]Unknown[/dim]"
    return "[green]Yes[/green]" if val else "[dim]No[/dim]"


@settings.command("show")
async def settings_show_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show the tailnet settings."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        s = await client.tailnet_settings()

    table = Table(title="Tailnet Settings", show_header=True, border_style="dim")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Device Approval", _bool_display(s.devices_approval_on))
    table.add_row("Auto Updates", _bool_display(s.devices_auto_updates_on))
    table.add_row(
        "Key Duration",
        f"{s.devices_key_duration_days} days"
        if s.devices_key_duration_days is not None
        else "[dim]Unknown[/dim]",
    )
    table.add_row("User Approval", _bool_display(s.users_approval_on))
    table.add_row(
        "External Tailnets",
        s.users_role_allowed_to_join_external_tailnets or "[dim]Unknown[/dim]",
    )
    table.add_row("Network Flow Logging", _bool_display(s.network_flow_logging_on))
    table.add_row("Regional Routing", _bool_display(s.regional_routing_on))
    table.add_row(
        "Posture Identity Collection",
        _bool_display(s.posture_identity_collection_on),
    )
    table.add_row("HTTPS", _bool_display(s.https_enabled))
    table.add_row("Route Selection", s.route_selection or "[dim]Unknown[/dim]")
    table.add_row(
        "ACLs Externally Managed", _bool_display(s.acls_externally_managed_on)
    )
    if s.acls_external_link:
        table.add_row("ACLs External Link", s.acls_external_link)

    console.print(table)


@cli.command("keys")
async def keys_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """List all keys in the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        keys = await client.keys()

    table = Table(title="Keys", show_header=True, border_style="dim")
    table.add_column("Key ID", style="cyan")
    table.add_column("Type")
    table.add_column("Description", style="bold")
    table.add_column("Reusable")
    table.add_column("Ephemeral")
    table.add_column("Scopes")
    table.add_column("Expires")

    for k in keys:
        reusable = (
            "[green]Yes[/green]"
            if k.capabilities.devices.create.reusable
            else "[dim]No[/dim]"
        )
        ephemeral = (
            "[green]Yes[/green]"
            if k.capabilities.devices.create.ephemeral
            else "[dim]No[/dim]"
        )
        expires = str(k.expires) if k.expires else "[dim]-[/dim]"
        scopes = ", ".join(k.scopes) if k.scopes else "[dim]-[/dim]"
        table.add_row(
            k.key_id,
            k.key_type or "",
            k.description,
            reusable,
            ephemeral,
            scopes,
            expires,
        )

    console.print(table)


@cli.command("delete-key")
async def delete_key_command(
    key_id: Annotated[
        str,
        typer.Argument(help="Key ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Delete a key from the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.delete_key(key_id)
    console.print(f"[red]Key {key_id} deleted.[/red]")


@settings.command("device-approval")
async def settings_device_approval_command(
    enable: Annotated[
        bool,
        typer.Option("--enable/--disable", help="Enable or disable device approval"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Enable or disable device approval."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(devices_approval_on=enable)
    state = "enabled" if enable else "disabled"
    console.print(f"[green]Device approval {state}.[/green]")


@settings.command("auto-updates")
async def settings_auto_updates_command(
    enable: Annotated[
        bool,
        typer.Option("--enable/--disable", help="Enable or disable auto-updates"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Enable or disable device auto-updates."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(devices_auto_updates_on=enable)
    state = "enabled" if enable else "disabled"
    console.print(f"[green]Auto-updates {state}.[/green]")


@settings.command("key-duration")
async def settings_key_duration_command(
    days: Annotated[
        int,
        typer.Argument(help="Key expiry duration in days"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set the device key expiry duration."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(devices_key_duration_days=days)
    console.print(f"[green]Key duration set to {days} days.[/green]")


@settings.command("user-approval")
async def settings_user_approval_command(
    enable: Annotated[
        bool,
        typer.Option("--enable/--disable", help="Enable or disable user approval"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Enable or disable user approval."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(users_approval_on=enable)
    state = "enabled" if enable else "disabled"
    console.print(f"[green]User approval {state}.[/green]")


@settings.command("external-tailnets")
async def settings_external_tailnets_command(
    role: Annotated[
        str,
        typer.Argument(help="Role for external tailnets (none/admin/member)"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set which role can join external tailnets."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(
            users_role_allowed_to_join_external_tailnets=role,
        )
    console.print(f"[green]External tailnets role set to {role}.[/green]")


@settings.command("network-flow-logging")
async def settings_network_flow_logging_command(
    enable: Annotated[
        bool,
        typer.Option(
            "--enable/--disable", help="Enable or disable network flow logging"
        ),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Enable or disable network flow logging."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(network_flow_logging_on=enable)
    state = "enabled" if enable else "disabled"
    console.print(f"[green]Network flow logging {state}.[/green]")


@settings.command("regional-routing")
async def settings_regional_routing_command(
    enable: Annotated[
        bool,
        typer.Option("--enable/--disable", help="Enable or disable regional routing"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Enable or disable regional routing."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(regional_routing_on=enable)
    state = "enabled" if enable else "disabled"
    console.print(f"[green]Regional routing {state}.[/green]")


@settings.command("https")
async def settings_https_command(
    enable: Annotated[
        bool,
        typer.Option("--enable/--disable", help="Enable or disable HTTPS"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Enable or disable HTTPS certificates."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(https_enabled=enable)
    state = "enabled" if enable else "disabled"
    console.print(f"[green]HTTPS {state}.[/green]")


@settings.command("route-selection")
async def settings_route_selection_command(
    mode: Annotated[
        str,
        typer.Argument(
            help=(
                "Route selection (active-passive-failover/regional-routing/"
                "regional-routing-failover)"
            )
        ),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set how routes are selected."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(route_selection=mode)
    console.print(f"[green]Route selection set to {mode}.[/green]")


@settings.command("posture-identity")
async def settings_posture_identity_command(
    enable: Annotated[
        bool,
        typer.Option(
            "--enable/--disable",
            help="Enable or disable posture identity collection",
        ),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Enable or disable posture identity collection."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        await client.update_tailnet_settings(
            posture_identity_collection_on=enable,
        )
    state = "enabled" if enable else "disabled"
    console.print(f"[green]Posture identity collection {state}.[/green]")


LogHours = Annotated[
    int,
    typer.Option("--hours", help="How many hours of logs to show", min=1),
]

policy = AsyncTyper(
    help="Show, validate, and set the policy file of the tailnet.",
    no_args_is_help=True,
)
cli.add_typer(policy, name="policy")

PolicyPath = Annotated[
    Path,
    typer.Argument(
        help="Path to a policy file, as HuJSON or JSON",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
]


@policy.command("show")
async def policy_show_command(
    etag: Annotated[
        bool,
        typer.Option("--etag", help="Show the ETag instead of the policy file"),
    ] = False,
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Show the policy file, with its comments, as HuJSON."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        policy_file = await client.policy_file()
    typer.echo(policy_file.etag if etag else policy_file.policy)


@policy.command("validate")
async def policy_validate_command(
    path: PolicyPath,
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Validate a policy file, and run its tests, without setting it."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        validation = await client.validate_policy_file(path.read_text(encoding="utf-8"))

    if validation.valid:
        console.print("[green]The policy file is valid.[/green]")
        return

    console.print(f"[red]The policy file is not valid: {validation.message}[/red]")
    for result in validation.data:
        for error in result.errors:
            console.print(f"  [bold]{result.user}[/bold]: {error}")
    sys.exit(1)


@policy.command("set")
async def policy_set_command(
    path: PolicyPath,
    etag: Annotated[
        str | None,
        typer.Option(
            "--etag",
            help=(
                "Only set it when the policy file is still at this ETag, "
                "from policy show --etag"
            ),
        ),
    ] = None,
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Set the policy file of the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        policy_file = await client.set_policy_file(
            path.read_text(encoding="utf-8"), etag=etag
        )
    console.print(f"[green]Policy file set (ETag {policy_file.etag}).[/green]")


@cli.command("webhooks")
async def webhooks_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """List all webhooks in the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        webhooks = await client.webhooks()

    table = Table(title="Webhooks", show_header=True, border_style="dim")
    table.add_column("Endpoint ID", style="cyan")
    table.add_column("URL", style="bold")
    table.add_column("Provider")
    table.add_column("Events")

    for webhook in webhooks:
        table.add_row(
            webhook.endpoint_id,
            webhook.endpoint_url,
            webhook.provider_type or "[dim]-[/dim]",
            ", ".join(webhook.subscriptions),
        )

    console.print(table)


@cli.command("services")
async def services_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """List all Services in the tailnet."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        services = await client.services()

    table = Table(title="Services", show_header=True, border_style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Addresses")
    table.add_column("Ports")
    table.add_column("Tags")
    table.add_column("Comment")

    for service in services:
        table.add_row(
            service.name,
            ", ".join(service.addrs) or "[dim]-[/dim]",
            ", ".join(service.ports) or "[dim]-[/dim]",
            ", ".join(service.tags) or "[dim]-[/dim]",
            service.comment or "",
        )

    console.print(table)


@cli.command("audit-logs")
async def audit_logs_command(
    hours: LogHours = 24,
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """List the configuration changes of the last hours."""
    end = datetime.now(UTC)
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        logs = await client.configuration_audit_logs(
            start=end - timedelta(hours=hours), end=end
        )

    table = Table(title="Audit logs", show_header=True, border_style="dim")
    table.add_column("Time", style="cyan")
    table.add_column("Actor", style="bold")
    table.add_column("Action")
    table.add_column("Target")
    table.add_column("Property")

    for log in logs:
        actor = log.actor.login_name or log.actor.display_name or log.actor.actor_id
        target = " ".join(
            part for part in (log.target.target_type, log.target.name) if part
        )
        table.add_row(
            log.event_time.isoformat(timespec="seconds"),
            actor,
            log.action or "",
            target,
            log.target.property or "",
        )

    console.print(table)


dump = AsyncTyper(
    help="Dump raw API responses as JSON (useful for debugging/fixtures).",
    no_args_is_help=True,
)
cli.add_typer(dump, name="dump")


async def _dump(  # pylint: disable=too-many-arguments
    tailnet: str,
    api_key: str | None,
    oauth_client_id: str | None,
    oauth_client_secret: str | None,
    uri: str,
    *,
    params: dict[str, str] | None = None,
) -> None:
    """Print the raw JSON response of the Tailscale API for a URI.

    A "{tailnet}" in the URI is replaced by the tailnet in use.
    """
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        data = await client._request(  # noqa: SLF001
            uri.replace("{tailnet}", client.tailnet), params=params
        )
    typer.echo(json.dumps(json.loads(data), indent=2, default=str))


@dump.command("devices")
async def dump_devices_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump all devices as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/devices?fields=all",
    )


@dump.command("device")
async def dump_device_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump a single device as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"device/{device_id}?fields=all",
    )


@dump.command("routes")
async def dump_routes_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump device routes as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"device/{device_id}/routes",
    )


@dump.command("device-posture-attributes")
async def dump_device_posture_attributes_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the posture attributes of a device as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"device/{device_id}/attributes",
    )


@dump.command("device-invites")
async def dump_device_invites_command(
    device_id: Annotated[
        str,
        typer.Argument(help="Device ID or node ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the invites to share a device as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"device/{device_id}/device-invites",
    )


@dump.command("dns-configuration")
async def dump_dns_configuration_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the full DNS configuration as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/dns/configuration",
    )


@dump.command("dns-nameservers")
async def dump_dns_nameservers_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump DNS nameservers as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/dns/nameservers",
    )


@dump.command("dns-preferences")
async def dump_dns_preferences_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump DNS preferences as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/dns/preferences",
    )


@dump.command("dns-search-paths")
async def dump_dns_search_paths_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump DNS search paths as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/dns/searchpaths",
    )


@dump.command("dns-split")
async def dump_dns_split_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump split DNS configuration as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/dns/split-dns",
    )


@dump.command("users")
async def dump_users_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump all users as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/users?type=all",
    )


@dump.command("user")
async def dump_user_command(
    user_id: Annotated[
        str,
        typer.Argument(help="User ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump a single user as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"users/{user_id}",
    )


@dump.command("user-invites")
async def dump_user_invites_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the open invites for users as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/user-invites",
    )


@dump.command("keys")
async def dump_keys_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump all keys as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/keys?all=true",
    )


@dump.command("key")
async def dump_key_command(
    key_id: Annotated[
        str,
        typer.Argument(help="Key ID"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump a single key as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"tailnet/{{tailnet}}/keys/{key_id}",
    )


@dump.command("settings")
async def dump_settings_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump tailnet settings as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/settings",
    )


@dump.command("policy")
async def dump_policy_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the policy file as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/acl",
    )


@dump.command("webhooks")
async def dump_webhooks_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump all webhooks as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/webhooks",
    )


@dump.command("services")
async def dump_services_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump all Services as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/services",
    )


@dump.command("service")
async def dump_service_command(
    name: Annotated[
        str,
        typer.Argument(help="Service name, like svc:example"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump a single Service as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"tailnet/{{tailnet}}/services/{name}",
    )


@dump.command("service-hosts")
async def dump_service_hosts_command(
    name: Annotated[
        str,
        typer.Argument(help="Service name, like svc:example"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the devices hosting a Service as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"tailnet/{{tailnet}}/services/{name}/devices",
    )


@dump.command("posture-integrations")
async def dump_posture_integrations_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the posture integrations as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/posture/integrations",
    )


@dump.command("oauth-apps")
async def dump_oauth_apps_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the OAuth apps as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/oauth-apps",
    )


@dump.command("contacts")
async def dump_contacts_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the contacts of the tailnet as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/contacts",
    )


@dump.command("organization-tailnets")
async def dump_organization_tailnets_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the tailnets of the organization as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "organizations/-/tailnets",
    )


@dump.command("log-stream")
async def dump_log_stream_command(
    log_type: Annotated[
        str,
        typer.Argument(help="Log type (configuration/network)"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the log streaming configuration as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"tailnet/{{tailnet}}/logging/{log_type}/stream",
    )


@dump.command("log-stream-status")
async def dump_log_stream_status_command(
    log_type: Annotated[
        str,
        typer.Argument(help="Log type (configuration/network)"),
    ],
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the log streaming status as raw JSON."""
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        f"tailnet/{{tailnet}}/logging/{log_type}/stream/status",
    )


@dump.command("audit-logs")
async def dump_audit_logs_command(
    hours: LogHours = 24,
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the configuration audit logs as raw JSON."""
    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/logging/configuration",
        params={"start": start.isoformat(), "end": end.isoformat()},
    )


@dump.command("network-logs")
async def dump_network_logs_command(
    hours: LogHours = 24,
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump the network flow logs as raw JSON."""
    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    await _dump(
        tailnet,
        api_key,
        oauth_client_id,
        oauth_client_secret,
        "tailnet/{tailnet}/logging/network",
        params={"start": start.isoformat(), "end": end.isoformat()},
    )
