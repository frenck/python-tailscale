"""Asynchronous Python client for the Tailscale API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mashumaro import field_options
from mashumaro.mixins.orjson import DataClassORJSONMixin


@dataclass
class ClientSupports(DataClassORJSONMixin):
    """Object holding Tailscale client support capabilities."""

    ipv6: bool | None = None
    pcp: bool | None = None
    pmp: bool | None = None
    udp: bool | None = None
    upnp: bool | None = None


@dataclass
class Latency(DataClassORJSONMixin):
    """Object holding DERP region latency information."""

    latency_ms: float = field(metadata=field_options(alias="latencyMs"))
    preferred: bool | None = None


@dataclass
class ClientConnectivity(DataClassORJSONMixin):
    """Object holding Tailscale client connectivity details."""

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
    client_version: str = field(metadata=field_options(alias="clientVersion"))
    connected_to_control: bool = field(
        metadata=field_options(alias="connectedToControl")
    )
    device_id: str = field(metadata=field_options(alias="id"))
    hostname: str
    is_external: bool = field(metadata=field_options(alias="isExternal"))
    key_expiry_disabled: bool = field(metadata=field_options(alias="keyExpiryDisabled"))
    machine_key: str = field(metadata=field_options(alias="machineKey"))
    name: str
    node_id: str = field(metadata=field_options(alias="nodeId"))
    node_key: str = field(metadata=field_options(alias="nodeKey"))
    os: str
    tailnet_lock_key: str = field(metadata=field_options(alias="tailnetLockKey"))
    update_available: bool = field(metadata=field_options(alias="updateAvailable"))
    user: str
    advertised_routes: list[str] = field(
        default_factory=list, metadata=field_options(alias="advertisedRoutes")
    )
    client_connectivity: ClientConnectivity | None = field(
        default=None,
        metadata=field_options(alias="clientConnectivity"),
    )
    created: datetime | None = None
    enabled_routes: list[str] = field(
        default_factory=list, metadata=field_options(alias="enabledRoutes")
    )
    expires: datetime | None = None
    is_ephemeral: bool | None = field(
        default=None,
        metadata=field_options(alias="isEphemeral"),
    )
    last_seen: datetime | None = field(
        default=None,
        metadata=field_options(alias="lastSeen"),
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
        """Pre-process raw API data before deserialization.

        Args:
        ----
            d: The raw API response data.

        Returns:
        -------
            The adjusted data ready for deserialization.

        """
        # Convert an empty string to None.
        if not d.get("created"):
            d["created"] = None
        if not d.get("tailnetLockError"):
            d["tailnetLockError"] = None
        return d


@dataclass
class DeviceRoutes(DataClassORJSONMixin):
    """Object holding Tailscale device route information."""

    advertised_routes: list[str] = field(
        default_factory=list, metadata=field_options(alias="advertisedRoutes")
    )
    enabled_routes: list[str] = field(
        default_factory=list, metadata=field_options(alias="enabledRoutes")
    )


@dataclass
class Devices(DataClassORJSONMixin):
    """Object holding a collection of Tailscale devices."""

    devices: dict[str, Device]

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre-process raw API data before deserialization.

        Args:
        ----
            d: The raw API response data.

        Returns:
        -------
            The adjusted data ready for deserialization.

        """
        # Convert list into dict, keyed by device ID.
        d["devices"] = {device["id"]: device for device in d["devices"]}
        return d
