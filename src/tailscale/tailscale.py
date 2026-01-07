"""Asynchronous client for the Tailscale API."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Self

from aiohttp.client import ClientError, ClientResponseError, ClientSession
from aiohttp.hdrs import METH_GET, METH_POST
from yarl import URL

from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)
from .models import Device, Devices

if TYPE_CHECKING:
    from .storage import TokenStorage


@dataclass
# pylint: disable-next=too-many-instance-attributes
class Tailscale:
    """Main class for handling connections with the Tailscale API."""

    # tailnet of '-' is the default tailnet of the API key
    tailnet: str = "-"
    api_key: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None

    request_timeout: int = 8
    session: ClientSession | None = None
    token_storage: TokenStorage | None = None

    _get_oauth_token_task: asyncio.Task[None] | None = None
    _expire_oauth_token_task: asyncio.Task[None] | None = None
    _close_session: bool = False

    async def _check_api_key(self) -> None:
        """Initialize the Tailscale client.

        Raises:
            TailscaleAuthenticationError: when neither api_key nor oauth_client_id and
                oauth_client_secret are provided.

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
            # Handle some inconsistent state
            # possibly caused by user manually deleting api_key
            if self._expire_oauth_token_task:
                self._expire_oauth_token_task.cancel()
                self._expire_oauth_token_task = None
                if self._get_oauth_token_task:
                    self._get_oauth_token_task.cancel()
                    self._get_oauth_token_task = None
            # Get a new OAuth token if not already in the process of getting one
            if not self._get_oauth_token_task:
                self._get_oauth_token_task = asyncio.create_task(
                    self._get_oauth_token()
                )
            # Wait for the OAuth token to be retrieved
            await self._get_oauth_token_task

    async def _get_oauth_token(self) -> None:
        """Get an OAuth token from the Tailscale API or token storage.

        Raises:
            TailscaleAuthenticationError: when access token not found in response or
                access token expires in less than 5 minutes.

        """
        if self.token_storage:
            token_data = await self.token_storage.get_token()
            if token_data:
                access_token, expires_at = token_data
                expires_in = (expires_at - datetime.now(timezone.utc)).total_seconds()
                if expires_in > 60:
                    self._expire_oauth_token_task = asyncio.create_task(
                        self._expire_oauth_token(expires_in)
                    )
                    self.api_key = access_token
                    return

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
            _use_authentication=False,
            _use_form_encoding=True,
        )

        json_response = json.loads(response)
        access_token = str(json_response.get("access_token", ""))
        expires_in = float(json_response.get("expires_in", 0))
        if not access_token or not expires_in:
            msg = "Failed to get OAuth token"
            raise TailscaleAuthenticationError(msg)
        if expires_in <= 60:
            msg = "OAuth token expires in less than 1 minute"
            raise TailscaleAuthenticationError(msg)

        self._expire_oauth_token_task = asyncio.create_task(
            self._expire_oauth_token(expires_in)
        )
        if self.token_storage:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            await self.token_storage.set_token(access_token, expires_at)
        self.api_key = access_token

    async def _expire_oauth_token(self, expires_in: float) -> None:
        """Expires the OAuth token 1 minute before expiration."""
        await asyncio.sleep(expires_in - 60)
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
            method: HTTP Method to use.
            data: Dictionary of data to send to the Tailscale API.

        Returns:
        -------
            The response from the Tailscale API.

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
                    data=data if _use_form_encoding else None,
                    json=data if not _use_form_encoding else None,
                )
                response.raise_for_status()
        except asyncio.TimeoutError as exception:
            msg = "Timeout occurred while connecting to the Tailscale API"
            raise TailscaleConnectionError(msg) from exception
        except ClientResponseError as exception:
            if exception.status in [401, 403]:
                if _use_authentication and self.api_key and self.oauth_client_id:
                    # Invalidate the current OAuth token
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
        """Get devices information from the Tailscale API.

        Returns
        -------
            Returns a dictionary of Tailscale devices.

        """
        data = await self._request(f"tailnet/{self.tailnet}/devices?fields=all")
        return Devices.from_json(data).devices

    async def close(self) -> None:
        """Close open client session and cancel tasks."""
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
            _exc_info: Exec type.

        """
        await self.close()
