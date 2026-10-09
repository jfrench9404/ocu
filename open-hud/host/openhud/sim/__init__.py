"""Software stand-in for the glasses: same state machine and layout as the firmware."""
from .device import SimDevice
from .render import preview, render

__all__ = ["SimDevice", "render", "preview"]
