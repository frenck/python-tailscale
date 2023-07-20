"""Asynchronous client for the Tailscale API."""
from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Dict

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
            TailscaleAuthenticationError: when neither api_key nor oauth_client_id and
                oauth_client_secret are provided.
        """
        if (
            not self.api_key  # noqa: W503
            and not self.oauth_client_id  # noqa: W503
            and not self.oauth_client_secret  # noqa: W503
        ):
            raise TailscaleAuthenticationError(
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

        Raises:
            TailscaleAuthenticationError: when access key not found in response.

        Returns:
            A string with the OAuth token, or nothing on error

        """
        data = {
            "client_id": self.oauth_client_id,
            "client_secret": self.oauth_client_secret,
        }
        response = await self._get("oauth/token", data=data, use_auth_key=False)

        token = response.get("access_token", "")
        if not token:
            raise TailscaleAuthenticationError("Failed to get OAuth token")
        return str(token)

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

    async def devices(self) -> Dict[str, Device]:
        """Get devices information from the Tailscale API.

        Returns:
            Returns a dictionary of Tailscale devices.
        """
        data = await self._get(f"tailnet/{self.tailnet}/devices?fields=all")
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

    async def __aexit__(self, *_exc_info: Any) -> None:
        """Async exit.

        Args:
            _exc_info: Exec type.
        """
        await self.close()
