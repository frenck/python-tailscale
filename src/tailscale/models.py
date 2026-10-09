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
class DeviceDistro(DataClassORJSONMixin):
    """Object holding the operating system distribution of a device."""

    name: str | None = None
    version: str | None = None
    code_name: str | None = field(
        default=None, metadata=field_options(alias="codeName")
    )


@dataclass
class DevicePostureIdentity(DataClassORJSONMixin):
    """Object holding the posture identifiers of a device."""

    disabled: bool | None = None
    hardware_addresses: list[str] = field(
        default_factory=list, metadata=field_options(alias="hardwareAddresses")
    )
    serial_numbers: list[str] = field(
        default_factory=list, metadata=field_options(alias="serialNumbers")
    )


@dataclass
class DevicePostureStatus(DataClassORJSONMixin):
    """Object holding the posture status of a device."""

    failing_assertions: list[str] = field(
        default_factory=list, metadata=field_options(alias="failingAssertions")
    )
    impacting: bool | None = None
    passing: bool | None = None


@dataclass
# pylint: disable-next=too-many-instance-attributes
class Device(DataClassORJSONMixin):
    """Object holding Tailscale device information.

    The API marks none of the fields as required, and leaves out a lot of
    them for devices shared in from another tailnet. Only the identifiers
    of the device are required here; the rest is None when the API leaves
    it out.
    """

    device_id: str = field(metadata=field_options(alias="id"))
    hostname: str
    name: str
    node_id: str = field(metadata=field_options(alias="nodeId"))
    addresses: list[str] = field(default_factory=list)
    advertised_routes: list[str] = field(
        default_factory=list, metadata=field_options(alias="advertisedRoutes")
    )
    authorized: bool | None = None
    blocks_incoming_connections: bool | None = field(
        default=None, metadata=field_options(alias="blocksIncomingConnections")
    )
    client_connectivity: ClientConnectivity | None = field(
        default=None,
        metadata=field_options(alias="clientConnectivity"),
    )
    client_version: str | None = field(
        default=None, metadata=field_options(alias="clientVersion")
    )
    connected_to_control: bool | None = field(
        default=None, metadata=field_options(alias="connectedToControl")
    )
    created: datetime | None = None
    distro: DeviceDistro | None = None
    enabled_routes: list[str] = field(
        default_factory=list, metadata=field_options(alias="enabledRoutes")
    )
    expires: datetime | None = None
    is_ephemeral: bool | None = field(
        default=None,
        metadata=field_options(alias="isEphemeral"),
    )
    is_external: bool = field(default=False, metadata=field_options(alias="isExternal"))
    key_expiry_disabled: bool | None = field(
        default=None, metadata=field_options(alias="keyExpiryDisabled")
    )
    last_seen: datetime | None = field(
        default=None,
        metadata=field_options(alias="lastSeen"),
    )
    machine_key: str | None = field(
        default=None, metadata=field_options(alias="machineKey")
    )
    multiple_connections: bool | None = field(
        default=None,
        metadata=field_options(alias="multipleConnections"),
    )
    node_key: str | None = field(default=None, metadata=field_options(alias="nodeKey"))
    oauth_client_id: str | None = field(
        default=None, metadata=field_options(alias="oauthClientId")
    )
    os: str | None = None
    posture_identity: DevicePostureIdentity | None = field(
        default=None, metadata=field_options(alias="postureIdentity")
    )
    posture_status: DevicePostureStatus | None = field(
        default=None, metadata=field_options(alias="postureStatus")
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
    tailnet_lock_key: str | None = field(
        default=None, metadata=field_options(alias="tailnetLockKey")
    )
    update_available: bool | None = field(
        default=None, metadata=field_options(alias="updateAvailable")
    )
    user: str | None = None

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
        # The API sends an empty string or object for values it does not have.
        for key in (
            "created",
            "distro",
            "oauthClientId",
            "postureIdentity",
            "postureStatus",
            "tailnetLockError",
        ):
            if not d.get(key):
                d[key] = None
        return d


@dataclass
class DNSNameservers(DataClassORJSONMixin):
    """Object holding Tailscale DNS nameserver configuration."""

    dns: list[str] = field(default_factory=list)
    magic_dns: bool | None = field(
        default=None,
        metadata=field_options(alias="magicDNS"),
    )


@dataclass
class DNSPreferences(DataClassORJSONMixin):
    """Object holding Tailscale DNS preferences."""

    magic_dns: bool = field(metadata=field_options(alias="magicDNS"))


@dataclass
class DNSSearchPaths(DataClassORJSONMixin):
    """Object holding Tailscale DNS search paths."""

    search_paths: list[str] = field(
        default_factory=list, metadata=field_options(alias="searchPaths")
    )


@dataclass
class KeyCapabilitiesCreate(DataClassORJSONMixin):
    """Object holding key device creation capabilities."""

    reusable: bool = False
    ephemeral: bool = False
    preauthorized: bool = False
    tags: list[str] = field(default_factory=list)


@dataclass
class KeyCapabilitiesDevices(DataClassORJSONMixin):
    """Object holding key device capabilities."""

    create: KeyCapabilitiesCreate = field(default_factory=KeyCapabilitiesCreate)


@dataclass
class KeyCapabilities(DataClassORJSONMixin):
    """Object holding key capabilities."""

    devices: KeyCapabilitiesDevices = field(default_factory=KeyCapabilitiesDevices)


@dataclass
# pylint: disable-next=too-many-instance-attributes
class TailscaleKey(DataClassORJSONMixin):
    """Object holding a Tailscale key.

    A key is an auth key, an API access token, an OAuth client, or a
    federated identity; the key type tells which one.
    """

    key_id: str = field(metadata=field_options(alias="id"))
    description: str = ""
    key: str = ""
    created: datetime | None = None
    updated: datetime | None = None
    expires: datetime | None = None
    expiry_seconds: int | None = field(
        default=None, metadata=field_options(alias="expirySeconds")
    )
    revoked: datetime | None = None
    invalid: bool = False
    capabilities: KeyCapabilities = field(default_factory=KeyCapabilities)
    key_type: str | None = field(default=None, metadata=field_options(alias="keyType"))
    user_id: str | None = field(default=None, metadata=field_options(alias="userId"))
    scopes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    issuer: str | None = None
    subject: str | None = None
    audience: str | None = None
    custom_claim_rules: dict[str, str] = field(
        default_factory=dict, metadata=field_options(alias="customClaimRules")
    )


@dataclass
# pylint: disable-next=too-many-instance-attributes
class TailnetSettings(DataClassORJSONMixin):
    """Object holding tailnet-wide settings.

    The API allows every setting to be null, so a setting is None when the
    API does not return a value for it.
    """

    acls_external_link: str | None = field(
        default=None, metadata=field_options(alias="aclsExternalLink")
    )
    acls_externally_managed_on: bool | None = field(
        default=None, metadata=field_options(alias="aclsExternallyManagedOn")
    )
    devices_approval_on: bool | None = field(
        default=None, metadata=field_options(alias="devicesApprovalOn")
    )
    devices_auto_updates_on: bool | None = field(
        default=None, metadata=field_options(alias="devicesAutoUpdatesOn")
    )
    devices_key_duration_days: int | None = field(
        default=None, metadata=field_options(alias="devicesKeyDurationDays")
    )
    https_enabled: bool | None = field(
        default=None, metadata=field_options(alias="httpsEnabled")
    )
    network_flow_logging_on: bool | None = field(
        default=None, metadata=field_options(alias="networkFlowLoggingOn")
    )
    posture_identity_collection_on: bool | None = field(
        default=None,
        metadata=field_options(alias="postureIdentityCollectionOn"),
    )
    regional_routing_on: bool | None = field(
        default=None, metadata=field_options(alias="regionalRoutingOn")
    )
    route_selection: str | None = field(
        default=None, metadata=field_options(alias="routeSelection")
    )
    users_approval_on: bool | None = field(
        default=None, metadata=field_options(alias="usersApprovalOn")
    )
    users_role_allowed_to_join_external_tailnets: str | None = field(
        default=None,
        metadata=field_options(alias="usersRoleAllowedToJoinExternalTailnets"),
    )


@dataclass
# pylint: disable-next=too-many-instance-attributes
class TailscaleUser(DataClassORJSONMixin):
    """Object holding Tailscale user information."""

    user_id: str = field(metadata=field_options(alias="id"))
    display_name: str = field(metadata=field_options(alias="displayName"))
    login_name: str = field(metadata=field_options(alias="loginName"))
    profile_pic_url: str = field(
        default="", metadata=field_options(alias="profilePicUrl")
    )
    role: str = ""
    status: str = ""
    user_type: str = field(default="", metadata=field_options(alias="type"))
    created: datetime | None = None
    currently_connected: bool | None = field(
        default=None, metadata=field_options(alias="currentlyConnected")
    )
    device_count: int | None = field(
        default=None, metadata=field_options(alias="deviceCount")
    )
    last_seen: datetime | None = field(
        default=None,
        metadata=field_options(alias="lastSeen"),
    )
    tailnet_id: str | None = field(
        default=None, metadata=field_options(alias="tailnetId")
    )


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
