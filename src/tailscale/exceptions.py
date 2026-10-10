"""Exceptions for the Tailscale API."""


class TailscaleError(Exception):
    """Generic Tailscale exception."""


class TailscaleAuthenticationError(TailscaleError):
    """Tailscale authentication exception."""


class TailscaleConnectionError(TailscaleError):
    """Tailscale connection exception."""


class TailscaleResponseError(TailscaleError):
    """The Tailscale API responded with an error.

    The status is the HTTP status code, and the reason the explanation the
    API gave, like "feature not available on current billing plan".
    """

    def __init__(self, status: int, reason: str) -> None:
        """Initialize the error, with the reason as message."""
        super().__init__(reason)
        self.status = status
        self.reason = reason


class TailscaleUnauthorizedError(TailscaleResponseError, TailscaleAuthenticationError):
    """The Tailscale API did not accept the credentials (HTTP 401)."""


class TailscalePermissionError(TailscaleResponseError, TailscaleAuthenticationError):
    """The Tailscale API refused the request (HTTP 403).

    The credentials are fine, but they lack the permission or scope for the
    request, or the billing plan of the tailnet does not have the feature.
    """


class TailscaleNotFoundError(TailscaleResponseError):
    """Tailscale resource not found exception (HTTP 404)."""
