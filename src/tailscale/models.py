"""Asynchronous client for the Tailscale API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mashumaro import field_options
from mashumaro.mixins.orjson import DataClassORJSONMixin


@dataclass
class ClientSupports(DataClassORJSONMixin):
    """Object holding Tailscale device information."""

    hair_pinning: bool | None = field(metadata=field_options(alias="hairPinning"))
    ipv6: bool | None
    pcp: bool | None
    pmp: bool | None
    udp: bool | None
    upnp: bool | None


@dataclass
class Latency(DataClassORJSONMixin):
    """Object holding Tailscale device information."""

    latency_ms: float = field(metadata=field_options(alias="latencyMs"))
    preferred: bool | None = None


@dataclass
class ClientConnectivity(DataClassORJSONMixin):
    """Object holding Tailscale device information."""

    client_supports: ClientSupports = field(
        metadata=field_options(alias="clientSupports")
    )
    endpoints: list[str] = field(default_factory=list)
    latency: dict[str, Latency] = field(default_factory=dict)
    mapping_varies_by_dest_ip: bool | None = field(
        default=None,
        metadata=field_options(alias="mappingVariesByDestIP"),
    )


@dataclass
# pylint: disable-next=too-many-instance-attributes
class Device(DataClassORJSONMixin):
    """Object holding Tailscale device information."""

    addresses: list[str]
    authorized: bool
    blocks_incoming_connections: bool = field(
        metadata=field_options(alias="blocksIncomingConnections")
    )
    client_connectivity: ClientConnectivity | None = field(
        metadata=field_options(alias="clientConnectivity")
    )
    client_version: str = field(metadata=field_options(alias="clientVersion"))
    connected_to_control: bool = field(metadata=field_options(alias="connectedToControl"))
    created: datetime | None
    device_id: str = field(metadata=field_options(alias="id"))
    expires: datetime | None
    hostname: str
    is_external: bool = field(metadata=field_options(alias="isExternal"))
    key_expiry_disabled: bool = field(metadata=field_options(alias="keyExpiryDisabled"))
    last_seen: datetime | None = field(metadata=field_options(alias="lastSeen"))
    machine_key: str = field(metadata=field_options(alias="machineKey"))
    name: str
    node_key: str = field(metadata=field_options(alias="nodeKey"))
    node_id: str = field(metadata=field_options(alias="nodeId"))
    os: str
    tailnet_lock_key: str = field(metadata=field_options(alias="tailnetLockKey"))
    update_available: bool = field(metadata=field_options(alias="updateAvailable"))
    user: str
    advertised_routes: list[str] = field(
        default_factory=list, metadata=field_options(alias="advertisedRoutes")
    )
    enabled_routes: list[str] = field(
        default_factory=list, metadata=field_options(alias="enabledRoutes")
    )
    is_ephemeral: bool | None = field(
        default=None,
        metadata=field_options(alias="isEphemeral"),
    )
    multiple_connections: bool | None = field(
        default=None,
        metadata=field_options(alias="multipleConnections"),
    )
    ssh_enabled: bool | None = field(
        default=None,
        metadata=field_options(alias="sshEnabled"),
    )
    tags: list[str] = field(default_factory=list)
    tailnet_lock_error: str | None = field(
        default=None,
        metadata=field_options(alias="tailnetLockError"),
    )

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Handle some fields that are inconsistently named in the API.

        Args:
        ----
            data: The values of the model.

        Returns:
        -------
            The adjusted values of the model.

        """
        # Convert an empty string to None.
        if not d.get("created"):
            d["created"] = None
        if not d.get("tailnetLockError"):
            d["tailnetLockError"] = None
        return d


@dataclass
class Devices(DataClassORJSONMixin):
    """Object holding Tailscale device information."""

    devices: dict[str, Device]

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Handle some fields that are inconsistently named in the API.

        Args:
        ----
            data: The values of the model.

        Returns:
        -------
            The adjusted values of the model.

        """
        # Convert list into dict, keyed by device id.
        d["devices"] = {device["id"]: device for device in d["devices"]}
        return d
