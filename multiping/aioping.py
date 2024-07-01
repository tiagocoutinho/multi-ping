import asyncio
import time

from .socket import async_resolve_addresses, Socket
from .tools import cycle, new_id, SENTINEL


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


class AsyncPing:
    """Handle several hosts with a single "shared" ICMP socket"""

    def __init__(self, sock: Socket, icmp_id=None, timeout=None):
        self.socket = sock
        if icmp_id is None:
            icmp_id = new_id()
        self.icmp_id = icmp_id
        self.timeout = timeout

    def send_one_ping(self, ips: list[str], icmp_seq: int = 1):
        self.socket.send_one_ping(ips, self.icmp_id, icmp_seq)

    def async_receive_one_ping(
        self, ips: list[str], icmp_seq: int = 1, timeout=SENTINEL
    ):
        if timeout is SENTINEL:
            timeout = self.timeout
        return async_receive_one_ping(self.socket, ips, icmp_seq, timeout)

    def _async_one_ping(self, ips: list[str], icmp_seq, timeout):
        self.send_one_ping(ips, icmp_seq)
        return self.async_receive_one_ping(ips, icmp_seq, timeout)

    async def async_ping(
        self,
        addresses: list[str],
        interval: float = 1,
        strict_interval: bool = False,
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
            start = time.perf_counter()
            async for result in self._async_one_ping(ips, seq_id, timeout):
                ip = result["ip"]
                for info in addr_map[ip]:
                    result["host"] = info["host"]
                    yield result
            dt = time.perf_counter() - start
            nap = (interval - dt) if strict_interval else interval
            await asyncio.sleep(nap)


async def async_ping(
    hosts: list[str],
    icmp_id: int | None = None,
    interval: float = 1,
    count: int | None = None,
    timeout: float | None = 1,
):
    sock = Socket()
    ping = AsyncPing(sock, icmp_id, timeout)
    async for response in ping.async_ping(hosts, interval, True, count):
        yield response
