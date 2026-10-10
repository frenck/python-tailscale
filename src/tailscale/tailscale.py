"""Asynchronous Python client for the Tailscale API."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Self

from aiohttp.client import ClientError, ClientSession
from aiohttp.hdrs import METH_DELETE, METH_GET, METH_PATCH, METH_POST, METH_PUT
from yarl import URL

from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleNotFoundError,
    TailscalePermissionError,
    TailscaleResponseError,
    TailscaleUnauthorizedError,
)
from .models import (
    AcceptedDeviceInvite,
    AuditLog,
    AwsExternalId,
    CreatedTailnet,
    Device,
    DeviceInvite,
    DevicePostureAttributes,
    DeviceRoutes,
    Devices,
    DNSConfiguration,
    DNSNameservers,
    DNSPreferences,
    DNSSearchPaths,
    LogStreamConfiguration,
    LogStreamStatus,
    NetworkFlowLog,
    OAuthApp,
    OrganizationTailnets,
    PolicyFile,
    PolicyFileValidation,
    PolicyRulePreview,
    PostureIntegration,
    ServiceApproval,
    ServiceHost,
    TailnetContacts,
    TailnetSettings,
    TailscaleKey,
    TailscaleService,
    TailscaleUser,
    TailscaleWebhook,
    UserInvite,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .models import DevicePostureAttributeUpdate, PostureAttributeValue
    from .storage import TokenStorage


@dataclass
# pylint: disable-next=too-many-instance-attributes
class Tailscale:
    """Main class for handling connections with the Tailscale API."""

    tailnet: str = "-"
    api_key: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None

    request_timeout: int = 8
    session: ClientSession | None = None
    token_storage: TokenStorage | None = None

    _token_expiry_margin: int = 60

    _get_oauth_token_task: asyncio.Task[None] | None = None
    _expire_oauth_token_task: asyncio.Task[None] | None = None
    _rejected_oauth_token: str | None = None
    _close_session: bool = False

    async def _check_api_key(self) -> None:
        """Ensure valid authentication is available.

        Raises
        ------
            TailscaleAuthenticationError: When neither api_key nor
                oauth_client_id and oauth_client_secret are provided.

        """
        if not (
            (self.api_key and not self.oauth_client_id and not self.oauth_client_secret)
            or (not self.api_key and self.oauth_client_id and self.oauth_client_secret)
            or (
                self.api_key
                and self.oauth_client_id
                and self.oauth_client_secret
                and self._get_oauth_token_task
            )
        ):
            msg = (
                "Either api_key or oauth_client_id and oauth_client_secret "
                "are required when Tailscale client is initialized"
            )
            raise TailscaleAuthenticationError(msg)
        if not self.api_key:
            # Handle inconsistent state, e.g. manual token invalidation
            if self._expire_oauth_token_task:
                self._expire_oauth_token_task.cancel()
                self._expire_oauth_token_task = None
                if self._get_oauth_token_task:
                    self._get_oauth_token_task.cancel()
                    self._get_oauth_token_task = None
            # Get a new OAuth token if not already in progress
            task = self._get_oauth_token_task
            if task is None:
                task = self._get_oauth_token_task = asyncio.create_task(
                    self._get_oauth_token()
                )
            try:
                # Shielded, so a caller that gets cancelled, like by a timeout,
                # does not cancel getting the token for the others waiting on it.
                await asyncio.shield(task)
            except BaseException:
                # Forget a failed attempt, so the next request tries again,
                # unless another request already started a new one.
                if task.done() and self._get_oauth_token_task is task:
                    self._get_oauth_token_task = None
                raise

    async def _get_oauth_token(self) -> None:
        """Get an OAuth token from the Tailscale API or token storage.

        Raises
        ------
            TailscaleAuthenticationError: When access token is not found
                in response or expires in less than 1 minute.

        """
        if self.token_storage:
            token_data = await self.token_storage.get_token()
            # The API refused the stored token before, so it is not used again
            # even though it has not expired yet.
            if token_data and token_data[0] != self._rejected_oauth_token:
                access_token, expires_at = token_data
                expires_in = (expires_at - datetime.now(UTC)).total_seconds()
                if expires_in > self._token_expiry_margin:
                    self._use_oauth_token(access_token, expires_in)
                    return

        data = {
            "client_id": self.oauth_client_id,
            "client_secret": self.oauth_client_secret,
        }
        response = await self._request(
            "oauth/token",
            data=data,
            method=METH_POST,
            _use_authentication=False,
            _use_form_encoding=True,
        )

        json_response: dict[str, Any] = json.loads(response)
        access_token = str(json_response.get("access_token", ""))
        expires_in = float(json_response.get("expires_in", 0))
        if not access_token or not expires_in:
            msg = "Failed to get OAuth token"
            raise TailscaleAuthenticationError(msg)
        if expires_in <= self._token_expiry_margin:
            msg = "OAuth token expires in less than 1 minute"
            raise TailscaleAuthenticationError(msg)

        if self.token_storage:
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
            await self.token_storage.set_token(access_token, expires_at)
        self._use_oauth_token(access_token, expires_in)

    def _use_oauth_token(self, access_token: str, expires_in: float) -> None:
        """Start using an OAuth token, and expire it before it runs out.

        The token and its expiry are set together, without awaiting in
        between, so other requests never see one without the other.
        """
        self._expire_oauth_token_task = asyncio.create_task(
            self._expire_oauth_token(expires_in)
        )
        self.api_key = access_token

    async def _expire_oauth_token(self, expires_in: float) -> None:
        """Expire the OAuth token 1 minute before its expiration time."""
        await asyncio.sleep(expires_in - self._token_expiry_margin)
        self.api_key = None
        self._get_oauth_token_task = None
        self._expire_oauth_token_task = None

    async def _request(
        self,
        uri: str,
        *,
        method: str = METH_GET,
        data: dict[str, Any] | list[Any] | None = None,
        params: Mapping[str, str | Sequence[str]] | None = None,
        _use_authentication: bool = True,
        _use_form_encoding: bool = False,
    ) -> str:
        """Handle a request to the Tailscale API.

        Args:
        ----
            uri: Request URI, without '/api/v2/'.
            method: HTTP method to use.
            data: JSON data to send to the Tailscale API.
            params: Query string parameters to add to the request URI.
            _use_authentication: Whether to include authentication headers.
            _use_form_encoding: Whether to use form encoding instead of JSON.

        Returns:
        -------
            The response body as a string.

        """
        body, _ = await self._request_with_headers(
            uri,
            method=method,
            data=data,
            params=params,
            _use_authentication=_use_authentication,
            _use_form_encoding=_use_form_encoding,
        )
        return body

    async def _request_with_headers(  # noqa: PLR0913  # pylint: disable=too-many-arguments
        self,
        uri: str,
        *,
        method: str = METH_GET,
        data: dict[str, Any] | list[Any] | None = None,
        params: Mapping[str, str | Sequence[str]] | None = None,
        content: str | None = None,
        headers: dict[str, str] | None = None,
        _use_authentication: bool = True,
        _use_form_encoding: bool = False,
    ) -> tuple[str, Mapping[str, str]]:
        """Handle a request to the Tailscale API, and return its headers too.

        A generic method for sending/handling HTTP requests done against
        the Tailscale API.

        Args:
        ----
            uri: Request URI, without '/api/v2/'.
            method: HTTP method to use.
            data: JSON data to send to the Tailscale API.
            params: Query string parameters to add to the request URI.
            content: Raw body to send to the Tailscale API, instead of data.
            headers: Extra headers to send, like a different Accept header.
            _use_authentication: Whether to include authentication headers.
            _use_form_encoding: Whether to use form encoding instead of JSON.

        Returns:
        -------
            The response body as a string, and the response headers.

        Raises:
        ------
            TailscaleUnauthorizedError: The API did not accept the credentials.
            TailscalePermissionError: The credentials lack the permission for
                the request, or the billing plan lacks the feature.
            TailscaleNotFoundError: The requested resource does not exist.
            TailscaleResponseError: The API responded with another error.
            TailscaleConnectionError: An error occurred while communicating with
                the Tailscale API.

        """
        url = URL("https://api.tailscale.com/api/v2/").join(URL(uri))
        if params:
            url = url.update_query(params)

        request_headers: dict[str, str] = {
            "Accept": "application/json",
            **(headers or {}),
        }

        if _use_authentication:
            await self._check_api_key()
            request_headers["Authorization"] = f"Bearer {self.api_key}"

        if self.session is None:
            self.session = ClientSession()
            self._close_session = True

        try:
            async with asyncio.timeout(self.request_timeout):
                response = await self.session.request(
                    method,
                    url,
                    headers=request_headers,
                    data=content
                    if content is not None
                    else (data if _use_form_encoding else None),
                    json=data if not _use_form_encoding else None,
                )
                body = await response.text()
        except TimeoutError as exception:
            msg = "Timeout occurred while connecting to the Tailscale API"
            raise TailscaleConnectionError(msg) from exception
        except (
            ClientError,
            socket.gaierror,
        ) as exception:
            msg = "Error occurred while communicating with the Tailscale API"
            raise TailscaleConnectionError(msg) from exception

        if response.status >= 400:
            # Only a 401 means the token is no good. A 403 means the token
            # lacks the permission, or the billing plan lacks the feature,
            # which a new token does not change.
            if response.status == 401:
                self._forget_oauth_token(use_authentication=_use_authentication)
            raise _response_error(response.status, response.reason, body)

        return body, response.headers

    def _forget_oauth_token(self, *, use_authentication: bool) -> None:
        """Forget the OAuth token the API refused, so a new one is requested."""
        if not (use_authentication and self.api_key and self.oauth_client_id):
            return

        self._rejected_oauth_token = self.api_key
        self.api_key = None
        self._get_oauth_token_task = None
        if self._expire_oauth_token_task:
            self._expire_oauth_token_task.cancel()
        self._expire_oauth_token_task = None

    async def devices(self) -> dict[str, Device]:
        """Get all devices in the tailnet.

        Returns
        -------
            A dictionary of Tailscale devices, keyed by device ID.

        """
        try:
            data = await self._request(f"tailnet/{self.tailnet}/devices?fields=all")
        except TailscaleNotFoundError:
            # Since 2026-10-08, the Tailscale API fails the whole list with a 404
            # when the tailnet has devices shared in from another tailnet. The
            # default fields still work; they lack only the client connectivity.
            # https://github.com/tailscale/tailscale/issues/21721
            data = await self._request(f"tailnet/{self.tailnet}/devices?fields=default")

        return Devices.from_json(data).devices

    async def device(self, device_id: str) -> Device:
        """Get a single device by ID.

        Args:
        ----
            device_id: The ID of the device to retrieve.

        Returns:
        -------
            The device information.

        """
        data = await self._request(f"device/{device_id}?fields=all")
        return Device.from_json(data)

    async def delete_device(self, device_id: str) -> None:
        """Delete a device from the tailnet.

        Args:
        ----
            device_id: The ID of the device to delete.

        """
        await self._request(f"device/{device_id}", method=METH_DELETE)

    async def authorize_device(self, device_id: str, *, authorized: bool) -> None:
        """Authorize or deauthorize a device.

        Args:
        ----
            device_id: The ID of the device.
            authorized: Whether to authorize or deauthorize the device.

        """
        await self._request(
            f"device/{device_id}/authorized",
            method=METH_POST,
            data={"authorized": authorized},
        )

    async def expire_device_key(self, device_id: str) -> None:
        """Expire the key of a device, forcing it to re-authenticate.

        Args:
        ----
            device_id: The ID of the device.

        """
        await self._request(f"device/{device_id}/expire", method=METH_POST)

    async def set_device_key_expiry(
        self, device_id: str, *, key_expiry_disabled: bool
    ) -> None:
        """Enable or disable key expiry for a device.

        Args:
        ----
            device_id: The ID of the device.
            key_expiry_disabled: Whether to disable key expiry.

        """
        await self._request(
            f"device/{device_id}/key",
            method=METH_POST,
            data={"keyExpiryDisabled": key_expiry_disabled},
        )

    async def rename_device(self, device_id: str, *, name: str) -> None:
        """Rename a device.

        Args:
        ----
            device_id: The ID of the device.
            name: The new name for the device. Use an empty string
                to reset to the OS hostname.

        """
        await self._request(
            f"device/{device_id}/name",
            method=METH_POST,
            data={"name": name},
        )

    async def set_device_tags(self, device_id: str, *, tags: list[str]) -> None:
        """Set the ACL tags for a device.

        Args:
        ----
            device_id: The ID of the device.
            tags: The list of ACL tags (e.g., ["tag:server", "tag:prod"]).

        """
        await self._request(
            f"device/{device_id}/tags",
            method=METH_POST,
            data={"tags": tags},
        )

    async def device_routes(self, device_id: str) -> DeviceRoutes:
        """Get the subnet routes for a device.

        Args:
        ----
            device_id: The ID of the device.

        Returns:
        -------
            The advertised and enabled routes for the device.

        """
        data = await self._request(f"device/{device_id}/routes")
        return DeviceRoutes.from_json(data)

    async def set_device_routes(
        self, device_id: str, *, routes: list[str]
    ) -> DeviceRoutes:
        """Set the enabled subnet routes for a device.

        Args:
        ----
            device_id: The ID of the device.
            routes: The list of routes to enable (e.g., ["10.0.0.0/16"]).

        Returns:
        -------
            The updated advertised and enabled routes for the device.

        """
        data = await self._request(
            f"device/{device_id}/routes",
            method=METH_POST,
            data={"routes": routes},
        )
        return DeviceRoutes.from_json(data)

    async def set_device_ipv4_address(
        self, device_id: str, *, ipv4_address: str
    ) -> None:
        """Set the Tailscale IPv4 address for a device.

        Args:
        ----
            device_id: The ID of the device.
            ipv4_address: The IPv4 address to assign.

        """
        await self._request(
            f"device/{device_id}/ip",
            method=METH_POST,
            data={"ipv4": ipv4_address},
        )

    async def device_posture_attributes(
        self, device_id: str
    ) -> DevicePostureAttributes:
        """Get the posture attributes of a device.

        Args:
        ----
            device_id: The ID of the device.

        Returns:
        -------
            The posture attributes of the device, with their expiries.

        """
        data = await self._request(f"device/{device_id}/attributes")
        return DevicePostureAttributes.from_json(data)

    async def set_device_posture_attribute(  # pylint: disable=too-many-arguments
        self,
        device_id: str,
        key: str,
        *,
        value: PostureAttributeValue,
        expiry: datetime | None = None,
        comment: str | None = None,
    ) -> DevicePostureAttributes:
        """Set a custom posture attribute of a device.

        Args:
        ----
            device_id: The ID of the device.
            key: The name of the attribute, starting with "custom:".
            value: The value of the attribute.
            expiry: When Tailscale removes the attribute again.
            comment: Why the attribute is set, for the audit log.

        Returns:
        -------
            The posture attributes of the device.

        """
        payload: dict[str, Any] = {"value": value}
        if expiry is not None:
            payload["expiry"] = expiry.isoformat()
        if comment is not None:
            payload["comment"] = comment

        data = await self._request(
            f"device/{device_id}/attributes/{key}",
            method=METH_POST,
            data=payload,
        )
        return DevicePostureAttributes.from_json(data)

    async def delete_device_posture_attribute(self, device_id: str, key: str) -> None:
        """Delete a custom posture attribute of a device.

        Args:
        ----
            device_id: The ID of the device.
            key: The name of the attribute, starting with "custom:".

        """
        await self._request(f"device/{device_id}/attributes/{key}", method=METH_DELETE)

    async def update_device_posture_attributes(
        self,
        attributes: dict[str, dict[str, DevicePostureAttributeUpdate | None]],
        *,
        comment: str | None = None,
    ) -> None:
        """Set or delete custom posture attributes of several devices at once.

        Args:
        ----
            attributes: The attributes per device ID. An attribute that is
                None is deleted.
            comment: Why the attributes are changed, for the audit log.

        """
        nodes: dict[str, dict[str, dict[str, Any] | None]] = {}
        for device_id, device_attributes in attributes.items():
            nodes[device_id] = {}
            for key, update in device_attributes.items():
                if update is None:
                    nodes[device_id][key] = None
                    continue

                attribute: dict[str, Any] = {"value": update.value}
                if update.expiry is not None:
                    attribute["expiry"] = update.expiry.isoformat()
                nodes[device_id][key] = attribute

        payload: dict[str, Any] = {"nodes": nodes}
        if comment is not None:
            payload["comment"] = comment

        await self._request(
            f"tailnet/{self.tailnet}/device-attributes",
            method=METH_PATCH,
            data=payload,
        )

    async def dns_configuration(self) -> DNSConfiguration:
        """Get the full DNS configuration of the tailnet.

        Returns
        -------
            The nameservers, split DNS, search paths, and preferences.

        """
        data = await self._request(f"tailnet/{self.tailnet}/dns/configuration")
        return DNSConfiguration.from_json(data)

    async def set_dns_configuration(
        self, configuration: DNSConfiguration
    ) -> DNSConfiguration:
        """Replace the full DNS configuration of the tailnet.

        Args:
        ----
            configuration: The new DNS configuration. It replaces the current
                one as a whole; get the current one first to change a part.

        Returns:
        -------
            The new DNS configuration.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/dns/configuration",
            method=METH_POST,
            data=configuration.to_dict(),
        )
        return DNSConfiguration.from_json(data)

    async def dns_nameservers(self) -> DNSNameservers:
        """Get the DNS nameservers for the tailnet.

        Returns
        -------
            The DNS nameserver configuration.

        """
        data = await self._request(f"tailnet/{self.tailnet}/dns/nameservers")
        return DNSNameservers.from_json(data)

    async def set_dns_nameservers(self, *, dns: list[str]) -> DNSNameservers:
        """Set the DNS nameservers for the tailnet.

        Args:
        ----
            dns: The list of DNS nameserver IP addresses.

        Returns:
        -------
            The updated DNS nameserver configuration.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/dns/nameservers",
            method=METH_POST,
            data={"dns": dns},
        )
        return DNSNameservers.from_json(data)

    async def dns_preferences(self) -> DNSPreferences:
        """Get the DNS preferences for the tailnet.

        Returns
        -------
            The DNS preferences.

        """
        data = await self._request(f"tailnet/{self.tailnet}/dns/preferences")
        return DNSPreferences.from_json(data)

    async def set_dns_preferences(self, *, magic_dns: bool) -> DNSPreferences:
        """Set the DNS preferences for the tailnet.

        Args:
        ----
            magic_dns: Whether to enable MagicDNS.

        Returns:
        -------
            The updated DNS preferences.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/dns/preferences",
            method=METH_POST,
            data={"magicDNS": magic_dns},
        )
        return DNSPreferences.from_json(data)

    async def dns_search_paths(self) -> DNSSearchPaths:
        """Get the DNS search paths for the tailnet.

        Returns
        -------
            The DNS search paths.

        """
        data = await self._request(f"tailnet/{self.tailnet}/dns/searchpaths")
        return DNSSearchPaths.from_json(data)

    async def set_dns_search_paths(self, *, search_paths: list[str]) -> DNSSearchPaths:
        """Set the DNS search paths for the tailnet.

        Args:
        ----
            search_paths: The list of DNS search paths.

        Returns:
        -------
            The updated DNS search paths.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/dns/searchpaths",
            method=METH_POST,
            data={"searchPaths": search_paths},
        )
        return DNSSearchPaths.from_json(data)

    async def split_dns(self) -> dict[str, list[str]]:
        """Get the split DNS configuration for the tailnet.

        Returns
        -------
            A dictionary mapping domain names to lists of nameserver addresses.

        """
        data = await self._request(f"tailnet/{self.tailnet}/dns/split-dns")
        return json.loads(data)

    async def set_split_dns(
        self, *, split_dns: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """Replace the split DNS configuration for the tailnet.

        Args:
        ----
            split_dns: A dictionary mapping domain names to lists of
                nameserver addresses.

        Returns:
        -------
            The updated split DNS configuration.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/dns/split-dns",
            method=METH_PUT,
            data=split_dns,
        )
        return json.loads(data)

    async def update_split_dns(
        self, *, split_dns: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """Update part of the split DNS configuration for the tailnet.

        Args:
        ----
            split_dns: A dictionary mapping domain names to lists of
                nameserver addresses. Only provided domains are updated.

        Returns:
        -------
            The updated split DNS configuration.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/dns/split-dns",
            method=METH_PATCH,
            data=split_dns,
        )
        return json.loads(data)

    async def policy_file(self) -> PolicyFile:
        """Get the policy file of the tailnet.

        Returns
        -------
            The policy file as HuJSON, with its ETag.

        """
        policy, headers = await self._request_with_headers(
            f"tailnet/{self.tailnet}/acl",
            headers={"Accept": "application/hujson"},
        )
        return PolicyFile(policy=policy, etag=headers.get("ETag"))

    async def set_policy_file(
        self, policy: str, *, etag: str | None = None
    ) -> PolicyFile:
        """Set the policy file of the tailnet.

        Args:
        ----
            policy: The new policy file, as HuJSON or JSON.
            etag: The ETag of the policy file this one is based on. When the
                policy file has changed since, the API refuses the update
                and a TailscaleError is raised.

        Returns:
        -------
            The new policy file as HuJSON, with its ETag.

        """
        headers = {
            "Accept": "application/hujson",
            "Content-Type": "application/hujson",
        }
        if etag is not None:
            headers["If-Match"] = etag

        new_policy, response_headers = await self._request_with_headers(
            f"tailnet/{self.tailnet}/acl",
            method=METH_POST,
            content=policy,
            headers=headers,
        )
        return PolicyFile(policy=new_policy, etag=response_headers.get("ETag"))

    async def validate_policy_file(self, policy: str) -> PolicyFileValidation:
        """Validate a policy file, and run its tests, without saving it.

        Args:
        ----
            policy: The policy file to validate, as HuJSON or JSON.

        Returns:
        -------
            The result of the validation.

        """
        data, _ = await self._request_with_headers(
            f"tailnet/{self.tailnet}/acl/validate",
            method=METH_POST,
            content=policy,
            headers={"Content-Type": "application/hujson"},
        )
        return PolicyFileValidation.from_json(data)

    async def test_policy_file(
        self, tests: list[dict[str, Any]]
    ) -> PolicyFileValidation:
        """Run tests against the current policy file of the tailnet.

        Args:
        ----
            tests: The tests to run, in the format of the "tests" section
                of a policy file.

        Returns:
        -------
            The result of the tests.

        """
        data, _ = await self._request_with_headers(
            f"tailnet/{self.tailnet}/acl/validate",
            method=METH_POST,
            content=json.dumps(tests),
            headers={"Content-Type": "application/json"},
        )
        return PolicyFileValidation.from_json(data)

    async def preview_policy_rules(
        self, policy: str, *, preview_type: str, preview_for: str
    ) -> PolicyRulePreview:
        """Preview the rules of a policy file that apply to a resource.

        Args:
        ----
            policy: The policy file to preview, as HuJSON or JSON.
            preview_type: The type of resource, "user" for a user's email
                or "ipport" for an IP address and port.
            preview_for: The user's email, or the IP address and port.

        Returns:
        -------
            The rules that apply to the resource.

        """
        data, _ = await self._request_with_headers(
            f"tailnet/{self.tailnet}/acl/preview",
            method=METH_POST,
            params={"type": preview_type, "previewFor": preview_for},
            content=policy,
            headers={"Content-Type": "application/hujson"},
        )
        return PolicyRulePreview.from_json(data)

    async def users(
        self,
        *,
        user_type: str | None = None,
        role: str | None = None,
    ) -> list[TailscaleUser]:
        """Get the users in the tailnet.

        Args:
        ----
            user_type: Only return users of this type, like "member" or
                "shared". The API returns members only by default.
            role: Only return users with this role, like "admin".

        Returns:
        -------
            A list of Tailscale users.

        """
        params: dict[str, str] = {}
        if user_type is not None:
            params["type"] = user_type
        if role is not None:
            params["role"] = role

        data = await self._request(f"tailnet/{self.tailnet}/users", params=params)
        raw: list[dict[str, Any]] = json.loads(data).get("users", [])
        return [TailscaleUser.from_dict(user) for user in raw]

    async def user(self, user_id: str) -> TailscaleUser:
        """Get a single user by ID.

        Args:
        ----
            user_id: The ID of the user to retrieve.

        Returns:
        -------
            The user information.

        """
        data = await self._request(f"users/{user_id}")
        return TailscaleUser.from_json(data)

    async def set_user_role(self, user_id: str, *, role: str) -> None:
        """Set the role of a user.

        Args:
        ----
            user_id: The ID of the user.
            role: The new role, like "member", "admin", or "auditor".

        """
        await self._request(
            f"users/{user_id}/role",
            method=METH_POST,
            data={"role": role},
        )

    async def approve_user(self, user_id: str) -> None:
        """Approve a user that is waiting for approval to join the tailnet.

        Args:
        ----
            user_id: The ID of the user to approve.

        """
        await self._request(f"users/{user_id}/approve", method=METH_POST)

    async def suspend_user(self, user_id: str) -> None:
        """Suspend a user from the tailnet.

        Args:
        ----
            user_id: The ID of the user to suspend.

        """
        await self._request(f"users/{user_id}/suspend", method=METH_POST)

    async def restore_user(self, user_id: str) -> None:
        """Restore the access of a suspended user to the tailnet.

        Args:
        ----
            user_id: The ID of the user to restore.

        """
        await self._request(f"users/{user_id}/restore", method=METH_POST)

    async def delete_user(self, user_id: str) -> None:
        """Delete a user from the tailnet.

        Args:
        ----
            user_id: The ID of the user to delete.

        """
        await self._request(f"users/{user_id}/delete", method=METH_POST)

    async def tailnet_settings(self) -> TailnetSettings:
        """Get the settings for the tailnet.

        Returns
        -------
            The tailnet settings.

        """
        data = await self._request(f"tailnet/{self.tailnet}/settings")
        return TailnetSettings.from_json(data)

    async def update_tailnet_settings(  # noqa: PLR0913  # pylint: disable=too-many-arguments
        self,
        *,
        devices_approval_on: bool | None = None,
        devices_auto_updates_on: bool | None = None,
        devices_key_duration_days: int | None = None,
        users_approval_on: bool | None = None,
        users_role_allowed_to_join_external_tailnets: str | None = None,
        network_flow_logging_on: bool | None = None,
        regional_routing_on: bool | None = None,
        posture_identity_collection_on: bool | None = None,
        https_enabled: bool | None = None,
        route_selection: str | None = None,
        acls_externally_managed_on: bool | None = None,
        acls_external_link: str | None = None,
    ) -> None:
        """Update the settings for the tailnet.

        Only provided parameters are updated; omitted parameters
        are left unchanged. The API refuses the whole update when one of
        them is not allowed, like a feature the billing plan lacks.

        Args:
        ----
            devices_approval_on: Whether device approval is required.
            devices_auto_updates_on: Whether auto-updates are enabled.
            devices_key_duration_days: Key expiry duration in days.
            users_approval_on: Whether user approval is required.
            users_role_allowed_to_join_external_tailnets: Role allowed
                to join external tailnets ("none", "admin", "member").
            network_flow_logging_on: Whether network flow logging is on.
            regional_routing_on: Whether regional routing is on. Superseded
                by route_selection; the API refuses both in one update.
            posture_identity_collection_on: Whether posture identity
                collection is on.
            https_enabled: Whether HTTPS certificates are enabled.
            route_selection: How routes are selected ("active-passive-failover",
                "regional-routing", "regional-routing-failover").
            acls_externally_managed_on: Whether the policy file is managed
                outside of the admin console, like with GitOps.
            acls_external_link: Link to where the policy file is managed.

        """
        payload: dict[str, Any] = {}
        if devices_approval_on is not None:
            payload["devicesApprovalOn"] = devices_approval_on
        if devices_auto_updates_on is not None:
            payload["devicesAutoUpdatesOn"] = devices_auto_updates_on
        if devices_key_duration_days is not None:
            payload["devicesKeyDurationDays"] = devices_key_duration_days
        if users_approval_on is not None:
            payload["usersApprovalOn"] = users_approval_on
        if users_role_allowed_to_join_external_tailnets is not None:
            payload["usersRoleAllowedToJoinExternalTailnets"] = (
                users_role_allowed_to_join_external_tailnets
            )
        if network_flow_logging_on is not None:
            payload["networkFlowLoggingOn"] = network_flow_logging_on
        if regional_routing_on is not None:
            payload["regionalRoutingOn"] = regional_routing_on
        if posture_identity_collection_on is not None:
            payload["postureIdentityCollectionOn"] = posture_identity_collection_on
        if https_enabled is not None:
            payload["httpsEnabled"] = https_enabled
        if route_selection is not None:
            payload["routeSelection"] = route_selection
        if acls_externally_managed_on is not None:
            payload["aclsExternallyManagedOn"] = acls_externally_managed_on
        if acls_external_link is not None:
            payload["aclsExternalLink"] = acls_external_link
        await self._request(
            f"tailnet/{self.tailnet}/settings",
            method=METH_PATCH,
            data=payload,
        )

    async def keys(self) -> list[TailscaleKey]:
        """Get all keys in the tailnet.

        Returns
        -------
            A list of Tailscale keys.

        """
        data = await self._request(f"tailnet/{self.tailnet}/keys?all=true")
        raw: list[dict[str, Any]] = json.loads(data).get("keys", [])
        return [TailscaleKey.from_dict(key) for key in raw]

    async def key(self, key_id: str) -> TailscaleKey:
        """Get a single key by ID.

        Args:
        ----
            key_id: The ID of the key to retrieve.

        Returns:
        -------
            The key information.

        """
        data = await self._request(f"tailnet/{self.tailnet}/keys/{key_id}")
        return TailscaleKey.from_json(data)

    async def create_key(  # noqa: PLR0913  # pylint: disable=too-many-arguments
        self,
        *,
        key_type: str = "auth",
        description: str = "",
        expiry_seconds: int = 86400,
        reusable: bool = False,
        ephemeral: bool = False,
        preauthorized: bool = False,
        tags: list[str] | None = None,
        scopes: list[str] | None = None,
        issuer: str | None = None,
        subject: str | None = None,
        audience: str | None = None,
        custom_claim_rules: dict[str, str] | None = None,
    ) -> TailscaleKey:
        """Create a new auth key, OAuth client, or federated identity.

        Args:
        ----
            key_type: The type of key ("auth", "client", or "federated").
            description: A description for the key.
            expiry_seconds: Expiry time in seconds (default: 86400 / 24h).
                Only applies to auth keys.
            reusable: Whether the auth key can be used multiple times.
            ephemeral: Whether devices using this auth key are ephemeral.
            preauthorized: Whether devices using this auth key are
                pre-authorized.
            tags: For auth keys, the tags to assign to devices using the key.
                For OAuth clients and federated identities, the tags of the
                credential.
            scopes: The scopes of an OAuth client or federated identity.
            issuer: The issuer of the OIDC identity token of a federated
                identity.
            subject: The pattern to match the subject of the OIDC identity
                token of a federated identity against.
            audience: The audience of a federated identity; Tailscale
                generates one when left out.
            custom_claim_rules: Patterns to match other claims of the OIDC
                identity token of a federated identity against.

        Returns:
        -------
            The created key, including the secret key value.

        """
        payload: dict[str, Any] = {
            "keyType": key_type,
            "description": description,
        }
        if key_type == "auth":
            payload["expirySeconds"] = expiry_seconds
            payload["capabilities"] = {
                "devices": {
                    "create": {
                        "reusable": reusable,
                        "ephemeral": ephemeral,
                        "preauthorized": preauthorized,
                        "tags": tags or [],
                    },
                },
            }
        else:
            payload.update(
                _trust_credential_payload(
                    scopes=scopes,
                    tags=tags,
                    issuer=issuer,
                    subject=subject,
                    audience=audience,
                    custom_claim_rules=custom_claim_rules,
                )
            )

        data = await self._request(
            f"tailnet/{self.tailnet}/keys",
            method=METH_POST,
            data=payload,
        )
        return TailscaleKey.from_json(data)

    async def set_key(  # noqa: PLR0913  # pylint: disable=too-many-arguments
        self,
        key_id: str,
        *,
        key_type: str,
        scopes: list[str],
        description: str | None = None,
        tags: list[str] | None = None,
        issuer: str | None = None,
        subject: str | None = None,
        audience: str | None = None,
        custom_claim_rules: dict[str, str] | None = None,
    ) -> TailscaleKey:
        """Set the configuration of an OAuth client or federated identity.

        Args:
        ----
            key_id: The ID of the key to configure.
            key_type: The type of key ("client" or "federated").
            scopes: The scopes of the key.
            description: A description for the key.
            tags: The tags of the key.
            issuer: The issuer of the OIDC identity token of a federated
                identity.
            subject: The pattern to match the subject of the OIDC identity
                token of a federated identity against.
            audience: The audience of a federated identity.
            custom_claim_rules: Patterns to match other claims of the OIDC
                identity token of a federated identity against.

        Returns:
        -------
            The configured key.

        """
        payload: dict[str, Any] = {"keyType": key_type}
        if description is not None:
            payload["description"] = description
        payload.update(
            _trust_credential_payload(
                scopes=scopes,
                tags=tags,
                issuer=issuer,
                subject=subject,
                audience=audience,
                custom_claim_rules=custom_claim_rules,
            )
        )

        data = await self._request(
            f"tailnet/{self.tailnet}/keys/{key_id}",
            method=METH_PUT,
            data=payload,
        )
        return TailscaleKey.from_json(data)

    async def delete_key(self, key_id: str) -> None:
        """Delete a key from the tailnet.

        Args:
        ----
            key_id: The ID of the key to delete.

        """
        await self._request(
            f"tailnet/{self.tailnet}/keys/{key_id}",
            method=METH_DELETE,
        )

    async def webhooks(self) -> list[TailscaleWebhook]:
        """Get all webhooks of the tailnet.

        Returns
        -------
            A list of webhooks.

        """
        data = await self._request(f"tailnet/{self.tailnet}/webhooks")
        # The API returns null instead of an empty list when there are none.
        raw: list[dict[str, Any]] = json.loads(data).get("webhooks") or []
        return [TailscaleWebhook.from_dict(webhook) for webhook in raw]

    async def webhook(self, endpoint_id: str) -> TailscaleWebhook:
        """Get a single webhook by ID.

        Args:
        ----
            endpoint_id: The ID of the webhook.

        Returns:
        -------
            The webhook.

        """
        data = await self._request(f"webhooks/{endpoint_id}")
        return TailscaleWebhook.from_json(data)

    async def create_webhook(
        self,
        *,
        endpoint_url: str,
        subscriptions: list[str],
        provider_type: str | None = None,
    ) -> TailscaleWebhook:
        """Create a webhook in the tailnet.

        Args:
        ----
            endpoint_url: The URL that Tailscale sends the events to.
            subscriptions: The events to send, like "nodeCreated".
            provider_type: The provider of the endpoint, like "slack" or
                "discord", so the events are formatted for it.

        Returns:
        -------
            The created webhook, including its secret.

        """
        payload: dict[str, Any] = {
            "endpointUrl": endpoint_url,
            "subscriptions": subscriptions,
        }
        if provider_type is not None:
            payload["providerType"] = provider_type

        data = await self._request(
            f"tailnet/{self.tailnet}/webhooks",
            method=METH_POST,
            data=payload,
        )
        return TailscaleWebhook.from_json(data)

    async def update_webhook(
        self, endpoint_id: str, *, subscriptions: list[str]
    ) -> TailscaleWebhook:
        """Update the events a webhook is subscribed to.

        Args:
        ----
            endpoint_id: The ID of the webhook.
            subscriptions: The events to send, like "nodeCreated".

        Returns:
        -------
            The updated webhook.

        """
        data = await self._request(
            f"webhooks/{endpoint_id}",
            method=METH_PATCH,
            data={"subscriptions": subscriptions},
        )
        return TailscaleWebhook.from_json(data)

    async def delete_webhook(self, endpoint_id: str) -> None:
        """Delete a webhook.

        Args:
        ----
            endpoint_id: The ID of the webhook to delete.

        """
        await self._request(f"webhooks/{endpoint_id}", method=METH_DELETE)

    async def test_webhook(self, endpoint_id: str) -> None:
        """Send a test event to a webhook.

        The API queues the event and sends it shortly after.

        Args:
        ----
            endpoint_id: The ID of the webhook to test.

        """
        await self._request(f"webhooks/{endpoint_id}/test", method=METH_POST)

    async def rotate_webhook_secret(self, endpoint_id: str) -> TailscaleWebhook:
        """Rotate the secret a webhook signs its events with.

        Args:
        ----
            endpoint_id: The ID of the webhook.

        Returns:
        -------
            The webhook, including its new secret.

        """
        data = await self._request(f"webhooks/{endpoint_id}/rotate", method=METH_POST)
        return TailscaleWebhook.from_json(data)

    async def services(self) -> list[TailscaleService]:
        """Get all Tailscale Services of the tailnet.

        Returns
        -------
            A list of Services.

        """
        data = await self._request(f"tailnet/{self.tailnet}/services")
        raw: list[dict[str, Any]] = json.loads(data).get("vipServices") or []
        return [TailscaleService.from_dict(service) for service in raw]

    async def service(self, name: str) -> TailscaleService:
        """Get a single Tailscale Service by name.

        Args:
        ----
            name: The name of the Service, like "svc:example".

        Returns:
        -------
            The Service.

        """
        data = await self._request(f"tailnet/{self.tailnet}/services/{name}")
        return TailscaleService.from_json(data)

    async def set_service(
        self, service: TailscaleService, *, name: str | None = None
    ) -> TailscaleService:
        """Create or update a Tailscale Service.

        Args:
        ----
            service: The Service to create, or the new details of the Service.
            name: The current name of the Service, to rename it to the name
                of the given Service. Defaults to the name of the Service.

        Returns:
        -------
            The created or updated Service.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/services/{name or service.name}",
            method=METH_PUT,
            data=service.to_dict(),
        )
        return TailscaleService.from_json(data)

    async def delete_service(self, name: str) -> None:
        """Delete a Tailscale Service.

        Args:
        ----
            name: The name of the Service to delete.

        """
        await self._request(
            f"tailnet/{self.tailnet}/services/{name}", method=METH_DELETE
        )

    async def service_hosts(self, name: str) -> list[ServiceHost]:
        """Get the devices that host a Tailscale Service.

        Args:
        ----
            name: The name of the Service.

        Returns:
        -------
            A list of the devices hosting the Service.

        """
        data = await self._request(f"tailnet/{self.tailnet}/services/{name}/devices")
        raw: list[dict[str, Any]] = json.loads(data).get("hosts") or []
        return [ServiceHost.from_dict(host) for host in raw]

    async def service_approval(self, name: str, device_id: str) -> ServiceApproval:
        """Get whether a Tailscale Service is approved on a device.

        Args:
        ----
            name: The name of the Service.
            device_id: The ID of the device.

        Returns:
        -------
            The approval of the Service on the device.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/services/{name}/device/{device_id}/approved"
        )
        return ServiceApproval.from_json(data)

    async def set_service_approval(
        self, name: str, device_id: str, *, approved: bool
    ) -> ServiceApproval:
        """Approve a Tailscale Service on a device, or revoke the approval.

        Args:
        ----
            name: The name of the Service.
            device_id: The ID of the device.
            approved: Whether the Service is approved on the device.

        Returns:
        -------
            The approval of the Service on the device.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/services/{name}/device/{device_id}/approved",
            method=METH_POST,
            data={"approved": approved},
        )
        return ServiceApproval.from_json(data)

    async def device_invites(self, device_id: str) -> list[DeviceInvite]:
        """Get the invites to share a device.

        Args:
        ----
            device_id: The ID of the device.

        Returns:
        -------
            A list of invites to share the device.

        """
        data = await self._request(f"device/{device_id}/device-invites")
        return [DeviceInvite.from_dict(invite) for invite in json.loads(data) or []]

    async def create_device_invite(
        self,
        device_id: str,
        *,
        email: str | None = None,
        multi_use: bool = False,
        allow_exit_node: bool = False,
    ) -> DeviceInvite:
        """Create an invite to share a device.

        Args:
        ----
            device_id: The ID of the device to share.
            email: Who to email the invite to. Without it, share the invite
                URL of the returned invite yourself.
            multi_use: Whether the invite can be accepted more than once.
            allow_exit_node: Whether the invited user can use the device as
                an exit node.

        Returns:
        -------
            The created invite.

        """
        invite: dict[str, Any] = {
            "multiUse": multi_use,
            "allowExitNode": allow_exit_node,
        }
        if email is not None:
            invite["email"] = email

        data = await self._request(
            f"device/{device_id}/device-invites",
            method=METH_POST,
            data=[invite],
        )
        return DeviceInvite.from_dict(json.loads(data)[0])

    async def device_invite(self, invite_id: str) -> DeviceInvite:
        """Get a single invite to share a device.

        Args:
        ----
            invite_id: The ID of the invite.

        Returns:
        -------
            The invite.

        """
        data = await self._request(f"device-invites/{invite_id}")
        return DeviceInvite.from_json(data)

    async def delete_device_invite(self, invite_id: str) -> None:
        """Delete an invite to share a device.

        Args:
        ----
            invite_id: The ID of the invite to delete.

        """
        await self._request(f"device-invites/{invite_id}", method=METH_DELETE)

    async def resend_device_invite(self, invite_id: str) -> None:
        """Email an invite to share a device again.

        Args:
        ----
            invite_id: The ID of an invite that was created with an email.

        """
        await self._request(f"device-invites/{invite_id}/resend", method=METH_POST)

    async def accept_device_invite(self, invite: str) -> AcceptedDeviceInvite:
        """Accept an invite to share a device into the tailnet.

        Args:
        ----
            invite: The URL of the invite, or the code at the end of it.

        Returns:
        -------
            The shared device, and who shared and accepted it.

        """
        data = await self._request(
            "device-invites/-/accept",
            method=METH_POST,
            data={"invite": invite},
        )
        return AcceptedDeviceInvite.from_json(data)

    async def user_invites(self) -> list[UserInvite]:
        """Get the open invites for users to join the tailnet.

        Returns
        -------
            A list of invites that have not been accepted yet.

        """
        data = await self._request(f"tailnet/{self.tailnet}/user-invites")
        # The API returns null instead of an empty list when there are none.
        return [UserInvite.from_dict(invite) for invite in json.loads(data) or []]

    async def create_user_invite(
        self, *, role: str | None = None, email: str | None = None
    ) -> UserInvite:
        """Create an invite for a user to join the tailnet.

        Args:
        ----
            role: The role the user gets, like "member" or "admin".
            email: Who to email the invite to. Without it, share the invite
                URL of the returned invite yourself.

        Returns:
        -------
            The created invite.

        """
        invite: dict[str, Any] = {}
        if role is not None:
            invite["role"] = role
        if email is not None:
            invite["email"] = email

        data = await self._request(
            f"tailnet/{self.tailnet}/user-invites",
            method=METH_POST,
            data=[invite],
        )
        return UserInvite.from_dict(json.loads(data)[0])

    async def user_invite(self, invite_id: str) -> UserInvite:
        """Get a single invite for a user to join the tailnet.

        Args:
        ----
            invite_id: The ID of the invite.

        Returns:
        -------
            The invite.

        """
        data = await self._request(f"user-invites/{invite_id}")
        return UserInvite.from_json(data)

    async def delete_user_invite(self, invite_id: str) -> None:
        """Delete an invite for a user to join the tailnet.

        Args:
        ----
            invite_id: The ID of the invite to delete.

        """
        await self._request(f"user-invites/{invite_id}", method=METH_DELETE)

    async def resend_user_invite(self, invite_id: str) -> None:
        """Email an invite for a user to join the tailnet again.

        Args:
        ----
            invite_id: The ID of an invite that was created with an email.

        """
        await self._request(f"user-invites/{invite_id}/resend", method=METH_POST)

    async def contacts(self) -> TailnetContacts:
        """Get the contacts of the tailnet.

        Returns
        -------
            The account, support, and security contacts.

        """
        data = await self._request(f"tailnet/{self.tailnet}/contacts")
        return TailnetContacts.from_json(data)

    async def set_contact(self, contact_type: str, *, email: str) -> None:
        """Set the email address of a contact of the tailnet.

        The API emails the new address, to verify it.

        Args:
        ----
            contact_type: The contact, "account", "support", or "security".
            email: The new email address.

        """
        await self._request(
            f"tailnet/{self.tailnet}/contacts/{contact_type}",
            method=METH_PATCH,
            data={"email": email},
        )

    async def resend_contact_verification(self, contact_type: str) -> None:
        """Email the verification of a contact of the tailnet again.

        Args:
        ----
            contact_type: The contact, "account", "support", or "security".

        """
        await self._request(
            f"tailnet/{self.tailnet}/contacts/{contact_type}/resend-verification-email",
            method=METH_POST,
        )

    async def organization_tailnets(
        self,
        organization: str = "-",
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> OrganizationTailnets:
        """Get a page of the tailnets of an organization.

        Args:
        ----
            organization: The ID of the organization; "-" is the organization
                of the credentials in use.
            limit: The maximum number of tailnets on the page.
            cursor: The cursor of a previous page, to get the next page.

        Returns:
        -------
            The page of tailnets, with the cursor of the next page.

        """
        params: dict[str, str] = {}
        if limit is not None:
            params["limit"] = str(limit)
        if cursor is not None:
            params["cursor"] = cursor

        data = await self._request(
            f"organizations/{organization}/tailnets", params=params
        )
        return OrganizationTailnets.from_json(data)

    async def create_organization_tailnet(
        self, display_name: str, *, organization: str = "-"
    ) -> CreatedTailnet:
        """Create an API-only tailnet in an organization.

        Args:
        ----
            display_name: The name of the new tailnet.
            organization: The ID of the organization; "-" is the organization
                of the credentials in use.

        Returns:
        -------
            The new tailnet, with the OAuth client for it.

        """
        data = await self._request(
            f"organizations/{organization}/tailnets",
            method=METH_POST,
            data={"displayName": display_name},
        )
        return CreatedTailnet.from_json(data)

    async def delete_tailnet(self) -> None:
        """Delete the tailnet, with all of its users, devices, and settings.

        This cannot be undone. It is meant for API-only tailnets, using
        credentials for the tailnet that is deleted.
        """
        await self._request(f"tailnet/{self.tailnet}", method=METH_DELETE)

    async def oauth_apps(self) -> list[OAuthApp]:
        """Get the OAuth apps of the tailnet.

        Returns
        -------
            A list of OAuth apps.

        """
        data = await self._request(f"tailnet/{self.tailnet}/oauth-apps")
        raw: list[dict[str, Any]] = json.loads(data).get("oauthApps") or []
        return [OAuthApp.from_dict(app) for app in raw]

    async def oauth_app(self, app_id: str) -> OAuthApp:
        """Get a single OAuth app of the tailnet.

        Args:
        ----
            app_id: The ID of the OAuth app.

        Returns:
        -------
            The OAuth app.

        """
        data = await self._request(f"tailnet/{self.tailnet}/oauth-apps/{app_id}")
        return OAuthApp.from_json(data)

    async def create_oauth_app(  # pylint: disable=too-many-arguments
        self,
        *,
        name: str,
        redirect_uris: list[str],
        scopes: list[str],
        description: str | None = None,
        allowed_node_attributes: list[str] | None = None,
    ) -> OAuthApp:
        """Create an OAuth app in the tailnet.

        Args:
        ----
            name: The name of the OAuth app.
            redirect_uris: The redirect URIs allowed in the authorization
                code flow.
            scopes: The scopes the OAuth app gets.
            description: What the OAuth app is for.
            allowed_node_attributes: The custom device attributes the OAuth
                app may set.

        Returns:
        -------
            The created OAuth app, including its client secret, which the API
            does not return later.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/oauth-apps",
            method=METH_POST,
            data=_oauth_app_payload(
                name=name,
                redirect_uris=redirect_uris,
                scopes=scopes,
                description=description,
                allowed_node_attributes=allowed_node_attributes,
            ),
        )
        return OAuthApp.from_json(data)

    async def set_oauth_app(  # noqa: PLR0913  # pylint: disable=too-many-arguments
        self,
        app_id: str,
        *,
        name: str,
        redirect_uris: list[str],
        scopes: list[str],
        description: str | None = None,
        allowed_node_attributes: list[str] | None = None,
    ) -> OAuthApp:
        """Set the configuration of an OAuth app of the tailnet.

        This keeps the client secret of the OAuth app.

        Args:
        ----
            app_id: The ID of the OAuth app.
            name: The name of the OAuth app.
            redirect_uris: The redirect URIs allowed in the authorization
                code flow.
            scopes: The scopes the OAuth app gets.
            description: What the OAuth app is for.
            allowed_node_attributes: The custom device attributes the OAuth
                app may set.

        Returns:
        -------
            The configured OAuth app.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/oauth-apps/{app_id}",
            method=METH_PUT,
            data=_oauth_app_payload(
                name=name,
                redirect_uris=redirect_uris,
                scopes=scopes,
                description=description,
                allowed_node_attributes=allowed_node_attributes,
            ),
        )
        return OAuthApp.from_json(data)

    async def delete_oauth_app(self, app_id: str) -> None:
        """Delete an OAuth app of the tailnet.

        Args:
        ----
            app_id: The ID of the OAuth app to delete.

        """
        await self._request(
            f"tailnet/{self.tailnet}/oauth-apps/{app_id}", method=METH_DELETE
        )

    async def log_stream_configuration(self, log_type: str) -> LogStreamConfiguration:
        """Get where a type of logs of the tailnet is streamed to.

        Args:
        ----
            log_type: The type of logs, "configuration" or "network".

        Returns:
        -------
            The log streaming configuration.

        """
        data = await self._request(f"tailnet/{self.tailnet}/logging/{log_type}/stream")
        return LogStreamConfiguration.from_json(data)

    async def set_log_stream_configuration(
        self, log_type: str, configuration: LogStreamConfiguration
    ) -> None:
        """Set where a type of logs of the tailnet is streamed to.

        Args:
        ----
            log_type: The type of logs, "configuration" or "network".
            configuration: The log streaming configuration.

        """
        await self._request(
            f"tailnet/{self.tailnet}/logging/{log_type}/stream",
            method=METH_PUT,
            data=configuration.to_dict(),
        )

    async def disable_log_streaming(self, log_type: str) -> None:
        """Stop streaming a type of logs of the tailnet.

        Args:
        ----
            log_type: The type of logs, "configuration" or "network".

        """
        await self._request(
            f"tailnet/{self.tailnet}/logging/{log_type}/stream",
            method=METH_DELETE,
        )

    async def log_stream_status(self, log_type: str) -> LogStreamStatus:
        """Get how the streaming of a type of logs of the tailnet goes.

        Args:
        ----
            log_type: The type of logs, "configuration" or "network".

        Returns:
        -------
            The log streaming status.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/logging/{log_type}/stream/status"
        )
        return LogStreamStatus.from_json(data)

    async def aws_external_id(self, *, reusable: bool = False) -> AwsExternalId:
        """Get an AWS external ID, to stream logs to Amazon S3 with a role.

        Args:
        ----
            reusable: Whether later calls that are reusable too get the same
                external ID back, as long as it is not linked to an AWS
                account yet.

        Returns:
        -------
            The AWS external ID, with the AWS account ID of Tailscale.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/aws-external-id",
            method=METH_POST,
            data={"reusable": reusable},
        )
        return AwsExternalId.from_json(data)

    async def validate_aws_trust_policy(
        self, external_id: str, *, role_arn: str
    ) -> None:
        """Validate that Tailscale can assume an AWS IAM role.

        Raises a TailscaleResponseError, with the reason, when it cannot.

        Args:
        ----
            external_id: The AWS external ID.
            role_arn: The ARN of the AWS IAM role.

        """
        await self._request(
            f"tailnet/{self.tailnet}/aws-external-id/{external_id}"
            "/validate-aws-trust-policy",
            method=METH_POST,
            data={"roleArn": role_arn},
        )

    async def configuration_audit_logs(  # pylint: disable=too-many-arguments
        self,
        *,
        start: datetime,
        end: datetime,
        actors: list[str] | None = None,
        targets: list[str] | None = None,
        events: list[str] | None = None,
    ) -> list[AuditLog]:
        """Get the configuration changes of the tailnet in a period of time.

        Args:
        ----
            start: The start of the period.
            end: The end of the period.
            actors: Only return changes by these actors, by ID, or by a part
                of their login or display name prefixed with "~", like "~bob".
            targets: Only return changes to targets that match any part of
                these strings.
            events: Only return these events, like "NODE.CREATE" or
                "TAILNET.UPDATE.ACL".

        Returns:
        -------
            The configuration changes, oldest first.

        """
        params: dict[str, str | list[str]] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        if actors is not None:
            params["actor"] = actors
        if targets is not None:
            params["target"] = targets
        if events is not None:
            params["event"] = events

        data = await self._request(
            f"tailnet/{self.tailnet}/logging/configuration", params=params
        )
        raw: list[dict[str, Any]] = json.loads(data).get("logs") or []
        return [AuditLog.from_dict(log) for log in raw]

    async def network_flow_logs(
        self, *, start: datetime, end: datetime
    ) -> list[NetworkFlowLog]:
        """Get the network flows of the tailnet in a period of time.

        Args:
        ----
            start: The start of the period.
            end: The end of the period.

        Returns:
        -------
            The network flows, oldest first.

        """
        data = await self._request(
            f"tailnet/{self.tailnet}/logging/network",
            params={"start": start.isoformat(), "end": end.isoformat()},
        )
        raw: list[dict[str, Any]] = json.loads(data).get("logs") or []
        return [NetworkFlowLog.from_dict(log) for log in raw]

    async def posture_integrations(self) -> list[PostureIntegration]:
        """Get the integrations with device posture providers.

        Returns
        -------
            A list of posture integrations.

        """
        data = await self._request(f"tailnet/{self.tailnet}/posture/integrations")
        raw: list[dict[str, Any]] = json.loads(data).get("integrations") or []
        return [PostureIntegration.from_dict(integration) for integration in raw]

    async def posture_integration(self, integration_id: str) -> PostureIntegration:
        """Get a single integration with a device posture provider.

        Args:
        ----
            integration_id: The ID of the integration.

        Returns:
        -------
            The posture integration.

        """
        data = await self._request(f"posture/integrations/{integration_id}")
        return PostureIntegration.from_json(data)

    async def create_posture_integration(  # pylint: disable=too-many-arguments
        self,
        *,
        provider: str,
        client_secret: str,
        client_id: str | None = None,
        cloud_id: str | None = None,
        tenant_id: str | None = None,
    ) -> PostureIntegration:
        """Create an integration with a device posture provider.

        Args:
        ----
            provider: The provider, like "falcon", "intune", or "kandji".
            client_secret: The secret to authenticate with the provider.
            client_id: The ID of the client at the provider.
            cloud_id: Which cloud of the provider to integrate with.
            tenant_id: The Microsoft Intune directory (tenant) ID.

        Returns:
        -------
            The created posture integration.

        """
        payload = _posture_integration_payload(
            client_secret=client_secret,
            client_id=client_id,
            cloud_id=cloud_id,
            tenant_id=tenant_id,
        )
        payload["provider"] = provider

        data = await self._request(
            f"tailnet/{self.tailnet}/posture/integrations",
            method=METH_POST,
            data=payload,
        )
        return PostureIntegration.from_json(data)

    async def update_posture_integration(  # pylint: disable=too-many-arguments
        self,
        integration_id: str,
        *,
        client_secret: str | None = None,
        client_id: str | None = None,
        cloud_id: str | None = None,
        tenant_id: str | None = None,
    ) -> PostureIntegration:
        """Update an integration with a device posture provider.

        Only the given values are updated; leave out the client secret to
        keep the current one.

        Args:
        ----
            integration_id: The ID of the integration.
            client_secret: The new secret to authenticate with the provider.
            client_id: The ID of the client at the provider.
            cloud_id: Which cloud of the provider to integrate with.
            tenant_id: The Microsoft Intune directory (tenant) ID.

        Returns:
        -------
            The updated posture integration.

        """
        data = await self._request(
            f"posture/integrations/{integration_id}",
            method=METH_PATCH,
            data=_posture_integration_payload(
                client_secret=client_secret,
                client_id=client_id,
                cloud_id=cloud_id,
                tenant_id=tenant_id,
            ),
        )
        return PostureIntegration.from_json(data)

    async def delete_posture_integration(self, integration_id: str) -> None:
        """Delete an integration with a device posture provider.

        Args:
        ----
            integration_id: The ID of the integration to delete.

        """
        await self._request(
            f"posture/integrations/{integration_id}", method=METH_DELETE
        )

    async def close(self) -> None:
        """Close open client session and cancel background tasks."""
        if self.session and self._close_session:
            await self.session.close()
        if self._get_oauth_token_task:
            self._get_oauth_token_task.cancel()
        if self._expire_oauth_token_task:
            self._expire_oauth_token_task.cancel()

    async def __aenter__(self) -> Self:
        """Async enter.

        Returns
        -------
            The Tailscale object.

        """
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Async exit.

        Args:
        ----
            _exc_info: Exception type, value, and traceback.

        """
        await self.close()


def _trust_credential_payload(  # noqa: PLR0913  # pylint: disable=too-many-arguments
    *,
    scopes: list[str] | None,
    tags: list[str] | None,
    issuer: str | None,
    subject: str | None,
    audience: str | None,
    custom_claim_rules: dict[str, str] | None,
) -> dict[str, Any]:
    """Build the payload fields of an OAuth client or federated identity.

    Fields that are None are left out, so the API applies its defaults.

    Returns
    -------
        The payload fields.

    """
    fields: dict[str, Any] = {
        "scopes": scopes,
        "tags": tags,
        "issuer": issuer,
        "subject": subject,
        "audience": audience,
        "customClaimRules": custom_claim_rules,
    }
    return {name: value for name, value in fields.items() if value is not None}


def _response_error(
    status: int, http_reason: str | None, body: str
) -> TailscaleResponseError:
    """Build the error for a response with an error status.

    The Tailscale API explains errors in the "message" of a JSON body; fall
    back to the HTTP reason when it does not.

    Returns
    -------
        The error that fits the status.

    """
    reason = http_reason or f"HTTP {status}"
    try:
        message = json.loads(body).get("message")
    except (AttributeError, ValueError):
        message = None
    if isinstance(message, str) and message:
        reason = message

    if status == 401:
        return TailscaleUnauthorizedError(status, reason)
    if status == 403:
        return TailscalePermissionError(status, reason)
    if status == 404:
        return TailscaleNotFoundError(status, reason)
    return TailscaleResponseError(status, reason)


def _oauth_app_payload(
    *,
    name: str,
    redirect_uris: list[str],
    scopes: list[str],
    description: str | None,
    allowed_node_attributes: list[str] | None,
) -> dict[str, Any]:
    """Build the payload of an OAuth app.

    Returns
    -------
        The payload.

    """
    payload: dict[str, Any] = {
        "name": name,
        "redirectURIs": redirect_uris,
        "scopes": scopes,
    }
    if description is not None:
        payload["description"] = description
    if allowed_node_attributes is not None:
        payload["allowedNodeAttributes"] = allowed_node_attributes
    return payload


def _posture_integration_payload(
    *,
    client_secret: str | None,
    client_id: str | None,
    cloud_id: str | None,
    tenant_id: str | None,
) -> dict[str, Any]:
    """Build the payload fields of a posture integration.

    Fields that are None are left out, so the API keeps their current value.

    Returns
    -------
        The payload fields.

    """
    fields: dict[str, Any] = {
        "clientSecret": client_secret,
        "clientId": client_id,
        "cloudId": cloud_id,
        "tenantId": tenant_id,
    }
    return {name: value for name, value in fields.items() if value is not None}
