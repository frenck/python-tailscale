"""Asynchronous client for the Tailscale API."""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ClientSupports(BaseModel):
    """Object holding Tailscale device information."""

    hair_pinning: bool = Field(..., alias="hairPinning")
    ipv6: bool
    pcp: bool
    pmp: bool
    udp: bool
    upnp: bool


class ClientConnectivity(BaseModel):
    """Object holding Tailscale device information."""

    endpoints: List[str]
    derp: str
    mapping_varies_by_dest_ip: bool = Field(..., alias="mappingVariesByDestIp")
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
    client_connectivity: ClientConnectivity = Field(
        alias="clientConnectivity", default_factory=list
    )


class Devices(BaseModel):
    """Object holding Tailscale device information."""

    devices: List[Device]
