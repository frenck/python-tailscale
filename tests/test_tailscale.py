"""Asynchronous client for the Tailscale API."""

# pylint: disable=protected-access
import asyncio

import aiohttp
import pytest
from aresponses import Response, ResponsesMockServer

from tailscale import Tailscale
from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)


async def test_json_request(aresponses: ResponsesMockServer) -> None:
    """Test JSON response is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/test",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"status": "ok"}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        response = await tailscale._request("test")
        assert response == '{"status": "ok"}'
        await tailscale.close()


async def test_internal_session(aresponses: ResponsesMockServer) -> None:
    """Test JSON response is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/test",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"status": "ok"}',
        ),
    )
    async with Tailscale(tailnet="frenck", api_key="abc") as tailscale:
        response = await tailscale._request("test")
        assert response == '{"status": "ok"}'


async def test_put_request(aresponses: ResponsesMockServer) -> None:
    """Test PUT requests are handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/test",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"status": "ok"}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        response = await tailscale._request(
            "test",
            method=aiohttp.hdrs.METH_POST,
            data={},
        )
        assert response == '{"status": "ok"}'


async def test_timeout(aresponses: ResponsesMockServer) -> None:
    """Test request timeout from the Tailscale API."""

    # Faking a timeout by sleeping
    async def response_handler(_: aiohttp.ClientResponse) -> Response:
        """Response handler for this test."""
        await asyncio.sleep(2)
        return aresponses.Response(body="Goodmorning!")

    aresponses.add("api.tailscale.com", "/api/v2/test", "GET", response_handler)

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(
            tailnet="frenck",
            api_key="abc",
            session=session,
            request_timeout=1,
        )
        with pytest.raises(TailscaleConnectionError):
            assert await tailscale._request("test")


async def test_http_error400(aresponses: ResponsesMockServer) -> None:
    """Test HTTP 404 response handling."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/test",
        "GET",
        aresponses.Response(text="OMG PUPPIES!", status=404),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        with pytest.raises(TailscaleError):
            assert await tailscale._request("test")


async def test_http_error401(aresponses: ResponsesMockServer) -> None:
    """Test HTTP 401 response handling."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/test",
        "GET",
        aresponses.Response(text="Access denied!", status=401),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        with pytest.raises(TailscaleAuthenticationError):
            assert await tailscale._request("test")
