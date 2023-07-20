"""Asynchronous client for the Tailscale API.

This file tests the basics of the Tailscale class and authentication.
"""
# pylint: disable=protected-access
# pyright: reportGeneralTypeIssues=warning
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


@pytest.mark.asyncio
async def test_no_access() -> None:
    """Test api key or oauth key is checked correctly."""
    async with Tailscale(tailnet="frenck") as tailscale:
        with pytest.raises(TailscaleAuthenticationError):
            assert await tailscale._request("test")


@pytest.mark.asyncio
async def test_key_from_oauth(aresponses: ResponsesMockServer) -> None:
    """Test oauth key response is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token"}',
        ),
    )
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
        tailscale = Tailscale(
            tailnet="frenck",
            oauth_client_id="client",  # nosec
            oauth_client_secret="notsosecret",  # nosec
            session=session,
        )
        await tailscale._request("test")
        second_request = aresponses.history[1].request
        assert "Basic" in second_request.headers["Authorization"]
        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_bad_oauth(aresponses: ResponsesMockServer) -> None:
    """Test bad oauth error is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"no_access_token": "unauthorized"}',
        ),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(
            tailnet="frenck",
            oauth_client_id="client",  # nosec
            oauth_client_secret="notsosecret",  # nosec
            session=session,
        )
        with pytest.raises(TailscaleAuthenticationError) as excinfo:
            assert await tailscale._request("test")
            assert excinfo.value.args[0] == "Failed to get OAuth token"

        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
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
        assert response["status"] == "ok"
        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
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
        assert response["status"] == "ok"

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
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
        response = await tailscale._post("test", data={})
        assert response["status"] == "ok"

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
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
            tailnet="frenck", api_key="abc", session=session, request_timeout=1
        )
        with pytest.raises(TailscaleConnectionError):
            assert await tailscale._request("test")

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
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

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
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
            assert await tailscale._get("test")

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_http_error403(aresponses: ResponsesMockServer) -> None:
    """Test HTTP 403 response handling."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/test",
        "GET",
        aresponses.Response(text="Not allowed!", status=403),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        with pytest.raises(TailscaleAuthenticationError):
            assert await tailscale._get("test")

    aresponses.assert_plan_strictly_followed()


@pytest.mark.asyncio
async def test_http_delete(aresponses: ResponsesMockServer) -> None:
    """Test HTTP Delete response handling."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/test",
        "DELETE",
        aresponses.Response(status=200),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(tailnet="frenck", api_key="abc", session=session)
        assert await tailscale._delete("test") is None

    aresponses.assert_plan_strictly_followed()
