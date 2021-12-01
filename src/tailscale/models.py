"""Asynchronous client for the Tailscale API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class ClientSupports(BaseModel):
    """Object holding Tailscale device information."""

    hair_pinning: Optional[bool] = Field(..., alias="hairPinning")
    ipv6: bool
    pcp: bool
    pmp: bool
    udp: bool
    upnp: bool


class ClientConnectivity(BaseModel):
    """Object holding Tailscale device information."""

    endpoints: List[str] = Field(default_factory=list)
    derp: str
    mapping_varies_by_dest_ip: bool = Field(..., alias="mappingVariesByDestIP")
    latency: Any
    client_supports: ClientSupports = Field(..., alias="clientSupports")


class Device(BaseModel):
    """Object holding Tailscale device information."""

    addresses: List[str]
    device_id: str = Field(..., alias="id")
    user: str
    name: str
    hostname: str
    client_version: str = Field(..., alias="clientVersion")
    update_available: bool = Field(..., alias="updateAvailable")
    os: str
    created: datetime
    last_seen: Optional[datetime] = Field(..., alias="lastSeen")
    key_expiry_disabled: bool = Field(..., alias="keyExpiryDisabled")
    expires: Optional[datetime]
    authorized: bool
    is_external: bool = Field(..., alias="isExternal")
    machine_key: str = Field(..., alias="machineKey")
    node_key: str = Field(..., alias="nodeKey")
    blocks_incoming_connections: bool = Field(..., alias="blocksIncomingConnections")
    enabled_routes: List[str] = Field(alias="enabledRoutes", default_factory=list)
    advertised_routes: List[str] = Field(alias="advertisedRoutes", default_factory=list)
    client_connectivity: ClientConnectivity = Field(alias="clientConnectivity")


class Devices(BaseModel):
    """Object holding Tailscale device information."""

    devices: Dict[str, Device]

    @validator("devices", pre=True)
    @classmethod
    def convert_to_dict(cls, data: list[dict]) -> dict[Any, dict]:  # noqa: F841
        """Convert list into dict, keyed by device id.

        Args:
            data: List of dicts to convert.

        Returns:
            dict: Converted list of dicts.
        """
        return {device["id"]: device for device in data}
