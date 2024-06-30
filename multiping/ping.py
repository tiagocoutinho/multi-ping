import contextlib
import logging
import time

from .socket import address_info, Socket
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
        pending_ips = set(ips)
        with remaining_time(timeout) as timer:
            while pending_ips:
                try:
                    response = self.socket.receive_one_ping(timer())
                except TimeoutError as error:
                    for ip in pending_ips:
                        yield {"ip": ip, "error": error}
                    return
                if response["sequence"] != icmp_seq:
                    logging.warning("Received old response")
                    continue
                ip = response["ip"]
                pending_ips.remove(ip)
                yield response

    def _one_ping(self, ips: list[str], icmp_seq: int = 1, timeout=SENTINEL):
        self.send_one_ping(ips, icmp_seq)
        yield from self.receive_one_ping(ips, icmp_seq, timeout)

    def one_ping(self, addresses: list[str], icmp_seq: int = 1, timeout=SENTINEL):
        addr_map = {}
        for address in addresses:
            info = address_info(address)
            addr_map.setdefault(info["ip"], []).append(info)
        ips = set(addr_map)
        for result in self._one_ping(ips, icmp_seq, timeout):
            ip = result["ip"]
            for info in addr_map[ip]:
                result["host"] = info["host"]
                yield result


def ping_many(
    hosts: list[str],
    icmp_id: int | None = None,
    interval: float = 1,
    count: int | None = None,
    timeout: float | None = 1,
):
    sock = Socket()
    ping = Ping(sock, icmp_id, timeout)
    sequence = range(1, count + 1) if count else cycle()
    for seq_id in sequence:
        yield from ping.one_ping(hosts, seq_id, timeout)
        time.sleep(interval)
