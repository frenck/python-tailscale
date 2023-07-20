"""Asynchronous client for the Tailscale API."""
from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Dict, List

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
from .models import Device, Devices


@dataclass
class Tailscale:
    """Main class for handling connections with the Tailscale API."""

    api_key: str
    # '-' used in a URI will assume default tailnet of api key
    tailnet: str = "-"

    request_timeout: int = 8
    session: ClientSession | None = None

    _close_session: bool = False

    async def _post(
        self,
        uri: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a POST request to the Tailscale API.

        Args:
            uri: Request URI, without '/api/v2/'.
            data: Dictionary of data to send to the Tailscale API.

        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Tailscale API.

        """
        return await self._request(uri, method=METH_POST, data=data)

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
    ) -> dict[str, Any]:
        """Make a GET request to the Tailscale API.

        Args:
            uri: Request URI, without '/api/v2/'.
            data: Dictionary of data to send to the Tailscale API.

        Returns:
            A Python dictionary (JSON decoded) with the response from
            the Tailscale API.
        """
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
                "Error occurred while connecting to the Tailscale API: ",
                f"{exception.message}",
            ) from exception
        except (
            # raise_for_status always raises a ClientResponseError,
            # not sure this will be hit
            ClientError,
            socket.gaierror,
        ) as exception:
            raise TailscaleConnectionError(
                "Error occurred while communicating with the Tailscale API"
            ) from exception

        response_data: Dict[str, Any] = await response.json(content_type=None)
        return response_data

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
            tags: The tags to add to the device. Tags should be prefixed with "tag:".
        """
        cleaned_tags = [
            f"tag:{tag}" if not tag.startswith("tag:") else tag for tag in tags
        ]
        await self._post(f"device/{device_id}/tags", data={"tags": cleaned_tags})

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
