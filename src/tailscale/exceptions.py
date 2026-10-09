"""Exceptions for the Tailscale API."""


class TailscaleError(Exception):
    """Generic Tailscale exception."""


class TailscaleAuthenticationError(TailscaleError):
    """Tailscale authentication exception."""


class TailscaleConnectionError(TailscaleError):
    """Tailscale connection exception."""


class TailscaleNotFoundError(TailscaleError):
    """Tailscale resource not found exception."""
