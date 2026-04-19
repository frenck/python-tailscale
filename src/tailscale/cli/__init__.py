"""Command-line interface for the Tailscale API."""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
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


dump = AsyncTyper(
    help="Dump raw API responses as JSON (useful for debugging/fixtures).",
    no_args_is_help=True,
)
cli.add_typer(dump, name="dump")


@dump.command("devices")
async def dump_devices_command(
    tailnet: Tailnet = "-",
    api_key: ApiKey = None,
    oauth_client_id: OAuthClientId = None,
    oauth_client_secret: OAuthClientSecret = None,
) -> None:
    """Dump all devices as raw JSON."""
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        data = await client._request(  # noqa: SLF001
            f"tailnet/{client.tailnet}/devices?fields=all"
        )
    typer.echo(json.dumps(json.loads(data), indent=2, default=str))


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
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        data = await client._request(  # noqa: SLF001
            f"device/{device_id}?fields=all"
        )
    typer.echo(json.dumps(json.loads(data), indent=2, default=str))


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
    client = _build_client(tailnet, api_key, oauth_client_id, oauth_client_secret)
    async with client:
        data = await client._request(  # noqa: SLF001
            f"device/{device_id}/routes"
        )
    typer.echo(json.dumps(json.loads(data), indent=2, default=str))
