"""Asynchronous client for the Tailscale API."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, validator

if TYPE_CHECKING:
    from datetime import datetime


class ClientSupports(BaseModel):
    """Object holding Tailscale device information."""

    hair_pinning: bool | None = Field(..., alias="hairPinning")
    ipv6: bool | None
    pcp: bool | None
    pmp: bool | None
    udp: bool | None
    upnp: bool | None


class ClientConnectivity(BaseModel):
    """Object holding Tailscale device information."""

    endpoints: list[str] = Field(default_factory=list)
    derp: str
    mapping_varies_by_dest_ip: bool | None = Field(
        None,
        alias="mappingVariesByDestIP",
    )
    latency: Any
    client_supports: ClientSupports = Field(..., alias="clientSupports")


class Device(BaseModel):
    """Object holding Tailscale device information."""

    addresses: list[str]
    device_id: str = Field(..., alias="id")
    user: str
    name: str
    hostname: str
    client_version: str = Field(..., alias="clientVersion")
    update_available: bool = Field(..., alias="updateAvailable")
    os: str
    created: datetime | None
    last_seen: datetime | None = Field(..., alias="lastSeen")
    tags: list[str] | None
    key_expiry_disabled: bool = Field(..., alias="keyExpiryDisabled")
    expires: datetime | None
    authorized: bool
    is_external: bool = Field(..., alias="isExternal")
    machine_key: str = Field(..., alias="machineKey")
    node_key: str = Field(..., alias="nodeKey")
    blocks_incoming_connections: bool = Field(..., alias="blocksIncomingConnections")
    enabled_routes: list[str] = Field(alias="enabledRoutes", default_factory=list)
    advertised_routes: list[str] = Field(alias="advertisedRoutes", default_factory=list)
    client_connectivity: ClientConnectivity = Field(alias="clientConnectivity")

    @validator("created", pre=True)
    @classmethod
    def empty_as_none(cls, data: str | None) -> str | None:
        """Convert an emtpty string to None.

        Args:
        ----
            data: String to convert.

        Returns:
        -------
            String or none if string is empty.
        """
        if not data:
            return None
        return data


class Devices(BaseModel):
    """Object holding Tailscale device information."""

    devices: dict[str, Device]

    @validator("devices", pre=True)
    @classmethod
    def convert_to_dict(
        cls,
        data: list[dict[str, Any]],
    ) -> dict[Any, dict[str, Any]]:
        """Convert list into dict, keyed by device id.

        Args:
        ----
            data: List of dicts to convert.

        Returns:
        -------
            dict: Converted list of dicts.
        """
        return {device["id"]: device for device in data}
