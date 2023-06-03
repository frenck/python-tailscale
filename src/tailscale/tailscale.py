"""Asynchronous client for the Tailscale API."""
from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from importlib import metadata
from typing import Any, List

import async_timeout
from aiohttp import BasicAuth
from aiohttp.client import ClientError, ClientResponseError, ClientSession
from aiohttp.hdrs import METH_GET, METH_POST, METH_DELETE
from yarl import URL

from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)
from .models import (
    Device, 
    Devices, 
    Policy, 
    AuthKey,
    AuthKeys,
    AuthKeyRequest, 
    KeyAttributes, 
    KeyCapabilities, 
)


@dataclass
class Tailscale:
    """Main class for handling connections with the Tailscale API."""

    api_key: str
    tailnet: str = "-" # default tailnet of api key

    request_timeout: int = 8
    session: ClientSession | None = None

    _close_session: bool = False

    async def _post(
        self,
        uri: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Wrapper for POST requests to the Tailscale API."""
        return await self._request(uri, method=METH_POST, data=data)
    
    async def _delete(
        self,
        uri: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Wrapper for DELETE requests to the Tailscale API."""
        return await self._request(uri, method=METH_DELETE, data=data)
    
    async def _get(
        self,
        uri: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Wrapper for GET requests to the Tailscale API."""
        return await self._request(uri, method=METH_GET, data=data)

    async def _request(
        self,
        uri: str,
        *,
        method: str = METH_GET,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handle a request to the Tailscale API.

        A generic method for sending/handling HTTP requests done against
        the Tailscale API.

        Args:
            uri: Request URI, without '/api/v2/'.
            method: HTTP Method to use.
            data: Dictionary of data to send to the Tailscale API.

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

        try:
            async with async_timeout.timeout(self.request_timeout):
                response = await self.session.request(
                    method,
                    url,
                    json=data,
                    auth=BasicAuth(self.api_key),
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
                f"Error occurred while connecting to the Tailscale API: {exception.message}"
            ) from exception
        except (
            ClientError,
            socket.gaierror,
        ) as exception:
            raise TailscaleConnectionError(
                "Error occurred while communicating with the Tailscale API"
            ) from exception

        response_data: dict[str, Any] = await response.json(content_type=None)
        return response_data

    async def policy(self, details=False) -> Policy:
        """Get policy/acl information from the Tailscale API.

        Returns:
            Returns a model of the Tailscale policy.
        """
        data = await self._get(f"tailnet/{self.tailnet}/acl{'?details=1' if details else ''}")
        return Policy.parse_obj(data)

    async def update_policy(self, policy: Policy) -> Policy:
        """Get policy/acl information from the Tailscale API.

        Returns:
            Returns the updated policy.
        """
        data = await self._post(f"tailnet/{self.tailnet}/acl", data=policy.dict())
        return Policy.parse_obj(data)

    async def devices(self, allFields=True) -> dict[str, Device]:
        """Get devices information from the Tailscale API.

        Returns:
            Returns a dictionary of Tailscale devices.
        """
        data = await self._get(f"tailnet/{self.tailnet}/devices{'?fields=all' if allFields else ''}")
        return Devices.parse_obj(data).devices
    
    async def device(self, device_id: str, allFields=True) -> Device:
        """Get devices information from the Tailscale API.

        Returns:
            Returns a model of the Tailscale device.
        """
        data = await self._get(f"device/{device_id}{'?fields=all' if allFields else ''}")
        return Device.parse_obj(data)
    
    async def delete_device(self, device_id: str) -> None:
        """Delete device from the Tailscale API."""
        await self._delete(f"device/{device_id}")
    
    async def authorize_device(self, device_id: str, authorized=True) -> bool:
        """Get devices information from the Tailscale API.

        Returns:
            Returns a model of the Tailscale device.
        """
        await self._post(f"device/{device_id}/authorized", data={"authorized": authorized})
        return True

    async def tag_device(self, device_id: str, tags: List[str]=[]) -> None:
        """Tag device with the Tailscale API.
        Params:
            device_id: The id of the device to tag.
            tags: The tags to add to the device. Each entry must start with 'tag:'.

        Returns:
            Returns a model of the deleted Tailscale device.
        """
        await self._post(f"device/{device_id}/tags", data={"tags": tags})
    
    async def keys(self) -> List[str]:
        """Alias for list_keys."""
        return self.list_keys()
    
    async def list_keys(self) -> List[str]:
        """Get keys information from the Tailscale API.
        
        Returns:
            Returns a list of Tailscale auth key ids."""

        data = await self._get(f"tailnet/{self.tailnet}/keys")
        # there is only the id attribute in the response, so we just return a list of ids
        return [ key['id'] for key in AuthKeys.parse_obj(data).keys ]
    
    async def get_key(self, key_id: str) -> AuthKey:
        """Get key information from the Tailscale API."""
        data = await self._get(f"tailnet/{self.tailnet}/keys/{key_id}")
        return AuthKey.parse_obj(data)
    
    async def delete_key(self, key_id: str) -> AuthKey:
        """Deletes key from the Tailscale API."""
        await self._delete(f"tailnet/{self.tailnet}/keys/{key_id}")
    
    async def create_auth_key(self, 
        request: Optional[AuthKeyRequest] = None,
        expiry_seconds: int = 86400,
        tags: List[str] = [],
        preauthorized: bool = True, 
        ephemeral: bool = False, 
        reusable: bool = False
    ) -> AuthKey:
        """Creates a new tailscale auth key.
        
        Params:
            request: The request object to use for creating the auth key.
            tags: The tags to add to the auth key. Each entry must start with 'tag:'.
            preauthorized: Whether the auth key is preauthorized.
            ephemeral: Whether the auth key is ephemeral. Any nodes connected with this key will be removed when the node disconnects.
            reusable: Whether the auth key is reusable.
            expiry_seconds: The number of seconds until the auth key expires.
            
        Returns:
            Returns a model of the created Tailscale auth key."""

        if request is None:
            key_attributes = KeyAttributes(tags=tags, preauthorized=preauthorized, ephemeral=ephemeral, reusable=reusable)
            key_capabilities = KeyCapabilities(devices={"create": key_attributes})
            request = AuthKeyRequest(capabilities=key_capabilities, expiry_seconds=expiry_seconds)

        print(request.json(indent=2))
        data = await self._post(f"tailnet/{self.tailnet}/keys", data=request.dict())
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
