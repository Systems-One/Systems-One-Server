"""Raw TCP relay for a network label printer (e.g. TSC ML241P on port 9100).

Remote clients (PPNAM Station 1 over Tailscale) connect to this relay, and
every byte is piped unchanged to the printer on the office LAN.

The listening socket is only open while the printer accepts TCP connections.
Clients treat a successful TCP connect as "printer online", so a relay that
always listened would report a powered-off printer as online and silently drop
labels. Closing the listener instead gives clients "connection refused".
Run with host networking: Docker's port-publishing proxy would accept
connections itself and defeat this.
"""
import asyncio
import ipaddress
import logging
import os
import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("printer_relay")


@dataclass
class Config:
    listen_host: str
    printer_host: str
    listen_port: int = 9100
    printer_port: int = 9100
    check_interval: float = 5.0
    connect_timeout: float = 3.0
    idle_timeout: float = 60.0
    reply_grace: float = 2.0
    allowed_clients: list = field(default_factory=lambda: ["100.64.0.0/10"])
    heartbeat_file: str | None = "/tmp/relay-heartbeat"

    @classmethod
    def from_env(cls, env=os.environ):
        printer_host = env.get("PRINTER_HOST", "").strip()
        if not printer_host:
            raise ValueError("PRINTER_HOST is required")
        cfg = cls(
            listen_host=env.get("LISTEN_HOST", "0.0.0.0").strip(),
            printer_host=printer_host,
        )
        for name, cast in (
            ("listen_port", int), ("printer_port", int),
            ("check_interval", float), ("connect_timeout", float),
            ("idle_timeout", float), ("reply_grace", float),
        ):
            if env.get(name.upper()):
                setattr(cfg, name, cast(env[name.upper()]))
        if env.get("ALLOWED_CLIENTS"):
            cfg.allowed_clients = [c.strip() for c in env["ALLOWED_CLIENTS"].split(",") if c.strip()]
        if "HEARTBEAT_FILE" in env:
            cfg.heartbeat_file = env["HEARTBEAT_FILE"] or None
        return cfg


def _abort(writer):
    """Close with RST so the client sees an error rather than a clean EOF."""
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except OSError:
            pass
    writer.close()


class Relay:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._networks = [ipaddress.ip_network(c, strict=False) for c in cfg.allowed_clients]
        self._server = None
        self._task = None
        self._conns = set()

    @property
    def listening(self):
        return self._server is not None

    async def listening_async(self):
        return self.listening

    def _allowed(self, host):
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(addr in net for net in self._networks)

    async def printer_reachable(self):
        try:
            _, w = await asyncio.wait_for(
                asyncio.open_connection(self.cfg.printer_host, self.cfg.printer_port),
                self.cfg.connect_timeout,
            )
        except (OSError, asyncio.TimeoutError):
            return False
        w.close()
        try:
            await w.wait_closed()
        except OSError:
            pass
        return True

    async def _open_listener(self):
        try:
            self._server = await asyncio.start_server(
                self._handle, self.cfg.listen_host, self.cfg.listen_port, reuse_address=True,
            )
        except OSError as exc:
            # e.g. Tailscale address not up yet after boot; retried next tick.
            log.warning("cannot listen on %s:%s: %s", self.cfg.listen_host, self.cfg.listen_port, exc)
            self._server = None
            return
        log.info("printer %s:%s reachable - listening on %s:%s",
                 self.cfg.printer_host, self.cfg.printer_port, self.cfg.listen_host, self.cfg.listen_port)

    async def _close_listener(self):
        if self._server is None:
            return
        self._server.close()
        self._server = None
        log.warning("printer %s:%s unreachable - listener closed (clients will see Offline)",
                    self.cfg.printer_host, self.cfg.printer_port)

    async def _watch(self):
        while True:
            up = await self.printer_reachable()
            if up and not self.listening:
                await self._open_listener()
            elif not up and self.listening:
                await self._close_listener()
            if self.cfg.heartbeat_file:
                try:
                    Path(self.cfg.heartbeat_file).write_text(str(int(time.time())))
                except OSError:
                    pass
            await asyncio.sleep(self.cfg.check_interval)

    async def _pipe(self, reader, writer):
        total = 0
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(65536), self.cfg.idle_timeout)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
                total += len(chunk)
            if writer.can_write_eof():
                writer.write_eof()
        except (OSError, asyncio.TimeoutError):
            pass
        return total

    async def _handle(self, c_reader, c_writer):
        task = asyncio.current_task()
        self._conns.add(task)
        peer = c_writer.get_extra_info("peername") or ("?", 0)
        client = peer[0]
        started = time.monotonic()
        p_writer = None
        pipes = ()
        try:
            if not self._allowed(client):
                log.warning("rejected client %s (not in ALLOWED_CLIENTS)", client)
                _abort(c_writer)
                return
            try:
                p_reader, p_writer = await asyncio.wait_for(
                    asyncio.open_connection(self.cfg.printer_host, self.cfg.printer_port),
                    self.cfg.connect_timeout,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                log.error("client %s: printer connect failed: %r", client, exc)
                _abort(c_writer)
                await self._close_listener()
                return
            up = asyncio.create_task(self._pipe(c_reader, p_writer))
            down = asyncio.create_task(self._pipe(p_reader, c_writer))
            pipes = (up, down)
            done, _ = await asyncio.wait(pipes, return_when=asyncio.FIRST_COMPLETED)
            if up in done:
                # Client finished sending. The printer may hold its side open
                # indefinitely, which would block the next job on printers that
                # take one connection at a time, so only wait briefly for a reply.
                await asyncio.wait((down,), timeout=self.cfg.reply_grace)
            else:
                await asyncio.wait((up,), timeout=self.cfg.reply_grace)
            sent = up.result() if up.done() else 0
            received = down.result() if down.done() else 0
            if sent or received:
                log.info("client %s: job relayed, %d bytes to printer, %d bytes back, %.2fs",
                         client, sent, received, time.monotonic() - started)
            else:
                log.debug("client %s: connection probe (no data)", client)
        finally:
            for t in pipes:
                t.cancel()
            for w in (p_writer, c_writer):
                if w is not None:
                    w.close()
            self._conns.discard(task)

    async def start(self):
        self._task = asyncio.create_task(self._watch())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._close_listener()
        conns = list(self._conns)
        for t in conns:
            t.cancel()
        await asyncio.gather(*conns, return_exceptions=True)


async def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    cfg = Config.from_env()
    log.info("relay %s:%s -> printer %s:%s, allowed clients %s",
             cfg.listen_host, cfg.listen_port, cfg.printer_host, cfg.printer_port,
             ",".join(cfg.allowed_clients))
    relay = Relay(cfg)
    await relay.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
