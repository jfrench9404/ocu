"""Open-HUD host: turns phone/laptop events into tiny BLE frames for the glasses."""
from . import events, protocol
from .hud import Hud

__all__ = ["Hud", "events", "protocol"]
__version__ = "0.1.0"
