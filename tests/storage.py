"""Dummy token storage."""

from datetime import datetime

from tailscale.storage import TokenStorage


class InMemoryTokenStorage(TokenStorage):
    """In-memory token storage for testing purposes."""

    def __init__(
        self, access_token: str | None = None, expires_at: datetime | None = None
    ) -> None:
        """Initialize the in-memory token storage."""
        self._access_token = access_token
        self._expires_at = expires_at

    async def get_token(self) -> tuple[str, datetime] | None:
        """Get the stored token."""
        if self._access_token and self._expires_at:
            return self._access_token, self._expires_at
        return None

    async def set_token(self, access_token: str, expires_at: datetime) -> None:
        """Store the token."""
        self._access_token = access_token
        self._expires_at = expires_at
