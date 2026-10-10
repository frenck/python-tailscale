"""Asynchronous Python client for the Tailscale API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeAlias

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.orjson import DataClassORJSONMixin


class _LenientModel(DataClassORJSONMixin):
    """Base for models of responses that use null or "" for unset values.

    Those values are left out before parsing, so the defaults of the model
    apply instead of failing on, or keeping, the null or empty value.
    """

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Leave out null and empty values, so the defaults apply.

        Args:
        ----
            d: The raw API response data.

        Returns:
        -------
            The data without null and empty values.

        """
        return {key: value for key, value in d.items() if value not in (None, "")}


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


PostureAttributeValue: TypeAlias = bool | int | float | str


@dataclass
class DevicePostureAttributes(DataClassORJSONMixin):
    """Object holding the posture attributes of a device.

    Attributes in the "custom:" namespace are managed by users; the others,
    like "node:os", are set by Tailscale.
    """

    attributes: dict[str, PostureAttributeValue] = field(default_factory=dict)
    expiries: dict[str, datetime] = field(default_factory=dict)


@dataclass
class DevicePostureAttributeUpdate:
    """Object holding a new value of a posture attribute, for a batch update."""

    value: PostureAttributeValue
    expiry: datetime | None = None


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


# pylint: disable-next=too-few-public-methods
class _RequestBodyConfig(BaseConfig):
    """Send a model with the names the API uses, leaving out unset values."""

    serialize_by_alias = True
    omit_none = True


@dataclass
class DNSResolver(DataClassORJSONMixin):
    """Object holding a DNS resolver of the DNS configuration."""

    address: str
    use_with_exit_node: bool | None = field(
        default=None, metadata=field_options(alias="useWithExitNode")
    )

    Config = _RequestBodyConfig


@dataclass
class DNSConfigurationPreferences(DataClassORJSONMixin):
    """Object holding the preferences of the DNS configuration."""

    magic_dns: bool | None = field(
        default=None, metadata=field_options(alias="magicDNS")
    )
    override_local_dns: bool | None = field(
        default=None, metadata=field_options(alias="overrideLocalDNS")
    )

    Config = _RequestBodyConfig


@dataclass
class DNSConfiguration(DataClassORJSONMixin):
    """Object holding the full DNS configuration of a tailnet."""

    nameservers: list[DNSResolver] = field(default_factory=list)
    preferences: DNSConfigurationPreferences = field(
        default_factory=DNSConfigurationPreferences
    )
    search_paths: list[str] = field(
        default_factory=list, metadata=field_options(alias="searchPaths")
    )
    split_dns: dict[str, list[DNSResolver]] = field(
        default_factory=dict, metadata=field_options(alias="splitDNS")
    )

    Config = _RequestBodyConfig

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Leave out null values, so the defaults apply.

        Args:
        ----
            d: The raw API response data.

        Returns:
        -------
            The data without null values.

        """
        d = {key: value for key, value in d.items() if value is not None}
        if "splitDNS" in d:
            d["splitDNS"] = {
                domain: resolvers or [] for domain, resolvers in d["splitDNS"].items()
            }
        return d


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


@dataclass
class PolicyFile:
    """Object holding the policy file of a tailnet.

    The policy is kept as HuJSON text, so its comments and formatting
    survive a round trip. The ETag identifies this version of the policy
    file; pass it along when setting the policy file, to avoid overwriting
    changes made by someone else in the meantime.
    """

    policy: str
    etag: str | None = None


@dataclass
class PolicyTestResult(_LenientModel):
    """Object holding the result of a failing policy file test."""

    user: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PolicyFileValidation(_LenientModel):
    """Object holding the result of validating or testing a policy file."""

    message: str | None = None
    data: list[PolicyTestResult] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        """Return whether the policy file is valid and its tests pass."""
        return self.message is None


@dataclass
class PolicyRuleMatch(_LenientModel):
    """Object holding a policy file rule that applies to a resource."""

    users: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    postures: list[str] = field(default_factory=list)
    line_number: int | None = field(
        default=None, metadata=field_options(alias="lineNumber")
    )


@dataclass
class PolicyRulePreview(_LenientModel):
    """Object holding the policy file rules that apply to a resource."""

    preview_type: str = field(metadata=field_options(alias="type"))
    preview_for: str = field(metadata=field_options(alias="previewFor"))
    matches: list[PolicyRuleMatch] = field(default_factory=list)


@dataclass
# pylint: disable-next=too-many-instance-attributes
class TailscaleWebhook(_LenientModel):
    """Object holding a webhook of a tailnet."""

    endpoint_id: str = field(metadata=field_options(alias="endpointId"))
    endpoint_url: str = field(metadata=field_options(alias="endpointUrl"))
    created: datetime | None = None
    creator_login_name: str | None = field(
        default=None, metadata=field_options(alias="creatorLoginName")
    )
    last_modified: datetime | None = field(
        default=None, metadata=field_options(alias="lastModified")
    )
    provider_type: str | None = field(
        default=None, metadata=field_options(alias="providerType")
    )
    secret: str | None = None
    subscriptions: list[str] = field(default_factory=list)


@dataclass
class TailscaleService(_LenientModel):
    """Object holding a Tailscale Service."""

    name: str
    addrs: list[str] = field(default_factory=list)
    comment: str | None = None
    display_name: str | None = field(
        default=None, metadata=field_options(alias="displayName")
    )
    ports: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    Config = _RequestBodyConfig


@dataclass
class ServiceHost(DataClassORJSONMixin):
    """Object holding a device that hosts a Tailscale Service."""

    stable_node_id: str = field(metadata=field_options(alias="stableNodeID"))
    approval_level: str | None = field(
        default=None, metadata=field_options(alias="approvalLevel")
    )
    configured: str | None = None


@dataclass
class ServiceApproval(DataClassORJSONMixin):
    """Object holding whether a Tailscale Service is approved on a device."""

    approved: bool = False
    auto_approved: bool = field(
        default=False, metadata=field_options(alias="autoApproved")
    )


@dataclass
class InviteUser(_LenientModel):
    """Object holding a user involved in an invite."""

    user_id: int | str = field(metadata=field_options(alias="id"))
    display_name: str | None = field(
        default=None, metadata=field_options(alias="displayName")
    )
    login_name: str | None = field(
        default=None, metadata=field_options(alias="loginName")
    )
    profile_pic_url: str | None = field(
        default=None,
        metadata=field_options(alias="profilePicUrl"),
    )

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Leave out empty values, and accept both spellings of the picture.

        The API spells it "profilePicUrl" on device invites, and
        "profilePicURL" when accepting one.

        Args:
        ----
            d: The raw API response data.

        Returns:
        -------
            The adjusted data ready for deserialization.

        """
        d = super().__pre_deserialize__(d)
        if "profilePicURL" in d:
            d.setdefault("profilePicUrl", d.pop("profilePicURL"))
        return d


@dataclass
# pylint: disable-next=too-many-instance-attributes
class DeviceInvite(_LenientModel):
    """Object holding an invite to share a device."""

    invite_id: str = field(metadata=field_options(alias="id"))
    accepted: bool = False
    accepted_by: InviteUser | None = field(
        default=None, metadata=field_options(alias="acceptedBy")
    )
    allow_exit_node: bool = field(
        default=False, metadata=field_options(alias="allowExitNode")
    )
    created: datetime | None = None
    device_id: int | None = field(
        default=None, metadata=field_options(alias="deviceId")
    )
    email: str | None = None
    invite_url: str | None = field(
        default=None, metadata=field_options(alias="inviteUrl")
    )
    last_email_sent_at: datetime | None = field(
        default=None, metadata=field_options(alias="lastEmailSentAt")
    )
    multi_use: bool = field(default=False, metadata=field_options(alias="multiUse"))
    sharer_id: int | None = field(
        default=None, metadata=field_options(alias="sharerId")
    )
    tailnet_id: int | None = field(
        default=None, metadata=field_options(alias="tailnetId")
    )


@dataclass
class SharedDevice(_LenientModel):
    """Object holding a device shared through an accepted invite."""

    device_id: str = field(metadata=field_options(alias="id"))
    fqdn: str | None = None
    include_exit_node: bool = field(
        default=False, metadata=field_options(alias="includeExitNode")
    )
    ipv4: str | None = None
    ipv6: str | None = None
    name: str | None = None
    os: str | None = None


@dataclass
class AcceptedDeviceInvite(_LenientModel):
    """Object holding the result of accepting an invite to share a device."""

    device: SharedDevice
    accepted_by: InviteUser | None = field(
        default=None, metadata=field_options(alias="acceptedBy")
    )
    sharer: InviteUser | None = None


@dataclass
class UserInvite(_LenientModel):
    """Object holding an invite for a user to join the tailnet."""

    invite_id: str = field(metadata=field_options(alias="id"))
    role: str
    email: str | None = None
    invite_url: str | None = field(
        default=None, metadata=field_options(alias="inviteUrl")
    )
    inviter_id: int | None = field(
        default=None, metadata=field_options(alias="inviterId")
    )
    last_email_sent_at: datetime | None = field(
        default=None, metadata=field_options(alias="lastEmailSentAt")
    )
    tailnet_id: int | None = field(
        default=None, metadata=field_options(alias="tailnetId")
    )
