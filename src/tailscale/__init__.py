"""Asynchronous client for the Tailscale API."""
from .models import ClientConnectivity, ClientSupports, Device
from .tailscale import (
    Tailscale,
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)

__all__ = [
    "ClientConnectivity",
    "ClientSupports",
    "Device",
    "Tailscale",
    "TailscaleAuthenticationError",
    "TailscaleConnectionError",
    "TailscaleError",
]
