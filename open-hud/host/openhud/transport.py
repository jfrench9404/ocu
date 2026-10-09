"""Transports move encoded frames to a device: real glasses over BLE, or the
built-in simulator. Both expose the same small async interface."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from . import protocol as p

log = logging.getLogger("openhud.transport")

ReceiveCallback = Callable[[bytes], None]


class Transport:
    on_receive: ReceiveCallback | None = None
    on_disconnect: Callable[[], None] | None = None

    @property
    def connected(self) -> bool:
        raise NotImplementedError

    async def connect(self) -> None:
        raise NotImplementedError

    async def send(self, data: bytes) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class BleTransport(Transport):
    """BLE central using bleak (Windows, macOS, Linux)."""

    def __init__(self, address: str | None = None, scan_timeout: float = 5.0) -> None:
        self.address = address          # remembered after first connect -> faster reconnects
        self.scan_timeout = scan_timeout
        self._client = None

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    async def _find(self):
        from bleak import BleakScanner

        if self.address:
            dev = await BleakScanner.find_device_by_address(self.address, timeout=self.scan_timeout)
            if dev:
                return dev
        return await BleakScanner.find_device_by_filter(
            lambda d, ad: p.SERVICE_UUID in [u.lower() for u in ad.service_uuids]
            or (d.name or "") == p.DEVICE_NAME,
            timeout=self.scan_timeout,
        )

    async def connect(self) -> None:
        from bleak import BleakClient

        dev = await self._find()
        if dev is None:
            raise ConnectionError("Open-HUD glasses not found (are they powered and advertising?)")
        client = BleakClient(dev, disconnected_callback=lambda _c: self._disconnected())
        await client.connect()
        self._client = client
        self.address = dev.address
        await client.start_notify(p.TX_UUID, lambda _h, data: self.on_receive and self.on_receive(bytes(data)))
        mtu = getattr(client, "mtu_size", 0)
        if mtu and mtu < p.MIN_MTU:
            log.warning("negotiated MTU %d < %d: frames over %d bytes will be dropped",
                        mtu, p.MIN_MTU, mtu - 3)
        log.info("connected to %s (MTU %s)", dev.address, mtu)

    def _disconnected(self) -> None:
        log.info("BLE disconnected")
        if self.on_disconnect:
            self.on_disconnect()

    async def send(self, data: bytes) -> None:
        if not self.connected:
            raise ConnectionError("not connected")
        await self._client.write_gatt_char(p.RX_UUID, data, response=False)

    async def close(self) -> None:
        if self._client:
            await self._client.disconnect()


class SimTransport(Transport):
    """Feeds frames into the in-process simulator (no hardware needed)."""

    def __init__(self, device, latency_s: float = 0.0) -> None:
        self.device = device
        self.latency_s = latency_s
        self._connected = False
        device.on_notify = lambda data: self.on_receive and self.on_receive(data)

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True
        self.device.set_connected(True)

    async def send(self, data: bytes) -> None:
        if not self._connected:
            raise ConnectionError("not connected")
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        self.device.receive(data)

    async def drop(self) -> None:
        """Simulate walking out of range (for testing reconnect logic)."""
        self._connected = False
        self.device.set_connected(False)
        if self.on_disconnect:
            self.on_disconnect()

    async def close(self) -> None:
        self._connected = False
        self.device.set_connected(False)
