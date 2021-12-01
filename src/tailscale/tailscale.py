"""Asynchronous client for the Tailscale API."""
from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from importlib import metadata
from typing import Any

import async_timeout
from aiohttp import BasicAuth
from aiohttp.client import ClientError, ClientResponseError, ClientSession
from aiohttp.hdrs import METH_GET
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

    tailnet: str
    api_key: str

    request_timeout: int = 8
    session: ClientSession | None = None

    _close_session: bool = False

    async def _request(
        self,
        uri: str,
        *,
        method: str = METH_GET,
        data: dict | None = None,
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
                "Error occurred while connecting to the Tailscale API"
            ) from exception
        except (
            ClientError,
            socket.gaierror,
        ) as exception:
            raise TailscaleConnectionError(
                "Error occurred while communicating with the Tailscale API"
            ) from exception

        return await response.json(content_type=None)

    async def devices(self) -> dict[str, Device]:
        """Get devices information from the Tailscale API.

        Returns:
            Returns a dictionary of Tailscale devices.
        """
        data = await self._request(f"tailnet/{self.tailnet}/devices?fields=all")
        return Devices.parse_obj(data).devices

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

    async def __aexit__(self, *_exc_info) -> None:
        """Async exit.

        Args:
            _exc_info: Exec type.
        """
        await self.close()
