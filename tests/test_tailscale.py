"""Asynchronous client for the Tailscale API."""

# pylint: disable=protected-access
import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
import pytest
from aresponses import Response, ResponsesMockServer

from tailscale import Tailscale
from tailscale.exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)
from tests.storage import InMemoryTokenStorage


async def test_wrong_arguments_no_auth() -> None:
    """Test api key or oauth key is checked correctly."""
    async with Tailscale() as tailscale:
        with pytest.raises(TailscaleAuthenticationError) as excinfo:
            assert await tailscale._request("test")

        assert excinfo.value.args[0] == (
            "Either api_key or oauth_client_id and oauth_client_secret "
            "are required when Tailscale client is initialized"
        )


async def test_wrong_arguments_both_auth() -> None:
    """Test api key or oauth key is checked correctly."""
    async with Tailscale(
        api_key="abc",
        oauth_client_id="client",
        oauth_client_secret="notsosecret",  # noqa: S106
    ) as tailscale:
        with pytest.raises(TailscaleAuthenticationError) as excinfo:
            assert await tailscale._request("test")

        assert excinfo.value.args[0] == (
            "Either api_key or oauth_client_id and oauth_client_secret "
            "are required when Tailscale client is initialized"
        )


async def test_wrong_arguments_partial_oauth() -> None:
    """Test api key or oauth key is checked correctly."""
    async with Tailscale(
        oauth_client_id="client",
    ) as tailscale:
        with pytest.raises(TailscaleAuthenticationError) as excinfo:
            assert await tailscale._request("test")

        assert excinfo.value.args[0] == (
            "Either api_key or oauth_client_id and oauth_client_secret "
            "are required when Tailscale client is initialized"
        )


async def test_key_from_oauth(aresponses: ResponsesMockServer) -> None:
    """Test oauth key response is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token", "expires_in": 3600}',
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
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
        )
        await tailscale._request("test")
        second_request = aresponses.history[1].request
        assert "Bearer" in second_request.headers["Authorization"]
        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


async def test_key_from_oauth_with_race_condition(
    aresponses: ResponsesMockServer,
) -> None:
    """Test oauth key request is sent out only once."""

    async def oauth_handler(_: aiohttp.ClientResponse) -> Response:
        """Response handler emulating slow oauth response."""
        await asyncio.sleep(1)
        return aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token", "expires_in": 3600}',
        )

    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        oauth_handler,
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
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
        )

        first_task = asyncio.create_task(tailscale._request("test"))
        second_task = asyncio.create_task(tailscale._request("test"))
        await asyncio.gather(first_task, second_task)
        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


async def test_new_key_from_oauth_on_manual_invalidation(
    aresponses: ResponsesMockServer,
) -> None:
    """Test oauth key manual invalidation is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token", "expires_in": 3600}',
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
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token", "expires_in": 3600}',
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
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
        )
        await tailscale._request("test")
        tailscale.api_key = None  # Manual invalidation
        await tailscale._request("test")
        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


async def test_oauth_key_expiration(aresponses: ResponsesMockServer) -> None:
    """Test oauth key expiration."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token", "expires_in": 61}',
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
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
        )
        await tailscale._request("test")
        assert tailscale.api_key == "short-lived-token"
        assert tailscale._get_oauth_token_task is not None
        assert tailscale._expire_oauth_token_task is not None
        await asyncio.sleep(2)
        assert tailscale.api_key is None
        assert tailscale._get_oauth_token_task is None
        assert tailscale._expire_oauth_token_task is None
        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


async def test_key_from_storage(aresponses: ResponsesMockServer) -> None:
    """Test oauth key is loaded from storage."""
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
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
            token_storage=InMemoryTokenStorage(
                "stored-token", datetime.now(timezone.utc) + timedelta(hours=1)
            ),
        )
        await tailscale._request("test")
        first_request = aresponses.history[0].request
        assert "Bearer" in first_request.headers["Authorization"]
        assert "stored-token" in first_request.headers["Authorization"]
        await tailscale.close()


async def test_drop_key_from_storage(aresponses: ResponsesMockServer) -> None:
    """Test oauth key response is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token", "expires_in": 3600}',
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
        token_storage = InMemoryTokenStorage(
            "stored-token", datetime.now(timezone.utc) + timedelta(seconds=30)
        )
        tailscale = Tailscale(
            tailnet="frenck",
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
            token_storage=token_storage,
        )
        await tailscale._request("test")
        second_request = aresponses.history[1].request
        assert "Bearer" in second_request.headers["Authorization"]
        assert "short-lived-token" in second_request.headers["Authorization"]
        assert token_storage._access_token == "short-lived-token"  # noqa: S105
        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


async def test_bad_oauth(aresponses: ResponsesMockServer) -> None:
    """Test bad oauth response is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"no_access_token": "unauthorized"}',
        ),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(
            tailnet="frenck",
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
        )
        with pytest.raises(TailscaleAuthenticationError) as excinfo:
            assert await tailscale._request("test")

        assert excinfo.value.args[0] == "Failed to get OAuth token"

        await tailscale.close()

    aresponses.assert_plan_strictly_followed()


async def test_too_short_oauth_expiration(aresponses: ResponsesMockServer) -> None:
    """Test too short oauth expiration is handled correctly."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token", "expires_in": 60}',
        ),
    )

    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(
            tailnet="frenck",
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
        )
        with pytest.raises(TailscaleAuthenticationError) as excinfo:
            assert await tailscale._request("test")

        assert excinfo.value.args[0] == "OAuth token expires in less than 1 minute"

        await tailscale.close()


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


async def test_http_error401_and_oauth_token_invalidation(
    aresponses: ResponsesMockServer,
) -> None:
    """Test HTTP 401 response handling and oauth token invalidation."""
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/oauth/token",
        "POST",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"access_token": "short-lived-token", "expires_in": 3600}',
        ),
    )
    aresponses.add(
        "api.tailscale.com",
        "/api/v2/test",
        "GET",
        aresponses.Response(text="Access denied!", status=401),
    )
    async with aiohttp.ClientSession() as session:
        tailscale = Tailscale(
            tailnet="frenck",
            oauth_client_id="client",
            oauth_client_secret="notsosecret",  # noqa: S106
            session=session,
        )
        with pytest.raises(TailscaleAuthenticationError) as excinfo:
            assert await tailscale._request("test")

        assert excinfo.value.args[0] == "Authentication to the Tailscale API failed"
        assert tailscale.api_key is None
        assert tailscale._get_oauth_token_task is None
        assert tailscale._expire_oauth_token_task is None

        await tailscale.close()

    aresponses.assert_plan_strictly_followed()
