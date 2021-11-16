"""Asynchronous client for the Tailscale API."""
from .models import ClientConnectivity, ClientSupports, Device, Devices
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
    "Devices",
    "Tailscale",
    "TailscaleAuthenticationError",
    "TailscaleConnectionError",
    "TailscaleError",
]
