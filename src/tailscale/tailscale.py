"""Asynchronous client for the Tailscale API."""
from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Dict, List, Optional

import async_timeout
from aiohttp import BasicAuth
from aiohttp.client import ClientError, ClientResponseError, ClientSession
from aiohttp.hdrs import METH_DELETE, METH_GET, METH_POST
from yarl import URL

from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)
from .models import (
    AuthKey,
    AuthKeyRequest,
    AuthKeys,
    Device,
    Devices,
    KeyAttributes,
    KeyCapabilities,
    Policy,
)


@dataclass
class Tailscale:
    """Main class for handling connections with the Tailscale API."""

    api_key: str = ""  # nosec
    # '-' used in a URI will assume default tailnet of api key
    tailnet: str = "-"
    oauth_client_id: str = ""  # nosec
    oauth_client_secret: str = ""  # nosec

    request_timeout: int = 8
    session: ClientSession | None = None

    _close_session: bool = False

    async def _check_access(self) -> None:
        """Initialize the Tailscale client.

        Raises:
            ValueError: when neither api_key nor oauth_client_id and
                oauth_client_secret are provided.
        """
        if (
            not self.api_key  # noqa: W503
            and not self.oauth_client_id  # noqa: W503
            and not self.oauth_client_secret  # noqa: W503
        ):
            raise ValueError(
                "Either api_key or (oauth_client_id and ",
                "oauth_client_secret) is required",
            )
        if not self.api_key:
            # set the api_key to a placeholder value so that the
            # _get_oauth_token method can set it to the actual value
            self.api_key = "pending"  # nosec
            self.api_key = await self._get_oauth_token()

    async def _get_oauth_token(self) -> str:
        """Get an OAuth token from the Tailscale API.

        Returns:
            A string with the OAuth token.
        """
        data = {
            "client_id": self.oauth_client_id,
            "client_secret": self.oauth_client_secret,
        }
        response = await self._get("oauth/token", data=data, use_auth_key=False)

        return response.get("access_token", "")

    async def _post(
        self,
        uri: str,
        *,
        data: dict[str, Any] | None = None,
        use_auth_key: bool = True,
    ) -> dict[str, Any]:
        """Make a POST request to the Tailscale API.

        Args:
            uri: Request URI, without '/api/v2/'.
            data: Dictionary of data to send to the Tailscale API.
            use_auth_key: Whether to use the API key or not.

        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Tailscale API.

        """
        return await self._request(
            uri, method=METH_POST, data=data, use_auth_key=use_auth_key
        )

    async def _delete(
        self,
        uri: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a DELETE request to the Tailscale API.

        Args:
            uri: Request URI, without '/api/v2/'.
            data: Dictionary of data to send to the Tailscale API.

        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Tailscale API.
        """
        return await self._request(uri, method=METH_DELETE, data=data)

    async def _get(
        self,
        uri: str,
        *,
        data: dict[str, Any] | None = None,
        use_auth_key: bool = True,
    ) -> dict[str, Any]:
        """Make a GET request to the Tailscale API.

        Args:
            uri: Request URI, without '/api/v2/'.
            data: Dictionary of data to send to the Tailscale API.
            use_auth_key: Whether to use the API key or not.

        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Tailscale API.
        """
        return await self._request(
            uri, method=METH_GET, data=data, use_auth_key=use_auth_key
        )

    async def _request(
        self,
        uri: str,
        *,
        method: str = METH_GET,
        data: dict[str, Any] | None = None,
        use_auth_key: bool = True,
    ) -> dict[str, Any]:
        """Handle a request to the Tailscale API.

        A generic method for sending/handling HTTP requests done against
        the Tailscale API.

        Args:
            uri: Request URI, without '/api/v2/'.
            method: HTTP Method to use.
            data: Dictionary of data to send to the Tailscale API.
            use_auth_key: Whether to use the API key or not.

        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Tailscale API.

        Raises:
            TailscaleAuthenticationError: If the API key is invalid.
            TailscaleConnectionError: An error occurred while communicating with
                the Tailscale API.
            TailscaleError: Received an unexpected response from the Tailscale
                API.
        """
        version = metadata.version(__package__)
        url = URL("https://api.tailscale.com/api/v2/").join(URL(uri))

        headers = {
            "User-Agent": f"PythonTailscale/{version}",
            "Accept": "application/json",
        }

        if self.session is None:
            self.session = ClientSession()
            self._close_session = True
        await self._check_access()

        try:
            async with async_timeout.timeout(self.request_timeout):
                auth = BasicAuth(self.api_key) if use_auth_key else None
                response = await self.session.request(
                    method,
                    url,
                    json=data,
                    auth=auth,
                    headers=headers,
                )
                response.raise_for_status()
        except asyncio.TimeoutError as exception:
            raise TailscaleConnectionError(
                "Timeout occurred while connecting to the Tailscale API"
            ) from exception
        except ClientResponseError as exception:
            if exception.status in [401, 403]:
                raise TailscaleAuthenticationError(
                    "Authentication to the Tailscale API failed"
                ) from exception
            raise TailscaleError(
                "Error occurred while connecting to the Tailscale API: ",
                f"{exception.message}",
            ) from exception
        except (
            ClientError,
            socket.gaierror,
        ) as exception:
            raise TailscaleConnectionError(
                "Error occurred while communicating with the Tailscale API"
            ) from exception

        response_data: Dict[str, Any] = await response.json(content_type=None)
        return response_data

    async def policy(self, details: bool = False) -> Policy:
        """Get policy/acl information from the Tailscale API.

        Args:
            details: Whether to include extra details in the response.
                will include the following:
                - tailnet policy file:
                    a base64-encoded string representation of the huJSON format
                - warnings:
                    array of strings for syntactically valid but nonsensical entries
                - errors:
                    an array of strings for parsing failures

        Returns:
            Returns a model of the Tailscale policy.
        """
        data = await self._get(
            f"tailnet/{self.tailnet}/acl{'?details=1' if details else ''}"
        )
        return Policy.parse_obj(data)

    async def update_policy(self, policy: Policy) -> Policy:
        """Get policy/acl information from the Tailscale API.

        Args:
            policy: The new policy to put in place.

        Returns:
            Returns the updated policy.
        """
        data = await self._post(f"tailnet/{self.tailnet}/acl", data=policy.dict())
        return Policy.parse_obj(data)

    async def devices(self, all_fields: bool = True) -> Dict[str, Device]:
        """Get devices information from the Tailscale API.

        Args:
            all_fields: Whether to include all fields in the response.

        Returns:
            Returns a dictionary of Tailscale devices.
        """
        data = await self._get(
            f"tailnet/{self.tailnet}/devices{'?fields=all' if all_fields else ''}"
        )
        return Devices.parse_obj(data).devices

    async def device(self, device_id: str, all_fields: bool = True) -> Device:
        """Get devices information from the Tailscale API.

        Args:
            device_id: The id of the device to get.
            all_fields: Whether to include all fields in the response.

        Returns:
            Returns a model of the Tailscale device.
        """
        data = await self._get(
            f"device/{device_id}{'?fields=all' if all_fields else ''}"
        )
        return Device.parse_obj(data)

    async def delete_device(self, device_id: str) -> bool:
        """Delete device from the Tailscale API.

        Args:
            device_id: The id of the device to delete.
        Returns:
            whether the device was deleted or not.
        """
        data = await self._delete(f"device/{device_id}")
        return data is None

    async def authorize_device(self, device_id: str, authorized: bool = True) -> None:
        """Get devices information from the Tailscale API.

        Args:
            device_id: The id of the device to authorize.
            authorized: Whether to authorize or deauthorize the device.
        """
        await self._post(
            f"device/{device_id}/authorized", data={"authorized": authorized}
        )

    async def tag_device(self, device_id: str, tags: List[str]) -> None:
        """Tag device with the Tailscale API.

        Args:
            device_id: The id of the device to tag.
            tags: The tags to add to the device. Each entry must start with 'tag:'.
        """
        if any([not tag.startswith("tag:") for tag in tags]):
            raise TailscaleError("Tags must start with 'tag:'")
        await self._post(f"device/{device_id}/tags", data={"tags": tags})

    async def keys(self) -> List[str]:
        """Alias for list_keys.

        Returns:
            Returns a list of Tailscale auth key ids.
        """
        return await self.list_keys()

    async def list_keys(self) -> List[str]:
        """Get keys information from the Tailscale API.

        Returns:
            Returns a list of Tailscale auth key ids.
        """

        data = await self._get(f"tailnet/{self.tailnet}/keys")
        # there is only the id attribute in the response,
        # so we just return a list of ids
        return [key["id"] for key in AuthKeys.parse_obj(data).keys]

    async def get_key(self, key_id: str) -> AuthKey:
        """Get key information from the Tailscale API.

        Args:
            key_id: The id of the key to get.

        Returns:
            Returns a model of the Tailscale auth key.
        """
        data = await self._get(f"tailnet/{self.tailnet}/keys/{key_id}")
        return AuthKey.parse_obj(data)

    async def delete_key(self, key_id: str) -> None:
        """Delete key from the Tailscale API.

        Args:
            key_id: The id of the key to delete.
        """
        await self._delete(f"tailnet/{self.tailnet}/keys/{key_id}")

    async def create_auth_key(
        self,
        request: Optional[AuthKeyRequest] = None,
        expiry_seconds: int = 86400,
        tags: Optional[List[str]] = None,
        preauthorized: bool = True,
        ephemeral: bool = False,
        reusable: bool = False,
    ) -> AuthKey:
        """Create a new tailscale auth key.

        Args:
            request: The request object to use for creating the auth key.
            tags: The tags to add to the auth key.
                Each entry must start with 'tag:'.
            preauthorized: Whether the auth key is preauthorized.
            ephemeral: Whether the auth key is ephemeral.
                Any nodes connected with this key will be removed when
                the node disconnects for too long.
            reusable: Whether the auth key is reusable.
            expiry_seconds: The number of seconds until the auth key expires.

        Returns:
            Returns a model of the created Tailscale auth key.
        """

        if tags is None:
            tags = []

        if request is None:
            key_attributes = KeyAttributes(
                tags=tags,
                preauthorized=preauthorized,
                ephemeral=ephemeral,
                reusable=reusable,
            )
            key_capabilities = KeyCapabilities(devices={"create": key_attributes})
            request = AuthKeyRequest(
                capabilities=key_capabilities, expirySeconds=expiry_seconds
            )

        data = await self._post(
            f"tailnet/{self.tailnet}/keys", data=request.dict(by_alias=True)
        )
        return AuthKey.parse_obj(data)

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()

    async def __aenter__(self) -> Tailscale:
        """Async enter.

        Returns:
            The Tailscale object.
        """
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        """Async exit.

        Args:
            _exc_info: Exec type.
        """
        await self.close()
