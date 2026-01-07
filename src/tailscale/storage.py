"""Abstract token storage."""

from abc import ABC, abstractmethod
from datetime import datetime


class TokenStorage(ABC):
    """Abstract class for token storage implementations."""

    @abstractmethod
    async def get_token(self) -> tuple[str, datetime] | None:
        """Get the stored token.

        Returns:
            The stored token and expiration time, or None if no token is stored.

        """
        raise NotImplementedError

    @abstractmethod
    async def set_token(self, access_token: str, expires_at: datetime) -> None:
        """Store the given token.

        Args:
            access_token: The access token to store.
            expires_at: The expiration time of the access token.

        """
        raise NotImplementedError
