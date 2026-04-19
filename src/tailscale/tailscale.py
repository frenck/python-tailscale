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
)
from .models import (
    Device,
    DeviceRoutes,
    Devices,
    DNSNameservers,
    DNSPreferences,
    DNSSearchPaths,
)

if TYPE_CHECKING:
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
        _use_authentication: bool = True,
        _use_form_encoding: bool = False,
    ) -> str:
        """Handle a request to the Tailscale API.

        A generic method for sending/handling HTTP requests done against
        the Tailscale API.

        Args:
        ----
            uri: Request URI, without '/api/v2/'.
            method: HTTP method to use.
            data: Dictionary of data to send to the Tailscale API.
            _use_authentication: Whether to include authentication headers.
            _use_form_encoding: Whether to use form encoding instead of JSON.

        Returns:
        -------
            The response body as a string.

        Raises:
        ------
            TailscaleAuthenticationError: If the API key is invalid.
            TailscaleConnectionError: An error occurred while communicating with
                the Tailscale API.
            TailscaleError: Received an unexpected response from the Tailscale
                API.

        """
        url = URL("https://api.tailscale.com/api/v2/").join(URL(uri))

        headers: dict[str, str] = {
            "Accept": "application/json",
        }

        if _use_authentication:
            await self._check_api_key()
            headers["Authorization"] = f"Bearer {self.api_key}"

        if self.session is None:
            self.session = ClientSession()
            self._close_session = True

        try:
            async with asyncio.timeout(self.request_timeout):
                response = await self.session.request(
                    method,
                    url,
                    headers=headers,
                    data=data if _use_form_encoding else None,
                    json=data if not _use_form_encoding else None,
                )
                response.raise_for_status()
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
            msg = "Error occurred while connecting to the Tailscale API"
            raise TailscaleError(msg) from exception
        except (
            ClientError,
            socket.gaierror,
        ) as exception:
            msg = "Error occurred while communicating with the Tailscale API"
            raise TailscaleConnectionError(msg) from exception

        return await response.text()

    async def devices(self) -> dict[str, Device]:
        """Get all devices in the tailnet.

        Returns
        -------
            A dictionary of Tailscale devices, keyed by device ID.

        """
        data = await self._request(f"tailnet/{self.tailnet}/devices?fields=all")
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
