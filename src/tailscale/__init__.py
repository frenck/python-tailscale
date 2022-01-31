"""Asynchronous client for the Tailscale API."""
from .exceptions import (
    TailscaleAuthenticationError,
    TailscaleConnectionError,
    TailscaleError,
)
from .models import ClientConnectivity, ClientSupports, Device, Devices
from .tailscale import Tailscale

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
