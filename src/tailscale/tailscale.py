"""Asynchronous Python client for the Tailscale API."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Self

from aiohttp.client import ClientError, ClientResponseError, ClientSession
from aiohttp.hdrs import METH_DELETE, METH_GET, METH_PATCH, METH_POST, METH_PUT
from yarl import URL

from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
    TailscaleNotFoundError,
)
from .models import (
    Device,
    DeviceRoutes,
    Devices,
    DNSConfiguration,
    DNSNameservers,
    DNSPreferences,
    DNSSearchPaths,
    PolicyFile,
    PolicyFileValidation,
    PolicyRulePreview,
    TailnetSettings,
    TailscaleKey,
    TailscaleUser,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

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
            if not self._get_oauth_token_task:
                self._get_oauth_token_task = asyncio.create_task(
                    self._get_oauth_token()
                )
            await self._get_oauth_token_task

    async def _get_oauth_token(self) -> None:
        """Get an OAuth token from the Tailscale API or token storage.

        Raises
        ------
            TailscaleAuthenticationError: When access token is not found
                in response or expires in less than 1 minute.

        """
        if self.token_storage:
            token_data = await self.token_storage.get_token()
            if token_data:
                access_token, expires_at = token_data
                expires_in = (expires_at - datetime.now(UTC)).total_seconds()
                if expires_in > self._token_expiry_margin:
                    self._expire_oauth_token_task = asyncio.create_task(
                        self._expire_oauth_token(expires_in)
                    )
                    self.api_key = access_token
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

        self._expire_oauth_token_task = asyncio.create_task(
            self._expire_oauth_token(expires_in)
        )
        if self.token_storage:
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
            await self.token_storage.set_token(access_token, expires_at)
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
        data: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        _use_authentication: bool = True,
        _use_form_encoding: bool = False,
    ) -> str:
        """Handle a request to the Tailscale API.

        Args:
        ----
            uri: Request URI, without '/api/v2/'.
            method: HTTP method to use.
            data: Dictionary of data to send to the Tailscale API.
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
        data: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
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
            data: Dictionary of data to send to the Tailscale API.
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
            TailscaleAuthenticationError: If the API key is invalid.
            TailscaleConnectionError: An error occurred while communicating with
                the Tailscale API.
            TailscaleNotFoundError: The requested resource does not exist.
            TailscaleError: Received an unexpected response from the Tailscale
                API.

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
                response.raise_for_status()
                body = await response.text()
        except TimeoutError as exception:
            msg = "Timeout occurred while connecting to the Tailscale API"
            raise TailscaleConnectionError(msg) from exception
        except ClientResponseError as exception:
            if exception.status in [401, 403]:
                if _use_authentication and self.api_key and self.oauth_client_id:
                    self.api_key = None
                    self._get_oauth_token_task = None
                    if self._expire_oauth_token_task:
                        self._expire_oauth_token_task.cancel()
                    self._expire_oauth_token_task = None
                msg = "Authentication to the Tailscale API failed"
                raise TailscaleAuthenticationError(msg) from exception
            if exception.status == 404:
                msg = "The requested Tailscale API resource was not found"
                raise TailscaleNotFoundError(msg) from exception
            msg = "Error occurred while connecting to the Tailscale API"
            raise TailscaleError(msg) from exception
        except (
            ClientError,
            socket.gaierror,
        ) as exception:
            msg = "Error occurred while communicating with the Tailscale API"
            raise TailscaleConnectionError(msg) from exception

        return body, response.headers

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
        are left unchanged.

        Args:
        ----
            devices_approval_on: Whether device approval is required.
            devices_auto_updates_on: Whether auto-updates are enabled.
            devices_key_duration_days: Key expiry duration in days.
            users_approval_on: Whether user approval is required.
            users_role_allowed_to_join_external_tailnets: Role allowed
                to join external tailnets ("none", "admin", "member").
            network_flow_logging_on: Whether network flow logging is on.
            regional_routing_on: Whether regional routing is on.
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
