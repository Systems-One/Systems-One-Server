"""Tests for the printer relay: raw TCP pass-through that only listens while
the printer is reachable (so the Station 1 app's connect-based "Online" check
stays truthful)."""
import asyncio
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "files" / "app"))

import relay  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakePrinter:
    """Accepts connections and records every byte received per connection."""

    def __init__(self, port, hold_open=False):
        self.port = port
        self.hold_open = hold_open  # like a real printer that never hangs up
        self.jobs = []
        self.server = None
        self._writers = set()

    async def _handle(self, reader, writer):
        self._writers.add(writer)
        data = await reader.read()  # until client EOF
        self.jobs.append(data)
        if self.hold_open:
            await asyncio.sleep(3600)
        writer.close()

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)

    async def stop(self):
        self.server.close()
        for w in self._writers:
            w.close()
        # Python 3.12+ wait_closed() waits for every connection; never hang CI.
        await asyncio.wait_for(self.server.wait_closed(), 5)


async def can_connect(port):
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 1)
    except (OSError, asyncio.TimeoutError):
        return False
    w.close()
    return True


async def wait_until(predicate, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if await predicate():
            return True
        await asyncio.sleep(0.05)
    return False


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.printer_port = free_port()
        self.listen_port = free_port()
        self.printer = FakePrinter(self.printer_port)
        self.cfg = relay.Config(
            listen_host="127.0.0.1",
            listen_port=self.listen_port,
            printer_host="127.0.0.1",
            printer_port=self.printer_port,
            check_interval=0.1,
            connect_timeout=0.5,
            idle_timeout=5,
            allowed_clients=["127.0.0.0/8"],
            heartbeat_file=None,
        )
        self.relay = relay.Relay(self.cfg)

    async def asyncTearDown(self):
        await self.relay.stop()
        if self.printer.server:
            await self.printer.stop()

    async def test_forwards_job_bytes_unchanged(self):
        await self.printer.start()
        await self.relay.start()
        self.assertTrue(await wait_until(lambda: can_connect(self.listen_port)))

        job = b'SIZE 50 mm,35 mm\r\nCLS\r\nQRCODE 10,10,M,4,A,0,M2,S7,"X"\r\nPRINT 4,1\r\n' * 50
        _, w = await asyncio.open_connection("127.0.0.1", self.listen_port)
        w.write(job)
        await w.drain()
        w.close()
        await w.wait_closed()

        async def got_job():
            return job in self.printer.jobs

        self.assertTrue(await wait_until(got_job))

    async def test_releases_printer_when_printer_never_hangs_up(self):
        self.printer = FakePrinter(self.printer_port, hold_open=True)
        self.cfg.reply_grace = 0.3
        self.relay = relay.Relay(self.cfg)
        await self.printer.start()
        await self.relay.start()
        self.assertTrue(await wait_until(lambda: self.relay.listening_async()))

        _, w = await asyncio.open_connection("127.0.0.1", self.listen_port)
        w.write(b"PRINT 1,1\r\n")
        await w.drain()
        w.close()

        async def released():
            return b"PRINT 1,1\r\n" in self.printer.jobs and not self.relay._conns

        self.assertTrue(await wait_until(released, timeout=2))

    async def test_stop_closes_open_connections(self):
        await self.printer.start()
        await self.relay.start()
        self.assertTrue(await wait_until(lambda: self.relay.listening_async()))
        _, w = await asyncio.open_connection("127.0.0.1", self.listen_port)
        w.write(b"SIZE 50 mm,35 mm\r\n")  # client stays connected
        await w.drain()
        self.assertTrue(await wait_until(self._has_conn))
        await asyncio.wait_for(self.relay.stop(), 2)
        await asyncio.wait_for(self.printer.stop(), 2)
        self.printer.server = None
        w.close()

    async def _has_conn(self):
        return bool(self.relay._conns)

    async def test_refuses_connections_while_printer_down(self):
        await self.relay.start()  # printer never started
        await asyncio.sleep(0.4)
        self.assertFalse(await can_connect(self.listen_port))

    async def test_starts_listening_when_printer_comes_back(self):
        await self.relay.start()
        await asyncio.sleep(0.3)
        self.assertFalse(await can_connect(self.listen_port))
        await self.printer.start()
        self.assertTrue(await wait_until(lambda: can_connect(self.listen_port)))

    async def test_stops_listening_when_printer_goes_away(self):
        await self.printer.start()
        await self.relay.start()
        self.assertTrue(await wait_until(lambda: can_connect(self.listen_port)))
        await self.printer.stop()
        self.printer.server = None

        async def refused():
            return not await can_connect(self.listen_port)

        self.assertTrue(await wait_until(refused))

    async def test_rejects_clients_outside_allowlist(self):
        self.cfg.allowed_clients = ["10.0.0.0/8"]
        self.relay = relay.Relay(self.cfg)
        await self.printer.start()
        await self.relay.start()
        self.assertTrue(await wait_until(lambda: self.relay.listening_async()))
        _, w = await asyncio.open_connection("127.0.0.1", self.listen_port)
        w.write(b"PRINT 1,1\r\n")
        await w.drain()
        w.close()
        await asyncio.sleep(0.3)
        self.assertEqual([j for j in self.printer.jobs if j], [])


class ConfigTests(unittest.TestCase):
    def test_from_env(self):
        cfg = relay.Config.from_env({
            "LISTEN_HOST": "100.102.46.89",
            "PRINTER_HOST": "192.168.1.45",
            "ALLOWED_CLIENTS": "100.64.0.0/10, 192.168.1.0/24",
        })
        self.assertEqual(cfg.listen_port, 9100)
        self.assertEqual(cfg.printer_port, 9100)
        self.assertEqual(cfg.allowed_clients, ["100.64.0.0/10", "192.168.1.0/24"])

    def test_printer_host_required(self):
        with self.assertRaises(ValueError):
            relay.Config.from_env({"LISTEN_HOST": "0.0.0.0"})


if __name__ == "__main__":
    unittest.main()
