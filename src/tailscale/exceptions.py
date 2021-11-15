"""Exceptions for the Tailscale API client."""


class TailscaleError(Exception):
    """Generic Tailscale exception."""


class TailscaleAuthenticationError(TailscaleError):
    """Tailscale authentication exception."""


class TailscaleConnectionError(TailscaleError):
    """Tailscale connection exception."""
