"""Asynchronous client for the Tailscale API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class ClientSupports(BaseModel):
    """Object holding Tailscale device information."""

    hair_pinning: Optional[bool] = Field(..., alias="hairPinning")
    ipv6: Optional[bool]
    pcp: Optional[bool]
    pmp: Optional[bool]
    udp: Optional[bool]
    upnp: Optional[bool]


class ClientConnectivity(BaseModel):
    """Object holding Tailscale device information."""

    endpoints: List[str] = Field(default_factory=list)
    derp: str
    mapping_varies_by_dest_ip: Optional[bool] = Field(
        None, alias="mappingVariesByDestIP"
    )
    latency: Any
    client_supports: ClientSupports = Field(..., alias="clientSupports")


class Device(BaseModel):
    """Object holding Tailscale device information."""

    addresses: List[str]
    device_id: str = Field(..., alias="id")
    node_id: str = Field(..., alias="nodeId")
    user: str
    name: str
    hostname: str
    client_version: str = Field(..., alias="clientVersion")
    update_available: bool = Field(..., alias="updateAvailable")
    os: str
    created: Optional[datetime]
    last_seen: Optional[datetime] = Field(..., alias="lastSeen")
    tags: Optional[List[str]]
    key_expiry_disabled: bool = Field(..., alias="keyExpiryDisabled")
    expires: Optional[datetime]
    authorized: bool
    is_external: bool = Field(..., alias="isExternal")
    machine_key: str = Field(..., alias="machineKey")
    node_key: str = Field(..., alias="nodeKey")
    blocks_incoming_connections: bool = Field(..., alias="blocksIncomingConnections")
    # not included in default response
    enabled_routes: List[str] = Field(alias="enabledRoutes", default_factory=list)
    advertised_routes: List[str] = Field(alias="advertisedRoutes", default_factory=list)
    client_connectivity: Optional[ClientConnectivity] = Field(
        alias="clientConnectivity"
    )

    @validator("created", pre=True)
    @classmethod
    def empty_as_none(cls, data: str | None) -> str | None:  # noqa: F841
        """Convert an emtpty string to None.

        Args:
            data: String to convert.

        Returns:
            String or none if string is empty.
        """
        if not data:
            return None
        return data


class Devices(BaseModel):
    """Object holding Tailscale device information."""

    devices: Dict[str, Device]

    @validator("devices", pre=True)
    @classmethod
    def convert_to_dict(
        cls, data: list[dict[str, Any]]  # noqa: F841
    ) -> dict[Any, dict[str, Any]]:
        """Convert list into dict, keyed by device id.

        Args:
            data: List of dicts to convert.

        Returns:
            dict: Converted list of dicts.
        """
        return {device.get("nodeId", device["id"]): device for device in data}


class AclBase(BaseModel):
    """Object holding Tailscale Acl base information."""

    action: str  # "accept" only, denied by default
    src: List[str]  # *, user, group, ip, cidr, tags, hosts
    dst: List[str]  # *, user, group, ip, cidr, tags, hosts


class Acl(AclBase):
    """Object holding Tailscale Acl information."""

    proto: Optional[str]  # iana protocol number or alias


class SshPolicy(AclBase):
    """Object holding Tailscale SSH policy information."""

    # action also can be "check" for ssh policy
    users: List[str]  # *, user, group
    check_period: Optional[str] = Field(
        alias="checkPeriod"
    )  # for checking access, e.g. "12h"


class AclTest(BaseModel):
    """Object holding Tailscale ACL Test information."""

    src: str  # user, group, tags, hosts
    accept: Optional[
        List[str]
    ]  # hosts, ips, tags, etc that src should be able to access
    deny: Optional[
        List[str]
    ]  # hosts, ips, tags, etc that src should not be able to access


class DerpNode(BaseModel):
    """Object holding Tailscale Derp Node information."""

    name: str = Field(..., alias="Name")
    region_id: int = Field(..., gt=0, alias="RegionID")
    hostname: str = Field(..., alias="HostName")


class DerpRegion(BaseModel):
    """Object holding Tailscale Derp Region information."""

    region_id: int = Field(..., gt=0, alias="RegionID")
    region_code: str = Field(alias="RegionCode")
    region_name: str = Field(alias="RegionName")
    nodes: List[DerpNode] = Field(alias="Nodes", default_factory=list)


class DerpMap(BaseModel):
    """Object holding Tailscale Derp Map information."""

    regions: Dict[str, DerpRegion] = Field(alias="Regions", default_factory=dict)
    omit_default_regions: Optional[bool] = Field(alias="OmitDefaultRegions")


class Policy(BaseModel):
    """Object holding Tailscale policy information."""

    acls: List[Acl]
    groups: Optional[Dict[str, List[str]]]
    hosts: Optional[Dict[str, str]]
    tag_owners: Optional[Dict[str, List[str]]] = Field(..., alias="tagOwners")
    derp_map: Optional[DerpMap] = Field(alias="derpMap")
    tests: Optional[List[AclTest]]
    auto_approvers: Optional[List[str]] = Field(alias="autoApprovers")
    ssh: Optional[List[SshPolicy]]
    node_attrs: Optional[Dict[str, str]] = Field(alias="nodeAttrs")
    disable_ipv4: Optional[bool] = Field(alias="disableIPv4")
    randomize_client_port: Optional[bool] = Field(alias="randomizeClientPort")
    one_cg_nat_route: Optional[str] = Field(alias="OneCGNATRoute")


class KeyAttributes(BaseModel):
    """Object describing Tailscale key capabilities."""

    reusable: bool = Field(default=False)
    ephemeral: bool = Field(default=False)
    preauthorized: bool = Field(default=True)
    tags: Optional[List[str]] = Field(default_factory=list)


class KeyCapabilities(BaseModel):
    """Object describing Tailscale key capabilities."""

    devices: Dict[str, KeyAttributes] = Field(default={"create": KeyAttributes()})


class AuthKeyRequest(BaseModel):
    """Object holding Tailscale API/Auth key information."""

    capabilities: KeyCapabilities
    expiry_seconds: int = Field(default=86400, alias="expirySeconds")


class AuthKey(BaseModel):
    """Object holding Tailscale API/Auth key information."""

    key_id: str = Field(..., alias="id")
    key: Optional[str]
    description: Optional[str] = Field(default="", max_length=100)
    created: datetime
    expires: datetime
    revoked: Optional[datetime]
    capabilities: Optional[KeyCapabilities]  # api keys don't have capabilities


class AuthKeys(BaseModel):
    """Object holding Tailscale multiple Auth keys information."""

    keys: List[Dict[str, str]]
