"""Asynchronous client for the Tailscale API."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass
from typing import Any, Self

from aiohttp.client import ClientError, ClientResponseError, ClientSession
from aiohttp.hdrs import METH_GET, METH_POST
from yarl import URL

from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)
from .models import Device, Devices

# Placeholder value for the access token when it is not yet set.
ACCESS_TOKEN_PENDING = "<pending>"  # noqa: S105


@dataclass
class Tailscale:
    """Main class for handling connections with the Tailscale API."""

    # tailnet of '-' is the default tailnet of the API key
    tailnet: str = "-"
    api_key: str = ""  # nosec
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
            not self.api_key
            and not self.oauth_client_id
            and not self.oauth_client_secret
        ):
            msg = "Either api_key or oauth client is required"
            raise TailscaleAuthenticationError(msg)
        if not self.api_key:
            self.api_key = ACCESS_TOKEN_PENDING
            self.api_key = await self._get_oauth_token()

    async def _get_oauth_token(self) -> str:
        """Get an OAuth token from the Tailscale API.

        Raises:
            TailscaleAuthenticationError: when access key not found in response.

        Returns:
            A string with the OAuth token, or nothing on error

        """
        # Tailscale's OAuth endpoint requires form-encoded body
        # with client_id and client_secret
        data = {
            "client_id": self.oauth_client_id,
            "client_secret": self.oauth_client_secret,
        }
        response = await self._request(
            "oauth/token",
            data=data,
            method=METH_POST,
            use_form_encoding=True,
        )

        token = json.loads(response).get("access_token", "")
        if not token:
            msg = "Failed to get OAuth token"
            raise TailscaleAuthenticationError(msg)
        return str(token)

    async def _request(
        self,
        uri: str,
        *,
        method: str = METH_GET,
        data: dict[str, Any] | None = None,
        use_form_encoding: bool = False,
    ) -> str:
        """Handle a request to the Tailscale API.

        A generic method for sending/handling HTTP requests done against
        the Tailscale API.

        Args:
        ----
            uri: Request URI, without '/api/v2/'.
            method: HTTP Method to use.
            data: Dictionary of data to send to the Tailscale API.

        Returns:
        -------
            A Python dictionary (JSON decoded) with the response from
            the Tailscale API.

        Raises:
        ------
            TailscaleAuthenticationError: If the API key is invalid.
            TailscaleConnectionError: An error occurred while communicating with
                the Tailscale API.
            TailscaleError: Received an unexpected response from the Tailscale
                API.

        """
        url = URL("https://api.tailscale.com/api/v2/").join(URL(uri))

        await self._check_access()

        headers: dict[str, str] = {
            "Accept": "application/json",
        }

        if self.api_key and self.api_key != ACCESS_TOKEN_PENDING:
            # API keys and oauth tokens can use Bearer authentication
            headers["Authorization"] = f"Bearer {self.api_key}"

        if self.session is None:
            self.session = ClientSession()
            self._close_session = True

        try:
            async with asyncio.timeout(self.request_timeout):
                # Use form encoding for OAuth token requests, JSON for others
                response = await self.session.request(
                    method,
                    url,
                    headers=headers if headers else None,
                    data=data if use_form_encoding else None,
                    json=data if not use_form_encoding else None,
                )
                response.raise_for_status()
        except asyncio.TimeoutError as exception:
            msg = "Timeout occurred while connecting to the Tailscale API"
            raise TailscaleConnectionError(msg) from exception
        except ClientResponseError as exception:
            if exception.status in [401, 403]:
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
        """Get devices information from the Tailscale API.

        Returns
        -------
            Returns a dictionary of Tailscale devices.

        """
        data = await self._request(f"tailnet/{self.tailnet}/devices?fields=all")
        return Devices.from_json(data).devices

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()

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
            _exc_info: Exec type.

        """
        await self.close()
