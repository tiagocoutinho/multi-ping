import asyncio
import asyncio.queues
import contextlib
import logging
import time

from .socket import address_info, async_address_info, Socket
from .tools import cycle, new_id, SENTINEL


@contextlib.contextmanager
def remaining_time(timeout):
    if timeout is None:
        remaining = lambda: None
    else:
        start = time.perf_counter()

        def remaining():
            if (remain := timeout - time.perf_counter() + start) <= 0:
                raise TimeoutError(f"timed out after {timeout}s")
            return remain

    yield remaining


def receive_pings_for_sequence(sock, icmp_seq, timeout):
    with remaining_time(timeout) as timer:
        while True:
            tout = timer()
            response = sock.receive_one_ping(tout)
            if response["sequence"] != icmp_seq:
                logging.warning("Received old response")
                continue
            yield response


def receive_one_ping(sock, ips, icmp_seq, timeout):
    pending_ips = set(ips)
    responses = receive_pings_for_sequence(sock, icmp_seq, timeout)
    while pending_ips:
        try:
            response = next(responses)
        except TimeoutError as error:
            for ip in pending_ips:
                yield {"ip": ip, "error": error}
            return
        pending_ips.remove(response["ip"])
        yield response


async def async_receive_one_ping(sock, ips, icmp_seq, timeout):
    def cb():
        response = sock.read_one_ping()
        if response["sequence"] != icmp_seq:
            return
        pending_ips.remove(response["ip"])
        responses.put_nowait(response)
        if not pending_ips:
            responses.put_nowait(None)

    pending_ips = set(ips)
    loop = asyncio.get_event_loop()
    responses = asyncio.Queue()
    loop.add_reader(sock, cb)
    try:
        async with asyncio.timeout(timeout):
            while True:
                if (response := await responses.get()) is None:
                    break
                yield response
    except TimeoutError as error:
        for ip in pending_ips:
            yield {"ip": ip, "error": error}
    finally:
        loop.remove_reader(sock)


def resolve_addresses(addresses):
    addr_map, errors = {}, {}
    for address in addresses:
        try:
            info = address_info(address)
            addr_map.setdefault(info["ip"], []).append(info)
        except OSError as error:
            errors[address] = error
    return addr_map, errors


async def async_resolve_addresses(addresses):
    addr_map, errors = {}, {}

    async def raise_to_return(address):
        try:
            return address, await async_address_info(address)
        except Exception as error:
            return address, error

    coros = [raise_to_return(address) for address in addresses]
    for info in await asyncio.gather(*coros, return_exceptions=True):
        addr, info = info
        if isinstance(info, Exception):
            errors[addr] = info
        else:
            addr_map.setdefault(info["ip"], []).append(info)
    return addr_map, errors


class Ping:
    """Handle several hosts with a single "shared" ICMP socket"""

    def __init__(self, sock: Socket, icmp_id=None, timeout=None):
        self.socket = sock
        if icmp_id is None:
            icmp_id = new_id()
        self.icmp_id = icmp_id
        self.timeout = timeout

    def send_one_ping(self, ips: list[str], icmp_seq: int = 1):
        self.socket.send_one_ping(ips, self.icmp_id, icmp_seq)

    def receive_one_ping(self, ips: list[str], icmp_seq: int = 1, timeout=SENTINEL):
        if timeout is SENTINEL:
            timeout = self.timeout
        yield from receive_one_ping(self.socket, ips, icmp_seq, timeout)

    def _one_ping(self, ips: list[str], icmp_seq: int, timeout: float | None):
        self.send_one_ping(ips, icmp_seq)
        yield from self.receive_one_ping(ips, icmp_seq, timeout)

    def one_ping(self, addresses: list[str], icmp_seq: int = 1, timeout=SENTINEL):
        addr_map, errors = resolve_addresses(addresses)
        for addr, error in errors.items():
            yield dict(ip=addr, host=addr, error=error)
        ips = set(addr_map)
        for result in self._one_ping(ips, icmp_seq, timeout):
            ip = result["ip"]
            for info in addr_map[ip]:
                result["host"] = info["host"]
                yield result

    def ping(
        self,
        addresses: list[str],
        interval: float = 1,
        count: int | None = None,
        timeout=SENTINEL,
    ):
        if timeout is SENTINEL:
            timeout = self.timeout
        addr_map, errors = resolve_addresses(addresses)
        for addr, error in errors.items():
            yield dict(ip=addr, host=addr, error=error)
        ips = set(addr_map)
        sequence = range(1, count + 1) if count else cycle()
        for seq_id in sequence:
            for result in self._one_ping(ips, seq_id, timeout):
                ip = result["ip"]
                for info in addr_map[ip]:
                    result["host"] = info["host"]
                    yield result
            time.sleep(interval)

    def async_receive_one_ping(
        self, ips: list[str], icmp_seq: int = 1, timeout=SENTINEL
    ):
        if timeout is SENTINEL:
            timeout = self.timeout
        return async_receive_one_ping(self.socket, ips, icmp_seq, timeout)

    def _async_one_ping(self, ips: list[str], icmp_seq, timeout):
        self.send_one_ping(ips, icmp_seq)
        return self.async_receive_one_ping(ips, icmp_seq, timeout)

    async def async_one_ping(
        self, addresses: list[str], icmp_seq: int = 1, timeout=SENTINEL
    ):
        addr_map, errors = await async_resolve_addresses(addresses)
        for addr, error in errors.items():
            yield dict(ip=addr, host=addr, error=error)
        ips = set(addr_map)
        async for result in self._async_one_ping(ips, icmp_seq, timeout):
            ip = result["ip"]
            for info in addr_map[ip]:
                result["host"] = info["host"]
                yield result

    async def async_ping(
        self,
        addresses: list[str],
        interval: float = 1,
        count: int | None = None,
        timeout=SENTINEL,
    ):
        if timeout is SENTINEL:
            timeout = self.timeout
        addr_map, errors = await async_resolve_addresses(addresses)
        for addr, error in errors.items():
            yield dict(ip=addr, host=addr, error=error)
        ips = set(addr_map)
        sequence = range(1, count + 1) if count else cycle()
        for seq_id in sequence:
            async for result in self._async_one_ping(ips, seq_id, timeout):
                ip = result["ip"]
                for info in addr_map[ip]:
                    result["host"] = info["host"]
                    yield result
            await asyncio.sleep(interval)


def ping(
    hosts: list[str],
    icmp_id: int | None = None,
    interval: float = 1,
    count: int | None = None,
    timeout: float | None = 1,
):
    sock = Socket()
    ping = Ping(sock, icmp_id, timeout)
    yield from ping.ping(hosts, interval, count)


async def async_ping(
    hosts: list[str],
    icmp_id: int | None = None,
    interval: float = 1,
    count: int | None = None,
    timeout: float | None = 1,
):
    sock = Socket()
    ping = Ping(sock, icmp_id, timeout)
    async for response in ping.async_ping(hosts, interval, count):
        yield response
